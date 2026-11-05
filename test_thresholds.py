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
# Count markets also need an absolute gap > 1.0 unit before a line is dropped.
COUNT_MARKETS = {"player_receptions", "player_pass_tds", "player_rush_attempts"}

HISTORY_COLS = ['passing_yards', 'passing_tds', 'rushing_yards', 'rushing_tds',
                'receiving_yards', 'receiving_tds', 'receptions']


def get_played_history(conn, player_id, season, week, max_games=17):
    """Played regular-season games strictly before (season, week), most recent first.

    Crosses into earlier seasons. Keyed on player_id. NULL stats read as 0.
    This is the only history query model v2 uses (live and in backtest.py), so
    it owns the leak-free invariant. SQLAlchemyError propagates to the caller.
    """
    rows = conn.execute(text(f"""
        SELECT season, week, gp, position, team, passing_yards, passing_tds, rushing_yards,
               rushing_tds, receiving_yards, receiving_tds, receptions
        FROM player_weekly_stats
        WHERE player_id = :pid
          AND season_type = 'regular'
          AND season IS NOT NULL AND week IS NOT NULL
          AND (season < :season OR (season = :season AND week < :week))
          AND {PLAYED_FILTER}
        ORDER BY season DESC, CAST(week AS INTEGER) DESC
        LIMIT :max_games
    """), {"pid": player_id, "season": season, "week": week, "max_games": max_games}).mappings().all()
    history = []
    for r in rows:
        d = dict(r)
        d["season"] = int(d["season"])
        d["week"] = int(d["week"])
        for c in HISTORY_COLS:
            d[c] = float(d[c]) if d[c] is not None else 0.0
        history.append(d)
    return history


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
        logger.warning(f"Database error fetching stats for player_id {player_id}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error fetching stats for player_id {player_id}: {e}")
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
            logger.info(f"Ambiguous player name skipped: {display_name} -> {sorted(pid for pid, _ in candidates)}")
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
                    SELECT market, line, bookmaker, event_name, price, outcome, commence_time
                    FROM odds
                    WHERE player_id = :custom_id
                    AND season = :season
                    AND week = :week
                """), {"custom_id": f"custom_{name_variant}", "season": season, "week": week}).mappings().all()
                
                if result:
                    return [dict(row) for row in result]
            
            return []
    except SQLAlchemyError as e:
        logger.warning(f"Database error fetching odds for {player_display_name}: {e}")
        return []
    except Exception as e:
        logger.warning(f"Unexpected error fetching odds for {player_display_name}: {e}")
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
            "event_name": r.get("event_name"), "commence_time": r.get("commence_time"), "prices": {},
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
            rel = abs(e["line"] - median) / abs(median)
            if market in COUNT_MARKETS:
                # A one-unit alt line on a count market is a real line: drop only
                # when it is also more than 1.0 unit from the median (strict).
                drop = rel > OUTLIER_MAX_DEVIATION and abs(e["line"] - median) > 1.0
            else:
                drop = rel > OUTLIER_MAX_DEVIATION
            if drop:
                dropped.add(id(e))
                logger.info(f"Dropped outlier line: {player_name} {market} {e['bookmaker']} {e['line']} "
                            f"(median {median}, wk {week} {season})")
    return [e for e in entries if id(e) not in dropped]


def compute_adjustments(conn, player_id, player_stats, odds, season):
    """Display-only weather x matchup adjustments, keyed by stat.

    Returns (opponent_abbr, {stat: build_adjustment(...)}) or (None, {}) when the
    opponent can't be matched exactly. Never feeds the flag rule or probability.
    """
    from team_stats import build_adjustment, MATCHUP_BETA
    from teams import find_opponent
    from weather_adjustments import get_weather_adjustments, format_weather_explanation
    from weather_api import get_weather_for_game

    if not odds or not odds[0].get('event_name'):
        return None, {}
    player_team = get_player_team(conn, player_id, season)
    opponent_abbrev = find_opponent(player_team, odds[0]['event_name'])
    if not opponent_abbrev:
        return None, {}

    # Home stadium weather at kickoff (weather_api returns neutral values + a note when unavailable)
    commence_time = next((o.get('commence_time') for o in odds if o.get('commence_time')), None)
    weather_data = get_weather_for_game(odds[0]['event_name'], commence_time)
    weather_factors = get_weather_adjustments(
        weather_data['temperature'], weather_data['wind_speed'], weather_data['conditions'])
    weather_text = weather_data.get('note') or format_weather_explanation(
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

def _validate_policy(config):
    margin = config.get("V2_EDGE_MARGIN")
    min_games = config.get("V2_MIN_GAMES_FOR_FLAG")
    if isinstance(margin, bool) or not isinstance(margin, (int, float)) or not 0 <= margin <= 0.2:
        raise ValueError("V2_EDGE_MARGIN must be a number in [0, 0.2]")
    if isinstance(min_games, bool) or not isinstance(min_games, int) or not 1 <= min_games <= 17:
        raise ValueError("V2_MIN_GAMES_FOR_FLAG must be an integer in [1, 17]")
    return {"margin": float(margin), "min_games": min_games}


def get_model_info(config, params):
    """Model description returned with /generate-picks (v1: just the version)."""
    if params is None:
        return {"version": "v1"}
    import model_v2
    window = params["window"]
    return {
        "version": "v2",
        "window_label": model_v2.window_label(window),
        "window_n": window["n"] if window["type"] == "last_n" else None,
        "edge_margin_pts": round(100 * float(config["V2_EDGE_MARGIN"]), 1),
        "min_games_for_flag": config["V2_MIN_GAMES_FOR_FLAG"],
        "params_fitted_on": params["fitted_on"],
        "gate_label": params["gate_label"],
        "ou_k_all_zero": all(params["stats"][s]["k"] == 0 for s in model_v2.ALL_STATS),
        "td_k_zero": params["td"]["k"] == 0,
    }


def evaluate_week(season, week, model_version, config, params=None, adjustments=True, include_unflagged=False):
    """Evaluate every player for (season, week) with model v1 or v2.

    Returns (players, summary). players = [{player, player_id, matchup, stats}].
    v1 returns flagged rows only (include_unflagged=True: every line, for the
    harness). v2 returns every evaluated row with a `flagged` boolean.
    Params/policy errors and resolve_player_ids errors propagate to the caller.
    """
    if model_version not in ("v1", "v2"):
        raise ValueError("MODEL_VERSION must be 'v1' or 'v2'")
    policy = None
    if model_version == "v2":
        import model_v2
        policy = _validate_policy(config)
        if params is None:
            params = model_v2.load_params(MODEL_V2_PARAMS_PATH)
    else:
        params = None
    thresholds = config["THRESHOLDS"]
    incomplete = set(config.get("INCOMPLETE_DATA_PLAYERS", []))

    with engine.connect() as conn:
        players = resolve_player_ids(conn, season, week)

    summary = {"players_checked": 0, "flagged": 0, "skipped_db_error": 0, "v1_probability_errors": 0,
               "markets_evaluated": 0, "skipped_no_history": 0, "skipped_mu_le_0": 0, "model_errors": 0,
               "unsupported_line": 0, "no_price": 0, "excluded_far_line": 0}
    v1_errors = []
    out = []
    for player_display_name, player_id in players.items():
        if player_display_name in incomplete:
            continue
        summary["players_checked"] += 1
        try:
            if model_version == "v1":
                player_stats = get_recent_3_game_stats_by_id(season, player_id, current_week=week)
                if not player_stats:
                    continue
                has_meaningful_stats = any(v > 0 for v in player_stats["avg"].values() if isinstance(v, (int, float)))
                if not has_meaningful_stats:
                    continue
                odds = get_odds_for_player(player_display_name, season=season, week=week)
                if not odds:
                    continue
                odds = drop_outlier_lines(collapse_odds(odds), player_display_name, season, week)
                adj = {}
                if adjustments:
                    try:
                        with engine.connect() as conn:
                            _, adj = compute_adjustments(conn, player_id, player_stats, odds, season)
                        store_adjustments_in_avg(player_stats, adj)
                    except Exception as e:
                        logger.warning(f"Adjustment error for {player_display_name}: {e}")
                        adj = {}
                rows = check_stat_against_odds(player_display_name, player_stats, odds, thresholds,
                                               errors=v1_errors, include_unflagged=include_unflagged)
                if rows and adj:
                    apply_adjustments_to_flagged(rows, adj)
                summary["markets_evaluated"] += len(rows)
                summary["flagged"] += sum(1 for r in rows if r["threshold_rule"] != "No Bet")
            else:
                try:
                    with engine.connect() as conn:
                        history = get_played_history(conn, player_id, season, week)
                except SQLAlchemyError as e:
                    logger.warning(f"History query failed for player_id {player_id}: {e}")
                    summary["skipped_db_error"] += 1
                    continue
                odds = get_odds_for_player(player_display_name, season=season, week=week)
                if not odds:
                    continue
                odds = drop_outlier_lines(collapse_odds(odds), player_display_name, season, week)
                rows, counters = model_v2.evaluate_player(player_display_name, history, odds, params, policy,
                                                          target=(season, week))
                for k, v in counters.items():
                    summary[k] += v
                if rows and adjustments:
                    try:
                        mu = {r["stat"]: r["player_value"] for r in rows if r["stat"] in model_v2.ALL_STATS}
                        with engine.connect() as conn:
                            _, adj = compute_adjustments(conn, player_id, {"avg": mu}, odds, season)
                        apply_adjustments_to_flagged(rows, adj)
                    except Exception as e:
                        logger.warning(f"Adjustment error for {player_display_name}: {e}")
                summary["flagged"] += sum(1 for r in rows if r["flagged"])
            if rows:
                out.append({
                    "player": player_display_name,
                    "player_id": player_id,
                    "matchup": (odds[0].get("event_name") or "") if odds else "",
                    "stats": rows,
                })
        except Exception as e:
            logger.exception(f"Error processing player {player_display_name}: {e}")
            continue

    summary["v1_probability_errors"] = len(v1_errors)
    summary["model"] = get_model_info(config, params)
    logger.info("evaluate_week %s %s wk%s: players checked %d, markets evaluated %d, flagged %d, no_price %d, "
                "excluded_far_line %d, model_errors %d, skipped_db_error %d, v1_probability_errors %d",
                model_version, season, week, summary["players_checked"], summary["markets_evaluated"],
                summary["flagged"], summary["no_price"], summary["excluded_far_line"], summary["model_errors"],
                summary["skipped_db_error"], summary["v1_probability_errors"])
    return out, summary


def get_picks_with_model():
    """(players, model info) for the configured season/week and MODEL_VERSION."""
    config = read_config_from_file()
    season, week = config['SEASON'], config['COMPARISON_WEEK']
    version = config.get('MODEL_VERSION', 'v1')
    logger.info(f"Generating picks for Season={season}, Week={week}, model={version} "
                f"(config source: {config.get('CONFIG_SOURCE', 'unknown')})")
    players, summary = evaluate_week(season, week, version, config)
    return players, summary["model"]


def get_flagged_players_json_updated():
    """Return flagged players as JSON for API use"""
    return get_picks_with_model()[0]


def _fmt(v, suffix=""):
    return "-" if v is None else f"{v}{suffix}"


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    output_json = '--json' in sys.argv

    config = read_config_from_file()
    SEASON = config['SEASON']
    COMPARISON_WEEK = config['COMPARISON_WEEK']
    version = config.get('MODEL_VERSION', 'v1')

    if not output_json:
        print(f"Using config: Season={SEASON}, Week={COMPARISON_WEEK}, model={version}")
        if version == "v1":
            print(f"Thresholds: {config['THRESHOLDS']}")

    try:
        players, summary = evaluate_week(SEASON, COMPARISON_WEEK, version, config)
    except Exception as e:
        if output_json:
            print(json.dumps({"success": False, "error": str(e)}))
        else:
            print(f"Error: {e}")
        sys.exit(1)

    if output_json:
        print(json.dumps({"success": True, "players": players, "count": len(players), "model": summary["model"]}))
    elif version == "v1":
        for p in players:
            print(f"\nFlagged stats for {p['player']} - {p['matchup']}:")
            for f in p["stats"]:
                print(f"  Player={f['player_name']}, Bookmaker={f['bookmaker']}, "
                      f"Stat={f['stat']}, Player Value={f['player_value']}, "
                      f"Line={f['line']}, Diff={f['difference']}, "
                      f"Std Dev={f['std_dev']}, Rule={f['threshold_rule']}")
    else:
        n_label = summary["model"]["window_label"]
        print(f"Player, Stat, Line, Side, Avg({n_label}), Model%, Market%, Final%, Price, Edge, Flagged/Reason")
        for p in players:
            for r in p["stats"]:
                print(f"{p['player']}, {r['stat']}, {_fmt(r['line'])}, {r['side']}, {r['player_value']}, "
                      f"{_fmt(r['probModel'])}, {_fmt(r['probMarket'])}, {_fmt(r['probFinal'])}, "
                      f"{_fmt(r['price'])}, {_fmt(r['edgePts'])}, "
                      f"{'FLAGGED' if r['flagged'] else r['noFlagReason']}")
