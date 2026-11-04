"""NFL player-prop model v2: pure calculations, no DB, no pandas.

Every function here is shared by the live path (test_thresholds.evaluate_week)
and the back-test harness (backtest.py), so the two can't diverge.

Probabilities are for half-point lines: P(Over) = P(X >= ceil(L)).
"""
import json
import logging
import math
import statistics

logger = logging.getLogger(__name__)

OU_MARKETS = {
    "player_pass_yds": "passing_yards",
    "player_pass_tds": "passing_tds",
    "player_reception_yds": "receiving_yards",
    "player_receptions": "receptions",
    "player_rush_yds": "rushing_yards",
}
TD_MARKET = "player_anytime_td"
YARDS_STATS = ("passing_yards", "receiving_yards", "rushing_yards")
COUNT_STATS = ("receptions", "passing_tds")
ALL_STATS = YARDS_STATS + COUNT_STATS
DIST_CHOICES = {
    **{s: ("lognormal", "empirical_ratio", "normal") for s in YARDS_STATS},
    **{s: ("negbin", "poisson", "normal") for s in COUNT_STATS},
}
DEFAULT_O_OU = 1.064
DEFAULT_O_TD = 1.25
K_CAP = 0.25
TD_POSITIONS = ("QB", "RB", "WR", "TE")
BLEND_MIN_GAMES = 6
BLEND_PRIOR_GAMES = 10
MAX_RATIOS = 2000


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

class ParamsError(Exception):
    """Model v2 parameters missing, unreadable or out of range."""


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def validate_params(d):
    """Raise ParamsError naming the offending key; return d when valid."""
    if not isinstance(d, dict):
        raise ParamsError("params must be a JSON object")
    if d.get("version") != 2:
        raise ParamsError("version must be 2")
    w = d.get("window")
    if not isinstance(w, dict):
        raise ParamsError("window missing")
    if w.get("type") == "last_n":
        n = w.get("n")
        if not (isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= 17):
            raise ParamsError("window.n must be an integer in [1, 17]")
    elif w.get("type") == "ewma":
        h = w.get("half_life")
        if not (_num(h) and 1 <= h <= 17):
            raise ParamsError("window.half_life must be in [1, 17]")
        mg = w.get("max_games", 17)
        if not (isinstance(mg, int) and 1 <= mg <= 17):
            raise ParamsError("window.max_games must be an integer in [1, 17]")
    else:
        raise ParamsError("window.type must be 'last_n' or 'ewma'")
    stats = d.get("stats")
    if not isinstance(stats, dict):
        raise ParamsError("stats missing")
    for s in ALL_STATS:
        p = stats.get(s)
        if not isinstance(p, dict):
            raise ParamsError(f"stats.{s} missing")
        for key in ("c", "a", "b", "dist", "k", "blend"):
            if key not in p:
                raise ParamsError(f"stats.{s}.{key} missing")
        if not (_num(p["c"]) and 0.8 <= p["c"] <= 1.2):
            raise ParamsError(f"stats.{s}.c must be in [0.8, 1.2]")
        if not (_num(p["a"]) and p["a"] > 0):
            raise ParamsError(f"stats.{s}.a must be > 0")
        if not (_num(p["b"]) and p["b"] >= p["a"]):
            raise ParamsError(f"stats.{s}.b must be >= a")
        if p["dist"] not in DIST_CHOICES[s]:
            raise ParamsError(f"stats.{s}.dist must be one of {DIST_CHOICES[s]}")
        if not (_num(p["k"]) and 0 <= p["k"] <= K_CAP):
            raise ParamsError(f"stats.{s}.k must be in [0, {K_CAP}]")
        if not isinstance(p["blend"], bool):
            raise ParamsError(f"stats.{s}.blend must be true or false")
        if p["dist"] == "empirical_ratio":
            r = p.get("ratios")
            if not (isinstance(r, list) and 0 < len(r) <= MAX_RATIOS and all(_num(x) for x in r)):
                raise ParamsError(f"stats.{s}.ratios must be a list of 1-{MAX_RATIOS} numbers")
    td = d.get("td")
    if not isinstance(td, dict):
        raise ParamsError("td missing")
    if not (_num(td.get("n0")) and td["n0"] >= 0):
        raise ParamsError("td.n0 must be >= 0")
    lam0 = td.get("lambda0")
    if not isinstance(lam0, dict) or "ALL" not in lam0:
        raise ParamsError("td.lambda0 must include ALL")
    for pos, v in lam0.items():
        if not (_num(v) and 0 < v < 2):
            raise ParamsError(f"td.lambda0.{pos} must be in (0, 2)")
    if not (_num(td.get("k")) and 0 <= td["k"] <= K_CAP):
        raise ParamsError(f"td.k must be in [0, {K_CAP}]")
    if not (_num(td.get("o")) and 1.0 <= td["o"] <= 1.6):
        raise ParamsError("td.o must be in [1.0, 1.6]")
    if not (_num(d.get("o_ou")) and 1.0 <= d["o_ou"] <= 1.6):
        raise ParamsError("o_ou must be in [1.0, 1.6]")
    for key in ("fitted_on", "gate_label"):
        if not (isinstance(d.get(key), str) and d[key].strip()):
            raise ParamsError(f"{key} must be a non-empty string")
    return d


def load_params(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        raise ParamsError(f"not found: {path}")
    except (OSError, ValueError) as e:
        raise ParamsError(f"unreadable {path}: {e}")
    return validate_params(d)


def window_label(window):
    if window["type"] == "last_n":
        return f"last {window['n']} played"
    return f"weighted, half-life {window['half_life']:g} games"


# ---------------------------------------------------------------------------
# Mean, dispersion, distributions
# ---------------------------------------------------------------------------

def window_mean(values, window):
    """(mu, n_eff, n_used) over the most-recent-first values, or None."""
    if not values:
        return None
    if window["type"] == "last_n":
        used = values[:window["n"]]
        return sum(used) / len(used), float(len(used)), len(used)
    h = float(window["half_life"])
    used = values[:window.get("max_games", 17)]
    w = [0.5 ** (j / h) for j in range(len(used))]
    sw = sum(w)
    mu = sum(wi * x for wi, x in zip(w, used)) / sw
    n_eff = sw * sw / sum(wi * wi for wi in w)
    return mu, n_eff, len(used)


def cv(a, b, n_eff):
    return math.sqrt(a + b / n_eff)


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _threshold(line):
    """Smallest integer outcome that beats the line."""
    return math.ceil(line)


def p_over_lognormal(mu, cv_, line):
    s2 = math.log(1.0 + cv_ * cv_)
    s = math.sqrt(s2)
    m = math.log(mu) - s2 / 2.0
    return 1.0 - norm_cdf((math.log(line) - m) / s)


def p_over_normal(mu, cv_, line):
    return 1.0 - norm_cdf((line - mu) / (cv_ * mu))


def p_over_poisson(mu, line):
    kmax = _threshold(line)
    cdf = 0.0
    for j in range(kmax):
        cdf += math.exp(-mu + j * math.log(mu) - math.lgamma(j + 1))
    return min(max(1.0 - cdf, 0.0), 1.0)


def p_over_negbin(mu, cv_, line):
    var = (cv_ * mu) ** 2
    if var <= mu:
        return p_over_poisson(mu, line)
    r = mu * mu / (var - mu)
    p = r / (r + mu)
    kmax = _threshold(line)
    cdf = 0.0
    for j in range(kmax):
        cdf += math.exp(math.lgamma(j + r) - math.lgamma(r) - math.lgamma(j + 1)
                        + r * math.log(p) + j * math.log(1.0 - p))
    return min(max(1.0 - cdf, 0.0), 1.0)


def p_over_empirical(mu, ratios, line):
    hits = sum(1 for r in ratios if r * mu > line)
    return (hits + 0.5) / (len(ratios) + 1)


def p_over_dist(dist, mu, cv_, line, ratios=None):
    if dist == "lognormal":
        return p_over_lognormal(mu, cv_, line)
    if dist == "normal":
        return p_over_normal(mu, cv_, line)
    if dist == "negbin":
        return p_over_negbin(mu, cv_, line)
    if dist == "poisson":
        return p_over_poisson(mu, line)
    if dist == "empirical_ratio":
        return p_over_empirical(mu, ratios, line)
    raise ValueError(f"unknown dist {dist}")


def model_prob_over(stat, values, line, stat_params, window):
    """(p_over, mu_raw, mu_used, n_eff, n_used), or (None, reason)."""
    if line is None or not math.isfinite(line) or line <= 0:
        return None, "unsupported line"
    if float(line).is_integer():
        logger.info("integer line not supported: %s %s", stat, line)
        return None, "integer line not supported"
    wm = window_mean(values, window)
    if wm is None:
        logger.debug("no played history: %s", stat)
        return None, "no history"
    mu_raw, n_eff, n_used = wm
    dist = stat_params["dist"]
    c = 1.0 if dist == "empirical_ratio" else stat_params["c"]
    mu = c * mu_raw
    if mu <= 0:
        logger.debug("mu <= 0: %s", stat)
        return None, "mu<=0"
    cv_ = cv(stat_params["a"], stat_params["b"], n_eff)
    if stat_params.get("blend"):
        own = values[:17]
        if len(own) >= BLEND_MIN_GAMES:
            w = len(own) / (len(own) + BLEND_PRIOR_GAMES)
            var = (1 - w) * (cv_ * mu) ** 2 + w * statistics.stdev(own) ** 2
            cv_ = max(math.sqrt(var) / mu, 1e-6)
    p = p_over_dist(dist, mu, cv_, line, stat_params.get("ratios"))
    return p, mu_raw, mu, n_eff, n_used


# ---------------------------------------------------------------------------
# Prices, market probability, anchoring, edge, flag rule
# ---------------------------------------------------------------------------

_WARNED = set()


def _warn_once(key, msg, *args):
    if key not in _WARNED:
        _WARNED.add(key)
        logger.warning(msg, *args)


def valid_price(p):
    """Decimal price as float if 1.01 <= p <= 1000, else None."""
    if isinstance(p, bool):
        return None
    try:
        p = float(p)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(p) or p < 1.01 or p > 1000:
        return None
    return p


def sides_for(market):
    return ("Yes", "No") if market == TD_MARKET else ("Over", "Under")


def group_lines(entries, player_name=""):
    """{(market, line): group} from collapse_odds-shaped entries.

    group = {"market", "line", "event_name", "books_both", "valid": {side: [(book, price)]},
             "best": {side: (price, [books])}, "unknown_books", "prices": {book: {outcome: price}}}
    "unknown" (NULL outcome) prices are display-only for O/U; for anytime TD they mean Yes.
    """
    groups = {}
    for e in entries:
        market = e.get("market")
        if market not in OU_MARKETS and market != TD_MARKET:
            continue
        line = e.get("line")
        if market == TD_MARKET:
            line = None
        book = e.get("bookmaker")
        g = groups.setdefault((market, line), {
            "market": market, "line": line, "event_name": e.get("event_name"),
            "books_both": [], "valid": {}, "best": {}, "unknown_books": [], "prices": {},
        })
        prices = dict(e.get("prices") or {})
        g["prices"].setdefault(book, {}).update(prices)
        sides = sides_for(market)
        book_sides = {}
        if market != TD_MARKET and prices and set(prices) == {"unknown"}:
            g["unknown_books"].append(book)
        for outcome, raw in prices.items():
            if outcome == "unknown":
                if market != TD_MARKET:
                    continue  # side unknown: display only
                side = "Yes"
            elif outcome in sides:
                side = outcome
            else:
                _warn_once(("outcome", player_name, market, book, outcome),
                           "Ignored odds outcome %r: %s %s %s", outcome, player_name, market, book)
                continue
            p = valid_price(raw)
            if p is None:
                _warn_once(("price", player_name, market, book),
                           "Invalid price %r treated as missing: %s %s %s", raw, player_name, market, book)
                continue
            book_sides[side] = p
        for side, p in book_sides.items():
            g["valid"].setdefault(side, []).append((book, p))
        if all(s in book_sides for s in sides):
            g["books_both"].append((book, book_sides[sides[0]], book_sides[sides[1]]))
    for g in groups.values():
        for side, lst in g["valid"].items():
            best = max(p for _, p in lst)
            g["best"][side] = (best, [b for b, p in lst if p == best])
    return groups


def market_prob(group, o_family):
    """(P_mkt of the first side (Over / Yes), source, overround or None)."""
    s0, s1 = sides_for(group["market"])
    if group["books_both"]:
        per_book = []
        for _, d0, d1 in group["books_both"]:
            q0, q1 = 1.0 / d0, 1.0 / d1
            per_book.append(q0 / (q0 + q1))
        return statistics.median(per_book), "no-vig", None
    v0, v1 = group["valid"].get(s0), group["valid"].get(s1)
    if v0 and v1:
        q0 = statistics.median(1.0 / p for _, p in v0)
        q1 = statistics.median(1.0 / p for _, p in v1)
        return q0 / (q0 + q1), "no-vig (cross-book)", None
    if v0 or v1:
        lst = v0 or v1
        p_side = statistics.median(1.0 / p for _, p in lst) / o_family
        p_side = min(max(p_side, 0.001), 0.999)
        return (p_side if v0 else 1.0 - p_side), "one-sided (de-vigged)", o_family
    return 0.5, "none", None


def anchor(p_mkt, p_model, k):
    return p_mkt + k * (p_model - p_mkt)


def far_line(stat, line, mu_used):
    """True when the line is far from the player's mean (alt/stale line or role change)."""
    if line is None or not mu_used or mu_used <= 0:
        return False
    gap = abs(line - mu_used)
    floor = 10.0 if stat in YARDS_STATS else 2.0
    return gap / mu_used > 0.60 and gap >= floor


def decide_flag(*, model_error, price, market_source, games_used, is_td, far_line, edge, policy):
    """(flagged, noFlagReason). Single owner of "never flag without a known side price"."""
    if model_error:
        return False, "model error"
    if price is None or market_source == "none":
        return False, "no price"
    if not is_td and games_used < policy["min_games"]:
        return False, f"fewer than {policy['min_games']} games"
    if far_line:
        return False, "line far from player mean"
    if edge is None or edge <= policy["margin"]:
        return False, f"edge below {100 * policy['margin']:.1f} pts"
    return True, None


# ---------------------------------------------------------------------------
# Anytime TD
# ---------------------------------------------------------------------------

def td_values(history):
    return [h.get("rushing_tds", 0.0) + h.get("receiving_tds", 0.0) for h in history]


def td_lambda(t_values, window, n0, lambda0_pos):
    """Gamma-Poisson posterior mean of TDs per game, clamped >= 1e-6."""
    wm = window_mean(t_values, window) if t_values else None
    if wm is None:
        lam = lambda0_pos if n0 > 0 else 0.0
        return max(lam, 1e-6), 0
    mu, n_eff, n_used = wm
    lam = (mu * n_eff + n0 * lambda0_pos) / (n_eff + n0)
    return max(lam, 1e-6), n_used


def p_td(lam):
    return 1.0 - math.exp(-lam)


def td_prior(params, position):
    lam0 = params["td"]["lambda0"]
    return lam0.get(position if position in TD_POSITIONS else "ALL", lam0["ALL"])


# ---------------------------------------------------------------------------
# One player
# ---------------------------------------------------------------------------

COUNTER_KEYS = ("markets_evaluated", "skipped_no_history", "skipped_mu_le_0", "model_errors",
                "unsupported_line", "no_price", "excluded_far_line")


def _pct(p):
    return None if p is None else round(100.0 * p, 1)


def _build_row(player_name, stat, group, p_model_over, k, o_family, policy, games_used,
               player_value, is_td, is_far, mu_raw=None):
    market, line = group["market"], group["line"]
    s0, s1 = sides_for(market)
    p_mkt, source, overround = market_prob(group, o_family)
    p_final = anchor(p_mkt, p_model_over, k)
    final = {s0: p_final, s1: 1.0 - p_final}
    model = {s0: p_model_over, s1: 1.0 - p_model_over}
    mkt = {s0: p_mkt, s1: 1.0 - p_mkt}
    edges = {}
    for s in (s0, s1):
        if s in group["best"]:
            edges[s] = final[s] - 1.0 / group["best"][s][0]
    if edges:
        side = max(edges, key=lambda s: (edges[s], s == s0))
    elif is_td:
        side = s0
    else:
        side = s0 if final[s0] >= final[s1] else s1
    best = group["best"].get(side)
    price = best[0] if best else None
    edge = edges.get(side)
    flagged, reason = decide_flag(model_error=False, price=price, market_source=source,
                                  games_used=games_used, is_td=is_td, far_line=is_far,
                                  edge=edge, policy=policy)
    has_mkt = source != "none"
    return {
        "model_version": "v2",
        "player_name": player_name,
        "stat": stat,
        "market": market,
        "line": line,
        "player_value": player_value,
        "muRaw": None if mu_raw is None else round(mu_raw, 2),
        "gamesUsed": games_used,
        "side": side,
        "threshold_rule": side,
        "probModelOver": _pct(p_model_over),
        "probMarketOver": _pct(p_mkt) if has_mkt else None,
        "probFinalOver": _pct(p_final),
        "probModel": _pct(model[side]),
        "probMarket": _pct(mkt[side]) if has_mkt else None,
        "probFinal": _pct(final[side]),
        "probabilityOver": _pct(final[s0]),
        "probabilityUnder": _pct(final[s1]),
        "marketSource": source,
        "overround": overround,
        "price": price,
        "bookmaker": best[1][0] if best else None,
        "bookmakers": list(best[1]) if best else [],
        "impliedProb": round(100.0 / price, 1) if price else None,
        "edgePts": None if edge is None else round(100.0 * edge, 1),
        "edgeSource": "price only" if k == 0 else "model + price",
        "flagged": flagged,
        "noFlagReason": reason,
        "farLine": is_far,
        "prices": group["prices"],
        "adjustmentDetails": None,
        # unrounded fractions for the back-test harness (first side = Over / Yes)
        "pRaw": {"model": p_model_over, "market": p_mkt, "final": p_final},
    }


def evaluate_player(player_name, history, odds_entries, params, policy, target=None):
    """(rows, counters) for one player: one row per (market, line) plus one anytime-TD row."""
    counters = {k: 0 for k in COUNTER_KEYS}
    rows = []
    window = params["window"]
    groups = group_lines(odds_entries, player_name)
    for (market, line), group in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)):
        try:
            if market == TD_MARKET:
                if not history:
                    counters["skipped_no_history"] += 1
                    continue
                td = params["td"]
                lam, n_used = td_lambda(td_values(history), window, td["n0"],
                                        td_prior(params, history[0].get("position")))
                row = _build_row(player_name, "anytime_td", group, p_td(lam), td["k"], td["o"], policy,
                                 n_used, round(lam, 2), True, False)
            else:
                stat = OU_MARKETS[market]
                sp = params["stats"][stat]
                res = model_prob_over(stat, [h.get(stat, 0.0) for h in history], line, sp, window)
                if res[0] is None:
                    reason = res[1]
                    if reason == "no history":
                        counters["skipped_no_history"] += 1
                    elif reason == "mu<=0":
                        counters["skipped_mu_le_0"] += 1
                    else:
                        counters["unsupported_line"] += 1
                    continue
                p_over, mu_raw, mu_used, _n_eff, n_used = res
                is_far = far_line(stat, line, mu_used)
                if is_far:
                    counters["excluded_far_line"] += 1
                    wk = f"wk {target[1]} {target[0]}" if target else "wk ?"
                    logger.info("Excluded far line: %s %s %s (%d books) vs mean %.1f over %d games (%s)",
                                player_name, market, line, len(group["prices"]), mu_used, n_used, wk)
                row = _build_row(player_name, stat, group, p_over, sp["k"], params["o_ou"], policy,
                                 n_used, round(mu_used, 1), False, is_far, mu_raw)
        except Exception:
            logger.exception("model v2 failed: player=%s market=%s line=%s", player_name, market, line)
            counters["model_errors"] += 1
            continue
        counters["markets_evaluated"] += 1
        if row["noFlagReason"] == "no price":
            counters["no_price"] += 1
        rows.append(row)
    return rows, counters
