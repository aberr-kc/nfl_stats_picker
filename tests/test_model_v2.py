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


import math
import json

import model_v2

LAST3 = {"type": "last_n", "n": 3}
LAST6 = {"type": "last_n", "n": 6}


def _sp(dist, a, b, c=1.0, k=0.25, blend=False, ratios=None):
    d = {"c": c, "a": a, "b": b, "dist": dist, "k": k, "blend": blend}
    if ratios is not None:
        d["ratios"] = ratios
    return d


def valid_params(**over):
    p = {
        "version": 2,
        "window": {"type": "last_n", "n": 6},
        "stats": {
            "passing_yards": _sp("lognormal", 0.13, 0.13),
            "receiving_yards": _sp("lognormal", 0.63, 0.63),
            "rushing_yards": _sp("lognormal", 0.86, 0.86),
            "receptions": _sp("negbin", 0.36, 0.36),
            "passing_tds": _sp("negbin", 0.59, 0.59),
        },
        "td": {"n0": 2, "lambda0": {"QB": 0.08, "RB": 0.35, "WR": 0.25, "TE": 0.2, "ALL": 0.22}, "k": 0.0, "o": 1.25},
        "o_ou": 1.064,
        "fitted_on": "unit test",
        "gate_label": "unit test",
    }
    p.update(over)
    return p


class TestModelCore(unittest.TestCase):
    def test_window_mean_last_n(self):
        mu, n_eff, n = model_v2.window_mean([10, 20, 30, 40], LAST3)
        self.assertAlmostEqual(mu, 20.0)
        self.assertEqual((n_eff, n), (3.0, 3))
        self.assertIsNone(model_v2.window_mean([], LAST3))

    def test_window_mean_ewma(self):
        mu, n_eff, n = model_v2.window_mean([10, 20], {"type": "ewma", "half_life": 1, "max_games": 17})
        self.assertAlmostEqual(mu, (10 + 0.5 * 20) / 1.5)
        self.assertAlmostEqual(n_eff, 1.5 ** 2 / 1.25)
        self.assertEqual(n, 2)
        # equal weights (huge half-life) -> n_eff = n
        _, n_eff, _ = model_v2.window_mean([1, 2, 3, 4], {"type": "ewma", "half_life": 1e9, "max_games": 17})
        self.assertAlmostEqual(n_eff, 4.0, places=6)

    def test_cv_widens_with_small_n(self):
        self.assertGreater(model_v2.cv(0.3, 0.3, 1), model_v2.cv(0.3, 0.3, 3))
        self.assertGreater(model_v2.cv(0.3, 0.3, 3), model_v2.cv(0.3, 0.3, 6))

    def test_bug8_receptions(self):
        sp = _sp("negbin", 0.362, 0.362)
        p7 = model_v2.model_prob_over("receptions", [6, 6, 7], 4.5, sp, LAST3)[0]
        p6 = model_v2.model_prob_over("receptions", [6, 6, 6], 4.5, sp, LAST3)[0]
        self.assertGreaterEqual(p7, p6)
        self.assertLess(p7 - p6, 0.05)

    def test_normal_small_n_closer_to_half(self):
        p1 = model_v2.p_over_normal(50, model_v2.cv(0.3, 0.3, 1), 60.5)
        p6 = model_v2.p_over_normal(50, model_v2.cv(0.3, 0.3, 6), 60.5)
        self.assertLess(abs(p1 - 0.5), abs(p6 - 0.5))

    def test_negbin_small_n_closer_to_half(self):
        p1 = model_v2.p_over_negbin(6, model_v2.cv(0.362, 0.362, 1), 4.5)
        p6 = model_v2.p_over_negbin(6, model_v2.cv(0.362, 0.362, 6), 4.5)
        self.assertLess(abs(p1 - 0.5), abs(p6 - 0.5))

    def test_lognormal_widening_documented(self):
        # Mean-preserving widening lowers the median: with L > mu, P(Over) falls (correct).
        p1 = model_v2.p_over_lognormal(50, model_v2.cv(0.6, 0.6, 1), 60.5)
        p6 = model_v2.p_over_lognormal(50, model_v2.cv(0.6, 0.6, 6), 60.5)
        self.assertAlmostEqual(p1, 0.255, delta=0.002)
        self.assertAlmostEqual(p6, 0.266, delta=0.002)
        self.assertLess(p1, p6)

    def test_lognormal_median(self):
        mu, c = 50.0, 0.8
        med = mu / math.sqrt(1 + c * c)
        self.assertAlmostEqual(model_v2.p_over_lognormal(mu, c, med), 0.5, places=9)

    def test_negbin_falls_back_to_poisson(self):
        # Var = (0.3*2)^2 = 0.36 <= mu = 2
        self.assertAlmostEqual(model_v2.p_over_negbin(2.0, 0.3, 1.5), model_v2.p_over_poisson(2.0, 1.5))

    def test_poisson_review_example(self):
        self.assertAlmostEqual(model_v2.p_over_poisson(1.667, 1.5), 0.496, delta=0.001)

    def test_discrete_tail_uses_ceil(self):
        # P(X >= 1) for Poisson = 1 - e^-mu at line 0.5
        self.assertAlmostEqual(model_v2.p_over_poisson(0.7, 0.5), 1 - math.exp(-0.7))

    def test_over_plus_under_is_one(self):
        p = model_v2.model_prob_over("rushing_yards", [50, 60, 70], 55.5, _sp("lognormal", 0.8, 0.8), LAST3)[0]
        self.assertAlmostEqual(p + (1 - p), 1.0)
        self.assertTrue(0 < p < 1)

    def test_integer_line_unsupported(self):
        r = model_v2.model_prob_over("rushing_yards", [50, 60], 55.0, _sp("lognormal", 0.8, 0.8), LAST3)
        self.assertEqual(r, (None, "integer line not supported"))

    def test_mu_le_zero_skipped(self):
        r = model_v2.model_prob_over("rushing_yards", [0, 0], 5.5, _sp("lognormal", 0.8, 0.8), LAST3)
        self.assertEqual(r, (None, "mu<=0"))


class TestParams(unittest.TestCase):
    def test_valid(self):
        self.assertIsNotNone(model_v2.validate_params(valid_params()))

    def _bad(self, p):
        with self.assertRaises(model_v2.ParamsError):
            model_v2.validate_params(p)

    def test_rejects(self):
        p = valid_params(); del p["o_ou"]; self._bad(p)
        p = valid_params(); p["stats"]["receptions"]["k"] = 0.3; self._bad(p)
        p = valid_params(); p["stats"]["receptions"]["a"] = -0.1; self._bad(p)
        p = valid_params(); p["stats"]["passing_yards"]["c"] = 1.5; self._bad(p)
        p = valid_params(); p["td"]["o"] = 1.7; self._bad(p)
        self._bad(valid_params(o_ou=0.9))

    def test_missing_file(self):
        with self.assertRaises(model_v2.ParamsError) as cm:
            model_v2.load_params(os.path.join(tempfile.gettempdir(), "nfl_backtest", "no_such_params.json"))
        self.assertTrue(str(cm.exception).startswith("not found:"))


if __name__ == "__main__":
    unittest.main()
