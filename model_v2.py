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
