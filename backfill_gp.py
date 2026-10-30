# backfill_gp.py - fill player_weekly_stats.gp (Sleeper "games played") for
# rows saved before the column existed.
#
# Only UPDATEs gp on existing rows: re-inserting would restamp old rows with
# today's team. A player without a gp key in Sleeper's weekly stats did not
# play, so gp = 0. Idempotent; safe to rerun.
import time

import requests

import models  # runs the gp column migration on the absolute DB path
from sqlalchemy import text

SEASONS = {2025: range(1, 18)}  # 2025 weeks 1-17; the current season is added below


def fetch_gp(season, week):
    url = f"https://api.sleeper.app/v1/stats/nfl/regular/{season}/{week}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json() or {}


def backfill(season, week):
    data = fetch_gp(season, week)
    if not data:
        print(f"{season} wk{week}: Sleeper returned no data, skipped")
        return
    with models.engine.begin() as conn:
        ids = [r[0] for r in conn.execute(text(
            "SELECT DISTINCT player_id FROM player_weekly_stats "
            "WHERE season = :s AND week = :w AND season_type = 'regular'"), {"s": season, "w": week})]
        params = [{"gp": float((data.get(pid) or {}).get("gp") or 0), "pid": pid, "s": season, "w": week}
                  for pid in ids]
        if params:
            # Session-only TEMP table keyed on player_id, so one UPDATE per week
            # instead of one full-table scan per player (no index on the real table).
            conn.execute(text("CREATE TEMP TABLE IF NOT EXISTS gp_week (player_id TEXT PRIMARY KEY, gp REAL)"))
            conn.execute(text("DELETE FROM gp_week"))
            conn.execute(text("INSERT INTO gp_week (player_id, gp) VALUES (:pid, :gp)"), params)
            conn.execute(text(
                "UPDATE player_weekly_stats "
                "SET gp = (SELECT g.gp FROM gp_week g WHERE g.player_id = player_weekly_stats.player_id) "
                "WHERE season = :s AND week = :w AND season_type = 'regular'"), {"s": season, "w": week})
    played = sum(1 for p in params if p["gp"] > 0)
    print(f"{season} wk{week}: {len(params)} players updated, {played} with gp > 0")


if __name__ == "__main__":
    from pipeline_config import SEASON, STATS_WEEK
    seasons = dict(SEASONS)
    seasons[SEASON] = range(1, STATS_WEEK + 1)
    first = True
    for season, weeks in seasons.items():
        for week in weeks:
            if not first:
                time.sleep(1)
            first = False
            backfill(season, week)
