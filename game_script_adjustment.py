# game_script_adjustment.py - Adjust player projections based on game script

from sqlalchemy import create_engine, text

DB_PATH = "sqlite:///nfl_stats.db"
engine = create_engine(DB_PATH)

def get_game_spread(event_name, season, week):
    """Get the spread for a specific game from odds data"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT player_id, line FROM odds 
                WHERE event_name = :event_name 
                  AND market = 'spreads' 
                  AND season = :season 
                  AND week = :week
                LIMIT 2
            """), {"event_name": event_name, "season": season, "week": week}).fetchall()
            
            if len(result) >= 2:
                # Return the spread (negative line indicates favorite)
                team1_line = result[0][1]
                team2_line = result[1][1]
                
                # The favorite has the negative line
                if team1_line < 0:
                    return team1_line  # e.g., -6.5
                else:
                    return team2_line  # e.g., -6.5
            
            return 0  # No spread data or close game
    except Exception as e:
        print(f"Error getting game spread: {e}")
        return 0

def get_game_script_multiplier(spread):
    """Calculate game script multiplier based on spread"""
    abs_spread = abs(spread)
    
    if abs_spread >= 7:  # Expected blowout (7+ point spread)
        return {
            "favorite_receiving": 0.9,   # 10% fewer targets (run more in 2nd half)
            "favorite_rushing": 1.1,     # 10% more carries (clock management)
            "underdog_receiving": 1.15,  # 15% more targets (garbage time)
            "underdog_rushing": 0.85     # 15% fewer carries (abandoning run)
        }
    elif abs_spread >= 3.5:  # Moderate favorite (3.5-6.5 point spread)
        return {
            "favorite_receiving": 0.95,  # 5% fewer targets
            "favorite_rushing": 1.05,    # 5% more carries
            "underdog_receiving": 1.08,  # 8% more targets
            "underdog_rushing": 0.92     # 8% fewer carries
        }
    else:  # Close game (spread < 3.5)
        return {
            "favorite_receiving": 1.0,   # No adjustment
            "favorite_rushing": 1.0,
            "underdog_receiving": 1.0,
            "underdog_rushing": 1.0
        }

def apply_game_script_adjustment(player_stats, player_team, event_name, season, week):
    """Apply game script adjustments to player stats"""
    if not player_stats or not event_name:
        return player_stats
    
    # Get the spread for this game
    spread = get_game_spread(event_name, season, week)
    if spread == 0:
        return player_stats  # No adjustment for close games or missing data
    
    # Get multipliers
    multipliers = get_game_script_multiplier(spread)
    
    # Determine if player's team is favorite or underdog
    # Parse event name to get teams
    if " vs " in event_name:
        teams = event_name.split(" vs ")
        team1 = teams[0].strip()
        team2 = teams[1].strip()
        
        # Map team abbreviations to full names for comparison
        team_mapping = {
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
        
        player_team_full = team_mapping.get(player_team, player_team)
        
        # Determine if player's team is favorite or underdog
        # Need to check which team has the negative spread in the odds data
        try:
            with engine.connect() as conn:
                spread_data = conn.execute(text("""
                    SELECT player_id, line FROM odds 
                    WHERE event_name = :event_name AND market = 'spreads' 
                    AND season = :season AND week = :week
                    ORDER BY line ASC LIMIT 2
                """), {"event_name": event_name, "season": season, "week": week}).fetchall()
                
                is_favorite = False
                if spread_data:
                    # The team with negative line is the favorite
                    favorite_team_id = spread_data[0][0] if spread_data[0][1] < 0 else spread_data[1][0]
                    favorite_team_name = favorite_team_id.replace('team_', '')
                    
                    # Check if player's team matches the favorite
                    is_favorite = (player_team_full in favorite_team_name or player_team in favorite_team_name)
        except:
            is_favorite = False
        
        # Apply adjustments
        adjusted_stats = player_stats.copy()
        adjusted_avg = adjusted_stats["avg"].copy()
        
        if is_favorite:
            # Favorite team adjustments
            if "receiving_yards" in adjusted_avg:
                adjusted_avg["receiving_yards"] *= multipliers["favorite_receiving"]
            if "receptions" in adjusted_avg:
                adjusted_avg["receptions"] *= multipliers["favorite_receiving"]
            if "rushing_yards" in adjusted_avg:
                adjusted_avg["rushing_yards"] *= multipliers["favorite_rushing"]
        else:
            # Underdog team adjustments
            if "receiving_yards" in adjusted_avg:
                adjusted_avg["receiving_yards"] *= multipliers["underdog_receiving"]
            if "receptions" in adjusted_avg:
                adjusted_avg["receptions"] *= multipliers["underdog_receiving"]
            if "rushing_yards" in adjusted_avg:
                adjusted_avg["rushing_yards"] *= multipliers["underdog_rushing"]
        
        adjusted_stats["avg"] = adjusted_avg
        return adjusted_stats
        

    
    return player_stats

def test_game_script_adjustment():
    """Test game script adjustments with real data"""
    print("Testing game script adjustments...")
    
    # Test with a known game
    event_name = "Houston Texans vs Buffalo Bills"
    season = 2025
    week = 12
    
    spread = get_game_spread(event_name, season, week)
    print(f"Spread for {event_name}: {spread}")
    
    if spread != 0:
        multipliers = get_game_script_multiplier(spread)
        print(f"Game script multipliers: {multipliers}")
        
        # Test with a sample player
        sample_stats = {
            "avg": {"receiving_yards": 60.0, "receptions": 5.0, "rushing_yards": 10.0},
            "std": {"receiving_yards": 20.0, "receptions": 2.0, "rushing_yards": 5.0}
        }
        
        # Test as favorite team player
        adjusted_fav = apply_game_script_adjustment(sample_stats, "BUF", event_name, season, week)
        print(f"Favorite team adjustments: {adjusted_fav['avg']}")
        
        # Test as underdog team player  
        adjusted_dog = apply_game_script_adjustment(sample_stats, "HOU", event_name, season, week)
        print(f"Underdog team adjustments: {adjusted_dog['avg']}")
        
        return True
    else:
        print("No spread data found")
        return False

if __name__ == "__main__":
    test_game_script_adjustment()