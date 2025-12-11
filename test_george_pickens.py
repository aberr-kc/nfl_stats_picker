#!/usr/bin/env python3

from sqlalchemy import create_engine, text
from pipeline_config import SEASON, COMPARISON_WEEK, STATS_WEEK, ODDS_WEEK

engine = create_engine("sqlite:///nfl_stats.db")

print(f"=== Testing George Pickens Data ===")
print(f"Config: Season={SEASON}, Stats Week={STATS_WEEK}, Odds Week={ODDS_WEEK}, Comparison Week={COMPARISON_WEEK}")

with engine.connect() as conn:
    # Check if George Pickens exists in player stats
    print("\n1. Checking player_weekly_stats for George Pickens...")
    result = conn.execute(text("""
        SELECT player_display_name, team, week, season, receiving_yards, receptions 
        FROM player_weekly_stats 
        WHERE player_display_name LIKE '%Pickens%' 
        ORDER BY season DESC, week DESC 
        LIMIT 5
    """)).fetchall()
    
    if result:
        print("   Found George Pickens in player_weekly_stats:")
        for row in result:
            print(f"     {row[0]} ({row[1]}) - Week {row[2]}, Season {row[3]} - {row[4]} rec yds, {row[5]} rec")
    else:
        print("   ❌ George Pickens NOT found in player_weekly_stats")
    
    # Check odds for George Pickens
    print(f"\n2. Checking odds for George Pickens (Week {ODDS_WEEK})...")
    name_variations = [
        "George Pickens",
        "George Pickens",  # No periods to remove
    ]
    
    found_odds = False
    for name_variant in name_variations:
        result = conn.execute(text("""
            SELECT player_id, market, line, bookmaker, event_name
            FROM odds 
            WHERE player_id = :custom_id
            AND season = :season
            AND week = :week
        """), {"custom_id": f"custom_{name_variant}", "season": SEASON, "week": ODDS_WEEK}).fetchall()
        
        if result:
            found_odds = True
            print(f"   Found odds for '{name_variant}':")
            for row in result:
                print(f"     {row[1]}: {row[2]} ({row[3]}) - {row[4]}")
            break
    
    if not found_odds:
        print("   ❌ No odds found for George Pickens")
        
        # Check what players DO have odds for this week
        print(f"\n3. Sample players with odds for Week {ODDS_WEEK}...")
        result = conn.execute(text("""
            SELECT DISTINCT player_id, event_name
            FROM odds 
            WHERE season = :season
            AND week = :week
            LIMIT 5
        """), {"season": SEASON, "week": ODDS_WEEK}).fetchall()
        
        if result:
            print("   Sample players with odds:")
            for row in result:
                print(f"     {row[0]} - {row[1]}")
        else:
            print(f"   ❌ NO odds found for ANY player in Week {ODDS_WEEK}")
    
    # Check what weeks have odds data
    print(f"\n4. Available odds data by week...")
    result = conn.execute(text("""
        SELECT DISTINCT week, season, COUNT(DISTINCT player_id) as player_count
        FROM odds 
        WHERE season = :season
        GROUP BY week, season 
        ORDER BY week DESC 
        LIMIT 5
    """), {"season": SEASON}).fetchall()
    
    if result:
        print("   Available weeks:")
        for row in result:
            print(f"     Week {row[0]} Season {row[1]}: {row[2]} players")
    else:
        print("   ❌ No odds data found for any week")

print("\n=== Test Complete ===")