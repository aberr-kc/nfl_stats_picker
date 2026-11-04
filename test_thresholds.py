# check_thresholds.py
import logging
import os
import statistics
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from Odds_vs_Stats_Check import check_stat_against_odds, compute_player_stats
import traceback

# NFL_STATS_DB lets backtest.py / verification point every engine at a DB copy.
DB_PATH = "sqlite:///" + os.getenv("NFL_STATS_DB", "nfl_stats.db")
# Fitted v2 parameters (written only by backtest.py --write-params).
MODEL_V2_PARAMS_PATH = os.getenv(
    "NFL_MODEL_V2_PARAMS", str(Path(__file__).resolve().parent / "model_v2_params.json"))
engine = create_engine(DB_PATH)
logger = logging.getLogger(__name__)

STAT_COLS = ['passing_yards', 'passing_tds', 'rushing_yards', 'rushing_tds',
             'receiving_yards', 'receiving_tds', 'receptions']
_ANY_STAT_NONZERO = "(" + " OR ".join(f"COALESCE({c}, 0) <> 0" for c in STAT_COLS) + ")"
# A game counts only if the player played: Sleeper gp > 0. Rows not yet
# backfilled (gp NULL) fall back to "any stat non-zero".
PLAYED_FILTER = f"(gp > 0 OR (gp IS NULL AND {_ANY_STAT_NONZERO}))"

# Stat -> key used for the adjusted value in flagged rows (as before)
ADJUSTED_KEYS = {
    'passing_yards': 'adjustedPassingYards',
    'rushing_yards': 'adjustedRushingYards',
    'receiving_yards': 'adjustedReceivingYards',
    'receptions': 'adjustedReceptions',
}

# Outlier lines: drop a bookmaker's line when it is more than this fraction
# away from the median line across bookmakers (math review S10 / rec #10).
OUTLIER_MAX_DEVIATION = 0.25


def get_recent_3_game_stats_by_id(year: int, player_id: str, current_week: int):
    """
    Pull a player's last 3 games played before current_week (regular season)
    and compute rolling averages/std dev.
    Special-case handling: if only 1 game exists, use raw values with std=0.
    Now includes reception share calculations.
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT *
                FROM player_weekly_stats
                WHERE season = :year 
                  AND player_id = :pid
                  AND week < :current_week
                  AND season_type = 'regular'
                  AND {PLAYED_FILTER}
                ORDER BY CAST(week AS INTEGER) DESC
                LIMIT 3
            """), {"year": year, "pid": player_id, "current_week": current_week}).fetchall()

            if not result:
                return None

            rows = [dict(r._mapping) for r in result]

            # ✅ If only 1 game → just return raw stats
            if len(rows) == 1:
                single = rows[0]
                avg = {k: float(v) for k, v in single.items() if isinstance(v, (int, float))}
                stats = {"avg": avg, "std": {k: 0.0 for k in avg}, "weekly": rows}
            else:
                # ✅ Otherwise use the shared averaging function
                stats = compute_player_stats(rows)
                stats["weekly"] = rows
            
            # Add reception share calculation
            try:
                from target_share_calc import calculate_team_totals, calculate_player_reception_share
                
                # Get player's team
                player_team = rows[0].get('team')
                if player_team:
                    # Calculate team totals for the weeks this player played
                    weeks_played = [row['week'] for row in rows if row.get('week')]
                    if weeks_played:
                        team_totals = calculate_team_totals(year, weeks_played)
                        shares = calculate_player_reception_share(stats, team_totals, player_team)
                        stats["reception_share"] = shares["reception_share"]
                        stats["rushing_opportunity"] = shares["rushing_opportunity"]
            except Exception as e:
                # Don't fail if reception share calculation fails
                stats["reception_share"] = 0
                stats["rushing_opportunity"] = 0
            
            return stats

    except SQLAlchemyError as e:
        print(f"Database error fetching stats for player_id {player_id}: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error fetching stats for player_id {player_id}: {e}")
        return None


def get_recent_3_game_stats(year: int, player_display_name: str, current_week: int):
    """Name-based wrapper (for the qb/target-share/debug scripts): resolves the name to one player_id."""
    with engine.connect() as conn:
        player_id = resolve_player_id(conn, player_display_name, year, current_week)
    if player_id is None:
        return None
    return get_recent_3_game_stats_by_id(year, player_id, current_week)


def _resolve_names(conn, season, current_week, name=None):
    """Return {display_name: player_id} for players with rows before current_week.

    A name used by several player_ids maps to the one with real stats (a played
    game with a non-zero offensive stat) in this season, most recent first.
    Still ambiguous (or no such id) -> the name is skipped and logged.
    """
    name_clause = "AND player_display_name = :name" if name is not None else ""
    rows = conn.execute(text(f"""
        SELECT player_display_name, player_id,
               MAX(CASE WHEN {PLAYED_FILTER} AND {_ANY_STAT_NONZERO}
                        THEN CAST(week AS INTEGER) END) AS last_stat_week
        FROM player_weekly_stats
        WHERE season = :season
          AND week < :current_week
          AND season_type = 'regular'
          AND player_display_name IS NOT NULL
          AND player_display_name <> ''
          {name_clause}
        GROUP BY player_display_name, player_id
    """), {"season": season, "current_week": current_week, "name": name}).fetchall()

    by_name = {}
    for display_name, pid, last_week in rows:
        by_name.setdefault(display_name, []).append((pid, last_week))

    resolved = {}
    for display_name, candidates in by_name.items():
        if len(candidates) == 1:
            resolved[display_name] = candidates[0][0]
            continue
        with_stats = [(pid, wk) for pid, wk in candidates if wk is not None]
        best_week = max((wk for _, wk in with_stats), default=None)
        best = [pid for pid, wk in with_stats if wk == best_week]
        if len(best) == 1:
            resolved[display_name] = best[0]
        else:
            # stderr, so the --json CLI output stays valid JSON
            print(f"Ambiguous player name skipped: {display_name} -> {sorted(pid for pid, _ in candidates)}", file=sys.stderr)
    return resolved


def resolve_player_ids(conn, season, current_week):
    """{display_name: player_id} for every player in the season before current_week."""
    return _resolve_names(conn, season, current_week)


def resolve_player_id(conn, name, season, current_week):
    """player_id for one display name, or None if unknown/ambiguous."""
    return _resolve_names(conn, season, current_week, name=name).get(name)


def get_player_team(conn, player_id, season):
    """Player's team for the season (latest row by week), or None."""
    row = conn.execute(text("""
        SELECT team FROM player_weekly_stats
        WHERE player_id = :pid AND season = :season AND team IS NOT NULL AND team <> ''
        ORDER BY week DESC
        LIMIT 1
    """), {"pid": player_id, "season": season}).fetchone()
    return row[0] if row else None


def get_weekly_breakdown(weekly_data, stat_name):
    """Get weekly breakdown for a specific stat"""
    breakdown = []
    for week_data in weekly_data[-5:]:  # Last 5 weeks
        week = week_data.get('week', 'N/A')
        value = week_data.get(stat_name, 0)
        breakdown.append(f"W{week}: {value}")
    return ", ".join(breakdown)


def get_odds_for_player(player_display_name: str, season=None, week=None):
    """Fetch all odds for a player from your odds table for current week only"""
    try:
        # Use provided values or read from config
        if season is None or week is None:
            config = read_config_from_file()
            season = season or config['SEASON']
            week = week or config['COMPARISON_WEEK']
            
        with engine.connect() as conn:
            # Try multiple name variations to handle formatting differences
            name_variations = [
                player_display_name,  # Original name
                player_display_name.replace('.', ''),  # Remove periods: A.J. Brown -> AJ Brown
                player_display_name.replace(' Jr.', ''),  # Remove Jr.
                player_display_name.replace(' Sr.', ''),  # Remove Sr.
            ]
            
            for name_variant in name_variations:
                result = conn.execute(text("""
                    SELECT market, line, bookmaker, event_name, price, outcome
                    FROM odds
                    WHERE player_id = :custom_id
                    AND season = :season
                    AND week = :week
                """), {"custom_id": f"custom_{name_variant}", "season": season, "week": week}).mappings().all()
                
                if result:
                    return [dict(row) for row in result]
            
            return []
    except SQLAlchemyError as e:
        print(f"Database error fetching odds for {player_display_name}: {e}")
        return []
    except Exception as e:
        print(f"Unexpected error fetching odds for {player_display_name}: {e}")
        return []


def collapse_odds(rows):
    """One entry per (market, bookmaker, line) with a prices dict.

    Over and Under are separate DB rows; here they become
    {"prices": {"Over": 1.87, "Under": 1.95}}. Rows saved before the outcome
    column existed give {"unknown": price}, and are ignored for a
    market/bookmaker that also has rows with an outcome.
    """
    with_outcome = {(r.get("market"), r.get("bookmaker")) for r in rows if r.get("outcome")}
    entries = {}
    for r in rows:
        mb = (r.get("market"), r.get("bookmaker"))
        outcome = r.get("outcome")
        if not outcome and mb in with_outcome:
            continue
        key = (r.get("market"), r.get("bookmaker"), r.get("line"))
        entry = entries.setdefault(key, {
            "market": r.get("market"), "line": r.get("line"), "bookmaker": r.get("bookmaker"),
            "event_name": r.get("event_name"), "prices": {},
        })
        entry["prices"][outcome or "unknown"] = r.get("price")
    return list(entries.values())


def drop_outlier_lines(entries, player_name, season, week):
    """Drop a bookmaker's line that is >25% from the median line for that market.

    Evaluation-time only; the DB keeps every line. A market quoted by a single
    entry can't be checked and is kept.
    """
    by_market = {}
    for e in entries:
        if e.get("line") is not None:
            by_market.setdefault(e["market"], []).append(e)

    dropped = set()
    for market, group in by_market.items():
        if len(group) < 2:
            logger.debug(f"Outlier check not checkable (single line): {player_name} {market} "
                         f"{group[0]['bookmaker']} {group[0]['line']} (wk {week} {season})")
            continue
        median = statistics.median(e["line"] for e in group)
        if median == 0:
            continue
        for e in group:
            if abs(e["line"] - median) / abs(median) > OUTLIER_MAX_DEVIATION:
                dropped.add(id(e))
                print(f"Dropped outlier line: {player_name} {market} {e['bookmaker']} {e['line']} "
                      f"(median {median}, wk {week} {season})", file=sys.stderr)
    return [e for e in entries if id(e) not in dropped]


def compute_adjustments(conn, player_id, player_stats, odds, season):
    """Display-only weather x matchup adjustments, keyed by stat.

    Returns (opponent_abbr, {stat: build_adjustment(...)}) or (None, {}) when the
    opponent can't be matched exactly. Never feeds the flag rule or probability.
    """
    from team_stats import build_adjustment, MATCHUP_BETA
    from teams import ABBR_TO_FULL, find_opponent
    from weather_adjustments import get_weather_adjustments, format_weather_explanation
    from weather_api import get_weather_for_game

    if not odds or not odds[0].get('event_name'):
        return None, {}
    player_team = get_player_team(conn, player_id, season)
    opponent_abbrev = find_opponent(player_team, odds[0]['event_name'])
    if not opponent_abbrev:
        return None, {}

    weather_data = get_weather_for_game(ABBR_TO_FULL[player_team], ABBR_TO_FULL[opponent_abbrev])
    weather_factors = get_weather_adjustments(
        weather_data['temperature'], weather_data['wind_speed'], weather_data['conditions'])
    weather_text = format_weather_explanation(
        weather_data['temperature'], weather_data['wind_speed'], weather_data['conditions'])

    adjustments = {}
    for stat_name in MATCHUP_BETA:  # passing_tds stays unadjusted
        if stat_name in player_stats["avg"]:
            adjustments[stat_name] = build_adjustment(
                stat_name, player_stats["avg"][stat_name], weather_factors.get(stat_name, 1.0),
                weather_text, opponent_abbrev, season)
    return opponent_abbrev, adjustments


def store_adjustments_in_avg(player_stats, adjustments):
    """Write adjusted_<stat> and factor/explanation keys into player_stats['avg'] (display only)."""
    for stat_name, adj in adjustments.items():
        player_stats["avg"][f"adjusted_{stat_name}"] = adj["adjusted"]
        player_stats["avg"][f"{stat_name}_weather_factor"] = adj["weatherFactor"]
        player_stats["avg"][f"{stat_name}_team_factor"] = adj["teamFactor"]
        player_stats["avg"][f"{stat_name}_team_explanation"] = adj["teamExplanation"]


def apply_adjustments_to_flagged(flagged, adjustments):
    """Set adjusted<Stat> and adjustmentDetails on flagged rows."""
    for f in flagged:
        adj = adjustments.get(f['stat'])
        if not adj:
            continue
        f[ADJUSTED_KEYS[f['stat']]] = adj["adjusted"]
        f['adjustmentDetails'] = {
            'original': adj["original"],
            'adjusted': adj["adjusted"],
            'changePct': adj["changePct"],
            'explanation': adj["explanation"],
        }


def read_config_from_file():
    """Read config values directly from file to avoid caching"""
    config = {}
    with open('pipeline_config.py', 'r') as f:
        content = f.read()
        # amazonq-ignore-next-line
        exec(content, config)
    # Verification-only override; validated in evaluate_week.
    if os.getenv("NFL_MODEL_VERSION"):
        config["MODEL_VERSION"] = os.getenv("NFL_MODEL_VERSION")
    return config

def get_flagged_players_json_updated():
    """Return flagged players as JSON for API use"""
    import json
    
    config = read_config_from_file()
    SEASON = config['SEASON']
    COMPARISON_WEEK = config['COMPARISON_WEEK']
    THRESHOLDS = config['THRESHOLDS']
    INCOMPLETE_DATA_PLAYERS = config['INCOMPLETE_DATA_PLAYERS']
    print(f"Generating picks for Season={SEASON}, Week={COMPARISON_WEEK} (config source: {config.get('CONFIG_SOURCE', 'unknown')})")
    
    flagged_players = []
    
    try:
        with engine.connect() as conn:
            players = resolve_player_ids(conn, SEASON, COMPARISON_WEEK)
    except Exception as e:
        print(f"Error in get_flagged_players_json: {e}")
        import traceback
        traceback.print_exc()
        return []
    
    players_checked = 0
    players_with_stats = 0
    players_with_odds = 0
    
    for player_display_name, player_id in players.items():
        players_checked += 1
        
        try:
            player_stats = get_recent_3_game_stats_by_id(SEASON, player_id, current_week=COMPARISON_WEEK)
            if not player_stats:
                continue

            has_meaningful_stats = any(v > 0 for v in player_stats["avg"].values() if isinstance(v, (int, float)))
            if not has_meaningful_stats or player_display_name in INCOMPLETE_DATA_PLAYERS:
                continue
            
            players_with_stats += 1

            odds = get_odds_for_player(player_display_name, season=SEASON, week=COMPARISON_WEEK)
            if not odds:
                if players_with_odds < 5:  # Debug first few
                    print(f"DEBUG: No odds for {player_display_name}")
                continue
            
            players_with_odds += 1
            odds = drop_outlier_lines(collapse_odds(odds), player_display_name, SEASON, COMPARISON_WEEK)

            # Calculate adjusted stats before flagging (display only)
            adjustments = {}
            try:
                with engine.connect() as conn:
                    _, adjustments = compute_adjustments(conn, player_id, player_stats, odds, SEASON)
                store_adjustments_in_avg(player_stats, adjustments)
            except Exception as e:
                print(f"Adjustment error for {player_display_name}: {e}")
                adjustments = {}
            
            flagged = check_stat_against_odds(player_display_name, player_stats, odds, THRESHOLDS)
            if flagged:
                apply_adjustments_to_flagged(flagged, adjustments)

                matchup_info = ""
                if odds and odds[0].get('event_name'):
                    matchup_info = odds[0]['event_name']
                
                flagged_players.append({
                    'player': player_display_name,
                    'matchup': matchup_info,
                    'stats': flagged
                })
        except Exception as e:
            print(f"Error processing player {player_display_name}: {e}")
            continue
    
    print(f"DEBUG: Checked {players_checked} players, {players_with_stats} had stats, {players_with_odds} had odds, {len(flagged_players)} flagged")
    return flagged_players

if __name__ == "__main__":
    import json
    import sys
    
    # Check if we should output JSON
    output_json = '--json' in sys.argv
    
    # Read fresh config from file
    config = read_config_from_file()
    
    SEASON = config['SEASON']
    COMPARISON_WEEK = config['COMPARISON_WEEK']
    THRESHOLDS = config['THRESHOLDS']
    INCOMPLETE_DATA_PLAYERS = config['INCOMPLETE_DATA_PLAYERS']
    
    year = SEASON
    current_week = COMPARISON_WEEK
    
    if not output_json:
        print(f"Using config: Season={SEASON}, Week={COMPARISON_WEEK}")
        print(f"Thresholds: {THRESHOLDS}")

    # Fetch all players in DB (one player_id per display name)
    try:
        with engine.connect() as conn:
            players = resolve_player_ids(conn, year, current_week)
    except SQLAlchemyError as e:
        if output_json:
            print(json.dumps({"error": f"Database error: {e}"}))
        else:
            print(f"Database error fetching players: {e}")
        exit(1)
    except Exception as e:
        if output_json:
            print(json.dumps({"error": f"Unexpected error: {e}"}))
        else:
            print(f"Unexpected error fetching players: {e}")
        exit(1)

    flagged_players = []
    
    for player_display_name, player_id in players.items():
        try:
            player_stats = get_recent_3_game_stats_by_id(year, player_id, current_week=current_week)
            if not player_stats:
                continue

            has_meaningful_stats = any(v > 0 for v in player_stats["avg"].values() if isinstance(v, (int, float)))
            
            if not has_meaningful_stats or player_display_name in INCOMPLETE_DATA_PLAYERS:
                continue

            odds = get_odds_for_player(player_display_name, season=year, week=current_week)
            if not odds:
                continue
            odds = drop_outlier_lines(collapse_odds(odds), player_display_name, year, current_week)

            flagged = check_stat_against_odds(player_display_name, player_stats, odds, THRESHOLDS)

            if flagged:
                # Calculate adjusted stats (display only)
                try:
                    with engine.connect() as conn:
                        _, adjustments = compute_adjustments(conn, player_id, player_stats, odds, year)
                    apply_adjustments_to_flagged(flagged, adjustments)
                except Exception:
                    pass

                # Get matchup info
                matchup_info = ""
                if odds and odds[0].get('event_name'):
                    matchup_info = odds[0]['event_name']
                
                if output_json:
                    flagged_players.append({
                        'player': player_display_name,
                        'matchup': matchup_info,
                        'stats': flagged
                    })
                else:
                    print(f"\nFlagged stats for {player_display_name} - {matchup_info}:")
                    for f in flagged:
                        print(f"  Player={f['player_name']}, Bookmaker={f['bookmaker']}, "
                              f"Stat={f['stat']}, Player Value={f['player_value']}, "
                              f"Line={f['line']}, Diff={f['difference']}, "
                              f"Std Dev={f['std_dev']}, Rule={f['threshold_rule']}")

        except Exception as e:
            if not output_json:
                print(f"Error checking thresholds for player {player_display_name}: {e}")
    
    if output_json:
        print(json.dumps(flagged_players))
