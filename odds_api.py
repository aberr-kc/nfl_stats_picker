# odds_api.py
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import requests
import logging
from dotenv import load_dotenv
from models import Session, Player, Odds, engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, Integer, DateTime
from sqlalchemy.exc import SQLAlchemyError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------------
# SQLAlchemy session
# -------------------------------
Session = sessionmaker(bind=engine)
Base = declarative_base()

# -------------------------------
# API key management
# -------------------------------
# Keys come from ODDS_API_KEYS (comma-separated) in .env next to this file
# or in the environment. See .env.example. Keys are tried in order.
load_dotenv(Path(__file__).resolve().parent / ".env")
API_KEYS = [k.strip() for k in os.getenv("ODDS_API_KEYS", "").split(",") if k.strip()]
if not API_KEYS:
    logger.warning("No Odds API keys configured. Set ODDS_API_KEYS in .env (see .env.example).")

# -------------------------------
# New DB table for API usage tracking
# -------------------------------
class ApiUsage(Base):
    __tablename__ = "api_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    api_key = Column(String, nullable=False)
    month = Column(String, nullable=False)  # Format: YYYY-MM
    calls_made = Column(Integer, default=0)
    last_used = Column(DateTime, default=lambda: datetime.now(timezone.utc))

# Ensure table exists
Base.metadata.create_all(engine)

# -------------------------------
# Valid markets (player props + game lines)
# -------------------------------
VALID_MARKETS = [
    "player_pass_yds",
    "player_pass_tds",
    "player_receptions",
    "player_reception_yds",
    "player_rush_attempts",
    "player_rush_yds",
    "player_anytime_td",
    "spreads",
    "totals"
]

# -------------------------------
# API Key Rotator with Usage Tracking
# -------------------------------
def call_odds_api(url, params, max_retries=2):
    """
    Try API call with key rotation. Tracks usage per key per month.
    Returns response or raises error if all keys fail.
    """
    if not API_KEYS:
        raise RuntimeError("No Odds API keys configured. Set ODDS_API_KEYS in .env (see .env.example).")
    session = Session()
    try:
        for i, key in enumerate(API_KEYS):
            try:
                params["apiKey"] = key
                # amazonq-ignore-next-line
                resp = requests.get(url, params=params, timeout=30, verify=False)

                if resp.status_code == 200:
                    # Track usage in DB - each market counts as 1 request
                    month = datetime.now(timezone.utc).strftime("%Y-%m")
                    usage = session.query(ApiUsage).filter_by(api_key=key, month=month).first()
                    if not usage:
                        usage = ApiUsage(api_key=key, month=month, calls_made=0)
                        session.add(usage)

                    # Count markets in the request
                    market_count = len(params.get('markets', '').split(',')) if 'markets' in params else 1
                    usage.calls_made += market_count
                    usage.last_used = datetime.now(timezone.utc)
                    session.commit()
                    logger.info(f"API call successful with key {i+1}, {market_count} markets counted")
                    return resp

                # Quota exceeded (Odds API returns 402) or explicit quota message
                if resp.status_code == 402 or "usage" in resp.text.lower():
                    logger.warning(f"API key {i+1} quota reached, switching to next key...")
                    continue

                logger.error(f"API call failed with key {i+1}: {resp.status_code} {resp.text}")
            
            except requests.RequestException as e:
                logger.error(f"Request failed with key {i+1}: {e}")
                continue
            except SQLAlchemyError as e:
                logger.error(f"Database error tracking API usage: {e}")
                session.rollback()
                # Continue with API call even if tracking fails
                if 'resp' in locals() and resp.status_code == 200:
                    return resp

        raise RuntimeError("All API keys failed or quota exceeded.")
    except Exception as e:
        logger.error(f"Unexpected error in call_odds_api: {e}")
        raise
    finally:
        session.close()

# -------------------------------
# Save odds to DB
# -------------------------------
def save_odds(player_name, event_id, event_name, bookmaker, market, line, price, season, week):
    if not market or not bookmaker:
        logger.error("Missing required parameters for save_odds")
        return
    
    session = Session()
    try:
        # Handle team-level markets (spreads, totals) vs player props
        if market in ["spreads", "totals"]:
            # For team markets, use team name as player_id
            player_id = f"team_{player_name or 'unknown'}"
        else:
            # For player props, lookup/create player
            if not player_name:
                logger.error("Player name required for player prop markets")
                return
                
            player = session.query(Player).filter_by(name=player_name).first()
            if not player:
                player = Player(name=player_name)
                session.add(player)
                session.flush()  # Get the ID without committing
            player_id = f"custom_{player_name}"

        # Check if odds already exist for same player/market/bookmaker/season/week
        existing = session.query(Odds).filter_by(
            player_id=player_id,
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
                player_id=player_id,
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
        # Removed individual player logging - only log at game level
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Database error saving odds for {player_name or 'team'}: {e}")
        raise
    except Exception as e:
        session.rollback()
        logger.error(f"Unexpected error saving odds for {player_name or 'team'}: {e}")
        raise
    finally:
        session.close()

# -------------------------------
# Fetch upcoming odds from API
# -------------------------------
def fetch_and_store_odds(days_ahead: int = 4, season=None, week=None):
    """
    Fetch NFL events within the next `days_ahead` days, pull player prop odds,
    and save them to the DB. Skips games if the API quota is reached.
    """
    if days_ahead <= 0:
        raise ValueError("days_ahead must be positive")
    
    try:
        # Clear only existing odds data for the current week to avoid conflicts
        session = Session()
        try:
            # Only delete odds for the current week/season being fetched
            deleted = session.query(Odds).filter_by(season=season, week=week).delete()
            session.commit()
            logger.info(f"Cleared {deleted} existing odds records for Season {season} Week {week}")
        except Exception as e:
            session.rollback()
            logger.error(f"Error clearing existing odds for week {week}: {e}")
        finally:
            session.close()
        
        now = datetime.now(timezone.utc)
        start_date = now
        end_date = now + timedelta(days=days_ahead)
        logger.info(f"Fetching games between {start_date} and {end_date}")

        # --- Step 1: Get all NFL events ---
        events_url = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events/"
        events_params = {}
        
        try:
            events_resp = call_odds_api(events_url, events_params)
            events = events_resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch events: {e}")
            raise

        # --- Step 2: Filter upcoming events ---
        upcoming_events = []
        for e in events:
            try:
                event_time = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
                if start_date <= event_time <= end_date:
                    upcoming_events.append(e)
                    logger.info(f"Found upcoming game: {e.get('home_team')} vs {e.get('away_team')} at {event_time}")
            except (KeyError, ValueError) as err:
                logger.warning(f"Invalid event data: {err}")
                continue
        
        logger.info(f"Found {len(upcoming_events)} upcoming events")

        # --- Step 3: Fetch odds for those events ---
        processed_count = 0
        for event in upcoming_events:
            try:
                event_id = event["id"]
                event_name = f"{event['home_team']} vs {event['away_team']}"
                odds_url = f"https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events/{event_id}/odds"
                odds_params = {
                    "regions": "au",
                    "markets": ",".join(VALID_MARKETS),
                    "oddsFormat": "decimal",
                }
                
                odds_resp = call_odds_api(odds_url, odds_params)
                data = odds_resp.json()
                markets_collected = set()

                for bookmaker in data.get("bookmakers", []):
                    book_name = bookmaker.get("title")
                    if not book_name:
                        continue
                        
                    for market in bookmaker.get("markets", []):
                        market_key = market.get("key")
                        if not market_key:
                            continue
                            
                        markets_collected.add(market_key)
                        
                        # Handle team markets (spreads, totals) vs player props
                        if market_key in ["spreads", "totals"]:
                            # Team markets - outcomes are team names
                            for outcome in market.get("outcomes", []):
                                team_name = outcome.get("name")
                                if not team_name:
                                    continue
                                    
                                line = outcome.get("point")
                                price = outcome.get("price")

                                try:
                                    save_odds(
                                        player_name=team_name,  # Team name for spreads/totals
                                        event_id=event_id,
                                        event_name=event_name,
                                        bookmaker=book_name,
                                        market=market_key,
                                        line=line,
                                        price=price,
                                        season=season,
                                        week=week
                                    )
                                except Exception as save_err:
                                    logger.error(f"Failed to save {market_key} odds for {team_name}: {save_err}")
                                    continue
                        else:
                            # Player prop markets - outcomes are player names
                            for outcome in market.get("outcomes", []):
                                player_name = outcome.get("description") or outcome.get("name")
                                if not player_name:
                                    continue
                                    
                                line = outcome.get("point")
                                price = outcome.get("price")

                                try:
                                    save_odds(
                                        player_name=player_name,
                                        event_id=event_id,
                                        event_name=event_name,
                                        bookmaker=book_name,
                                        market=market_key,
                                        line=line,
                                        price=price,
                                        season=season,
                                        week=week
                                    )
                                except Exception as save_err:
                                    logger.error(f"Failed to save odds for {player_name}: {save_err}")
                                    continue

                market_list_str = ", ".join(sorted(markets_collected))
                logger.info(f"Odds saved for {event_name} - Markets: {market_list_str}")
                processed_count += 1
                
            except Exception as event_err:
                logger.error(f"Failed to process event {event.get('id', 'unknown')}: {event_err}")
                continue

        return {"events_processed": processed_count}
    
    except Exception as e:
        logger.error(f"Fatal error in fetch_and_store_odds: {e}")
        raise

# -------------------------------
# Query latest odds from DB
# -------------------------------
def get_latest_odds_for_player(player_name, season, week):
    """Fetch latest odds for a player for a given season and week."""
    if not player_name:
        raise ValueError("Player name is required")
    
    session = Session()
    try:
        player = session.query(Player).filter_by(player_name=player_name).first()
        if not player:
            logger.info(f"Player {player_name} not found")
            return []

        odds_list = session.query(Odds).filter_by(
            player_id=player.player_id,
            season=season,
            week=week
        # amazonq-ignore-next-line
        ).order_by(Odds.retrieved_at.desc()).all()

        return [
            {"market": o.market, "line": o.line, "bookmaker": o.bookmaker}
            for o in odds_list
        ]
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching odds for {player_name}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error fetching odds for {player_name}: {e}")
        raise
    finally:
        session.close()

# -------------------------------
# Report monthly API usage
# -------------------------------
def get_api_usage_report():
    """Return API usage per key for the current month."""
    session = Session()
    try:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        usage = session.query(ApiUsage).filter_by(month=month).all()
        return [
            {"api_key": u.api_key, "calls_made": u.calls_made, "last_used": u.last_used}
            for u in usage
        ]
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching API usage report: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error fetching API usage report: {e}")
        raise
    finally:
        session.close()

# -------------------------------
# Optional: run standalone
# -------------------------------
if __name__ == "__main__":
    from pipeline_config import SEASON, ODDS_WEEK, ODDS_DAYS_AHEAD
    
    try:
        result = fetch_and_store_odds(days_ahead=ODDS_DAYS_AHEAD, season=SEASON, week=ODDS_WEEK)
        logger.info(f"Events processed: {result['events_processed']}")

        # Print API usage report
        usage_report = get_api_usage_report()
        logger.info("API Usage This Month:")
        for u in usage_report:
            logger.info(f"  Key: {u['api_key'][:6]}... | Calls: {u['calls_made']} | Last used: {u['last_used']}")
    except Exception as e:
        logger.error(f"Script execution failed: {e}")
        raise
