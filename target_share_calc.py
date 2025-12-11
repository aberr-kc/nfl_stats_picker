# target_share_calc.py - Calculate target share and opportunity adjustments

from sqlalchemy import create_engine, text

DB_PATH = "sqlite:///nfl_stats.db"
engine = create_engine(DB_PATH)

def calculate_team_totals(season, week_range):
    """Calculate team totals for receptions and rushing attempts for given weeks"""
    try:
        with engine.connect() as conn:
            week_placeholders = ','.join([':week' + str(i) for i in range(len(week_range))])
            week_params = {f'week{i}': week for i, week in enumerate(week_range)}
            week_params['season'] = season
            
            result = conn.execute(text(f"""
                SELECT team, week, 
                       SUM(COALESCE(receptions, 0)) as total_receptions,
                       COUNT(CASE WHEN rushing_yards > 0 THEN 1 END) as total_rushers
                FROM player_weekly_stats
                WHERE season = :season 
                  AND week IN ({week_placeholders})
                  AND team IS NOT NULL
                GROUP BY team, week
            """), week_params).fetchall()
            
            team_totals = {}
            for row in result:
                team = row[0]
                week = row[1] 
                receptions = row[2] or 0
                rushers = row[3] or 0
                
                if team not in team_totals:
                    team_totals[team] = {}
                team_totals[team][week] = {
                    'total_receptions': receptions,
                    'total_rushers': rushers
                }
            
            return team_totals
    except Exception as e:
        print(f"Error calculating team totals: {e}")
        return {}

def calculate_player_reception_share(player_stats, team_totals, player_team):
    """Calculate player's average reception share over their recent games"""
    if not player_stats.get("weekly") or player_team not in team_totals:
        return {"reception_share": 0, "rushing_opportunity": 0}
    
    reception_shares = []
    rushing_opportunities = []
    
    for week_data in player_stats["weekly"]:
        week = week_data.get('week')
        player_receptions = week_data.get('receptions', 0) or 0
        player_rushing_yards = week_data.get('rushing_yards', 0) or 0
        
        if week in team_totals[player_team]:
            team_week_data = team_totals[player_team][week]
            total_receptions = team_week_data['total_receptions']
            total_rushers = team_week_data['total_rushers']
            
            if total_receptions > 0:
                reception_shares.append(player_receptions / total_receptions)
            if player_rushing_yards > 0 and total_rushers > 0:
                rushing_opportunities.append(1 / total_rushers)  # Simple share of rushing opportunities
    
    avg_reception_share = sum(reception_shares) / len(reception_shares) if reception_shares else 0
    avg_rushing_opportunity = sum(rushing_opportunities) / len(rushing_opportunities) if rushing_opportunities else 0
    
    return {
        "reception_share": round(avg_reception_share, 3),
        "rushing_opportunity": round(avg_rushing_opportunity, 3)
    }

def test_target_share_calculation():
    """Test function to verify target share calculations work"""
    print("Testing target share calculation...")
    
    # Test with a known player
    from test_thresholds import get_recent_3_game_stats, read_config_from_file
    
    config = read_config_from_file()
    season = config['SEASON']
    week = config['COMPARISON_WEEK']
    
    # Get team totals for recent weeks
    week_range = [week-2, week-1, week] if week >= 3 else [1, 2, 3]
    team_totals = calculate_team_totals(season, week_range)
    
    print(f"Team totals calculated for weeks {week_range}")
    print(f"Found data for {len(team_totals)} teams")
    
    # Test with a specific player
    test_player = "Josh Allen"  # Known QB with targets/carries
    player_stats = get_recent_3_game_stats(season, test_player, week)
    
    if player_stats:
        # Get player's team
        try:
            with engine.connect() as conn:
                team_result = conn.execute(text("""
                    SELECT team FROM player_weekly_stats 
                    WHERE player_display_name = :player LIMIT 1
                """), {"player": test_player}).fetchone()
                
                if team_result:
                    player_team = team_result[0]
                    shares = calculate_player_reception_share(player_stats, team_totals, player_team)
                    print(f"\n{test_player} ({player_team}):")
                    print(f"Reception Share: {shares['reception_share']:.1%}")
                    print(f"Rushing Opportunity: {shares['rushing_opportunity']:.1%}")
                    return True
        except Exception as e:
            print(f"Error testing: {e}")
    
    print("Test completed")
    return False

if __name__ == "__main__":
    test_target_share_calculation()