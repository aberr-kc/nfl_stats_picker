from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
import pandas as pd
from Odds_vs_Stats_Check import check_stat_against_odds
import ipaddress
import logging
import os
import time
import refresh_jobs

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI()

# ✅ Add CORS so frontend can fetch from backend
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],  # Restrict to specific origins
    allow_credentials=True,
    allow_methods=["GET", "POST"],  # Restrict to needed methods
    allow_headers=["*"],
)

# DB connection with error handling
try:
    engine = create_engine("sqlite:///" + os.getenv("NFL_STATS_DB", "nfl_stats.db"))  # Use the correct database file
except Exception as e:
    logger.error(f"Failed to create database engine: {e}")
    raise


# ---------------------------
# Endpoints
# ---------------------------

@app.get("/")
def read_root():
    return FileResponse(BASE_DIR / "index.html")

@app.get("/debug/tables")
def debug_tables():
    """Debug endpoint to see what tables exist"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            tables = [row[0] for row in result]
            return {"tables": tables}
    except Exception as e:
        return {"error": str(e)}

@app.get("/debug/odds/{player_name}")
def debug_odds(player_name: str):
    """Debug odds for specific player"""
    try:
        with engine.connect() as conn:
            # Check if player exists
            player_check = conn.execute(text(
                "SELECT player_id FROM player_weekly_stats WHERE player_display_name = :player_name LIMIT 1"
            ), {"player_name": player_name})
            player_result = player_check.fetchone()
            
            if not player_result:
                return {"error": f"Player {player_name} not found"}
            
            player_id = player_result[0]
            
            # Check odds table structure
            odds_structure = conn.execute(text("PRAGMA table_info(odds)"))
            columns = [row[1] for row in odds_structure]
            
            # Get odds count
            odds_count = conn.execute(text("SELECT COUNT(*) FROM odds WHERE player_id = :player_id"), {"player_id": player_id})
            count = odds_count.fetchone()[0]
            
            # Get sample odds
            sample_odds = conn.execute(text("SELECT * FROM odds WHERE player_id = :player_id LIMIT 3"), {"player_id": player_id})
            sample = [dict(r._mapping) for r in sample_odds]
            
            return {
                "player_id": player_id,
                "odds_columns": columns,
                "odds_count": count,
                "sample_odds": sample
            }
    except Exception as e:
        return {"error": str(e)}

# Mount static files: only the dedicated static/ folder (never the project root,
# which holds the DB, .env and source)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


# ---------------------------
# Refresh buttons (stats / odds). Loopback only unless ALLOW_REMOTE_REFRESH=1.
# ---------------------------
LOCAL_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}
FORBIDDEN_MESSAGE = ("Refresh actions are only allowed from the computer running the server. "
                     "Set ALLOW_REMOTE_REFRESH=1 to allow LAN use.")


class RefreshForbidden(Exception):
    def __init__(self, message=FORBIDDEN_MESSAGE):
        self.message = message


@app.exception_handler(RefreshForbidden)
def _refresh_forbidden_handler(request: Request, exc: RefreshForbidden):
    return JSONResponse(status_code=403, content={"error": "forbidden", "message": exc.message})


def _is_loopback(host) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except (ValueError, TypeError):
        return False
    if ip.is_loopback:
        return True
    return ip.version == 6 and ip.ipv4_mapped is not None and ip.ipv4_mapped.is_loopback


def _host_header_name(value) -> str:
    host = (value or "").strip().lower()
    if host.startswith("["):  # [::1]:8000
        return host[1:host.find("]")] if "]" in host else host
    if host.count(":") == 1:  # 127.0.0.1:8000
        return host.split(":", 1)[0]
    return host


def require_local_refresh(request: Request):
    """Gate for refresh endpoints. X-Forwarded-For is never trusted."""
    client_host = request.client.host if request.client else None
    # A custom header forces a CORS preflight, so other web pages can't trigger POSTs
    if request.method == "POST" and request.headers.get("x-nfl-refresh") != "1":
        logger.warning(f"Refresh request without X-NFL-Refresh header from {client_host}")
        raise RefreshForbidden("Missing X-NFL-Refresh header.")
    if os.getenv("ALLOW_REMOTE_REFRESH") == "1":
        return
    if not _is_loopback(client_host) or _host_header_name(request.headers.get("host")) not in LOCAL_HOSTNAMES:
        logger.warning(f"Rejected refresh request from {client_host}")
        raise RefreshForbidden()


class OddsConfirm(BaseModel):
    confirm_games: int = Field(ge=0, le=64)


def _start_job(step, fn, *args):
    job, busy = refresh_jobs.RUNNER.start(step, fn, *args)
    if busy:
        return JSONResponse(status_code=409, content=busy)
    return JSONResponse(status_code=202, content={k: job[k] for k in ("job_id", "step", "status", "started_at")})


@app.post("/refresh/stats", dependencies=[Depends(require_local_refresh)])
def refresh_stats():
    """Reload the last completed week from Sleeper and re-scrape team stats (background job)."""
    return _start_job("stats", refresh_jobs.run_stats_job)


@app.get("/refresh/odds/preview", dependencies=[Depends(require_local_refresh)])
def refresh_odds_preview():
    """Free: upcoming games, estimated credits and remaining quota."""
    try:
        return refresh_jobs.odds_preview()
    except refresh_jobs.NoApiKeys as e:
        return JSONResponse(status_code=503, content={"error": "no_api_keys", "message": str(e)})
    except Exception as e:
        import odds_api
        message = odds_api.redact(str(e))
        logger.error(f"Odds preview failed: {message}")
        return JSONResponse(status_code=502, content={"error": "events_failed", "message": message})


@app.post("/refresh/odds", dependencies=[Depends(require_local_refresh)])
def refresh_odds(body: OddsConfirm):
    """Paid: fetch odds for at most the confirmed number of games (background job)."""
    return _start_job("odds", refresh_jobs.run_odds_job, body.confirm_games)


@app.get("/refresh/status")
def refresh_status():
    last_runs = refresh_jobs.STATE.load().get("last_runs", {})
    return {"running": refresh_jobs.RUNNER.is_running(),
            "job": refresh_jobs.RUNNER.snapshot(),
            "last_runs": {s: last_runs.get(s) for s in refresh_jobs.STEPS}}

@app.get("/players")
@app.get("/players/")
def get_players():
    try:
        with engine.connect() as conn:
            # Try multiple possible table names
            tables_to_try = [
                "SELECT DISTINCT player_display_name FROM player_weekly_stats ORDER BY player_display_name",
                "SELECT DISTINCT player_name FROM player_stats ORDER BY player_name",
                "SELECT DISTINCT full_name FROM players ORDER BY full_name"
            ]
            
            for query_str in tables_to_try:
                try:
                    result = conn.execute(text(query_str))
                    players = [row[0] for row in result if row[0]]
                    if players:
                        logger.info(f"Found {len(players)} players using query: {query_str}")
                        return players
                # amazonq-ignore-next-line
                except Exception:
                    continue
            
            logger.warning("No players found in any table")
            return []
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching players: {e}")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception as e:
        logger.error(f"Unexpected error fetching players: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")



@app.get("/stats/year/{year}/player/{player_name}")
def get_player_stats(year: int, player_name: str):
    """Return all game stats for a player in a season."""
    try:
        with engine.connect() as conn:
            query = text(
                "SELECT * FROM player_weekly_stats WHERE season = :year AND player_display_name = :player_name"
            )
            result = conn.execute(query, {"year": year, "player_name": player_name})
            return [dict(r._mapping) for r in result]
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching player stats: {e}")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception as e:
        logger.error(f"Unexpected error fetching player stats: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/stats/year/{year}/player/{player_name}/season_avg")
def get_player_season_average(year: int, player_name: str):
    """Return season average stats for a player."""
    try:
        with engine.connect() as conn:
            query = text(
                "SELECT * FROM player_weekly_stats WHERE season = :year AND player_display_name = :player_name"
            )
            result = conn.execute(query, {"year": year, "player_name": player_name})
            df = pd.DataFrame([dict(r._mapping) for r in result])
            if df.empty:
                return {}
            
            # Only include actual stat columns, exclude metadata
            stat_columns = ['passing_yards', 'passing_tds', 'rushing_yards', 'rushing_tds', 
                          'receiving_yards', 'receiving_tds', 'receptions', 'targets', 
                          'completions', 'attempts', 'interceptions', 'carries']
            
            # Filter to only existing stat columns
            available_stats = [col for col in stat_columns if col in df.columns]
            if available_stats:
                averages = df[available_stats].mean().to_dict()
            else:
                averages = df.select_dtypes(include=['number']).drop(columns=['season', 'week'], errors='ignore').mean().to_dict()
            
            return averages
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching season averages: {e}")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception as e:
        logger.error(f"Unexpected error fetching season averages: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/stats/recent_average/{year}/player/{player_name}")
def get_recent_average(year: int, player_name: str):
    """Return average of last 5 games for a player."""
    try:
        with engine.connect() as conn:
            query = text(
                """
                SELECT * FROM player_weekly_stats 
                WHERE season = :year AND player_display_name = :player_name
                ORDER BY CAST(week AS INTEGER) DESC LIMIT 5
                """
            )
            result = conn.execute(query, {"year": year, "player_name": player_name})
            df = pd.DataFrame([dict(r._mapping) for r in result])
            if df.empty:
                return {}
            
            # Only include actual stat columns, exclude metadata
            stat_columns = ['passing_yards', 'passing_tds', 'rushing_yards', 'rushing_tds', 
                          'receiving_yards', 'receiving_tds', 'receptions', 'targets', 
                          'completions', 'attempts', 'interceptions', 'carries']
            
            # Filter to only existing stat columns
            available_stats = [col for col in stat_columns if col in df.columns]
            if available_stats:
                averages = df[available_stats].mean().to_dict()
            else:
                averages = df.select_dtypes(include=['number']).drop(columns=['season', 'week'], errors='ignore').mean().to_dict()
            
            return averages
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching recent averages: {e}")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception as e:
        logger.error(f"Unexpected error fetching recent averages: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/stats/recent_3_average/{year}/player/{player_name}")
def get_recent_3_average(year: int, player_name: str):
    """Return average of last 3 games for a player."""
    try:
        with engine.connect() as conn:
            query = text(
                """
                SELECT * FROM player_weekly_stats 
                WHERE season = :year AND player_display_name = :player_name
                ORDER BY CAST(week AS INTEGER) DESC LIMIT 3
                """
            )
            result = conn.execute(query, {"year": year, "player_name": player_name})
            df = pd.DataFrame([dict(r._mapping) for r in result])
            if df.empty:
                return {}
            
            # Only include actual stat columns, exclude metadata
            stat_columns = ['passing_yards', 'passing_tds', 'rushing_yards', 'rushing_tds', 
                          'receiving_yards', 'receiving_tds', 'receptions', 'targets', 
                          'completions', 'attempts', 'interceptions', 'carries']
            
            # Filter to only existing stat columns
            available_stats = [col for col in stat_columns if col in df.columns]
            if available_stats:
                averages = df[available_stats].mean().to_dict()
            else:
                averages = df.select_dtypes(include=['number']).drop(columns=['season', 'week'], errors='ignore').mean().to_dict()
            
            return averages
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching recent 3-game averages: {e}")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception as e:
        logger.error(f"Unexpected error fetching recent 3-game averages: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/odds/player/{player_name}")
def get_player_odds(player_name: str):
    """Return betting odds for a player."""
    try:
        # Read current config
        from pipeline_config import SEASON, COMPARISON_WEEK
        
        with engine.connect() as conn:
            # Use the same logic as the flagging system
            name_variations = [
                player_name,
                player_name.replace('.', ''),
                player_name.replace(' Jr.', ''),
                player_name.replace(' Sr.', ''),
            ]
            
            for name_variant in name_variations:
                result = conn.execute(text("""
                    SELECT * FROM odds 
                    WHERE player_id = :custom_id
                    AND season = :season
                    AND week = :week
                """), {"custom_id": f"custom_{name_variant}", "season": SEASON, "week": COMPARISON_WEEK})
                odds = [dict(r._mapping) for r in result]
                if odds:
                    return odds
            
            return []
    except SQLAlchemyError as e:
        logger.error(f"Database error fetching odds: {e}")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception as e:
        logger.error(f"Unexpected error fetching odds: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/debug/team-stats/{team_abbrev}")
def debug_team_stats(team_abbrev: str):
    """Debug endpoint to show raw team stats data"""
    try:
        from team_stats import get_team_stats_for_player
        raw_stats = get_team_stats_for_player(team_abbrev)
        return raw_stats or {"error": "No data found"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/league-averages")
def get_league_averages():
    """Get league averages for Rush Yards/Game and Pass Yards/Game"""
    try:
        from team_stats import get_league_averages
        return get_league_averages()
    except Exception as e:
        logger.error(f"Error fetching league averages: {e}")
        return {"error": str(e)}

@app.get("/league-defensive-averages")
def get_league_defensive_averages():
    """Get league defensive averages for Opp Rush Yards/Game and Opp Pass Yards/Game"""
    try:
        from team_stats import get_league_defensive_averages
        return get_league_defensive_averages()
    except Exception as e:
        logger.error(f"Error fetching league defensive averages: {e}")
        return {"error": str(e)}

@app.get("/upcoming-game/player/{player_name}")
def get_upcoming_game(player_name: str):
    """Get upcoming game info for a player"""
    try:
        # Read current config
        from pipeline_config import SEASON, COMPARISON_WEEK
        
        with engine.connect() as conn:
            # Use same logic as odds endpoint
            name_variations = [
                player_name,
                player_name.replace('.', ''),
                player_name.replace(' Jr.', ''),
                player_name.replace(' Sr.', ''),
            ]
            
            for name_variant in name_variations:
                result = conn.execute(text("""
                    SELECT DISTINCT event_name FROM odds 
                    WHERE player_id = :custom_id
                    AND season = :season
                    AND week = :week
                    LIMIT 1
                """), {"custom_id": f"custom_{name_variant}", "season": SEASON, "week": COMPARISON_WEEK})
                game = result.fetchone()
                if game:
                    return {"matchup": game[0]}
            
            return {"matchup": "No upcoming game found"}
    except Exception as e:
        logger.error(f"Error fetching upcoming game: {e}")
        return {"matchup": "Error loading game info"}

@app.get("/debug/player-odds/{player_name}")
def debug_player_odds(player_name: str):
    """Debug endpoint to show raw odds data for a player"""
    try:
        with engine.connect() as conn:
            query = text("""
                SELECT * FROM odds WHERE player_id = (
                    SELECT player_id FROM player_weekly_stats 
                    WHERE player_display_name = :player_name 
                    LIMIT 1
                )
            """)
            result = conn.execute(query, {"player_name": player_name})
            odds_data = [dict(r._mapping) for r in result]
            
            # Group by market for easier viewing
            markets = {}
            for odd in odds_data:
                market = odd.get('market', 'unknown')
                if market not in markets:
                    markets[market] = []
                markets[market].append({
                    'bookmaker': odd.get('bookmaker'),
                    'line': odd.get('line'),
                    'price': odd.get('price'),
                    'event_name': odd.get('event_name')
                })
            
            return {
                'player': player_name,
                'total_odds': len(odds_data),
                'markets': markets,
                'raw_sample': odds_data[:5]  # First 5 raw records
            }
    except Exception as e:
        return {"error": str(e)}

@app.get("/team-stats/{team_abbrev}")
def get_team_stats(team_abbrev: str):
    """Get team rushing, passing and defensive stats"""
    try:
        from team_stats import get_team_stats_for_player
        stats = get_team_stats_for_player(team_abbrev)
        # amazonq-ignore-next-line
        logger.info(f"Raw stats for {team_abbrev}: {stats}")
        
        rush_value = stats.get('rush_yards_game', 'N/A')
        pass_value = stats.get('pass_yards_game', 'N/A')
        opp_pass_value = stats.get('opp_pass_yards_game', 'N/A')
        opp_rush_value = stats.get('opp_rush_yards_game', 'N/A')
        
        result = {
            'rushing': {'Rush Yards/Game': rush_value, 'Opp Rush Yards/Game': opp_rush_value}, 
            'passing': {'Pass Yards/Game': pass_value}, 
            'defense': {'Opp Pass Yards/Game': opp_pass_value}
        }
        logger.info(f"Formatted result for {team_abbrev}: {result}")
        return result
    except Exception as e:
        logger.error(f"Error getting team stats for {team_abbrev}: {e}")
        return {'rushing': {}, 'passing': {}, 'defense': {}}


@app.get("/generate-picks")
def generate_picks():
    """Run the configured model (v1 or v2) and return its picks plus model info"""
    t0 = time.monotonic()
    response = _generate_picks_response()
    _record_picks_run(response, round(time.monotonic() - t0, 1))
    return response


NO_STATS_MESSAGE = ("No player stats in the database yet. Run `python save_to_db.py --all` once "
                    "(first-time setup), then Refresh stats each week.")


def _generate_picks_response():
    from model_v2 import ParamsError
    try:
        from test_thresholds import get_picks_with_model
        players, model = get_picks_with_model()
        logger.info(f"Generated picks for {len(players)} players (model {model.get('version')})")
        return {"success": True, "players": players, "count": len(players), "model": model}
    except ParamsError as e:
        logger.error(f"Model v2 parameters invalid: {e}")
        return {"success": False,
                "error": f"Model v2 parameters invalid: {e}. Run backtest.py --write-params or set MODEL_VERSION='v1'."}
    except SQLAlchemyError as e:
        logger.error(f"Database error running picks: {e}")
        if "no such table: player_weekly_stats" in str(e):
            return {"success": False, "error": NO_STATS_MESSAGE}
        return {"success": False, "error": f"Database error: {e}"}
    except Exception as e:
        logger.error(f"Error running threshold analysis: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def _record_picks_run(response, duration_s):
    """Save the picks last-run for the page. Never changes or breaks the picks response."""
    try:
        if response.get("success"):
            model = response.get("model") or {}
            version = model.get("version", "v1")
            rows = [r for p in response["players"] for r in (p.get("stats") or [])]
            flagged = sum(1 for r in rows if r.get("flagged")) if version == "v2" else len(rows)
            refresh_jobs.record_picks_run(True, response["count"], flagged, version, duration_s=duration_s)
        else:
            refresh_jobs.record_picks_run(False, 0, 0, None, error=response.get("error"), duration_s=duration_s)
    except Exception as e:
        logger.warning(f"Could not record picks run: {e}")

@app.get("/thresholds/player/{player_name}/year/{year}")
def test_thresholds(player_name: str, year: int):
    """Check thresholds for player stats vs betting odds."""
    try:
        with engine.connect() as conn:
            # Get player stats
            query = text(
                "SELECT * FROM player_weekly_stats WHERE season = :year AND player_display_name = :player_name"
            )
            result = conn.execute(query, {"year": year, "player_name": player_name})
            player_stats = [dict(r._mapping) for r in result]

            # Get player odds
            query = text("""
                SELECT * FROM odds WHERE player_id = (
                    SELECT player_id FROM player_weekly_stats 
                    WHERE player_display_name = :player_name 
                    LIMIT 1
                )
            """)
            result = conn.execute(query, {"player_name": player_name})
            odds = [dict(r._mapping) for r in result]

        # Example thresholds (customize as needed)
        thresholds = {
            "receiving_yards": 15,
            "rushing_yards": 15,
            "passing_yards": 20,
        }

        flagged = check_stat_against_odds(player_name, player_stats, odds, thresholds)
        return flagged
    except SQLAlchemyError as e:
        logger.error(f"Database error in threshold check: {e}")
        raise HTTPException(status_code=500, detail="Database error")
    except Exception as e:
        logger.error(f"Unexpected error in threshold check: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
