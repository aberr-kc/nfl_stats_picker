# save_to_db.py
import sqlite3
from sqlalchemy.exc import SQLAlchemyError
# models owns the DB location (honours NFL_STATS_DB) and creates the tables
from models import Player, Odds, engine, Session, DB_PATH
from fetch_stats import fetch_weekly_stats_sleeper as fetch_weekly_stats, fetch_players_df

UNIQUE_INDEX = "ux_player_weekly_stats_key"


def _say(msg):
    """print() that never raises on a non-UTF-8 console/pipe (e.g. server stdout redirected on Windows)."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))


def _create_unique_index(conn):
    """Enforce one row per (player_id, season, week, season_type). Warn if old duplicates block it."""
    try:
        conn.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {UNIQUE_INDEX} "
            "ON player_weekly_stats(player_id, season, week, season_type)"
        )
    except sqlite3.IntegrityError as e:
        _say(f"⚠️ Could not create unique index {UNIQUE_INDEX} (existing duplicate rows): {e}")


# --- Pandas direct save for stats ---
def save_stats_to_db(year: int, week: int, season_type: str = 'regular', db_path=None, players_df=None):
    """
    Fetch weekly stats from Sleeper API and save to SQLite DB.
    Replaces the rows for that season/week/season_type in one transaction, so
    reruns never duplicate rows and a failed insert keeps the old rows.

    Args:
        year: Season year
        week: Week number
        season_type: 'regular' or 'playoffs'
        db_path: SQLite file (default: models.DB_PATH)
        players_df: Optional pre-fetched Sleeper players list (saves a ~5 MB download per week)

    Returns:
        dict with season, week, season_type, rows_saved, rows_replaced, fetched
    """
    summary = {"season": year, "week": week, "season_type": season_type,
               "rows_saved": 0, "rows_replaced": 0, "fetched": 0}
    df = fetch_weekly_stats(year, week, season_type, players_df=players_df)
    if df.empty:
        _say(f"⚠️ No {season_type} stats fetched for Week {week}, {year}")
        return summary

    df = df.drop_duplicates(subset=["player_id"], keep="last")

    conn = None
    try:
        conn = sqlite3.connect(str(db_path or DB_PATH))
        cursor = conn.cursor()

        table_exists = cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='player_weekly_stats'"
        ).fetchone() is not None

        if table_exists:
            # Add season_type / gp columns if they don't exist (DBs from an older to_sql)
            for ddl in ("ALTER TABLE player_weekly_stats ADD COLUMN season_type TEXT DEFAULT 'regular'",
                        "ALTER TABLE player_weekly_stats ADD COLUMN gp REAL"):
                try:
                    cursor.execute(ddl)
                    conn.commit()
                except sqlite3.OperationalError:
                    pass  # Column already exists
            _create_unique_index(conn)
            conn.commit()

        # One transaction: delete the week, insert fresh rows, commit together
        # (pandas commits on success and rolls back on failure, which covers the DELETE too)
        rows_replaced = 0
        if table_exists:
            cursor.execute(
                "DELETE FROM player_weekly_stats WHERE season = ? AND week = ? AND season_type = ?",
                (year, week, season_type)
            )
            rows_replaced = cursor.rowcount

        df.to_sql("player_weekly_stats", conn, if_exists="append", index=False)
        if not table_exists:
            _create_unique_index(conn)

        # Count inserted rows
        cursor.execute(
            "SELECT COUNT(*) FROM player_weekly_stats WHERE season = ? AND week = ? AND season_type = ?",
            (year, week, season_type)
        )
        row_count = cursor.fetchone()[0]
        conn.commit()
        _say(f"✅ Saved {row_count} rows to player_weekly_stats for {season_type} Week {week}, {year}")
        summary.update(rows_saved=row_count, rows_replaced=max(rows_replaced, 0), fetched=len(df))
        return summary
    except Exception as e:
        _say(f"❌ Error saving {season_type} stats to DB: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def load_all_completed_weeks(season: int, current_week: int, db_path=None, prior_season_weeks: int = 18):
    """
    First-time load: every regular-season week of the prior season (1..prior_season_weeks)
    and every completed week of this season (1..current_week - 1), from Sleeper (free).
    Fetches the players list once. Safe to rerun (each week is replaced, not duplicated).

    Returns:
        list of per-week summaries from save_stats_to_db
    """
    players_df = fetch_players_df()
    weeks = [(season - 1, w) for w in range(1, prior_season_weeks + 1)]
    weeks += [(season, w) for w in range(1, min(current_week, prior_season_weeks + 1))]
    return [save_stats_to_db(year, week, db_path=db_path, players_df=players_df) for year, week in weeks]


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


def _main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Save Sleeper player stats to the database (free).")
    parser.add_argument("--all", action="store_true",
                        help="First-time setup: load every completed regular-season week of last season "
                             "and this season, then refresh team stats. Default: last completed week only.")
    args = parser.parse_args(argv)

    from pipeline_config import SEASON, STATS_WEEK, CURRENT_WEEK
    if not args.all:
        save_stats_to_db(SEASON, STATS_WEEK)
        return 0

    _say(f"Loading every completed regular-season week: {SEASON - 1} weeks 1-18 and "
         f"{SEASON} weeks 1-{min(CURRENT_WEEK - 1, 18)}")
    summaries = load_all_completed_weeks(SEASON, CURRENT_WEEK)
    import team_stats
    if team_stats.update_all_team_stats(season=SEASON) is None:
        _say("⚠️ Team stats were not updated (TeamRankings unreachable?). Matchup notes stay neutral.")
    total = sum(s["rows_saved"] for s in summaries)
    empty = [f"{s['season']} wk{s['week']}" for s in summaries if not s["rows_saved"]]
    _say(f"Done: {len(summaries)} weeks requested, {total} rows saved, "
         f"weeks with 0 rows: {', '.join(empty) if empty else 'none'}")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(_main())