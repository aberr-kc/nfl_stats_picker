from sqlalchemy import create_engine, text

engine = create_engine("sqlite:///nfl_stats.db")

with engine.connect() as conn:
    # Check what tables exist
    tables = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    print("Tables:", [t[0] for t in tables])
    
    # Check players table structure if it exists
    try:
        schema = conn.execute(text("PRAGMA table_info(players)")).fetchall()
        print("Players table columns:", [(row[1], row[2]) for row in schema])
    except:
        print("No players table found")
    
    # Check odds table structure
    try:
        schema = conn.execute(text("PRAGMA table_info(odds)")).fetchall()
        print("Odds table columns:", [(row[1], row[2]) for row in schema])
    except:
        print("No odds table found")