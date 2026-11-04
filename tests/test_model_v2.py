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


if __name__ == "__main__":
    unittest.main()
