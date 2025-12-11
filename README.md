# NFL Stat Picks

A comprehensive NFL statistics analysis system that compares player performance against betting lines to identify value betting opportunities.

## Overview

This system fetches NFL player statistics, betting odds, and team defensive data to generate statistical picks by comparing 3-game player averages against sportsbook lines with probability calculations and matchup adjustments.

## Core Features

### Data Collection
- **Player Stats**: Fetches weekly player statistics from Sleeper API
- **Betting Odds**: Collects player prop odds from multiple sportsbooks via The Odds API
- **Team Stats**: Processes team offensive/defensive statistics from saved JSON data
- **Database Storage**: SQLite database for all historical data

### Statistical Analysis
- **3-Game Averages**: Uses recent 3-game performance instead of season averages for more current form
- **Standard Deviation**: Calculates variance in player performance for probability modeling
- **Threshold Flagging**: Identifies players whose averages exceed betting lines by configurable thresholds

### Advanced Adjustments

#### Matchup Adjustments
Player stats are adjusted based on opponent defensive performance vs league average:
```
Adjusted Stat = Player 3-Game Average × (Opponent Defense Stat ÷ League Average Defense Stat)
```

#### Opportunity Adjustments
- **Reception Share**: Calculates player's share of team receptions as proxy for target share
- **Game Script**: Adjusts projections based on spread (favorites run more, underdogs pass more)
- **Variance Scaling**: Adjusts standard deviation based on opportunity changes

#### Probability Calculations
Uses normal distribution with Z-score formula:
```
Z-score = (Betting Line - Player Average) ÷ Standard Deviation
Probability = 1 - Φ(Z-score)  [using error function for accuracy]
```

## File Structure

### Core Pipeline Files
- `pipeline_config.py` - Configuration settings and main pipeline runner
- `fetch_stats.py` - Fetches player stats from Sleeper API
- `save_to_db.py` - Saves weekly stats and odds to database
- `odds_api.py` - Fetches betting odds and spread data
- `test_thresholds.py` - Main analysis script with full adjustments
- `test_thresholds_new.py` - Clean API version for web interface

### Analysis & Calculation Files
- `Odds_vs_Stats_Check.py` - Core comparison logic and flagging
- `probability_calc.py` - Statistical probability calculations using erf function
- `team_stats.py` - Team statistics processing and league averages
- `target_share_calc.py` - Reception share calculations
- `opportunity_adjustment.py` - Opportunity-based stat adjustments
- `game_script_adjustment.py` - Spread-based game script adjustments

### Web Interface
- `app.py` - FastAPI backend with REST endpoints
- `index.html` - Frontend interface for viewing picks and player stats

### Data Files
- `nfl_stats.db` - Main SQLite database
- `team_stats_data.json` - Team offensive/defensive statistics

## Configuration

### Season/Week Settings
```python
SEASON = 2025
STATS_WEEK = 11          # Week to fetch player stats
ODDS_WEEK = 12           # Week to fetch betting odds
COMPARISON_WEEK = 12     # Week for analysis
```

### Flagging Thresholds
```python
THRESHOLDS = {
    "receiving_yards": 25,   # Flag if player avg exceeds line by 25+ yards
    "passing_yards": 35,     # Flag if player avg exceeds line by 35+ yards
    "rushing_yards": 25,     # Flag if player avg exceeds line by 25+ yards
    "receptions": 1.5,       # Flag if player avg exceeds line by 1.5+ receptions
    "passing_tds": 2,        # Flag if player avg exceeds line by 2+ TDs
    "rushing_tds": 1         # Flag if player avg exceeds line by 1+ TDs
}
```

## Usage

### Run Complete Pipeline
```bash
python pipeline_config.py
```

### Start Web Interface
```bash
python app.py
```
Then visit `http://localhost:8000` to view the interface.

### Generate Picks Only
```bash
python test_thresholds.py --json
```

## Key Calculations

### Adjusted Statistics Formula
For receiving/passing yards:
```
Adjusted Yards = Player 3-Game Avg × (Opponent Pass Defense ÷ League Avg Pass Defense)
```

For rushing yards:
```
Adjusted Yards = Player 3-Game Avg × (Opponent Rush Defense ÷ League Avg Rush Defense)
```

### Game Script Adjustments
- **Favorites (-3.5 or more)**: +5% rushing stats, -3% receiving stats
- **Underdogs (+3.5 or more)**: -5% rushing stats, +5% receiving stats
- **Pick'em games**: No adjustment

### Probability Display
Results show probability in "X% Over | Y% Under" format where:
- **Over**: Probability player exceeds the betting line
- **Under**: Probability player stays under the betting line

## Output

The system generates picks showing:
- Player name and matchup
- Stat type and betting line
- 3-game average vs adjusted average
- Probability percentages
- Adjustment explanations
- Bookmaker and line details

Players and stats are sorted by highest probability for optimal betting opportunities.

## Database Schema

### player_weekly_stats
- Player performance data by week
- Includes all major stats (passing, rushing, receiving)

### odds
- Betting lines from multiple sportsbooks
- Player props and game spreads/totals

## Dependencies

- SQLAlchemy - Database operations
- Pandas - Data manipulation
- FastAPI - Web framework
- Requests - API calls
- Math - Statistical calculations