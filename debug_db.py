import sqlite3

# Check George Pickens in player stats
conn = sqlite3.connect('nfl_stats.db')
cursor = conn.cursor()

print("=== George Pickens in player_weekly_stats ===")
cursor.execute("SELECT * FROM player_weekly_stats WHERE player_display_name LIKE '%Pickens%' ORDER BY week DESC LIMIT 5")
rows = cursor.fetchall()
if rows:
    columns = [description[0] for description in cursor.description]
    print(f"Columns: {columns}")
    for row in rows:
        print(row)
else:
    print("No George Pickens found in player_weekly_stats")

print("\n=== George Pickens in odds table ===")
cursor.execute("SELECT * FROM odds WHERE player_id LIKE '%Pickens%' ORDER BY week DESC LIMIT 5")
rows = cursor.fetchall()
if rows:
    columns = [description[0] for description in cursor.description]
    print(f"Columns: {columns}")
    for row in rows:
        print(row)
else:
    print("No George Pickens found in odds table")

print("\n=== All odds for week 14 ===")
cursor.execute("SELECT DISTINCT player_id FROM odds WHERE week = 14 LIMIT 10")
rows = cursor.fetchall()
print(f"Sample week 14 odds players: {[r[0] for r in rows]}")

print("\n=== All upcoming games in odds ===")
cursor.execute("SELECT DISTINCT event_name, week FROM odds ORDER BY week DESC LIMIT 10")
rows = cursor.fetchall()
print("Recent games in odds:")
for row in rows:
    print(f"  {row[0]} - Week {row[1]}")

conn.close()