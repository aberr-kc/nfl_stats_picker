"""Live checks against tests/live_refresh_server.py (paid odds call mocked there).

    .venv\\Scripts\\python.exe tests\\live_refresh_check.py http://127.0.0.1:8011 --log <server log>

Uses the same NFL_STATS_DB / NFL_TEAM_STATS_PATH env vars as the server to
inspect the temp copies. Prints one PASS/FAIL line per check; exit 1 on any FAIL.
Never prints API key values.
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

import requests

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H = {"X-NFL-Refresh": "1"}
FAILS = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}: {name}{(' - ' + detail) if detail else ''}", flush=True)
    if not cond:
        FAILS.append(name)


def wait_job(base, job_id, timeout=240):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = requests.get(f"{base}/refresh/status", timeout=10).json()
        job = st.get("job") or {}
        if job.get("job_id") == job_id and job.get("status") != "running" and not st["running"]:
            return st
        time.sleep(1)
    raise TimeoutError(f"job {job_id} did not finish in {timeout}s")


def read_logs(paths):
    return "\n".join(open(p, encoding="utf-8", errors="replace").read() for p in paths)


def db():
    return sqlite3.connect(os.environ["NFL_STATS_DB"])


def run_stats(base, label):
    r = requests.post(f"{base}/refresh/stats", headers=H, timeout=10)
    check(f"{label}: POST /refresh/stats -> 202", r.status_code == 202, f"{r.status_code} {r.text[:200]}")
    t0 = time.time()
    st = wait_job(base, r.json()["job_id"])
    job = st["job"]
    print(f"    {label}: {round(time.time() - t0, 1)}s status={job['status']} error={job['error']} "
          f"warnings={job['warnings']} result={json.dumps(job['result'])}", flush=True)
    return job, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default="http://127.0.0.1:8011")
    ap.add_argument("--log", required=True, action="append", help="server stdout/stderr log (repeatable)")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    # 3. server uses the temp DB
    r = requests.get(f"{base}/debug/tables", timeout=10)
    check("GET /debug/tables works", r.status_code == 200 and "tables" in r.json(), r.text[:200])
    log = read_logs(args.log)
    db_line = next((l for l in log.splitlines() if l.startswith("VERIFY models.DB_PATH=")), "")
    check("server models.DB_PATH is the temp copy",
          os.path.normcase(db_line.split("=", 1)[-1].strip()) == os.path.normcase(os.path.abspath(os.environ["NFL_STATS_DB"])),
          db_line)

    # 4. stats twice
    with db() as conn:
        total_before = conn.execute("SELECT COUNT(*) FROM player_weekly_stats").fetchone()[0]
    job1, _ = run_stats(base, "stats run 1")
    with db() as conn:
        total_mid = conn.execute("SELECT COUNT(*) FROM player_weekly_stats").fetchone()[0]
    job2, st2 = run_stats(base, "stats run 2")
    with db() as conn:
        total_after = conn.execute("SELECT COUNT(*) FROM player_weekly_stats").fetchone()[0]
    r1, r2 = job1["result"] or {}, job2["result"] or {}
    check("both stats jobs succeeded", job1["status"] == job2["status"] == "succeeded")
    check("same season/week both runs", (r1.get("season"), r1.get("week")) == (r2.get("season"), r2.get("week")),
          f"{r1.get('season')} wk{r1.get('week')}")
    check("rows_saved equal", r1.get("rows_saved") == r2.get("rows_saved") and (r1.get("rows_saved") or 0) > 0,
          f"{r1.get('rows_saved')} / {r2.get('rows_saved')}")
    check("second run rows_replaced == rows_saved", r2.get("rows_replaced") == r2.get("rows_saved"),
          f"{r2.get('rows_replaced')}")
    check("gp_null_rows == 0", r2.get("gp_null_rows") == 0, f"{r2.get('gp_null_rows')}")
    check("table total unchanged by second run", total_mid == total_after,
          f"before={total_before} after1={total_mid} after2={total_after}")
    ts = r2.get("team_stats") or {}
    check("team stats refreshed", ts.get("ok") is True and bool(ts.get("data_as_of")), json.dumps(ts))
    with db() as conn:
        dups = conn.execute("SELECT COUNT(*) FROM (SELECT player_id,season,week,season_type,COUNT(*) c "
                            "FROM player_weekly_stats GROUP BY 1,2,3,4 HAVING c>1)").fetchone()[0]
        week_rows = conn.execute("SELECT COUNT(*) FROM player_weekly_stats WHERE season=? AND week=? AND season_type=?",
                                 (r2.get("season"), r2.get("week"), r2.get("season_type"))).fetchone()[0]
        idx = [row[1] for row in conn.execute("PRAGMA index_list(player_weekly_stats)")]
    check("zero duplicate (player_id, season, week, season_type) groups", dups == 0, str(dups))
    check("week row count == rows_saved", week_rows == r2.get("rows_saved"), str(week_rows))
    check("unique index exists", "ux_player_weekly_stats_key" in idx)
    with open(os.environ["NFL_TEAM_STATS_PATH"], encoding="utf-8") as f:
        scraped_at = json.load(f).get("scraped_at")
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(scraped_at)).total_seconds() if scraped_at else 1e9
    check("temp team_stats_data.json has a fresh scraped_at", age < 600, f"{scraped_at}")
    check("last_runs.stats recorded", (st2["last_runs"].get("stats") or {}).get("status") == "succeeded",
          (st2["last_runs"].get("stats") or {}).get("summary", ""))
    print(f"    stats summary: {(st2['last_runs'].get('stats') or {}).get('summary')}", flush=True)

    # 5. 409 while a stats job runs
    r = requests.post(f"{base}/refresh/stats", headers=H, timeout=10)
    first_id = r.json().get("job_id")
    b1 = requests.post(f"{base}/refresh/stats", headers=H, timeout=10)
    b2 = requests.post(f"{base}/refresh/odds", headers=H, json={"confirm_games": 0}, timeout=10)
    check("second POST /refresh/stats -> 409 running_step stats",
          b1.status_code == 409 and b1.json().get("running_step") == "stats", f"{b1.status_code} {b1.text[:150]}")
    check("POST /refresh/odds during stats -> 409 running_step stats",
          b2.status_code == 409 and b2.json().get("running_step") == "stats", f"{b2.status_code} {b2.text[:150]}")
    wait_job(base, first_id)

    # 8. live gate checks
    r = requests.post(f"{base}/refresh/stats", headers={"X-NFL-Refresh": "1", "Host": "evil.example:8011"}, timeout=10)
    check("Host: evil.example -> 403", r.status_code == 403, r.text[:150])
    r = requests.post(f"{base}/refresh/stats", timeout=10)
    check("missing X-NFL-Refresh -> 403", r.status_code == 403, r.text[:150])

    # 6. real free preview
    r = requests.get(f"{base}/refresh/odds/preview", headers=H, timeout=60)
    check("GET /refresh/odds/preview -> 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    p = r.json() if r.status_code == 200 else {}
    n = p.get("game_count", -1)
    q = p.get("quota") or {}
    print(f"    preview: season {p.get('season')} wk{p.get('week')} days_ahead={p.get('days_ahead')} games={n} "
          f"est={p.get('estimated_credits')} quota={json.dumps(q)} enough={p.get('enough_quota')}", flush=True)
    for g in p.get("games", []):
        print(f"      {g['away_team']} @ {g['home_team']} {g['commence_time']}", flush=True)
    check("game_count == len(games)", n == len(p.get("games", [])))
    check("estimated_credits == games x 9", p.get("estimated_credits") == n * 9)
    check("quota is live with an int total_remaining",
          q.get("source") == "live" and isinstance(q.get("total_remaining"), int), json.dumps(q))

    # 9a. picks DOM check on the copied real odds (before the mocked odds replace them)
    out = subprocess.run(["node", os.path.join(REPO, "tests", "check_picks_dom.js"), base],
                         capture_output=True, text=True, timeout=600)
    print("    " + out.stdout.strip().replace("\n", "\n    "), flush=True)
    check("check_picks_dom.js -> DOM CHECK PASSED", "DOM CHECK PASSED" in out.stdout)

    # 7. odds POST with the mocked paid call
    calls0 = requests.get(f"{base}/__verify/mock_calls", timeout=10).json()["mock_fetch_event_odds_calls"]
    season, week = p.get("season"), p.get("week")
    with db() as conn:
        odds_before = conn.execute("SELECT COUNT(*) FROM odds WHERE season=? AND week=?", (season, week)).fetchone()[0]
    if n > 0:
        r = requests.post(f"{base}/refresh/odds", headers=H, json={"confirm_games": 0}, timeout=10)
        st = wait_job(base, r.json()["job_id"])
        check("confirm_games=0 with games -> job failed 'changed since preview'",
              st["job"]["status"] == "failed" and "since preview" in (st["job"]["error"] or ""), st["job"]["error"] or "")
        calls1 = requests.get(f"{base}/__verify/mock_calls", timeout=10).json()["mock_fetch_event_odds_calls"]
        check("no mock paid call on the aborted job", calls1 == calls0)
    r = requests.post(f"{base}/refresh/odds", headers=H, json={"confirm_games": max(n, 0)}, timeout=10)
    check("POST /refresh/odds -> 202", r.status_code == 202, f"{r.status_code} {r.text[:200]}")
    st = wait_job(base, r.json()["job_id"])
    res = st["job"]["result"] or {}
    print(f"    odds job: status={st['job']['status']} error={st['job']['error']} result={json.dumps(res)}", flush=True)
    calls2 = requests.get(f"{base}/__verify/mock_calls", timeout=10).json()["mock_fetch_event_odds_calls"]
    check("odds job succeeded", st["job"]["status"] == "succeeded")
    check("events_processed == game_count", res.get("events_processed") == n, str(res.get("events_processed")))
    check("credits_used == 2 x games (mock header)", res.get("credits_used") == 2 * n, str(res.get("credits_used")))
    check("mock call count == game_count", calls2 - calls0 == n, str(calls2 - calls0))
    with db() as conn:
        rows = conn.execute("SELECT player_id, bookmaker FROM odds WHERE season=? AND week=?", (season, week)).fetchall()
    if n > 0:
        # save_odds upserts on (player, market, book, outcome, season, week), so the same
        # mock player in every game collapses to 4 rows; 4 outcomes saved per game.
        check("week odds rows are only the mock rows",
              len(rows) == 4 and all(b == "MockBook" for _, b in rows) and res.get("odds_rows_saved") == 4 * n
              and res.get("rows_cleared") == odds_before,
              f"{len(rows)} rows, {res.get('odds_rows_saved')} outcomes saved, cleared {res.get('rows_cleared')} (before {odds_before})")
    else:
        check("zero games: odds rows untouched", len(rows) == odds_before, f"{len(rows)} == {odds_before}")
    print(f"    odds summary: {(st['last_runs'].get('odds') or {}).get('summary')}", flush=True)

    # 9b. picks after the odds job
    r = requests.get(f"{base}/generate-picks", timeout=600)
    body = r.json()
    check("GET /generate-picks success", body.get("success") is True and set(body) == {"success", "players", "count", "model"},
          f"count={body.get('count')} error={body.get('error')}")
    st = requests.get(f"{base}/refresh/status", timeout=10).json()
    check("last_runs.picks recorded", bool(st["last_runs"].get("picks")), (st["last_runs"].get("picks") or {}).get("summary", ""))

    # 6b. log hygiene: no key text, no paid call reached the network path
    keys = [k.strip() for k in os.getenv("ODDS_API_KEYS", "").split(",") if k.strip()]
    try:
        from dotenv import dotenv_values
        keys += [k.strip() for k in (dotenv_values(os.path.join(REPO, ".env")).get("ODDS_API_KEYS") or "").split(",") if k.strip()]
    except ImportError:
        pass
    log = read_logs(args.log)
    state_text = open(os.environ["NFL_REFRESH_STATE"], encoding="utf-8").read()
    check("server log contains no API key", sum(k in log for k in keys) == 0, f"{len(keys)} keys checked")
    check("refresh_state.json contains no API key", sum(k in state_text for k in keys) == 0)
    check("blocked paid call never reached", "paid call blocked in verification" not in log)
    check("no apiKey= in server log", "apiKey=" not in log)

    print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nALL LIVE CHECKS PASSED", flush=True)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
