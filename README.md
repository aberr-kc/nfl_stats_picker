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

#### Weather
Display only: weather changes the "Adjusted" value and its explanation, never the flag rule or the probability.
- **Source**: [Open-Meteo](https://open-meteo.com) (free, no API key). Forecast API for upcoming and recent games, historical archive API for older games. Values are for the hour nearest kickoff: temperature (°C), wind (km/h) and the WMO weather code, mapped to a condition (rain/snow trigger the precipitation factor).
- **Location**: the home team's stadium from `stadiums.py` (home = first team in the odds event name, "Home vs Away"). Dome and retractable-roof stadiums get no weather adjustment.
- **Kickoff time**: `odds.commence_time`, saved on every odds fetch. For rows saved before that column existed, `backfill_commence_times.py` fills it from the free `/events` endpoint (0 credits; only upcoming/live games are listed, so older weeks stay without a kickoff time and get no weather adjustment).
- **Caching**: in memory per (home team, kickoff hour): past games for the server's lifetime, forecasts for 1 hour, failures for 10 minutes. Any failure (network, missing data, unknown team, no kickoff time) is neutral and logged as a warning.
- **Known limitation**: neutral-site and international games can't be detected from the odds data (no venue), so they use the designated home team's stadium.
- **Thresholds**: the factors in `weather_adjustments.py` are unchanged. They look aggressive (windy from 15 km/h, cold below 10 °C); consider higher wind thresholds (about 25/40 km/h) and a smaller cold penalty, calibrated against backtests.

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
.\.venv\Scripts\python.exe run_local.py
```
Then visit `http://localhost:8000` to view the interface.

### Weekly workflow
Start the server with `.\.venv\Scripts\python.exe run_local.py` (binds 127.0.0.1; add `--host 0.0.0.0` to share on your LAN), open `http://localhost:8000` and use the three buttons in order:

1. **Refresh stats (free)**: reloads the last completed week of player stats from Sleeper and re-scrapes TeamRankings team stats. Takes about 15-30 s and is safe to rerun (the week is replaced, never duplicated).
2. **Fetch odds (uses credits)**: first shows the games in the next `ODDS_DAYS_AHEAD` days, the estimated cost (games × 9 markets × 1 region, an upper bound) and the remaining Odds API quota. Odds are fetched only after you confirm.
3. **Generate picks**: builds picks from the data already in the DB (no API calls).

Each button shows its last run time and result, saved in `refresh_state.json`. Buttons 1 and 2 only work from the computer running the server unless you set `ALLOW_REMOTE_REFRESH=1`.

Terminal equivalents:
```bash
.\.venv\Scripts\python.exe save_to_db.py        # 1. stats (Sleeper)
.\.venv\Scripts\python.exe team_stats.py        # 1. team stats (TeamRankings)
.\.venv\Scripts\python.exe odds_api.py          # 2. odds (spends credits, no confirmation)
.\.venv\Scripts\python.exe test_thresholds.py   # 3. picks (add --json for JSON)
.\.venv\Scripts\python.exe pipeline_config.py   # all three in a row
```

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