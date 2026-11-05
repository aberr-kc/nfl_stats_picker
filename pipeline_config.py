# pipeline_config.py - Central configuration and pipeline runner
#
# Season and week are worked out automatically. Priority order:
#   1. Env vars NFL_SEASON / NFL_WEEK (e.g. $env:NFL_WEEK='16')
#   2. SEASON_OVERRIDE / WEEK_OVERRIDE below (set to a number to pin)
#   3. Sleeper https://api.sleeper.app/v1/state/nfl
#   4. FALLBACK_SEASON / FALLBACK_WEEK if Sleeper is unreachable
# Sleeper's "week" is the current/upcoming week. Odds and comparison use that
# week; stats use the last completed week (week - 1).
#
# Note: test_thresholds.read_config_from_file() exec()s this file on every
# request, so don't rely on __file__ here and don't print at module level.
import os
import requests

SEASON_OVERRIDE = None
WEEK_OVERRIDE = None

FALLBACK_SEASON = 2026
FALLBACK_WEEK = 8


def _sleeper_state():
    """Return (season, week) from Sleeper, or None on any failure."""
    try:
        resp = requests.get("https://api.sleeper.app/v1/state/nfl", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return int(data["season"]), int(data["week"])
    except Exception:
        return None


def _resolve_season_week():
    env_season, env_week = os.getenv("NFL_SEASON"), os.getenv("NFL_WEEK")
    if env_season and env_week:
        return int(env_season), int(env_week), "env"
    if SEASON_OVERRIDE is not None and WEEK_OVERRIDE is not None:
        return SEASON_OVERRIDE, WEEK_OVERRIDE, "override"
    state = _sleeper_state()
    if state:
        return state[0], state[1], "sleeper"
    return FALLBACK_SEASON, FALLBACK_WEEK, "fallback"


# Season and week configuration
SEASON, CURRENT_WEEK, CONFIG_SOURCE = _resolve_season_week()

# Odds configuration - use current week
ODDS_WEEK = CURRENT_WEEK
ODDS_DAYS_AHEAD = 2

# Stats configuration - use previous (last completed) week
STATS_WEEK = max(CURRENT_WEEK - 1, 1)

# Comparison configuration - use current week
COMPARISON_WEEK = CURRENT_WEEK

# Known players with incomplete data (to skip in analysis)
INCOMPLETE_DATA_PLAYERS = [
    "test"
]

# Thresholds for flagging
THRESHOLDS = {
    "receiving_yards": 20,
    "passing_yards": 30,
    "rushing_yards": 18,
    "receptions": 1.2,
    "passing_tds": 0.6,
    "rushing_tds": 0.4
}

# Live picks model: 'v1' (3-game average + fixed thresholds) or 'v2'
# (calibrated model anchored to the market, see model_v2.py). Switched to 'v2'
# only in a separate commit after backtest.py's gate passes and
# model_v2_params.json is written. NFL_MODEL_VERSION overrides it.
MODEL_VERSION = 'v2'
# v2 flag policy: minimum edge (probability points / 100) over the
# vig-inclusive price, and minimum games played in the window.
V2_EDGE_MARGIN = 0.03
V2_MIN_GAMES_FOR_FLAG = 3

def run_pipeline():
    """Run the complete data pipeline"""
    
    print(f"=== Running Pipeline for Season {SEASON} (config source: {CONFIG_SOURCE}) ===")
    print(f"Odds Week: {ODDS_WEEK}, Stats Week: {STATS_WEEK}, Comparison Week: {COMPARISON_WEEK}")
    
    # Step 1: Fetch and save stats
    print("\n1. Fetching and saving stats...")
    from save_to_db import save_stats_to_db
    save_stats_to_db(SEASON, STATS_WEEK) 
    
    # Step 2: Fetch and save odds
    print("\n2. Fetching and saving odds...")
    from odds_api import fetch_and_store_odds
    result = fetch_and_store_odds(days_ahead=ODDS_DAYS_AHEAD, season=SEASON, week=ODDS_WEEK)
    print(f"Events processed: {result['events_processed']}")
    
    # Step 3: Run threshold analysis
    print("\n3. Running threshold analysis...")
    import subprocess
    import sys
    # Use the same interpreter (e.g. the .venv) that is running this pipeline.
    subprocess.run([sys.executable, "test_thresholds.py"])

if __name__ == "__main__":
    run_pipeline()