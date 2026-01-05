# pipeline_config.py - Central configuration and pipeline runner

# Season and week configuration
SEASON = 2025
CURRENT_WEEK = 18

# Odds configuration - use current week
ODDS_WEEK = 18
ODDS_DAYS_AHEAD = 2



# Stats configuration  - use previous week
STATS_WEEK = 17

# Comparison configuration - use current week
COMPARISON_WEEK = 18

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

def run_pipeline():
    """Run the complete data pipeline"""
    
    print(f"=== Running Pipeline for Season {SEASON} ===")
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
    subprocess.run(["python", "test_thresholds.py"])

if __name__ == "__main__":
    run_pipeline()