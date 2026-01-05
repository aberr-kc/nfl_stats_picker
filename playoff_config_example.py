# playoff_config_example.py - Example configuration for playoff weeks

# For Wild Card Round (Playoff Week 1)
SEASON = 2025
STATS_WEEK = 1
SEASON_TYPE = 'playoffs'
COMPARISON_WEEK = 1
COMPARISON_SEASON_TYPE = 'playoffs'
ODDS_WEEK = 1  # Assuming odds continue with playoff week numbers

# NFL Schedule Constants
REGULAR_SEASON_WEEKS = 18
PLAYOFF_WEEKS = {
    1: 'Wild Card',
    2: 'Divisional', 
    3: 'Conference Championship',
    4: 'Super Bowl'
}

def get_season_info(week, season_type='regular'):
    """Get human-readable season information"""
    if season_type == 'playoffs':
        return f"Playoffs {PLAYOFF_WEEKS.get(week, f'Week {week}')}"
    else:
        return f"Week {week}"

print(f"""
=== NFL Playoff Configuration ===

To transition to playoffs, update pipeline_config.py:

1. Add SEASON_TYPE = 'playoffs'
2. Set STATS_WEEK to playoff week (1-4)
3. Add COMPARISON_SEASON_TYPE = 'playoffs'
4. Set COMPARISON_WEEK to playoff week

Playoff Week Structure:
- Week 1: Wild Card Round
- Week 2: Divisional Round  
- Week 3: Conference Championship
- Week 4: Super Bowl

Current Config:
- Season: {SEASON}
- Stats Week: {STATS_WEEK} ({SEASON_TYPE})
- Comparison Week: {COMPARISON_WEEK} ({COMPARISON_SEASON_TYPE})

Database Changes:
- Added 'season_type' column to player_weekly_stats, odds, and weather tables
- Stats are stored separately for regular season and playoffs
- Week numbers reset to 1-4 for playoffs

Example Usage:
python save_to_db.py  # Will use playoff config
python test_thresholds_combined.py  # Will analyze playoff data
""")