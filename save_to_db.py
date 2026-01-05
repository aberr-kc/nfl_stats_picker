# save_to_db.py
import sqlite3
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from models import Base, Player, Odds
from fetch_stats import fetch_weekly_stats_sleeper as fetch_weekly_stats


# --- Pandas direct save for stats ---
def save_stats_to_db(year: int, week: int, season_type: str = 'regular'):
    """
    Fetch weekly stats from Sleeper API and save to SQLite DB.
    Automatically deletes existing rows for that season/week/season_type before inserting.
    
    Args:
        year: Season year
        week: Week number
        season_type: 'regular' or 'playoffs'
    """
    df = fetch_weekly_stats(year, week, season_type)
    if df.empty:
        print(f"⚠️ No {season_type} stats fetched for Week {week}, {year}")
        return

    conn = None
    try:
        conn = sqlite3.connect("nfl_stats.db")
        cursor = conn.cursor()

        # Add season_type column if it doesn't exist
        try:
            cursor.execute("ALTER TABLE player_weekly_stats ADD COLUMN season_type TEXT DEFAULT 'regular'")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists

        # Delete existing rows for this season/week/season_type to avoid duplicates
        cursor.execute(
            "DELETE FROM player_weekly_stats WHERE season = ? AND week = ? AND season_type = ?",
            (year, week, season_type)
        )
        conn.commit()

        # Append fresh rows
        df.to_sql("player_weekly_stats", conn, if_exists="append", index=False)

        # Count inserted rows
        cursor.execute(
            "SELECT COUNT(*) FROM player_weekly_stats WHERE season = ? AND week = ? AND season_type = ?",
            (year, week, season_type)
        )
        row_count = cursor.fetchone()[0]
        print(f"✅ Saved {row_count} rows to player_weekly_stats for {season_type} Week {week}, {year}")
    except Exception as e:
        print(f"❌ Error saving {season_type} stats to DB: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


# --- SQLAlchemy setup for odds ---
engine = create_engine("sqlite:///nfl_stats.db")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)


def save_player_if_not_exists(player_name, session):
    """
    Ensure a player exists in the Player table.
    Returns the Player object.
    """
    try:
        player = session.query(Player).filter_by(player_name=player_name).first()
        if not player:
            player = Player(player_id=f"custom_{player_name}", player_name=player_name)
            session.add(player)
            session.flush()
        return player
    except SQLAlchemyError as e:
        session.rollback()
        raise SQLAlchemyError(f"Error creating player {player_name}: {e}")


def save_odds(player_name, event_id, event_name, bookmaker, market, line, price, season, week):
    """
    Save odds for a player into the DB. Updates if an entry for the same
    player, market, bookmaker, season, and week already exists.
    """
    session = Session()
    try:
        # Get or create player
        player = save_player_if_not_exists(player_name, session=session)

        # Check for existing odds
        existing = session.query(Odds).filter_by(
            player_id=player.player_id,
            market=market,
            bookmaker=bookmaker,
            season=season,
            week=week
        ).first()

        if existing:
            existing.line = line
            existing.price = price
        else:
            odds_entry = Odds(
                player_id=player.player_id,
                event_id=event_id,
                event_name=event_name,
                bookmaker=bookmaker,
                market=market,
                line=line,
                price=price,
                season=season,
                week=week
            )
            session.add(odds_entry)

        session.commit()
        print(f"✅ Saved odds for {player_name} - {market} ({bookmaker}) season {season} week {week}")
    except SQLAlchemyError as e:
        session.rollback()
        print(f"❌ Database error saving odds for {player_name}: {e}")
        raise
    except Exception as e:
        session.rollback()
        print(f"❌ Unexpected error saving odds for {player_name}: {e}")
        raise
    finally:
        session.close()


# --- Example usage ---
if __name__ == "__main__":
    year = 2025
    week = 10
    save_stats_to_db(year, week)