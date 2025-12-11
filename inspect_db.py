from sqlalchemy import create_engine, text

engine = create_engine("sqlite:///nfl_stats.db")

print("=== Checking George Pickens in player_weekly_stats ===")
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT player_display_name, team, week, season, receiving_yards, receptions 
        FROM player_weekly_stats 
        WHERE player_display_name LIKE '%Pickens%' 
        ORDER BY season DESC, week DESC 
        LIMIT 10
    """)).fetchall()
    
    if result:
        for row in result:
            print(f"  {row[0]} ({row[1]}) - Week {row[2]}, Season {row[3]} - {row[4]} rec yds, {row[5]} rec")
    else:
        print("  No George Pickens found")

print("\n=== Checking odds table for week 14 ===")
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT DISTINCT player_id, event_name, week, season 
        FROM odds 
        WHERE week = 14 AND season = 2025
        ORDER BY player_id 
        LIMIT 10
    """)).fetchall()
    
    if result:
        print(f"  Found {len(result)} odds entries for week 14:")
        for row in result:
            print(f"    {row[0]} - {row[1]} (Week {row[2]}, Season {row[3]})")
    else:
        print("  No odds found for week 14")

print("\n=== Checking for any George Pickens in odds ===")
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT player_id, market, line, bookmaker, week, season, event_name
        FROM odds 
        WHERE player_id LIKE '%Pickens%' 
        ORDER BY week DESC 
        LIMIT 5
    """)).fetchall()
    
    if result:
        for row in result:
            print(f"  {row[0]} - {row[1]}: {row[2]} ({row[3]}) Week {row[4]} Season {row[5]} - {row[6]}")
    else:
        print("  No George Pickens found in odds")

print("\n=== Recent weeks in player_weekly_stats ===")
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT DISTINCT week, season, COUNT(*) as player_count
        FROM player_weekly_stats 
        WHERE season = 2025
        GROUP BY week, season 
        ORDER BY week DESC 
        LIMIT 5
    """)).fetchall()
    
    for row in result:
        print(f"  Week {row[0]} Season {row[1]}: {row[2]} players")

print("\n=== Recent weeks in odds ===")
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT DISTINCT week, season, COUNT(DISTINCT player_id) as player_count
        FROM odds 
        WHERE season = 2025
        GROUP BY week, season 
        ORDER BY week DESC 
        LIMIT 5
    """)).fetchall()
    
    for row in result:
        print(f"  Week {row[0]} Season {row[1]}: {row[2]} players with odds")