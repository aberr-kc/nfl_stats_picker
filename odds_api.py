# odds_api.py
from datetime import datetime, timedelta, timezone
import os
import re
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

EVENTS_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events"

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

NO_KEYS_MESSAGE = "No Odds API keys configured. Set ODDS_API_KEYS in .env (see .env.example)."
_APIKEY_RE = re.compile(r"(apiKey=)[^&\s'\"]+")


def redact(text) -> str:
    """Remove API key values from text (exception messages, URLs, response bodies)."""
    text = str(text)
    for key in API_KEYS:
        if key:
            text = text.replace(key, "***")
    return _APIKEY_RE.sub(r"\1***", text)


# Last known quota per key index (1-based), from the x-requests-* response headers
QUOTA = {}


def _header_int(resp, name):
    try:
        return int(float(resp.headers.get(name)))
    except (TypeError, ValueError):
        return None


def _record_quota(key_index, resp):
    QUOTA[key_index] = {
        "remaining": _header_int(resp, "x-requests-remaining"),
        "used": _header_int(resp, "x-requests-used"),
        "last": _header_int(resp, "x-requests-last"),
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def quota_snapshot(source="live"):
    """Per-key remaining/used (key index only, never the key) and the total remaining."""
    keys = [{"key": i, "remaining": q["remaining"], "used": q["used"]} for i, q in sorted(QUOTA.items())]
    known = [k["remaining"] for k in keys if k["remaining"] is not None]
    as_of = max((q["as_of"] for q in QUOTA.values()), default=None)
    return {"keys": keys, "total_remaining": sum(known) if known else None,
            "source": source if keys else "unknown", "as_of": as_of}

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
        raise RuntimeError(NO_KEYS_MESSAGE)
    session = Session()
    try:
        for i, key in enumerate(API_KEYS):
            try:
                params["apiKey"] = key
                # TLS verification stays on: the key travels in the query string
                resp = requests.get(url, params=params, timeout=30)

                if resp.status_code == 200:
                    _record_quota(i + 1, resp)
                    # Track usage in DB: credits charged (x-requests-last), else 1 per market requested
                    month = datetime.now(timezone.utc).strftime("%Y-%m")
                    usage = session.query(ApiUsage).filter_by(api_key=key, month=month).first()
                    if not usage:
                        usage = ApiUsage(api_key=key, month=month, calls_made=0)
                        session.add(usage)

                    market_count = len(params.get('markets', '').split(',')) if 'markets' in params else 1
                    credits = _header_int(resp, "x-requests-last")
                    counted = credits if credits is not None else market_count
                    usage.calls_made = (usage.calls_made or 0) + counted
                    usage.last_used = datetime.now(timezone.utc)
                    session.commit()
                    logger.info(f"API call successful with key {i+1}, {counted} credits counted")
                    return resp

                # Quota exceeded (Odds API returns 402) or explicit quota message
                if resp.status_code == 402 or "usage" in resp.text.lower():
                    logger.warning(f"API key {i+1} quota reached, switching to next key...")
                    continue

                logger.error("API call failed with key %d: %s %s", i + 1, resp.status_code, redact(resp.text))
            
            except requests.RequestException as e:
                logger.error("Request failed with key %d: %s", i + 1, redact(str(e)))
                continue
            except SQLAlchemyError as e:
                logger.error(f"Database error tracking API usage: {e}")
                session.rollback()
                # Continue with API call even if tracking fails
                if 'resp' in locals() and resp.status_code == 200:
                    return resp

        raise RuntimeError("All API keys failed or quota exceeded.")
    except Exception as e:
        logger.error("Unexpected error in call_odds_api: %s", redact(str(e)))
        raise
    finally:
        session.close()

# -------------------------------
# Save odds to DB
# -------------------------------
def save_odds(player_name, event_id, event_name, bookmaker, market, line, price, season, week, outcome=None,
              commence_time=None):
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

        # Check if odds already exist for same player/market/bookmaker/outcome/season/week
        # (Over and Under are separate rows, so their prices don't overwrite each other)
        existing = session.query(Odds).filter_by(
            player_id=player_id,
            market=market,
            bookmaker=bookmaker,
            outcome=outcome,
            season=season,
            week=week
        ).first()

        if existing:
            existing.line = line
            existing.price = price
            if commence_time is not None:
                existing.commence_time = commence_time
        else:
            odds_entry = Odds(
                player_id=player_id,
                event_id=event_id,
                event_name=event_name,
                bookmaker=bookmaker,
                market=market,
                line=line,
                price=price,
                outcome=outcome,
                commence_time=commence_time,
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
def _get_free_events(key):
    """GET the free /events endpoint (no quota cost). Refuses any other URL."""
    url = EVENTS_URL
    if not url.rstrip("/").endswith("/events"):
        raise ValueError("free events helper may only call the /events endpoint")
    return requests.get(url, params={"apiKey": key}, timeout=30)


def get_upcoming_events(days_ahead):
    """Free: NFL events starting in [now, now + days_ahead days], sorted by kick-off.

    Calls /events once per key so every key's x-requests-* quota headers are read.
    Does not touch api_usage (the endpoint costs nothing).
    Returns (events, window_start, window_end, quota_snapshot).
    """
    if not API_KEYS:
        raise RuntimeError(NO_KEYS_MESSAGE)
    if days_ahead <= 0:
        raise ValueError("days_ahead must be positive")

    events = None
    for i, key in enumerate(API_KEYS):
        try:
            resp = _get_free_events(key)
        except requests.RequestException as e:
            logger.error("Events request failed with key %d: %s", i + 1, redact(str(e)))
            continue
        if resp.status_code != 200:
            logger.error("Events request failed with key %d: %s %s", i + 1, resp.status_code, redact(resp.text[:300]))
            continue
        _record_quota(i + 1, resp)
        if events is None:
            events = resp.json()
    if events is None:
        raise RuntimeError("Events request failed for all keys")

    now = datetime.now(timezone.utc)
    start_date = now
    end_date = now + timedelta(days=days_ahead)
    logger.info(f"Fetching games between {start_date} and {end_date}")

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
    upcoming_events.sort(key=lambda e: e["commence_time"])
    logger.info(f"Found {len(upcoming_events)} upcoming events")
    return upcoming_events, start_date, end_date, quota_snapshot("live")


def fetch_event_odds(event_id):
    """The single paid call: odds for one event, all VALID_MARKETS, region au."""
    odds_url = f"https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events/{event_id}/odds"
    odds_params = {
        "regions": "au",
        "markets": ",".join(VALID_MARKETS),
        "oddsFormat": "decimal",
    }
    odds_resp = call_odds_api(odds_url, odds_params)
    return {"data": odds_resp.json(),
            "credits": _header_int(odds_resp, "x-requests-last"),
            "remaining": _header_int(odds_resp, "x-requests-remaining")}


def _store_event_odds(event, data, season, week):
    """Save one event's outcomes. Returns (markets_collected, rows_saved)."""
    event_id = event["id"]
    event_name = f"{event['home_team']} vs {event['away_team']}"
    markets_collected = set()
    rows_saved = 0

    for bookmaker in data.get("bookmakers", []):
        book_name = bookmaker.get("title")
        if not book_name:
            continue

        for market in bookmaker.get("markets", []):
            market_key = market.get("key")
            if not market_key:
                continue

            markets_collected.add(market_key)

            for outcome in market.get("outcomes", []):
                if market_key in ["spreads", "totals"]:
                    # Team markets - outcomes are team names
                    name = outcome.get("name")
                else:
                    # Player prop markets - outcomes are player names
                    name = outcome.get("description") or outcome.get("name")
                if not name:
                    continue

                try:
                    save_odds(
                        player_name=name,
                        event_id=event_id,
                        event_name=event_name,
                        bookmaker=book_name,
                        market=market_key,
                        line=outcome.get("point"),
                        price=outcome.get("price"),
                        outcome=outcome.get("name"),
                        commence_time=event.get("commence_time"),
                        season=season,
                        week=week
                    )
                    rows_saved += 1
                except Exception as save_err:
                    logger.error(f"Failed to save {market_key} odds for {name}: {save_err}")
                    continue

    return markets_collected, rows_saved


def fetch_and_store_odds(days_ahead: int = 4, season=None, week=None, max_games=None):
    """
    Fetch NFL events within the next `days_ahead` days, pull player prop odds,
    and save them to the DB.

    The week's existing odds are replaced only after at least one game's odds
    were fetched, so a failed or empty fetch keeps them. If max_games is set
    (the game count the user confirmed) and more games are found now, nothing
    is fetched.
    """
    if days_ahead <= 0:
        raise ValueError("days_ahead must be positive")

    try:
        upcoming_events, _, _, _ = get_upcoming_events(days_ahead)
        result = {"season": season, "week": week, "days_ahead": days_ahead,
                  "events_found": len(upcoming_events), "events_processed": 0,
                  "events_failed": [], "credits_used": 0, "credits_source": "header",
                  "rows_cleared": 0, "odds_rows_saved": 0}

        if max_games is not None and len(upcoming_events) > max_games:
            raise RuntimeError(f"Upcoming games changed from {max_games} to {len(upcoming_events)} "
                               f"since preview; preview again.")
        if not upcoming_events:
            logger.info("No upcoming events; existing odds kept")
            result["quota"] = quota_snapshot("live")
            return result

        # --- Paid calls: fetch every game first, keep responses in memory ---
        fetched = []
        for event in upcoming_events:
            event_name = f"{event.get('home_team')} vs {event.get('away_team')}"
            try:
                fetched.append((event, fetch_event_odds(event["id"])))
            except Exception as event_err:
                logger.error("Failed to fetch odds for %s: %s", event_name, redact(str(event_err)))
                result["events_failed"].append(event_name)

        if not fetched:
            raise RuntimeError(f"No odds fetched (all {len(upcoming_events)} games failed); existing odds kept.")

        # --- Replace the week's odds ---
        session = Session()
        try:
            deleted = session.query(Odds).filter_by(season=season, week=week).delete()
            session.commit()
            result["rows_cleared"] = deleted
            logger.info(f"Cleared {deleted} existing odds records for Season {season} Week {week}")
        except Exception as e:
            session.rollback()
            logger.error(f"Error clearing existing odds for week {week}: {e}")
        finally:
            session.close()

        for event, resp in fetched:
            event_name = f"{event['home_team']} vs {event['away_team']}"
            try:
                markets_collected, rows_saved = _store_event_odds(event, resp["data"], season, week)
            except Exception as event_err:
                logger.error(f"Failed to process event {event.get('id', 'unknown')}: {event_err}")
                result["events_failed"].append(event_name)
                continue
            if resp.get("credits") is not None:
                result["credits_used"] += resp["credits"]
            else:
                result["credits_used"] += len(markets_collected)
                result["credits_source"] = "estimated"
            result["odds_rows_saved"] += rows_saved
            market_list_str = ", ".join(sorted(markets_collected))
            logger.info(f"Odds saved for {event_name} - Markets: {market_list_str}")
            result["events_processed"] += 1

        result["quota"] = quota_snapshot("live")
        return result

    except Exception as e:
        logger.error("Fatal error in fetch_and_store_odds: %s", redact(str(e)))
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
        logger.info(f"Credits used: {result['credits_used']} ({result['credits_source']}), "
                    f"remaining: {result['quota']['total_remaining']}")

        # Print API usage report
        usage_report = get_api_usage_report()
        logger.info("API Usage This Month:")
        for u in usage_report:
            logger.info(f"  Key: {u['api_key'][:6]}... | Calls: {u['calls_made']} | Last used: {u['last_used']}")
    except Exception as e:
        logger.error(f"Script execution failed: {e}")
        raise
