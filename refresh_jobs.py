# refresh_jobs.py - background refresh jobs (stats, odds) and last-run state for the web page
#
# One lock covers both jobs (both write the DB). Jobs run in a daemon thread;
# the page polls GET /refresh/status. Last runs are kept in refresh_state.json
# (NFL_REFRESH_STATE overrides the path) so they survive a reload/restart.
# save_to_db / odds_api / team_stats / models are imported inside functions so
# importing this module (and app.py) never creates tables or reads keys.
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
STEPS = ("stats", "odds", "picks")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _redact(text):
    if text is None:
        return None
    if "odds_api" in sys.modules:
        return sys.modules["odds_api"].redact(text)
    return re.sub(r"(apiKey=)[^&\s'\"]+", r"\1***", str(text))


def _redact_obj(obj):
    if isinstance(obj, str):
        return _redact(obj)
    if isinstance(obj, dict):
        return {k: _redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_redact_obj(v) for v in obj]
    return obj


def load_config():
    """Fresh read of pipeline_config.py (picks up a new Sleeper week and edits without restart)."""
    config = {}
    path = BASE_DIR / "pipeline_config.py"
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), config)
    return config


class NoApiKeys(Exception):
    pass


# ---------------------------------------------------------------------------
# Persisted last-run state
# ---------------------------------------------------------------------------
class RefreshState:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data):
        tmp = self.path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_redact_obj(data), f, indent=2, default=str)
        os.replace(tmp, self.path)

    def record_run(self, step, run):
        with self._lock:
            data = self.load()
            data.setdefault("last_runs", {})[step] = run
            self._write(data)

    def set_quota(self, snapshot):
        with self._lock:
            data = self.load()
            data["quota"] = snapshot
            self._write(data)


STATE = RefreshState(Path(os.getenv("NFL_REFRESH_STATE") or (BASE_DIR / "refresh_state.json")))


# ---------------------------------------------------------------------------
# Job runner: one job at a time
# ---------------------------------------------------------------------------
class JobRunner:
    def __init__(self):
        self._lock = threading.Lock()
        self.current = None
        self.thread = None

    def is_running(self):
        return self._lock.locked() and bool(self.current) and self.current["status"] == "running"

    def start(self, step, fn, *args):
        """Start fn(job, *args) in a thread. Returns (job, None) or (None, busy) if a job is running."""
        if not self._lock.acquire(blocking=False):
            cur = self.current or {}
            return None, {"error": "busy", "running_step": cur.get("step"),
                          "job_id": cur.get("job_id"), "started_at": cur.get("started_at")}
        try:
            job = {"job_id": uuid.uuid4().hex[:8], "step": step, "status": "running",
                   "started_at": _now(), "finished_at": None, "result": None,
                   "error": None, "warnings": []}
            self.current = job
            self.thread = threading.Thread(target=self._run, args=(job, fn, args),
                                           daemon=True, name=f"refresh-{step}")
            self.thread.start()
        except Exception:
            self._lock.release()
            raise
        return dict(job), None

    def _run(self, job, fn, args):
        t0 = time.monotonic()
        summary, status, error = None, "failed", None
        try:
            result, summary = fn(job, *args)
            job["result"] = result
            status = "succeeded"
        except Exception as e:
            error = _redact(str(e)) or type(e).__name__
            logger.error("Refresh job %s failed: %s", job["step"], error)
        finally:
            finished_at = _now()
            duration_s = round(time.monotonic() - t0, 1)
            # Persist first, then publish the final status, then free the lock,
            # so a poller that sees the job finished also sees its last run.
            try:
                STATE.record_run(job["step"], {
                    "finished_at": finished_at, "status": status,
                    "summary": summary if status == "succeeded" else f"failed: {error}",
                    "result": job["result"], "error": error,
                    "warnings": list(job["warnings"]), "duration_s": duration_s,
                })
            except Exception as e:
                logger.error("Could not save refresh state: %s", _redact(str(e)))
            job.update(finished_at=finished_at, duration_s=duration_s, error=error, status=status)
            self._lock.release()

    def snapshot(self):
        return dict(self.current) if self.current else None


RUNNER = JobRunner()


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
TEAM_STATS_FAILED = ("TeamRankings scrape failed or incomplete; kept existing "
                     "team_stats_data.json (see server log).")


def run_stats_job(job):
    """Reload the last completed week from Sleeper and re-scrape team stats."""
    import save_to_db
    import team_stats
    from sqlalchemy import text
    from models import engine

    cfg = load_config()
    season, week = cfg["SEASON"], cfg["STATS_WEEK"]
    saved = save_to_db.save_stats_to_db(season, week)

    with engine.connect() as conn:
        gp_null = conn.execute(text(
            "SELECT COUNT(*) FROM player_weekly_stats WHERE season = :s AND week = :w "
            "AND season_type = :t AND gp IS NULL"), {"s": season, "w": week, "t": saved["season_type"]}).scalar()

    payload = None
    try:
        payload = team_stats.update_all_team_stats(season=season, output_path=team_stats.TEAM_STATS_PATH)
    except Exception as e:
        logger.error("Team stats refresh failed: %s", e)
    if payload:
        ts = {"ok": True, "season": payload.get("season"), "data_as_of": payload.get("data_as_of"),
              "scraped_at": payload.get("scraped_at"), "error": None}
    else:
        meta = team_stats.load_team_stats_meta()
        ts = {"ok": False, "season": meta.get("season"), "data_as_of": meta.get("data_as_of"),
              "scraped_at": meta.get("scraped_at"), "error": TEAM_STATS_FAILED}
        job["warnings"].append(TEAM_STATS_FAILED)

    result = {"season": season, "week": week, "season_type": saved["season_type"],
              "config_source": cfg.get("CONFIG_SOURCE"), "rows_saved": saved["rows_saved"],
              "rows_replaced": saved["rows_replaced"], "gp_null_rows": gp_null, "team_stats": ts}
    job["result"] = result
    if saved["rows_saved"] == 0:
        raise RuntimeError(f"Sleeper returned no stats for {season} week {week}; existing rows kept.")

    ts_text = (f"team stats as of {ts['data_as_of']}" if ts["ok"]
               else f"team stats FAILED (kept {ts['data_as_of']})")
    return result, f"{season} wk{week}: {saved['rows_saved']} rows; {ts_text}"


def odds_preview():
    """Free: upcoming games, estimated credits, remaining quota."""
    import odds_api

    cfg = load_config()
    days = cfg["ODDS_DAYS_AHEAD"]
    if not odds_api.API_KEYS:
        raise NoApiKeys(odds_api.NO_KEYS_MESSAGE)
    events, start, end, quota = odds_api.get_upcoming_events(days)
    try:
        STATE.set_quota(quota)
    except Exception as e:
        logger.error("Could not save quota: %s", _redact(str(e)))

    markets, regions = len(odds_api.VALID_MARKETS), 1
    estimated = len(events) * markets * regions
    remaining = quota.get("total_remaining")
    return {
        "season": cfg["SEASON"], "week": cfg["ODDS_WEEK"], "days_ahead": days,
        "window_start": start.isoformat(timespec="seconds"), "window_end": end.isoformat(timespec="seconds"),
        "games": [{"home_team": e.get("home_team"), "away_team": e.get("away_team"),
                   "commence_time": e.get("commence_time")} for e in events],
        "game_count": len(events), "markets": markets, "regions": regions,
        "estimated_credits": estimated,
        "estimate_note": "Upper bound: the API charges per market returned x regions.",
        "quota": quota,
        "enough_quota": None if remaining is None else remaining >= estimated,
    }


def run_odds_job(job, confirm_games):
    """Paid: fetch odds for the upcoming games (at most the confirmed game count)."""
    import odds_api

    cfg = load_config()
    result = odds_api.fetch_and_store_odds(days_ahead=cfg["ODDS_DAYS_AHEAD"], season=cfg["SEASON"],
                                           week=cfg["ODDS_WEEK"], max_games=confirm_games)
    if result.get("quota"):
        try:
            STATE.set_quota(result["quota"])
        except Exception as e:
            logger.error("Could not save quota: %s", _redact(str(e)))
    if result.get("events_failed"):
        job["warnings"].append(f"Failed games: {', '.join(result['events_failed'])}")
    left = (result.get("quota") or {}).get("total_remaining")
    summary = (f"{result['events_processed']}/{result['events_found']} games, "
               f"{result['credits_used']} credits, {left if left is not None else 'unknown'} left")
    return result, summary


def record_picks_run(success, count, flagged, model_version, error=None, duration_s=None):
    summary = (f"{count} players, {flagged} flagged (model {model_version})" if success
               else f"failed: {error}")
    STATE.record_run("picks", {
        "finished_at": _now(), "status": "succeeded" if success else "failed",
        "summary": summary, "result": {"count": count, "flagged": flagged, "model": model_version} if success else None,
        "error": None if success else error, "warnings": [], "duration_s": duration_s,
    })
