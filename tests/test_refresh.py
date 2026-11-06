"""Unit tests for the refresh buttons (stats save, odds fetch, jobs, endpoints).

No network, no real DB, no Odds API credits: every paid path is mocked and
odds_api.call_odds_api is replaced by a guard that fails the test if reached.
Run from the repo root: .venv\\Scripts\\python.exe -m unittest discover tests -v
"""
import os
import sys
import tempfile

# Before importing any repo module: pin season/week (no Sleeper call) and point
# the engines at a temp DB (test_model_v2 may already have set a path).
os.environ.setdefault("NFL_SEASON", "2026")
os.environ.setdefault("NFL_WEEK", "8")
os.environ.setdefault("NFL_STATS_DB", os.path.join(tempfile.mkdtemp(prefix="nfl_refresh_ut_"), "unit.db"))
os.makedirs(os.path.dirname(os.environ["NFL_STATS_DB"]), exist_ok=True)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import asyncio
import json
import shutil
import sqlite3
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import models

assert os.path.normcase(str(models.DB_PATH)) != os.path.normcase(os.path.join(REPO, "nfl_stats.db")), \
    "tests must not use the real nfl_stats.db"

import save_to_db
import odds_api
import refresh_jobs

REQUIRED_COLS = ["player_id", "player_name", "player_display_name", "team", "position",
                 "season", "week", "season_type", "gp", "passing_yards", "passing_tds",
                 "rushing_yards", "rushing_tds", "receiving_yards", "receiving_tds", "receptions"]


def _stats_df(week=8, extra=None):
    rows = []
    for pid, gp in (("p1", 1), ("p2", 1), ("p3", 0), ("p1", 1)):  # p1 twice
        row = {c: 0 for c in REQUIRED_COLS}
        row.update(player_id=pid, player_name=pid, player_display_name=pid.upper(), team="GB",
                   position="WR", season=2026, week=week, season_type="regular", gp=gp, receiving_yards=50.0)
        if extra:
            row.update(extra)
        rows.append(row)
    return pd.DataFrame(rows)


class TempDirMixin:
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nfl_refresh_case_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestSaveStats(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = os.path.join(self.tmp, "stats.db")

    def _count(self, week=8):
        with sqlite3.connect(self.db) as conn:
            return conn.execute("SELECT COUNT(*) FROM player_weekly_stats WHERE season=2026 AND week=?",
                                (week,)).fetchone()[0]

    def test_twice_is_idempotent_and_indexed(self):
        with mock.patch("save_to_db.fetch_weekly_stats", return_value=_stats_df()):
            first = save_to_db.save_stats_to_db(2026, 8, db_path=self.db)
            second = save_to_db.save_stats_to_db(2026, 8, db_path=self.db)
        self.assertEqual((first["rows_saved"], first["rows_replaced"]), (3, 0))
        self.assertEqual((second["rows_saved"], second["rows_replaced"]), (3, 3))
        self.assertEqual(self._count(), 3)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM player_weekly_stats WHERE gp IS NULL").fetchone()[0], 0)
            indexes = [r[1] for r in conn.execute("PRAGMA index_list(player_weekly_stats)")]
        self.assertIn("ux_player_weekly_stats_key", indexes)

    def test_failed_insert_keeps_old_rows(self):
        with mock.patch("save_to_db.fetch_weekly_stats", return_value=_stats_df()):
            save_to_db.save_stats_to_db(2026, 8, db_path=self.db)
        with mock.patch("save_to_db.fetch_weekly_stats", return_value=_stats_df(extra={"bogus": 1})):
            with self.assertRaises(Exception):
                save_to_db.save_stats_to_db(2026, 8, db_path=self.db)
        self.assertEqual(self._count(), 3)

    def test_empty_fetch_keeps_rows(self):
        with mock.patch("save_to_db.fetch_weekly_stats", return_value=_stats_df()):
            save_to_db.save_stats_to_db(2026, 8, db_path=self.db)
        with mock.patch("save_to_db.fetch_weekly_stats", return_value=pd.DataFrame()):
            res = save_to_db.save_stats_to_db(2026, 8, db_path=self.db)
        self.assertEqual(res["rows_saved"], 0)
        self.assertEqual(self._count(), 3)

    def test_other_week_untouched(self):
        with mock.patch("save_to_db.fetch_weekly_stats", return_value=_stats_df(week=7)):
            save_to_db.save_stats_to_db(2026, 7, db_path=self.db)
        with mock.patch("save_to_db.fetch_weekly_stats", return_value=_stats_df(week=8)):
            save_to_db.save_stats_to_db(2026, 8, db_path=self.db)
            save_to_db.save_stats_to_db(2026, 8, db_path=self.db)
        self.assertEqual(self._count(7), 3)
        self.assertEqual(self._count(8), 3)


class TestLoadAll(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.db = os.path.join(self.tmp, "stats.db")
        self.players = pd.DataFrame([{"player_id": "p1"}])

    def _fake_fetch(self, year, week, season_type="regular", players_df=None):
        df = _stats_df(week=week)
        df["season"] = year
        return df

    def _run(self, current_week):
        with mock.patch("save_to_db.fetch_players_df", return_value=self.players) as players, \
                mock.patch("save_to_db.fetch_weekly_stats", side_effect=self._fake_fetch) as fetch:
            out = save_to_db.load_all_completed_weeks(2026, current_week, db_path=self.db)
        return out, players, fetch

    def _total(self):
        with sqlite3.connect(self.db) as conn:
            return conn.execute("SELECT COUNT(*) FROM player_weekly_stats").fetchone()[0]

    def test_loads_prior_and_completed_weeks_once(self):
        out, players, fetch = self._run(3)
        players.assert_called_once()
        requested = [(c.args[0], c.args[1]) for c in fetch.call_args_list]
        self.assertEqual(requested, [(2025, w) for w in range(1, 19)] + [(2026, 1), (2026, 2)])
        self.assertTrue(all(c.kwargs["players_df"] is self.players for c in fetch.call_args_list))
        self.assertEqual(len(out), 20)
        self.assertEqual(self._total(), 60)
        self._run(3)
        self.assertEqual(self._total(), 60)

    def test_week_one_loads_prior_season_only(self):
        out, _, fetch = self._run(1)
        self.assertEqual({c.args[0] for c in fetch.call_args_list}, {2025})
        self.assertEqual(len(out), 18)

    def test_postseason_week_caps_at_18(self):
        out, _, fetch = self._run(20)
        self.assertEqual(max(c.args[1] for c in fetch.call_args_list if c.args[0] == 2026), 18)
        self.assertEqual(len(out), 36)


def _event(i, hours):
    t = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    return {"id": f"ev{i}", "home_team": f"Home{i}", "away_team": f"Away{i}", "commence_time": t}


def _book_data():
    return {"bookmakers": [{"title": "MockBook", "markets": [
        {"key": "player_reception_yds", "outcomes": [
            {"name": "Over", "description": "Mock Player", "point": 55.5, "price": 1.9},
            {"name": "Under", "description": "Mock Player", "point": 55.5, "price": 1.9}]},
        {"key": "totals", "outcomes": [
            {"name": "Over", "point": 44.5, "price": 1.91},
            {"name": "Under", "point": 44.5, "price": 1.91}]}]}]}


class TestOdds(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.engine = create_engine(f"sqlite:///{os.path.join(self.tmp, 'odds.db')}")
        models.Base.metadata.create_all(self.engine)
        odds_api.Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        for p in (mock.patch.object(odds_api, "Session", self.Session),
                  mock.patch.object(odds_api, "API_KEYS", ["test-key-AAA", "test-key-BBB"]),
                  mock.patch.object(odds_api, "call_odds_api", side_effect=AssertionError("paid call")),
                  mock.patch.dict(odds_api.QUOTA, clear=True)):
            p.start()
            self.addCleanup(p.stop)
        s = self.Session()
        s.add_all([models.Odds(player_id="custom_Old", bookmaker="B", market="totals", season=2026, week=9),
                   models.Odds(player_id="custom_Keep", bookmaker="B", market="totals", season=2026, week=8)])
        s.commit()
        s.close()

    def _rows(self, week):
        s = self.Session()
        try:
            return [o.player_id for o in s.query(models.Odds).filter_by(season=2026, week=week)]
        finally:
            s.close()

    def _events(self, events):
        now = datetime.now(timezone.utc)
        return mock.patch.object(odds_api, "get_upcoming_events",
                                 return_value=(events, now, now + timedelta(days=4), odds_api.quota_snapshot()))

    def test_partial_success_replaces_week(self):
        calls = []

        def fake(event_id):
            calls.append(event_id)
            if event_id == "ev2":
                raise RuntimeError("boom apiKey=test-key-AAA")
            return {"data": _book_data(), "credits": 2, "remaining": 100}

        with self._events([_event(1, 2), _event(2, 3)]), mock.patch.object(odds_api, "fetch_event_odds", side_effect=fake):
            res = odds_api.fetch_and_store_odds(4, 2026, 9)
        self.assertEqual(res["events_processed"], 1)
        self.assertEqual(res["events_failed"], ["Home2 vs Away2"])
        self.assertEqual(res["credits_used"], 2)
        self.assertEqual(res["credits_source"], "header")
        self.assertEqual(res["rows_cleared"], 1)
        self.assertEqual(res["odds_rows_saved"], 4)
        week9 = self._rows(9)
        self.assertNotIn("custom_Old", week9)
        self.assertIn("custom_Mock Player", week9)
        self.assertEqual(self._rows(8), ["custom_Keep"])

    def test_all_fail_keeps_rows(self):
        with self._events([_event(1, 2)]), \
                mock.patch.object(odds_api, "fetch_event_odds", side_effect=RuntimeError("x")):
            with self.assertRaises(RuntimeError):
                odds_api.fetch_and_store_odds(4, 2026, 9)
        self.assertEqual(self._rows(9), ["custom_Old"])

    def test_zero_events_keeps_rows(self):
        with self._events([]), mock.patch.object(odds_api, "fetch_event_odds") as fe:
            res = odds_api.fetch_and_store_odds(4, 2026, 9)
        self.assertEqual(res["events_processed"], 0)
        fe.assert_not_called()
        self.assertEqual(self._rows(9), ["custom_Old"])

    def test_more_games_than_confirmed_aborts(self):
        with self._events([_event(1, 2), _event(2, 3)]), mock.patch.object(odds_api, "fetch_event_odds") as fe:
            with self.assertRaisesRegex(RuntimeError, "changed"):
                odds_api.fetch_and_store_odds(4, 2026, 9, max_games=1)
        fe.assert_not_called()
        self.assertEqual(self._rows(9), ["custom_Old"])

    def test_redact(self):
        out = odds_api.redact("GET https://x/events?apiKey=test-key-AAA&regions=au failed test-key-BBB")
        self.assertNotIn("test-key-AAA", out)
        self.assertNotIn("test-key-BBB", out)

    def test_get_upcoming_events_free(self):
        events = [_event(1, 1), _event(2, 48), _event(3, 24 * 10)]
        resp = mock.Mock(status_code=200, headers={"x-requests-remaining": "412", "x-requests-used": "88"})
        resp.json.return_value = events

        def usage_rows():
            with self.engine.connect() as conn:
                return conn.execute(text("SELECT COUNT(*) FROM api_usage")).scalar()

        before = usage_rows()
        with mock.patch.object(odds_api.requests, "get", return_value=resp) as get:
            got, start, end, quota = odds_api.get_upcoming_events(4)
        self.assertEqual([e["id"] for e in got], ["ev1", "ev2"])
        self.assertEqual(quota["total_remaining"], 824)
        self.assertEqual(get.call_count, 2)
        for call in get.call_args_list:
            self.assertTrue(call.args[0].rstrip("/").endswith("/events"))
        self.assertEqual(usage_rows(), before)


class TestRefreshJobs(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.state = refresh_jobs.RefreshState(os.path.join(self.tmp, "state.json"))
        p = mock.patch.object(refresh_jobs, "STATE", self.state)
        p.start()
        self.addCleanup(p.stop)

    def test_state_round_trip_and_corruption(self):
        self.state.record_run("stats", {"status": "succeeded", "summary": "ok"})
        self.assertEqual(refresh_jobs.RefreshState(self.state.path).load()["last_runs"]["stats"]["summary"], "ok")
        self.state.path.write_text("{not json")
        self.assertEqual(self.state.load(), {})
        self.state.record_run("odds", {"status": "failed"})
        self.assertEqual(self.state.load()["last_runs"]["odds"]["status"], "failed")

    def test_state_never_writes_key(self):
        with mock.patch.object(odds_api, "API_KEYS", ["test-key-AAA"]):
            self.state.record_run("odds", {"error": "failed https://x?apiKey=test-key-AAA test-key-AAA"})
        self.assertNotIn("test-key-AAA", self.state.path.read_text())

    def _wait(self, runner):
        runner.thread.join(5)
        self.assertFalse(runner.is_running())

    def test_runner_busy_then_succeeds(self):
        runner = refresh_jobs.JobRunner()
        ev = threading.Event()

        def job_fn(job):
            ev.wait(5)
            return {"n": 1}, "done"

        job, busy = runner.start("stats", job_fn)
        self.assertIsNone(busy)
        job2, busy2 = runner.start("odds", job_fn)
        self.assertIsNone(job2)
        self.assertEqual(busy2["running_step"], "stats")
        self.assertEqual(busy2["job_id"], job["job_id"])
        ev.set()
        self._wait(runner)
        self.assertEqual(runner.snapshot()["status"], "succeeded")
        self.assertEqual(self.state.load()["last_runs"]["stats"]["summary"], "done")

    def test_runner_failure_redacted(self):
        runner = refresh_jobs.JobRunner()

        def job_fn(job):
            raise RuntimeError("bad apiKey=test-key-AAA")

        with mock.patch.object(odds_api, "API_KEYS", ["test-key-AAA"]):
            runner.start("odds", job_fn)
            self._wait(runner)
        snap = runner.snapshot()
        self.assertEqual(snap["status"], "failed")
        self.assertNotIn("test-key-AAA", snap["error"])
        self.assertNotIn("test-key-AAA", self.state.path.read_text())


import app as app_module  # noqa: E402  (after env setup)
import test_thresholds  # noqa: E402


def call(method, path, client=("127.0.0.1", 50000), host="127.0.0.1:8011", headers=None, body=b""):
    hdrs = [(b"host", host.encode())]
    if body:
        hdrs.append((b"content-type", b"application/json"))
        hdrs.append((b"content-length", str(len(body)).encode()))
    for k, v in (headers or {}).items():
        hdrs.append((k.lower().encode(), v.encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
             "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
             "root_path": "", "headers": hdrs, "client": client, "server": ("127.0.0.1", 8011)}
    sent = {"done": False}
    out = {"status": None, "body": b""}

    async def receive():
        if not sent["done"]:
            sent["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.sleep(10)
        return {"type": "http.disconnect"}

    async def send(msg):
        if msg["type"] == "http.response.start":
            out["status"] = msg["status"]
        elif msg["type"] == "http.response.body":
            out["body"] += msg.get("body", b"")

    asyncio.run(app_module.app(scope, receive, send))
    return out["status"], (json.loads(out["body"]) if out["body"] else None)


H = {"X-NFL-Refresh": "1"}


class TestApi(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.state_path = os.path.join(self.tmp, "state.json")
        self.runner = refresh_jobs.JobRunner()
        self.release = threading.Event()
        self.release.set()
        release = self.release

        def fake_stats(job):
            release.wait(5)
            return {"rows_saved": 3}, "2026 wk7: 3 rows"

        def fake_odds(job, confirm_games):
            return {"events_processed": confirm_games}, "ok"

        for p in (mock.patch.object(refresh_jobs, "STATE", refresh_jobs.RefreshState(self.state_path)),
                  mock.patch.object(refresh_jobs, "RUNNER", self.runner),
                  mock.patch.object(refresh_jobs, "run_stats_job", fake_stats),
                  mock.patch.object(refresh_jobs, "run_odds_job", fake_odds),
                  mock.patch.object(refresh_jobs, "odds_preview", return_value={"game_count": 2}),
                  mock.patch.object(odds_api, "call_odds_api", side_effect=AssertionError("paid call")),
                  mock.patch.dict(os.environ)):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("ALLOW_REMOTE_REFRESH", None)

    def tearDown(self):
        self.release.set()
        if self.runner.thread:
            self.runner.thread.join(5)
        super().tearDown()

    def _finish(self):
        self.runner.thread.join(5)

    def test_loopback_clients_allowed(self):
        for client in ("127.0.0.1", "::1", "127.0.0.2", "::ffff:127.0.0.1"):
            status, body = call("POST", "/refresh/stats", client=(client, 1), headers=H)
            self.assertEqual(status, 202, client)
            self.assertEqual(body["step"], "stats")
            self._finish()
        for host in ("localhost:8011", "[::1]:8011", "127.0.0.1"):
            status, _ = call("POST", "/refresh/stats", host=host, headers=H)
            self.assertEqual(status, 202, host)
            self._finish()

    def test_remote_client_blocked_unless_allowed(self):
        status, body = call("POST", "/refresh/stats", client=("192.168.1.50", 1), headers=H)
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "forbidden")
        os.environ["ALLOW_REMOTE_REFRESH"] = "0"
        self.assertEqual(call("POST", "/refresh/stats", client=("192.168.1.50", 1), headers=H)[0], 403)
        os.environ["ALLOW_REMOTE_REFRESH"] = "1"
        self.assertEqual(call("POST", "/refresh/stats", client=("192.168.1.50", 1),
                              host="192.168.1.10:8000", headers=H)[0], 202)
        self._finish()

    def test_forwarded_for_not_trusted(self):
        status, _ = call("POST", "/refresh/stats", client=("192.168.1.50", 1),
                         headers={"X-NFL-Refresh": "1", "X-Forwarded-For": "127.0.0.1"})
        self.assertEqual(status, 403)

    def test_bad_host_or_missing_header(self):
        self.assertEqual(call("POST", "/refresh/stats", host="evil.example:8011", headers=H)[0], 403)
        status, body = call("POST", "/refresh/stats")
        self.assertEqual(status, 403)
        self.assertEqual(body["message"], "Missing X-NFL-Refresh header.")
        os.environ["ALLOW_REMOTE_REFRESH"] = "1"
        self.assertEqual(call("POST", "/refresh/stats")[0], 403)

    def test_preview(self):
        self.assertEqual(call("GET", "/refresh/odds/preview", client=("192.168.1.50", 1), headers=H)[0], 403)
        status, body = call("GET", "/refresh/odds/preview", headers=H)
        self.assertEqual((status, body), (200, {"game_count": 2}))
        with mock.patch.object(refresh_jobs, "odds_preview", side_effect=refresh_jobs.NoApiKeys("none")):
            status, body = call("GET", "/refresh/odds/preview", headers=H)
        self.assertEqual((status, body["error"]), (503, "no_api_keys"))
        with mock.patch.object(refresh_jobs, "odds_preview", side_effect=RuntimeError("x")):
            self.assertEqual(call("GET", "/refresh/odds/preview", headers=H)[0], 502)

    def test_odds_body_validation(self):
        self.assertEqual(call("POST", "/refresh/odds", headers=H)[0], 422)
        self.assertEqual(call("POST", "/refresh/odds", headers=H, body=b'{"confirm_games": -1}')[0], 422)
        status, body = call("POST", "/refresh/odds", headers=H, body=b'{"confirm_games": 3}')
        self.assertEqual((status, body["step"]), (202, "odds"))
        self._finish()

    def test_busy_409_status_and_persistence(self):
        self.release.clear()
        status, job = call("POST", "/refresh/stats", headers=H)
        self.assertEqual(status, 202)
        status, busy = call("POST", "/refresh/stats", headers=H)
        self.assertEqual((status, busy["running_step"], busy["job_id"]), (409, "stats", job["job_id"]))
        status, busy = call("POST", "/refresh/odds", headers=H, body=b'{"confirm_games": 0}')
        self.assertEqual((status, busy["running_step"]), (409, "stats"))
        status, st = call("GET", "/refresh/status")
        self.assertTrue(st["running"])
        self.release.set()
        deadline = time.time() + 5
        while time.time() < deadline:
            st = call("GET", "/refresh/status")[1]
            if st["job"]["status"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(st["job"]["status"], "succeeded")
        self.assertFalse(st["running"])
        self.assertEqual(st["last_runs"]["stats"]["summary"], "2026 wk7: 3 rows")
        reloaded = refresh_jobs.RefreshState(self.state_path).load()
        self.assertEqual(reloaded["last_runs"]["stats"]["status"], "succeeded")

    def test_status_open_to_remote(self):
        status, body = call("GET", "/refresh/status", client=("192.168.1.50", 1))
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"running", "job", "last_runs"})

    def test_generate_picks_unchanged(self):
        players = [{"player": "A", "stats": [{"flagged": True}, {"flagged": False}]}]
        with mock.patch.object(test_thresholds, "get_picks_with_model", return_value=(players, {"version": "v2"})):
            status, body = call("GET", "/generate-picks")
            self.assertEqual(status, 200)
            self.assertEqual(set(body), {"success", "players", "count", "model"})
            self.assertEqual(body["count"], 1)
            st = call("GET", "/refresh/status")[1]
            self.assertIn("1 flagged", st["last_runs"]["picks"]["summary"])
            with mock.patch.object(refresh_jobs, "record_picks_run", side_effect=OSError("disk")):
                status2, body2 = call("GET", "/generate-picks")
        self.assertEqual((status2, body2), (status, body))

    def test_generate_picks_without_stats_table(self):
        empty = create_engine("sqlite:///" + os.path.join(self.tmp, "empty.db"))
        with mock.patch.object(test_thresholds, "engine", empty):
            status, body = call("GET", "/generate-picks")
        empty.dispose()
        self.assertEqual(status, 200)
        self.assertFalse(body["success"])
        self.assertIn("save_to_db.py --all", body["error"])


if __name__ == "__main__":
    unittest.main()
