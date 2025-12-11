from sqlalchemy import create_engine, text
from test_thresholds import get_recent_3_game_stats, read_config_from_file
from team_stats import get_team_stats_for_player, get_league_defensive_averages

DB_PATH = "sqlite:///nfl_stats.db"
engine = create_engine(DB_PATH)

def get_qb_passing_predictions():
    """Predict which QB will have highest passing yards for upcoming week"""
    
    config = read_config_from_file()
    SEASON = config['SEASON']
    COMPARISON_WEEK = config['COMPARISON_WEEK']
    
    qb_predictions = []
    
    # Get all QBs with recent passing stats
    with engine.connect() as conn:
        qbs = conn.execute(text("""
            SELECT DISTINCT player_display_name, team
            FROM player_weekly_stats
            WHERE season = :season 
            AND passing_yards > 0
            AND week >= :min_week
        """), {"season": SEASON, "min_week": COMPARISON_WEEK - 3}).fetchall()
    
    for qb_row in qbs:
        qb_name = qb_row[0]
        qb_team = qb_row[1]
        
        # Get QB's recent stats
        qb_stats = get_recent_3_game_stats(SEASON, qb_name, COMPARISON_WEEK)
        if not qb_stats or qb_stats["avg"].get("passing_yards", 0) < 100:
            continue
            
        # Get opponent info from odds table
        with engine.connect() as conn:
            matchup = conn.execute(text("""
                SELECT event_name FROM odds 
                WHERE season = :season AND week = :week
                AND event_name LIKE '%' || :team || '%'
                LIMIT 1
            """), {"season": SEASON, "week": COMPARISON_WEEK, "team": qb_team}).fetchone()
        
        opponent_team = None
        matchup_info = ""
        
        if matchup:
            event_name = matchup[0]
            matchup_info = event_name
            
            # Extract opponent team
            if ' vs ' in event_name:
                teams = event_name.split(' vs ')
                team1, team2 = teams[0].strip(), teams[1].strip()
                
                abbrev_to_full = {
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
                
                qb_team_full = abbrev_to_full.get(qb_team, qb_team)
                
                if qb_team_full in team1 or qb_team in team1:
                    opponent_team = team2
                elif qb_team_full in team2 or qb_team in team2:
                    opponent_team = team1
        
        # Calculate adjusted passing yards based on opponent defense
        base_passing_yards = qb_stats["avg"]["passing_yards"]
        adjusted_passing_yards = base_passing_yards
        adjustment_pct = 0
        
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
            
            opponent_abbrev = team_name_to_abbrev.get(opponent_team.lower())
            if opponent_abbrev:
                try:
                    opponent_stats = get_team_stats_for_player(opponent_abbrev)
                    league_def_avg = get_league_defensive_averages()
                    
                    if (opponent_stats.get('opp_pass_yards_game') != 'N/A' and 
                        league_def_avg.get('opp_pass_yards_game')):
                        
                        opp_pass_def = float(opponent_stats['opp_pass_yards_game'])
                        league_pass_def = float(league_def_avg['opp_pass_yards_game'])
                        
                        if league_pass_def > 0:
                            pass_multiplier = opp_pass_def / league_pass_def
                            adjusted_passing_yards = round(base_passing_yards * pass_multiplier, 1)
                            adjustment_pct = round((pass_multiplier - 1) * 100, 1)
                except:
                    pass
        
        qb_predictions.append({
            'qb_name': qb_name,
            'team': qb_team,
            'matchup': matchup_info,
            'base_avg': round(base_passing_yards, 1),
            'adjusted_avg': adjusted_passing_yards,
            'adjustment_pct': adjustment_pct,
            'std_dev': round(qb_stats["std"].get("passing_yards", 0), 1),
            'opponent': opponent_team or "Unknown"
        })
    
    # Sort by adjusted passing yards (highest first)
    qb_predictions.sort(key=lambda x: x['adjusted_avg'], reverse=True)
    
    return qb_predictions

if __name__ == "__main__":
    predictions = get_qb_passing_predictions()
    
    print("=== QB PASSING YARDS PREDICTIONS FOR UPCOMING WEEK ===\n")
    
    for i, qb in enumerate(predictions[:10], 1):  # Top 10
        print(f"{i}. {qb['qb_name']} ({qb['team']})")
        print(f"   Matchup: {qb['matchup']}")
        print(f"   3-Game Avg: {qb['base_avg']} yards")
        print(f"   Adjusted Avg: {qb['adjusted_avg']} yards ({qb['adjustment_pct']:+.1f}%)")
        print(f"   Std Dev: {qb['std_dev']}")
        print(f"   vs {qb['opponent']}")
        print()
    
    if predictions:
        top_qb = predictions[0]
        print(f"🏆 PREDICTION: {top_qb['qb_name']} ({top_qb['team']}) will have the highest passing yards")
        print(f"   Projected: {top_qb['adjusted_avg']} yards vs {top_qb['opponent']}")