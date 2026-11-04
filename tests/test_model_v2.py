"""Unit tests for model v2 and the v1 fixes. No DB, no network.

Run from the repo root: .venv\\Scripts\\python.exe -m unittest discover tests -v
"""
import os
import sys
import tempfile

# Before importing any repo module: pin season/week (no Sleeper call) and point
# the engines at a path no test connects to.
os.environ.setdefault("NFL_SEASON", "2026")
os.environ.setdefault("NFL_WEEK", "8")
os.environ["NFL_STATS_DB"] = os.path.join(tempfile.gettempdir(), "nfl_backtest", "unittest_unused.db")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import unittest
from unittest import mock

from probability_calc import calculate_probability
from Odds_vs_Stats_Check import check_stat_against_odds


def _v1_stats(avg, std):
    return {"avg": {"receiving_yards": avg}, "std": {"receiving_yards": std},
            "weekly": [{"receiving_yards": avg}, {"receiving_yards": avg}, {"receiving_yards": avg}]}


class TestV1Fixes(unittest.TestCase):
    def test_exception_returns_none_and_logs(self):
        with self.assertLogs("probability_calc", "ERROR") as cm:
            self.assertIsNone(calculate_probability(10, "x", 5.5))
        self.assertEqual(len(cm.records), 1)

    def test_none_input_returns_none(self):
        self.assertIsNone(calculate_probability(None, 5, 5.5))

    def test_check_drops_row_on_probability_error(self):
        odds = [{"market": "player_reception_yds", "line": 40.5, "bookmaker": "A", "prices": {}}]
        errors = []
        with mock.patch("probability_calc.calculate_probability", return_value=None):
            rows = check_stat_against_odds("P", _v1_stats(80.0, 10.0), odds, {"receiving_yards": 20}, errors=errors)
        self.assertEqual(rows, [])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["reason"], "probability error")

    def test_include_unflagged_returns_no_bet_row(self):
        odds = [{"market": "player_reception_yds", "line": 75.5, "bookmaker": "A", "prices": {}}]
        thr = {"receiving_yards": 20}
        self.assertEqual(check_stat_against_odds("P", _v1_stats(80.0, 10.0), odds, thr), [])
        rows = check_stat_against_odds("P", _v1_stats(80.0, 10.0), odds, thr, include_unflagged=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["threshold_rule"], "No Bet")
        self.assertIsNotNone(rows[0]["probabilityOver"])
        self.assertIsNotNone(rows[0]["probabilityUnder"])


class TestConfig(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        os.chdir(REPO)  # read_config_from_file opens the relative pipeline_config.py

    def tearDown(self):
        os.chdir(self._cwd)

    def test_defaults(self):
        import test_thresholds
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NFL_MODEL_VERSION", None)
            cfg = test_thresholds.read_config_from_file()
        self.assertEqual(cfg["MODEL_VERSION"], "v1")
        self.assertEqual(cfg["V2_EDGE_MARGIN"], 0.03)
        self.assertEqual(cfg["V2_MIN_GAMES_FOR_FLAG"], 3)

    def test_env_override(self):
        import test_thresholds
        with mock.patch.dict(os.environ, {"NFL_MODEL_VERSION": "v2"}):
            cfg = test_thresholds.read_config_from_file()
        self.assertEqual(cfg["MODEL_VERSION"], "v2")

    def test_engine_uses_nfl_stats_db(self):
        import test_thresholds
        self.assertEqual(os.path.normcase(test_thresholds.engine.url.database),
                         os.path.normcase(os.environ["NFL_STATS_DB"]))


def _entry(market, book, line):
    return {"market": market, "line": line, "bookmaker": book, "event_name": "A vs B", "prices": {"unknown": 1.87}}


class TestOutlierRule(unittest.TestCase):
    def _kept(self, market, lines):
        import test_thresholds
        entries = [_entry(market, f"B{i}", l) for i, l in enumerate(lines)]
        return [e["line"] for e in test_thresholds.drop_outlier_lines(entries, "P", 2025, 16)]

    def test_count_gap_one_kept(self):
        self.assertEqual(self._kept("player_receptions", [2.5, 2.5, 2.5, 3.5]), [2.5, 2.5, 2.5, 3.5])

    def test_count_gap_one_and_half_dropped(self):
        # 4.5 vs median 3.0: gap 1.5 > 1.0 and rel 0.5 > 0.25
        self.assertEqual(self._kept("player_receptions", [3.0, 3.0, 3.0, 4.5]), [3.0, 3.0, 3.0])

    def test_yards_rule_unchanged(self):
        self.assertEqual(self._kept("player_reception_yds", [20.5, 20.5, 20.5, 40.5]), [20.5, 20.5, 20.5])


class TestHistoryQuery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sqlalchemy import create_engine, text
        cls.engine = create_engine("sqlite://")
        with cls.engine.begin() as c:
            c.execute(text("""CREATE TABLE player_weekly_stats (player_id TEXT, player_display_name TEXT,
                season INTEGER, week INTEGER, season_type TEXT, gp REAL, position TEXT, team TEXT,
                passing_yards REAL, passing_tds REAL, rushing_yards REAL, rushing_tds REAL,
                receiving_yards REAL, receiving_tds REAL, receptions REAL)"""))
            rows = [(2025, w, 1, 10.0 * w) for w in range(12, 18)] + [(2026, w, 1, 100.0 + w) for w in (6, 7, 8)]
            rows.append((2026, 5, 0, 999.0))  # did not play
            for season, week, gp, ry in rows:
                c.execute(text("""INSERT INTO player_weekly_stats VALUES ('1', 'X', :s, :w, 'regular', :gp, 'RB', 'GB',
                    0, 0, :ry, 0, NULL, 0, 1)"""), {"s": season, "w": week, "gp": gp, "ry": ry})
            c.execute(text("""INSERT INTO player_weekly_stats VALUES ('2', 'Y', 2026, 7, 'regular', 1, 'WR', 'GB',
                0, 0, 5, 0, 5, 0, 1)"""))

    def _hist(self, **kw):
        import test_thresholds
        with self.engine.connect() as conn:
            return test_thresholds.get_played_history(conn, "1", 2026, 8, **kw)

    def test_order_and_cross_season(self):
        h = self._hist()
        self.assertEqual([(r["season"], r["week"]) for r in h[:4]], [(2026, 7), (2026, 6), (2025, 17), (2025, 16)])
        self.assertTrue(all((r["season"], r["week"]) < (2026, 8) for r in h))
        self.assertEqual(len(h), 8)

    def test_gp_zero_excluded_and_null_is_zero(self):
        h = self._hist()
        self.assertNotIn((2026, 5), [(r["season"], r["week"]) for r in h])
        self.assertEqual(h[0]["receiving_yards"], 0.0)
        self.assertIsInstance(h[0]["season"], int)

    def test_max_games(self):
        self.assertEqual(len(self._hist(max_games=3)), 3)


if __name__ == "__main__":
    unittest.main()
