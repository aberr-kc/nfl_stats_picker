# check_thresholds.py
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from Odds_vs_Stats_Check import check_stat_against_odds, compute_player_stats
import traceback

DB_PATH = "sqlite:///nfl_stats.db"
engine = create_engine(DB_PATH)


def get_recent_3_game_stats(year: int, player_display_name: str, current_week: int):
    """
    Pull recent player stats and compute rolling averages/std dev for last 3 games.
    Special-case handling: if only 1 game exists, use raw values with std=0.
    Now includes reception share calculations.
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT *
                FROM player_weekly_stats
                WHERE season = :year 
                  AND player_display_name = :player
                  AND week <= :current_week
                ORDER BY CAST(week AS INTEGER) DESC
                LIMIT 3
            """), {"year": year, "player": player_display_name, "current_week": current_week}).fetchall()

            if not result:
                return None

            rows = [dict(r._mapping) for r in result]

            # ✅ If only 1 game → just return raw stats
            if len(rows) == 1:
                single = rows[0]
                avg = {k: float(v) for k, v in single.items() if isinstance(v, (int, float))}
                stats = {"avg": avg, "std": {k: 0.0 for k in avg}, "weekly": rows}
            else:
                # ✅ Otherwise use the shared averaging function
                stats = compute_player_stats(rows)
                stats["weekly"] = rows
            
            # Add reception share calculation
            try:
                from target_share_calc import calculate_team_totals, calculate_player_reception_share
                
                # Get player's team
                player_team = rows[0].get('team')
                if player_team:
                    # Calculate team totals for the weeks this player played
                    weeks_played = [row['week'] for row in rows if row.get('week')]
                    if weeks_played:
                        team_totals = calculate_team_totals(year, weeks_played)
                        shares = calculate_player_reception_share(stats, team_totals, player_team)
                        stats["reception_share"] = shares["reception_share"]
                        stats["rushing_opportunity"] = shares["rushing_opportunity"]
            except Exception as e:
                # Don't fail if reception share calculation fails
                stats["reception_share"] = 0
                stats["rushing_opportunity"] = 0
            
            return stats

    except SQLAlchemyError as e:
        print(f"Database error fetching stats for {player_display_name}: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error fetching stats for {player_display_name}: {e}")
        return None


def get_weekly_breakdown(weekly_data, stat_name):
    """Get weekly breakdown for a specific stat"""
    breakdown = []
    for week_data in weekly_data[-5:]:  # Last 5 weeks
        week = week_data.get('week', 'N/A')
        value = week_data.get(stat_name, 0)
        breakdown.append(f"W{week}: {value}")
    return ", ".join(breakdown)


def get_odds_for_player(player_display_name: str, season=None, week=None):
    """Fetch all odds for a player from your odds table for current week only"""
    try:
        # Use provided values or read from config
        if season is None or week is None:
            config = read_config_from_file()
            season = season or config['SEASON']
            week = week or config['COMPARISON_WEEK']
            
        with engine.connect() as conn:
            # Try multiple name variations to handle formatting differences
            name_variations = [
                player_display_name,  # Original name
                player_display_name.replace('.', ''),  # Remove periods: A.J. Brown -> AJ Brown
                player_display_name.replace(' Jr.', ''),  # Remove Jr.
                player_display_name.replace(' Sr.', ''),  # Remove Sr.
            ]
            
            for name_variant in name_variations:
                result = conn.execute(text("""
                    SELECT market, line, bookmaker, event_name
                    FROM odds
                    WHERE player_id = :custom_id
                    AND season = :season
                    AND week = :week
                """), {"custom_id": f"custom_{name_variant}", "season": season, "week": week}).mappings().all()
                
                if result:
                    return [dict(row) for row in result]
            
            return []
    except SQLAlchemyError as e:
        print(f"Database error fetching odds for {player_display_name}: {e}")
        return []
    except Exception as e:
        print(f"Unexpected error fetching odds for {player_display_name}: {e}")
        return []


def read_config_from_file():
    """Read config values directly from file to avoid caching"""
    config = {}
    with open('pipeline_config.py', 'r') as f:
        content = f.read()
        # amazonq-ignore-next-line
        exec(content, config)
    return config

def get_flagged_players_json_updated():
    """Return flagged players as JSON for API use"""
    import json
    
    config = read_config_from_file()
    SEASON = config['SEASON']
    COMPARISON_WEEK = config['COMPARISON_WEEK']
    THRESHOLDS = config['THRESHOLDS']
    INCOMPLETE_DATA_PLAYERS = config['INCOMPLETE_DATA_PLAYERS']
    print(f"Generating picks for Season={SEASON}, Week={COMPARISON_WEEK} (config source: {config.get('CONFIG_SOURCE', 'unknown')})")
    
    flagged_players = []
    
    try:
        with engine.connect() as conn:
            players = conn.execute(text("""
                SELECT DISTINCT player_display_name
                FROM player_weekly_stats
                WHERE season = :year
            """), {"year": SEASON}).fetchall()
    except Exception as e:
        print(f"Error in get_flagged_players_json: {e}")
        import traceback
        traceback.print_exc()
        return []
    
    players_checked = 0
    players_with_stats = 0
    players_with_odds = 0
    
    for row in players:
        player_display_name = row[0]
        players_checked += 1
        
        try:
            player_stats = get_recent_3_game_stats(SEASON, player_display_name, current_week=COMPARISON_WEEK)
            if not player_stats:
                continue

            has_meaningful_stats = any(v > 0 for v in player_stats["avg"].values() if isinstance(v, (int, float)))
            if not has_meaningful_stats or player_display_name in INCOMPLETE_DATA_PLAYERS:
                continue
            
            players_with_stats += 1

            odds = get_odds_for_player(player_display_name)
            if not odds:
                if players_with_odds < 5:  # Debug first few
                    print(f"DEBUG: No odds for {player_display_name}")
                continue
            
            players_with_odds += 1

            # Calculate adjusted stats before flagging
            try:
                from team_stats import get_team_stats_for_player, get_league_defensive_averages
                from weather_adjustments import get_weather_adjustments, format_weather_explanation
                from weather_api import get_weather_for_game
                
                if odds and odds[0].get('event_name'):
                    event_name = odds[0]['event_name']
                    if ' vs ' in event_name:
                        teams = event_name.split(' vs ')
                        team1 = teams[0].strip()
                        team2 = teams[1].strip()
                        
                        # Get weather data
                        weather_data = get_weather_for_game(team1, team2)
                        weather_adjustments = get_weather_adjustments(
                            weather_data['temperature'],
                            weather_data['wind_speed'], 
                            weather_data['conditions']
                        )
                        
                        with engine.connect() as conn:
                            team_result = conn.execute(text("""
                                SELECT team FROM player_weekly_stats 
                                WHERE player_display_name = :player 
                                LIMIT 1
                            """), {"player": player_display_name}).fetchone()
                            if team_result:
                                player_team = team_result[0]
                                
                                abbrev_to_full_name = {
                                    'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens',
                                    'BUF': 'Buffalo Bills', 'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears',
                                    'CIN': 'Cincinnati Bengals', 'CLE': 'Cleveland Browns', 'DAL': 'Dallas Cowboys',
                                    'DEN': 'Denver Broncos', 'DET': 'Detroit Lions', 'GB': 'Green Bay Packers',
                                    'HOU': 'Houston Texans', 'IND': 'Indianapolis Colts', 'JAX': 'Jacksonville Jaguars',
                                    'KC': 'Kansas City Chiefs', 'LV': 'Las Vegas Raiders', 'LAC': 'Los Angeles Chargers',
                                    'LAR': 'Los Angeles Rams', 'MIA': 'Miami Dolphins', 'MIN': 'Minnesota Vikings',
                                    'NE': 'New England Patriots', 'NO': 'New Orleans Saints', 'NYG': 'New York Giants',
                                    'NYJ': 'New York Jets', 'PHI': 'Philadelphia Eagles', 'PIT': 'Pittsburgh Steelers',
                                    'SF': 'San Francisco 49ers', 'SEA': 'Seattle Seahawks', 'TB': 'Tampa Bay Buccaneers',
                                    'TEN': 'Tennessee Titans', 'WAS': 'Washington Commanders'
                                }
                                
                                player_team_full = abbrev_to_full_name.get(player_team, player_team)
                                
                                opponent_team = None
                                if player_team_full in team1 or player_team in team1:
                                    opponent_team = team2
                                elif player_team_full in team2 or player_team in team2:
                                    opponent_team = team1
                                
                                if opponent_team:
                                    # Create comprehensive team mappings
                                    team_mappings = {
                                        # Full names to abbreviations
                                        'arizona cardinals': 'ARI', 'atlanta falcons': 'ATL', 'baltimore ravens': 'BAL',
                                        'buffalo bills': 'BUF', 'carolina panthers': 'CAR', 'chicago bears': 'CHI',
                                        'cincinnati bengals': 'CIN', 'cleveland browns': 'CLE', 'dallas cowboys': 'DAL',
                                        'denver broncos': 'DEN', 'detroit lions': 'DET', 'green bay packers': 'GB',
                                        'houston texans': 'HOU', 'indianapolis colts': 'IND', 'jacksonville jaguars': 'JAX',
                                        'kansas city chiefs': 'KC', 'las vegas raiders': 'LV', 'los angeles chargers': 'LAC',
                                        'los angeles rams': 'LAR', 'miami dolphins': 'MIA', 'minnesota vikings': 'MIN',
                                        'new england patriots': 'NE', 'new orleans saints': 'NO', 'new york giants': 'NYG',
                                        'new york jets': 'NYJ', 'philadelphia eagles': 'PHI', 'pittsburgh steelers': 'PIT',
                                        'san francisco 49ers': 'SF', 'seattle seahawks': 'SEA', 'tampa bay buccaneers': 'TB',
                                        'tennessee titans': 'TEN', 'washington commanders': 'WAS',
                                        # Abbreviations to full names
                                        'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens',
                                        'BUF': 'Buffalo Bills', 'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears',
                                        'CIN': 'Cincinnati Bengals', 'CLE': 'Cleveland Browns', 'DAL': 'Dallas Cowboys',
                                        'DEN': 'Denver Broncos', 'DET': 'Detroit Lions', 'GB': 'Green Bay Packers',
                                        'HOU': 'Houston Texans', 'IND': 'Indianapolis Colts', 'JAX': 'Jacksonville Jaguars',
                                        'KC': 'Kansas City Chiefs', 'LV': 'Las Vegas Raiders', 'LAC': 'Los Angeles Chargers',
                                        'LAR': 'Los Angeles Rams', 'MIA': 'Miami Dolphins', 'MIN': 'Minnesota Vikings',
                                        'NE': 'New England Patriots', 'NO': 'New Orleans Saints', 'NYG': 'New York Giants',
                                        'NYJ': 'New York Jets', 'PHI': 'Philadelphia Eagles', 'PIT': 'Pittsburgh Steelers',
                                        'SF': 'San Francisco 49ers', 'SEA': 'Seattle Seahawks', 'TB': 'Tampa Bay Buccaneers',
                                        'TEN': 'Tennessee Titans', 'WAS': 'Washington Commanders'
                                    }
                                    
                                    # Find opponent team with better matching logic
                                    opponent_team = None
                                    player_team_full = team_mappings.get(player_team, player_team)
                                    
                                    # Try multiple matching approaches
                                    for team_option in [team1, team2]:
                                        # Check if player team matches this option
                                        team_matches = (
                                            player_team.upper() in team_option.upper() or
                                            team_option.upper() in player_team.upper() or
                                            (isinstance(player_team_full, str) and player_team_full.lower() in team_option.lower()) or
                                            (isinstance(player_team_full, str) and team_option.lower() in player_team_full.lower())
                                        )
                                        
                                        if team_matches:
                                            opponent_team = team2 if team_option == team1 else team1
                                            break
                                
                                if opponent_team:
                                    # Find opponent abbreviation
                                    opponent_abbrev = team_mappings.get(opponent_team.lower(), None)
                                    if not opponent_abbrev:
                                        # Try partial matching for team names
                                        for name, abbrev in team_mappings.items():
                                            if (isinstance(name, str) and len(name) > 3 and 
                                                name.lower() in opponent_team.lower()):
                                                opponent_abbrev = abbrev
                                                break
                                    if opponent_abbrev:
                                        opponent_stats = get_team_stats_for_player(opponent_abbrev)
                                        league_def_avg = get_league_defensive_averages()
                                        
                                        # Apply combined adjustments to player stats
                                        for stat_name in ['rushing_yards', 'passing_yards', 'receiving_yards', 'receptions']:
                                            if stat_name in player_stats["avg"]:
                                                original_value = player_stats["avg"][stat_name]
                                                
                                                # Weather adjustment
                                                weather_factor = weather_adjustments.get(stat_name, 1.0)
                                                
                                                # Team matchup adjustment
                                                team_factor = 1.0
                                                if stat_name in ['rushing_yards'] and opponent_stats.get('opp_rush_yards_game') != 'N/A':
                                                    try:
                                                        opp_def = float(opponent_stats['opp_rush_yards_game'])
                                                        league_def = float(league_def_avg.get('opp_rush_yards_game', 115.4))
                                                        team_factor = opp_def / league_def if league_def > 0 else 1
                                                    except:
                                                        pass
                                                elif stat_name in ['passing_yards', 'receiving_yards', 'receptions'] and opponent_stats.get('opp_pass_yards_game') != 'N/A':
                                                    try:
                                                        opp_def = float(opponent_stats['opp_pass_yards_game'])
                                                        league_def = float(league_def_avg.get('opp_pass_yards_game', 213.4))
                                                        team_factor = opp_def / league_def if league_def > 0 else 1
                                                    except:
                                                        pass
                                                
                                                # Combined adjustment
                                                combined_factor = weather_factor * team_factor
                                                adjusted_value = round(original_value * combined_factor, 1)
                                                
                                                # Store adjustments
                                                player_stats["avg"][f"adjusted_{stat_name}"] = adjusted_value
                                                player_stats["avg"][f"{stat_name}_weather_factor"] = weather_factor
                                                player_stats["avg"][f"{stat_name}_team_factor"] = team_factor
                                                player_stats["avg"][f"{stat_name}_weather_explanation"] = format_weather_explanation(
                                                    weather_data['temperature'], weather_data['wind_speed'], weather_data['conditions']
                                                )
                                                player_stats["avg"][f"{stat_name}_team_explanation"] = f"vs {opponent_abbrev} defense ({opponent_stats.get('opp_pass_yards_game' if stat_name in ['passing_yards', 'receiving_yards', 'receptions'] else 'opp_rush_yards_game', 'N/A')} vs {league_def_avg.get('opp_pass_yards_game' if stat_name in ['passing_yards', 'receiving_yards', 'receptions'] else 'opp_rush_yards_game', 'N/A')} league avg)"
            except:
                pass
            
            flagged = check_stat_against_odds(player_display_name, player_stats, odds, THRESHOLDS)
            if flagged:
                # Apply adjustments to flagged stats
                try:
                    if odds and odds[0].get('event_name'):
                        event_name = odds[0]['event_name']
                        if ' vs ' in event_name:
                            teams = event_name.split(' vs ')
                            with engine.connect() as conn:
                                team_result = conn.execute(text("""
                                    SELECT team FROM player_weekly_stats 
                                    WHERE player_display_name = :player 
                                    LIMIT 1
                                """), {"player": player_display_name}).fetchone()
                                if team_result:
                                    player_team = team_result[0]
                                    team1 = teams[0].strip()
                                    team2 = teams[1].strip()
                                    
                                    abbrev_to_full_name = {
                                        'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens',
                                        'BUF': 'Buffalo Bills', 'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears',
                                        'CIN': 'Cincinnati Bengals', 'CLE': 'Cleveland Browns', 'DAL': 'Dallas Cowboys',
                                        'DEN': 'Denver Broncos', 'DET': 'Detroit Lions', 'GB': 'Green Bay Packers',
                                        'HOU': 'Houston Texans', 'IND': 'Indianapolis Colts', 'JAX': 'Jacksonville Jaguars',
                                        'KC': 'Kansas City Chiefs', 'LV': 'Las Vegas Raiders', 'LAC': 'Los Angeles Chargers',
                                        'LAR': 'Los Angeles Rams', 'MIA': 'Miami Dolphins', 'MIN': 'Minnesota Vikings',
                                        'NE': 'New England Patriots', 'NO': 'New Orleans Saints', 'NYG': 'New York Giants',
                                        'NYJ': 'New York Jets', 'PHI': 'Philadelphia Eagles', 'PIT': 'Pittsburgh Steelers',
                                        'SF': 'San Francisco 49ers', 'SEA': 'Seattle Seahawks', 'TB': 'Tampa Bay Buccaneers',
                                        'TEN': 'Tennessee Titans', 'WAS': 'Washington Commanders'
                                    }
                                    
                                    player_team_full = abbrev_to_full_name.get(player_team, player_team)
                                    
                                    opponent_team = None
                                    if player_team_full in team1 or player_team in team1:
                                        opponent_team = team2
                                    elif player_team_full in team2 or player_team in team2:
                                        opponent_team = team1
                                    
                                    if opponent_team:
                                        team_name_to_abbrev = {
                                            'arizona cardinals': 'ARI', 'atlanta falcons': 'ATL', 'baltimore ravens': 'BAL',
                                            'buffalo bills': 'BUF', 'carolina panthers': 'CAR', 'chicago bears': 'CHI',
                                            'cincinnati bengals': 'CIN', 'cleveland browns': 'CLE', 'dallas cowboys': 'DAL',
                                            'denver broncos': 'DEN', 'detroit lions': 'DET', 'green bay packers': 'GB',
                                            'houston texans': 'HOU', 'indianapolis colts': 'IND', 'jacksonville jaguars': 'JAX',
                                            'kansas city chiefs': 'KC', 'las vegas raiders': 'LV', 'los angeles chargers': 'LAC',
                                            'los angeles rams': 'LAR', 'miami dolphins': 'MIA', 'minnesota vikings': 'MIN',
                                            'new england patriots': 'NE', 'new orleans saints': 'NO', 'new york giants': 'NYG',
                                            'new york jets': 'NYJ', 'philadelphia eagles': 'PHI', 'pittsburgh steelers': 'PIT',
                                            'san francisco 49ers': 'SF', 'seattle seahawks': 'SEA', 'tampa bay buccaneers': 'TB',
                                            'tennessee titans': 'TEN', 'washington commanders': 'WAS'
                                        }
                                        
                                        opponent_abbrev = team_name_to_abbrev.get(opponent_team.lower(), None)
                                        if opponent_abbrev:
                                            opponent_stats = get_team_stats_for_player(opponent_abbrev)
                                            league_def_avg = get_league_defensive_averages()
                                            
                                            for f in flagged:
                                                stat_name = f['stat']
                                                
                                                # Get weather and team adjustments
                                                weather_factor = weather_adjustments.get(stat_name, 1.0)
                                                team_factor = 1.0
                                                
                                                if stat_name == 'rushing_yards' and opponent_stats.get('opp_rush_yards_game') != 'N/A' and league_def_avg.get('opp_rush_yards_game'):
                                                    try:
                                                        opp_rush_def = float(opponent_stats['opp_rush_yards_game'])
                                                        league_rush_def = float(league_def_avg['opp_rush_yards_game'])
                                                        team_factor = opp_rush_def / league_rush_def if league_rush_def > 0 else 1
                                                        adjusted_value = round(player_stats["avg"].get("rushing_yards", 0) * weather_factor * team_factor, 1)
                                                        f['adjustedRushingYards'] = adjusted_value
                                                        f['adjustmentDetails'] = {
                                                            'original': player_stats["avg"].get("rushing_yards", 0),
                                                            'adjusted': adjusted_value,
                                                            'changePct': round((weather_factor * team_factor - 1) * 100, 1),
                                                            'explanation': f'<strong>Weather {round((weather_factor - 1) * 100, 1):+.1f}%</strong><br>&nbsp;&nbsp;&nbsp;&nbsp;{format_weather_explanation(weather_data["temperature"], weather_data["wind_speed"], weather_data["conditions"])}<br><strong>Matchup {round((team_factor - 1) * 100, 1):+.1f}%</strong><br>&nbsp;&nbsp;&nbsp;&nbsp;vs {opponent_abbrev} defense ({opp_rush_def} vs {league_rush_def} league avg)'
                                                        }
                                                    except:
                                                        pass
                                                elif stat_name in ['passing_yards', 'receiving_yards', 'receptions'] and opponent_stats.get('opp_pass_yards_game') != 'N/A' and league_def_avg.get('opp_pass_yards_game'):
                                                    try:
                                                        opp_pass_def = float(opponent_stats['opp_pass_yards_game'])
                                                        league_pass_def = float(league_def_avg['opp_pass_yards_game'])
                                                        team_factor = opp_pass_def / league_pass_def if league_pass_def > 0 else 1
                                                        
                                                        original_value = float(player_stats["avg"].get(stat_name, 0))
                                                        adjusted_value = round(original_value * weather_factor * team_factor, 1)
                                                        
                                                        if stat_name == 'passing_yards':
                                                            f['adjustedPassingYards'] = adjusted_value
                                                        elif stat_name == 'receiving_yards':
                                                            f['adjustedReceivingYards'] = adjusted_value
                                                        elif stat_name == 'receptions':
                                                            f['adjustedReceptions'] = adjusted_value
                                                            
                                                        f['adjustmentDetails'] = {
                                                            'original': original_value,
                                                            'adjusted': adjusted_value,
                                                            'changePct': round((weather_factor * team_factor - 1) * 100, 1),
                                                            'explanation': f'<strong>Weather {round((weather_factor - 1) * 100, 1):+.1f}%</strong><br>&nbsp;&nbsp;&nbsp;&nbsp;{format_weather_explanation(weather_data["temperature"], weather_data["wind_speed"], weather_data["conditions"])}<br><strong>Matchup {round((team_factor - 1) * 100, 1):+.1f}%</strong><br>&nbsp;&nbsp;&nbsp;&nbsp;vs {opponent_abbrev} defense ({opp_pass_def} vs {league_pass_def} league avg)'
                                                        }
                                                    except Exception as e:
                                                        pass
                except Exception as e:
                    pass

                matchup_info = ""
                if odds and odds[0].get('event_name'):
                    matchup_info = odds[0]['event_name']
                
                flagged_players.append({
                    'player': player_display_name,
                    'matchup': matchup_info,
                    'stats': flagged
                })
        except Exception as e:
            print(f"Error processing player {player_display_name}: {e}")
            continue
    
    print(f"DEBUG: Checked {players_checked} players, {players_with_stats} had stats, {players_with_odds} had odds, {len(flagged_players)} flagged")
    return flagged_players

if __name__ == "__main__":
    import json
    import sys
    
    # Check if we should output JSON
    output_json = '--json' in sys.argv
    
    # Read fresh config from file
    config = read_config_from_file()
    
    SEASON = config['SEASON']
    COMPARISON_WEEK = config['COMPARISON_WEEK']
    THRESHOLDS = config['THRESHOLDS']
    INCOMPLETE_DATA_PLAYERS = config['INCOMPLETE_DATA_PLAYERS']
    
    year = SEASON
    current_week = COMPARISON_WEEK
    
    if not output_json:
        print(f"Using config: Season={SEASON}, Week={COMPARISON_WEEK}")
        print(f"Thresholds: {THRESHOLDS}")

    # Fetch all distinct players in DB
    try:
        with engine.connect() as conn:
            players = conn.execute(text("""
                SELECT DISTINCT player_display_name
                FROM player_weekly_stats
                WHERE season = :year
            """), {"year": year}).fetchall()
    except SQLAlchemyError as e:
        if output_json:
            print(json.dumps({"error": f"Database error: {e}"}))
        else:
            print(f"Database error fetching players: {e}")
        exit(1)
    except Exception as e:
        if output_json:
            print(json.dumps({"error": f"Unexpected error: {e}"}))
        else:
            print(f"Unexpected error fetching players: {e}")
        exit(1)

    flagged_players = []
    
    for row in players:
        player_display_name = row[0]
        try:
            player_stats = get_recent_3_game_stats(year, player_display_name, current_week=current_week)
            if not player_stats:
                continue

            has_meaningful_stats = any(v > 0 for v in player_stats["avg"].values() if isinstance(v, (int, float)))
            
            if not has_meaningful_stats or player_display_name in INCOMPLETE_DATA_PLAYERS:
                continue

            odds = get_odds_for_player(player_display_name)
            if not odds:
                continue

            flagged = check_stat_against_odds(player_display_name, player_stats, odds, THRESHOLDS)

            if flagged:
                # Calculate adjusted stats
                try:
                    from team_stats import get_team_stats_for_player, get_league_defensive_averages
                    from weather_adjustments import get_weather_adjustments, format_weather_explanation
                    from weather_api import get_weather_for_game
                    
                    opponent_team = None
                    weather_data = None
                    weather_adjustments_dict = {}
                    
                    if odds and odds[0].get('event_name'):
                        event_name = odds[0]['event_name']
                        if ' vs ' in event_name:
                            teams = event_name.split(' vs ')
                            team1 = teams[0].strip()
                            team2 = teams[1].strip()
                            
                            # Get weather data
                            weather_data = get_weather_for_game(team1, team2)
                            weather_adjustments_dict = get_weather_adjustments(
                                weather_data['temperature'],
                                weather_data['wind_speed'], 
                                weather_data['conditions']
                            )
                            
                            with engine.connect() as conn:
                                team_result = conn.execute(text("""
                                    SELECT team FROM player_weekly_stats 
                                    WHERE player_display_name = :player 
                                    LIMIT 1
                                """), {"player": player_display_name}).fetchone()
                                if team_result:
                                    player_team = team_result[0]
                                    
                                    # Create comprehensive team mappings
                                    team_mappings = {
                                        # Full names to abbreviations
                                        'arizona cardinals': 'ARI', 'atlanta falcons': 'ATL', 'baltimore ravens': 'BAL',
                                        'buffalo bills': 'BUF', 'carolina panthers': 'CAR', 'chicago bears': 'CHI',
                                        'cincinnati bengals': 'CIN', 'cleveland browns': 'CLE', 'dallas cowboys': 'DAL',
                                        'denver broncos': 'DEN', 'detroit lions': 'DET', 'green bay packers': 'GB',
                                        'houston texans': 'HOU', 'indianapolis colts': 'IND', 'jacksonville jaguars': 'JAX',
                                        'kansas city chiefs': 'KC', 'las vegas raiders': 'LV', 'los angeles chargers': 'LAC',
                                        'los angeles rams': 'LAR', 'miami dolphins': 'MIA', 'minnesota vikings': 'MIN',
                                        'new england patriots': 'NE', 'new orleans saints': 'NO', 'new york giants': 'NYG',
                                        'new york jets': 'NYJ', 'philadelphia eagles': 'PHI', 'pittsburgh steelers': 'PIT',
                                        'san francisco 49ers': 'SF', 'seattle seahawks': 'SEA', 'tampa bay buccaneers': 'TB',
                                        'tennessee titans': 'TEN', 'washington commanders': 'WAS',
                                        # Abbreviations to full names
                                        'ARI': 'Arizona Cardinals', 'ATL': 'Atlanta Falcons', 'BAL': 'Baltimore Ravens',
                                        'BUF': 'Buffalo Bills', 'CAR': 'Carolina Panthers', 'CHI': 'Chicago Bears',
                                        'CIN': 'Cincinnati Bengals', 'CLE': 'Cleveland Browns', 'DAL': 'Dallas Cowboys',
                                        'DEN': 'Denver Broncos', 'DET': 'Detroit Lions', 'GB': 'Green Bay Packers',
                                        'HOU': 'Houston Texans', 'IND': 'Indianapolis Colts', 'JAX': 'Jacksonville Jaguars',
                                        'KC': 'Kansas City Chiefs', 'LV': 'Las Vegas Raiders', 'LAC': 'Los Angeles Chargers',
                                        'LAR': 'Los Angeles Rams', 'MIA': 'Miami Dolphins', 'MIN': 'Minnesota Vikings',
                                        'NE': 'New England Patriots', 'NO': 'New Orleans Saints', 'NYG': 'New York Giants',
                                        'NYJ': 'New York Jets', 'PHI': 'Philadelphia Eagles', 'PIT': 'Pittsburgh Steelers',
                                        'SF': 'San Francisco 49ers', 'SEA': 'Seattle Seahawks', 'TB': 'Tampa Bay Buccaneers',
                                        'TEN': 'Tennessee Titans', 'WAS': 'Washington Commanders'
                                    }
                                    
                                    # Find opponent team with better matching logic
                                    player_team_full = team_mappings.get(player_team, player_team)
                                    
                                    # Try multiple matching approaches
                                    for team_option in [team1, team2]:
                                        # Check if player team matches this option
                                        team_matches = (
                                            player_team.upper() in team_option.upper() or
                                            team_option.upper() in player_team.upper() or
                                            (isinstance(player_team_full, str) and player_team_full.lower() in team_option.lower()) or
                                            (isinstance(player_team_full, str) and team_option.lower() in player_team_full.lower())
                                        )
                                        
                                        if team_matches:
                                            opponent_team = team2 if team_option == team1 else team1
                                            break
                    
                    if opponent_team:
                        # Find opponent abbreviation
                        opponent_abbrev = team_mappings.get(opponent_team.lower(), None)
                        if not opponent_abbrev:
                            # Try partial matching for team names
                            for name, abbrev in team_mappings.items():
                                if (isinstance(name, str) and len(name) > 3 and 
                                    name.lower() in opponent_team.lower()):
                                    opponent_abbrev = abbrev
                                    break
                        if opponent_abbrev:
                            opponent_stats = get_team_stats_for_player(opponent_abbrev)
                            league_def_avg = get_league_defensive_averages()
                            
                            for f in flagged:
                                stat_name = f['stat']
                                
                                # Get weather and team adjustments
                                weather_factor = weather_adjustments_dict.get(stat_name, 1.0)
                                team_factor = 1.0
                                
                                if stat_name == 'rushing_yards' and opponent_stats.get('opp_rush_yards_game') != 'N/A' and league_def_avg.get('opp_rush_yards_game'):
                                    try:
                                        opp_rush_def = float(opponent_stats['opp_rush_yards_game'])
                                        league_rush_def = float(league_def_avg['opp_rush_yards_game'])
                                        team_factor = opp_rush_def / league_rush_def if league_rush_def > 0 else 1
                                        
                                        original_value = float(player_stats["avg"].get("rushing_yards", 0))
                                        adjusted_value = round(original_value * weather_factor * team_factor, 1)
                                        f['adjustedRushingYards'] = adjusted_value
                                        f['adjustmentDetails'] = {
                                            'original': original_value,
                                            'adjusted': adjusted_value,
                                            'changePct': round((weather_factor * team_factor - 1) * 100, 1),
                                            'explanation': f'Weather {round((weather_factor - 1) * 100, 1):+.1f}%\nWeather: {format_weather_explanation(weather_data["temperature"], weather_data["wind_speed"], weather_data["conditions"])}\nMatchup {round((team_factor - 1) * 100, 1):+.1f}%\nvs {opponent_abbrev} defense ({opp_rush_def} vs {league_rush_def} league avg)'
                                        }
                                    except:
                                        pass
                                elif stat_name in ['passing_yards', 'receiving_yards', 'receptions'] and opponent_stats.get('opp_pass_yards_game') != 'N/A' and league_def_avg.get('opp_pass_yards_game'):
                                    try:
                                        opp_pass_def = float(opponent_stats['opp_pass_yards_game'])
                                        league_pass_def = float(league_def_avg['opp_pass_yards_game'])
                                        team_factor = opp_pass_def / league_pass_def if league_pass_def > 0 else 1
                                        
                                        original_value = float(player_stats["avg"].get(stat_name, 0))
                                        adjusted_value = round(original_value * weather_factor * team_factor, 1)
                                        
                                        if stat_name == 'passing_yards':
                                            f['adjustedPassingYards'] = adjusted_value
                                        elif stat_name == 'receiving_yards':
                                            f['adjustedReceivingYards'] = adjusted_value
                                        elif stat_name == 'receptions':
                                            f['adjustedReceptions'] = adjusted_value
                                            
                                        f['adjustmentDetails'] = {
                                            'original': original_value,
                                            'adjusted': adjusted_value,
                                            'changePct': round((weather_factor * team_factor - 1) * 100, 1),
                                            'explanation': f'<strong>Weather {round((weather_factor - 1) * 100, 1):+.1f}%</strong><br>&nbsp;&nbsp;&nbsp;&nbsp;{format_weather_explanation(weather_data["temperature"], weather_data["wind_speed"], weather_data["conditions"])}<br><strong>Matchup {round((team_factor - 1) * 100, 1):+.1f}%</strong><br>&nbsp;&nbsp;&nbsp;&nbsp;vs {opponent_abbrev} defense ({opp_pass_def} vs {league_pass_def} league avg)'
                                        }
                                    except:
                                        pass
                except:
                    pass

                # Get matchup info
                matchup_info = ""
                if odds and odds[0].get('event_name'):
                    matchup_info = odds[0]['event_name']
                
                if output_json:
                    flagged_players.append({
                        'player': player_display_name,
                        'matchup': matchup_info,
                        'stats': flagged
                    })
                else:
                    print(f"\nFlagged stats for {player_display_name} - {matchup_info}:")
                    for f in flagged:
                        print(f"  Player={f['player_name']}, Bookmaker={f['bookmaker']}, "
                              f"Stat={f['stat']}, Player Value={f['player_value']}, "
                              f"Line={f['line']}, Diff={f['difference']}, "
                              f"Std Dev={f['std_dev']}, Rule={f['threshold_rule']}")

        except Exception as e:
            if not output_json:
                print(f"Error checking thresholds for player {player_display_name}: {e}")
    
    if output_json:
        print(json.dumps(flagged_players))