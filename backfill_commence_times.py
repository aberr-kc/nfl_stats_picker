# backfill_commence_times.py - fill odds.commence_time (ISO UTC kickoff) for
# rows saved before the column existed.
#
# Uses only the free /events endpoint (0 credits); never calls the paid odds
# endpoint. /events lists only upcoming and live games, so rows for games
# already played stay NULL (weather then shows "no kickoff time", neutral).
# Only UPDATEs rows whose commence_time is NULL. Idempotent; safe to rerun.
import sys

import requests
from sqlalchemy import text

import models
import odds_api  # importing runs the commence_time migration via models


def fetch_events():
    """Events from the first key that answers 200, or None."""
    for i, key in enumerate(odds_api.API_KEYS):
        try:
            resp = odds_api._get_free_events(key)
        except requests.RequestException as e:
            print(f"Events request failed with key {i + 1}: {odds_api.redact(e)}")
            continue
        if resp.status_code == 200:
            return resp.json()
        print(f"Events request failed with key {i + 1}: HTTP {resp.status_code}")
    return None


def backfill():
    if not odds_api.API_KEYS:
        sys.exit(odds_api.NO_KEYS_MESSAGE)
    events = fetch_events()
    if events is None:
        sys.exit("Events request failed for all keys; nothing updated.")
    print(f"{len(events)} events listed by /events")
    total = 0
    with models.engine.begin() as conn:
        for e in events:
            if not e.get("id") or not e.get("commence_time"):
                continue
            n = conn.execute(text(
                "UPDATE odds SET commence_time = :ct WHERE event_id = :eid AND commence_time IS NULL"),
                {"ct": e["commence_time"], "eid": e["id"]}).rowcount
            total += n
            print(f"{e.get('home_team')} vs {e.get('away_team')} {e['commence_time']}: {n} rows updated")
    print(f"{total} odds rows updated")


if __name__ == "__main__":
    backfill()
