from sqlalchemy import create_engine, text

engine = create_engine("sqlite:///nfl_stats.db")

with engine.connect() as conn:
    # Check for Travis Kelce odds
    kelce_odds = conn.execute(text("SELECT * FROM odds WHERE player_id LIKE '%Kelce%' OR player_id LIKE '%Travis%'")).fetchall()
    print(f"Kelce odds found: {len(kelce_odds)}")
    for odd in kelce_odds[:5]:  # Show first 5
        print(f"  {odd}")
    
    # Check all player names in odds
    players = conn.execute(text("SELECT DISTINCT player_id FROM odds WHERE player_id LIKE 'custom_%' LIMIT 20")).fetchall()
    print(f"\nSample player IDs in odds: {[p[0] for p in players]}")