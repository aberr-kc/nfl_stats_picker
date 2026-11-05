"""Verification launcher: runs the app on 127.0.0.1 with the paid Odds API call mocked.

    $env:NFL_STATS_DB=...; $env:NFL_TEAM_STATS_PATH=...; $env:NFL_REFRESH_STATE=...
    .venv\\Scripts\\python.exe tests\\live_refresh_server.py --port 8011

Refuses to start unless all three env vars point away from the repo's real
files. odds_api.call_odds_api (the only code path that spends credits) raises,
and odds_api.fetch_event_odds returns a canned response. The free /events
preview is real. Not used by the app.
"""
import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL = {"NFL_STATS_DB": "nfl_stats.db", "NFL_TEAM_STATS_PATH": "team_stats_data.json",
        "NFL_REFRESH_STATE": "refresh_state.json"}


def _same(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8011)
    args = parser.parse_args()

    for var, name in REAL.items():
        value = os.getenv(var)
        if not value:
            sys.exit(f"refusing to start: {var} is not set")
        if _same(value, os.path.join(REPO, name)):
            sys.exit(f"refusing to start: {var} points at the real {name}")

    os.chdir(REPO)
    sys.path.insert(0, REPO)

    import models
    import odds_api
    import team_stats

    def blocked(*a, **k):
        raise RuntimeError("paid call blocked in verification")

    mock_calls = {"n": 0}

    def mock_fetch_event_odds(event_id):
        mock_calls["n"] += 1
        return {"credits": 2, "remaining": None, "data": {"bookmakers": [{"title": "MockBook", "markets": [
            {"key": "player_reception_yds", "outcomes": [
                {"name": "Over", "description": "Mock Player", "point": 55.5, "price": 1.9},
                {"name": "Under", "description": "Mock Player", "point": 55.5, "price": 1.9}]},
            {"key": "totals", "outcomes": [
                {"name": "Over", "point": 44.5, "price": 1.91},
                {"name": "Under", "point": 44.5, "price": 1.91}]}]}]}}

    odds_api.call_odds_api = blocked
    odds_api.fetch_event_odds = mock_fetch_event_odds

    import app as app_module
    import refresh_jobs
    import uvicorn

    app_module.app.add_api_route("/__verify/mock_calls", lambda: {"mock_fetch_event_odds_calls": mock_calls["n"]})

    print(f"VERIFY models.DB_PATH={models.DB_PATH}", flush=True)
    print(f"VERIFY app engine={app_module.engine.url.database}", flush=True)
    print(f"VERIFY team_stats.TEAM_STATS_PATH={team_stats.TEAM_STATS_PATH}", flush=True)
    print(f"VERIFY refresh state={refresh_jobs.STATE.path}", flush=True)
    print("VERIFY paid call blocked, fetch_event_odds mocked", flush=True)
    uvicorn.run(app_module.app, host="127.0.0.1", port=args.port, reload=False)


if __name__ == "__main__":
    main()
