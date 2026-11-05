"""Back-test harness and acceptance gate for model v2.

Runs v1 and v2 on a COPY of nfl_stats.db under %TEMP%\\nfl_backtest\\<timestamp>\\,
never on the real DB (path guard + SHA256 check). Fits only on weeks before
the evaluated weeks (FIT_TEST), then grades v1, v2 and the baselines and
writes report.md and params_test.json to the output folder.

    python backtest.py [--out DIR] [--seed 20261030] [--matchup-experiment SCHEDULE_JSON]
                       [--write-params --production-target 2026-8]

Exit codes: 0 ok (gate result is in the report, not the exit code), 2 DB copy
failed, 3 path guard, 4 real DB changed, 5 CV fit failed, 6 --write-params
refused (gate failed or bad --production-target).

Importing this module does not touch any DB and does not import test_thresholds.
"""
import argparse
import datetime
import hashlib
import json
import math
import os
import random
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent

FIT_TEST = {
    "ou": {"fit": [(2025, w) for w in range(4, 14)],
           "test": [(2025, 14), (2025, 15), (2025, 16)]},
    "td": {"fit_lambda": [(2025, w) for w in range(4, 14)],
           "fit_k_overround": [(2025, 14), (2025, 15)],
           "test": [(2025, 16)]},
}
FOLD_A = list(range(4, 10))
FOLD_B = list(range(10, 14))
PROXY_HOLDOUT = list(range(14, 18))
PROXY_2026 = list(range(2, 8))
REAL_TEST_WEEKS = [14, 15, 16]
MINS = {"receiving_yards": 25, "rushing_yards": 25, "passing_yards": 150, "receptions": 2.0, "passing_tds": 0.8}
STATS = ("passing_yards", "receiving_yards", "rushing_yards", "receptions", "passing_tds")
MARKET = {"passing_yards": "player_pass_yds", "passing_tds": "player_pass_tds",
          "receiving_yards": "player_reception_yds", "receptions": "player_receptions",
          "rushing_yards": "player_rush_yds"}
OFF_POS = ("QB", "RB", "WR", "TE")
DEFAULT_SEED = 20261030
CANDIDATE_WINDOWS = ([{"type": "last_n", "n": n} for n in (3, 4, 6, 8, 10, 17)]
                     + [{"type": "ewma", "half_life": h, "max_games": 17} for h in (2, 3, 4, 6, 8)])
N0_CHOICES = (0, 1, 2, 4, 8)
WINDOW_TIE = 0.001
BLEND_MIN_GAIN = 0.002
DIST_TIE = 0.0005
K_GRID = [i / 100 for i in range(101)]
K_CAP = 0.25
MIN_K_CASES = 300
MIN_TD_EVENTS = 20
MIN_TD_CASES = 20
DEFAULT_O_TD = 1.25
DEFAULT_O_OU = 1.064
CLIP = 1e-6
TOL = 1e-9
MARGINS = (0.02, 0.03, 0.05)
GATE_MARGIN = 0.03
BUCKETS = [("0.50 (tie)", None, None), ("[0.50, 0.55)", 0.50, 0.55), ("[0.55, 0.60)", 0.55, 0.60),
           ("[0.60, 0.70)", 0.60, 0.70), ("[0.70, 1.00]", 0.70, 1.0000001)]
MIN_BUCKET = 30
HOLDOUT_DISCLOSURE = (
    "2025 wk14-16 is not a pristine hold-out. The math review already used those weeks to compare 3 "
    "against 6 games, normal against log-normal, and model weights up to 0.25. The k cap 0.25 is kept as a "
    "fixed policy cap that can only move probabilities toward the market. G5 (the 2026 proxy) and G3-proxy "
    "are the checks with no prior exposure.")
REFERENCE_FAR_LINES = [
    "single-book: Dissly rec yds 0.5 vs 10.8", "single-book: Singletary rec yds 5.5 vs 16.5",
    "single-book: I. Williams rec yds 28.5 vs 13.8", "single-book: Estime rush 30.5 vs 5.5",
    "single-book: Hull rush 25.5 vs 10.3", "single-book: Hooper rec yds 5.5 vs 16.2",
    "multi-book: Gardner Minshew pass yds 213.5 vs 7.3", "multi-book: Tank Bigsby rush 6.5 vs 27.3",
    "multi-book: Thielen rec yds 15.5 vs 4.3", "multi-book: Ferguson 20.0 vs 6.3",
    "multi-book: DJ Moore 49.5 vs 27.3", "multi-book: Dike 30.5 vs 18.7", "multi-book: Tipton 24.5 vs 7.8",
    "multi-book: D. Douglas 15.5 vs 40.0", "multi-book (2026 wk8): M. Evans 5.5 vs 17.5",
    "multi-book (2026 wk8): Tremayne 4.0 vs 19.2",
]


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested; no DB)
# ---------------------------------------------------------------------------

class FitError(Exception):
    pass


def clip_logloss(p, y, counter=None):
    """Log loss with p clipped to [1e-6, 1 - 1e-6]; counter (list of one int) counts clips."""
    pc = min(max(p, CLIP), 1 - CLIP)
    if pc != p and counter is not None:
        counter[0] += 1
    return -(y * math.log(pc) + (1 - y) * math.log(1 - pc))


def brier(p, y):
    return (p - y) ** 2


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def z_for_level(m):
    """z = Phi^-1(1 - 0.025/m) by bisection (two-sided family-wise 95% over m tests)."""
    target = 1 - 0.025 / m
    lo, hi = 0.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if _phi(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def wilson(k, n, z):
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def fit_cv(cases, stat="stat", notes=None):
    """WLS of r = ((y - mu)/mu)^2 on [1, 1/n_eff], weights mu^2, with the b >= a floor.

    cases: list of (r, inv_n, w). Returns (a, b). Raises FitError on < 50 cases or a <= 0.
    An unconstrained intercept a <= 0 (all variance put on the 1/n term, which is
    implausible: games vary even with a known mean) is refit on the iid floor
    b = a, like b < a; only a non-positive floor fit is fatal. notes (list)
    records which path was used.
    """
    if len(cases) < 50:
        raise FitError(f"{stat}: only {len(cases)} fit cases (< 50)")
    sw = sum(w for _, _, w in cases)
    swx = sum(w * x for _, x, w in cases)
    swxx = sum(w * x * x for _, x, w in cases)
    swr = sum(w * r for r, _, w in cases)
    swxr = sum(w * x * r for r, x, w in cases)
    det = sw * swxx - swx * swx
    a = b = None
    if det > 1e-12 * max(sw * swxx, 1e-300):
        a = (swr * swxx - swx * swxr) / det
        b = (sw * swxr - swx * swr) / det
    path = "unconstrained"
    if a is None or b < a or a <= 0:
        path = ("no 1/n variation" if a is None else "b < a" if b < a else "a <= 0") + " -> floor b = a"
        # iid floor: refit with b fixed to a, r = a * (1 + 1/n)
        num = sum(w * r * (1 + x) for r, x, w in cases)
        den = sum(w * (1 + x) ** 2 for _, x, w in cases)
        a = b = num / den
    if notes is not None:
        notes.append(f"{stat}: {path}")
    if a <= 0:
        raise FitError(f"{stat}: fitted a = {a:.4f} <= 0")
    return a, b


def fit_c(ys, mus):
    s = sum(mus)
    if s <= 0:
        return 1.0
    return min(max(sum(ys) / s, 0.8), 1.2)


def cluster_bootstrap(rows, fn, seed, n=2000):
    """rows: list of (cluster_key, item). Returns (point, lo, hi): percentile 95% CI of fn(items)."""
    clusters = {}
    for key, item in rows:
        clusters.setdefault(key, []).append(item)
    keys = list(clusters)
    point = fn([it for k in keys for it in clusters[k]])
    if not keys:
        return point, None, None
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        pick = rng.choices(keys, k=len(keys))
        vals.append(fn([it for k in pick for it in clusters[k]]))
    vals.sort()
    return point, vals[int(0.025 * n)], vals[int(0.975 * n) - 1]


def assert_fit_test(ft):
    """Per family: every fit (season, week) is before every test week, and none is in both."""
    for fam, d in ft.items():
        test = d["test"]
        fits = [sw for k, v in d.items() if k != "test" for sw in v]
        if set(fits) & set(test):
            raise AssertionError(f"{fam}: fit and test weeks overlap")
        if max(fits) >= min(test):
            raise AssertionError(f"{fam}: fit week {max(fits)} not before test week {min(test)}")
    return True


def subsample_quantiles(values, k=2000):
    v = sorted(values)
    if len(v) <= k:
        return v
    return [v[int(round(i * (len(v) - 1) / (k - 1)))] for i in range(k)]


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def f4(x):
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.4f}"


# ---------------------------------------------------------------------------
# Harness (runs only from main(); needs the DB copy and the repo modules)
# ---------------------------------------------------------------------------

class Report:
    def __init__(self, quiet=False):
        self.lines = []
        self.quiet = quiet

    def __call__(self, *parts):
        s = " ".join(str(p) for p in parts)
        if not self.quiet:
            print(s)
        self.lines.append(s)

    def table(self, header, rows):
        self("| " + " | ".join(header) + " |")
        self("|" + "|".join("---" for _ in header) + "|")
        for r in rows:
            self("| " + " | ".join(str(x) for x in r) + " |")
        self("")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(code, msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def parse_target(value):
    if value is None:
        fail(6, "--production-target SEASON-WEEK required")
    try:
        s, w = value.split("-")
        season, week = int(s), int(w)
    except ValueError:
        fail(6, f"invalid --production-target {value}")
    if season != 2026 or not 2 <= week <= 18:
        fail(6, f"invalid --production-target {value}")
    return season, week


class Ctx:
    """DB access, caches and case building on the DB copy."""

    def __init__(self, tt, mv):
        self.tt, self.mv = tt, mv
        self.hist = {}
        self.targets = {}
        self.names = {}
        self.v1stats = {}

    def history(self, pid, season, week):
        key = (pid, season, week)
        if key not in self.hist:
            with self.tt.engine.connect() as conn:
                h = self.tt.get_played_history(conn, pid, season, week, max_games=17)
            for r in h:
                assert (r["season"], r["week"]) < (season, week), f"leak: {key} {r['season']} {r['week']}"
            self.hist[key] = h
        return self.hist[key]

    def target_rows(self, season, week):
        """{player_id: row} for (season, week); duplicate rows -> None (void)."""
        key = (season, week)
        if key not in self.targets:
            from sqlalchemy import text
            with self.tt.engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT player_id, player_display_name, gp, position, team, passing_yards, passing_tds,
                           rushing_yards, rushing_tds, receiving_yards, receiving_tds, receptions
                    FROM player_weekly_stats
                    WHERE season = :s AND week = :w AND season_type = 'regular'
                """), {"s": season, "w": week}).mappings().all()
            out = {}
            for r in rows:
                d = {k: (float(v) if isinstance(v, (int, float)) and k not in ("player_id",) else v)
                     for k, v in dict(r).items()}
                for c in ("passing_yards", "passing_tds", "rushing_yards", "rushing_tds", "receiving_yards",
                          "receiving_tds", "receptions"):
                    d[c] = d[c] or 0.0
                out[r["player_id"]] = None if r["player_id"] in out else d
            self.targets[key] = out
        return self.targets[key]

    def played_target(self, pid, season, week):
        r = self.target_rows(season, week).get(pid)
        if r is None or not (r.get("gp") or 0) > 0:
            return None
        return r

    def resolve(self, season, week):
        key = (season, week)
        if key not in self.names:
            with self.tt.engine.connect() as conn:
                self.names[key] = self.tt.resolve_player_ids(conn, season, week)
        return self.names[key]

    def proxy_cases(self, season, weeks, cross_season):
        """O/U proxy cases and TD proxy cases for the given weeks."""
        ou, td = [], []
        for w in weeks:
            for name, pid in self.resolve(season, w).items():
                t = self.played_target(pid, season, w)
                if t is None or t.get("position") not in OFF_POS:
                    continue
                h = self.history(pid, season, w)
                if len(h) >= 3:
                    td.append({"season": season, "week": w, "pid": pid, "name": name, "position": t["position"],
                               "t_values": self.mv.td_values(h), "y": int(t["rushing_tds"] + t["receiving_tds"] >= 1)})
                prior = h if cross_season else [r for r in h if r["season"] == season]
                if len(prior) < 3:
                    continue
                for stat in STATS:
                    smean = mean(r[stat] for r in prior)
                    if smean < MINS[stat]:
                        continue
                    line = math.floor(smean) + 0.5
                    y = t[stat]
                    ou.append({"season": season, "week": w, "pid": pid, "name": name, "stat": stat, "line": line,
                               "y": y, "over": int(y > line), "values": [r[stat] for r in h],
                               "mu_season": smean, "n_season": len(prior), "team": t.get("team"),
                               "position": t["position"]})
        return ou, td

    def v1_proxy_prob(self, case, thresholds):
        """v1 P(Over) on a proxy case, or (None, reason)."""
        key = (case["pid"], case["season"], case["week"])
        if key not in self.v1stats:
            self.v1stats[key] = self.tt.get_recent_3_game_stats_by_id(case["season"], case["pid"], case["week"])
        ps = self.v1stats[key]
        if not ps:
            return None, "no in-season game"
        from Odds_vs_Stats_Check import check_stat_against_odds
        entry = [{"market": MARKET[case["stat"]], "line": case["line"], "bookmaker": "proxy", "prices": {}}]
        rows = check_stat_against_odds(case["name"], ps, entry, thresholds, errors=[], include_unflagged=True)
        if not rows:
            return None, "all-zero window or None probability"
        return rows[0]["probabilityOver"] / 100.0, ("fewer than 3 games" if len(ps.get("weekly", [])) < 3 else "")


def stat_fit(mv, cases, window, stat, dist, notes=None):
    """Fit (c, a, b, ratios) for one stat on cases with the given window."""
    ys, mus, items = [], [], []
    for c in cases:
        wm = mv.window_mean(c["values"], window)
        if wm is None or wm[0] <= 0:
            continue
        items.append((c["y"], wm[0], wm[1]))
        ys.append(c["y"]); mus.append(wm[0])
    cfac = fit_c(ys, mus)
    cv_cases = []
    for y, mu, ne in items:
        m = cfac * mu
        cv_cases.append((((y - m) / m) ** 2, 1.0 / ne, m * m))
    a, b = fit_cv(cv_cases, stat, notes)
    sp = {"c": round(cfac, 6), "a": round(a, 6), "b": round(b, 6), "dist": dist, "k": 0.0, "blend": False}
    if dist == "empirical_ratio":
        sp["ratios"] = [round(y / mu, 5) for y, mu, _ in items]
        sp["ratios"] = subsample_quantiles(sp["ratios"], 2000)
    return sp


def with_ratios(mv, sp, cases, window):
    sp = dict(sp)
    ratios = []
    for c in cases:
        wm = mv.window_mean(c["values"], window)
        if wm and wm[0] > 0:
            ratios.append(round(c["y"] / wm[0], 5))
    sp["ratios"] = subsample_quantiles(ratios, 2000)
    return sp


def model_p(mv, case, sp, window):
    r = mv.model_prob_over(case["stat"], case["values"], case["line"], sp, window)
    return None if r[0] is None else r[0]


def score_cases(mv, cases, sp, window):
    """(mean log loss, mean Brier, n, clips, unpriced) with unpriced cases scored at 0.5."""
    clips = [0]
    ll = br = 0.0
    unpriced = 0
    for c in cases:
        p = model_p(mv, c, sp, window)
        if p is None:
            p = 0.5
            unpriced += 1
        ll += clip_logloss(p, c["over"], clips)
        br += brier(p, c["over"])
    n = len(cases)
    return (ll / n if n else float("nan"), br / n if n else float("nan"), n, clips[0], unpriced)


def mean_neff(mv, cases, window):
    vals = [mv.window_mean(c["values"], window) for c in cases]
    return mean(v[1] for v in vals if v)


def standin_market(mv, case, sp):
    """B10.3 #6: P(Over) from the season mean with CV(n_season) and the chosen distribution."""
    if sp["dist"] == "empirical_ratio":
        mu = case["mu_season"]
    else:
        mu = case["mu_season"] * sp["c"]
    if mu <= 0:
        return 0.5
    cv_ = mv.cv(sp["a"], sp["b"], case["n_season"])
    return mv.p_over_dist(sp["dist"], mu, cv_, case["line"], sp.get("ratios"))


def best_k(pairs):
    """argmin over K_GRID of Brier(p_mkt + k(p_model - p_mkt)); pairs = [(p_mkt, p_model, y)]."""
    best = None
    for k in K_GRID:
        b = mean(brier(m + k * (p - m), y) for m, p, y in pairs)
        if best is None or b < best[1] - 1e-15:
            best = (k, b)
    return best


def td_lambda0(cases):
    """Pooled TDs per played game by position (and ALL) over TD proxy cases."""
    by = defaultdict(list)
    for c in cases:
        by[c["position"]].append(c["y_count"])
    lam = {pos: max(min(mean(by[pos]), 1.99), 1e-3) for pos in OFF_POS if by[pos]}
    lam["ALL"] = max(min(mean(c["y_count"] for c in cases), 1.99), 1e-3)
    return {k: round(v, 6) for k, v in lam.items()}


def calib_rows(items):
    """items: [(p_over, over)] -> per-bucket (n, mean stated favoured, hits)."""
    out = {b[0]: [] for b in BUCKETS}
    for p, y in items:
        if abs(p - 0.5) < 1e-9:
            out["0.50 (tie)"].append((0.5, y))
            continue
        fav = p if p > 0.5 else 1 - p
        hit = y if p > 0.5 else 1 - y
        for name, lo, hi in BUCKETS[1:]:
            if lo <= fav < hi:
                out[name].append((fav, hit))
                break
    return out


def calib_table(rep, title, buckets, z):
    rep(f"**{title}** (Bonferroni z = {z:.3f})")
    rows = []
    fails = []
    for name, _, _ in BUCKETS:
        v = buckets[name]
        if not v:
            rows.append([name, 0, "-", "-", "-", "-", "-"])
            continue
        n = len(v)
        stated = mean(s for s, _ in v)
        k = sum(h for _, h in v)
        w95 = wilson(k, n, 1.96)
        wbf = wilson(k, n, z)
        checked = n >= MIN_BUCKET
        ok = wbf[0] <= stated <= wbf[1]
        red = not (w95[0] <= stated <= w95[1])
        status = ("PASS" if ok else "FAIL") if checked else "not checked (< 30)"
        if red:
            status += " (red flag: outside 95%)"
        if checked and not ok:
            fails.append((title, name, stated, wbf))
        rows.append([name, n, f"{stated:.3f}", f"{k / n:.3f}", f"[{w95[0]:.3f}, {w95[1]:.3f}]",
                     f"[{wbf[0]:.3f}, {wbf[1]:.3f}]", status])
    rep.table(["bucket", "n", "mean stated", "observed", "Wilson 95%", "Bonferroni", "check"], rows)
    return fails


def n_checked(buckets):
    return sum(1 for v in buckets.values() if len(v) >= MIN_BUCKET)


def one_row_per_stat(rows):
    """rows: dicts with key (pid, week, stat), line, nbooks -> one per key (most books, then lower line)."""
    best = {}
    for r in rows:
        k = (r["pid"], r["week"], r["stat"])
        cur = best.get(k)
        if cur is None or (r["nbooks"], -r["line"]) > (cur["nbooks"], -cur["line"]):
            best[k] = r
    return [best[k] for k in sorted(best, key=lambda x: (x[1], str(x[0]), x[2]))]


def flags_table(mv, rep, rows, policy_min_games, title):
    """Assumed-price mode flags at MARGINS. rows: graded per-book v2 rows with price and probabilities."""
    rep(f"**{title}** (side of stored price unknown (S5); the stored price is assumed to be the price of the "
        f"side evaluated, so a long price is credited to whichever side is picked; ROI at that assumed price is "
        f"not evidence of profit)")
    out = []
    for m in MARGINS:
        pol = {"margin": m, "min_games": policy_min_games}
        flagged, removed_min = [], 0
        for r in rows:
            d = r["price"]
            if mv.valid_price(d) is None:
                continue
            pf = r["p_final"]
            edges = {"Over": pf - 1 / d, "Under": (1 - pf) - 1 / d}
            side = max(edges, key=lambda s: (edges[s], s == "Over"))
            args = dict(model_error=False, price=d, market_source="assumed (harness)", is_td=False,
                        far_line=r["far"], edge=edges[side], policy=pol)
            ok, _ = mv.decide_flag(games_used=r["games"], **args)
            if not ok:
                if mv.decide_flag(games_used=99, **args)[0]:
                    removed_min += 1
                continue
            win = r["over"] if side == "Over" else 1 - r["over"]
            flagged.append({"key": (r["pid"], r["week"], r["stat"]), "win": win, "edge": edges[side], "price": d,
                            "p": pf if side == "Over" else 1 - pf})
        uniq = {}
        for f in sorted(flagged, key=lambda f: -f["edge"]):
            uniq.setdefault(f["key"], f)
        u = list(uniq.values())
        def summ(fs):
            if not fs:
                return "0", "-", "-", "-", "-"
            k = sum(f["win"] for f in fs)
            lo, hi = wilson(k, len(fs), 1.96)
            roi = mean((f["price"] - 1) if f["win"] else -1 for f in fs)
            return (str(len(fs)), f"{k / len(fs):.3f} [{lo:.3f}, {hi:.3f}]", f"{mean(f['p'] for f in fs):.3f}",
                    f"{100 * mean(f['edge'] for f in fs):.1f}", f"{roi:+.3f}")
        a, b = summ(flagged), summ(u)
        label = f"{m * 100:.0f} pts" + (" (gate value)" if m == GATE_MARGIN else " (diagnostic)")
        out.append([label, a[0], a[1], b[0], b[1], b[2], b[3], b[4], removed_min])
    rep.table(["margin", "flag rows", "row hit [95% CI]", "unique picks", "unique hit [95% CI]",
               "mean stated P", "mean edge (pts)", "ROI (assumed price)", "removed by min-games"], out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--matchup-experiment", dest="matchup")
    ap.add_argument("--write-params", action="store_true")
    ap.add_argument("--production-target")
    args = ap.parse_args()
    os.chdir(REPO)
    target = parse_target(args.production_target) if args.write_params else None

    temp_root = Path(os.environ["TEMP"])
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) if args.out else temp_root / "nfl_backtest" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    repo_db = REPO / "nfl_stats.db"
    h0 = sha256(repo_db)
    copy = out_dir / "nfl_stats_copy.db"
    try:
        src = sqlite3.connect(f"file:{repo_db.as_posix()}?mode=ro", uri=True)
        dst = sqlite3.connect(str(copy))
        src.backup(dst)
        dst.close(); src.close()
    except Exception as e:
        fail(2, f"DB copy failed: {e}")
    os.environ["NFL_STATS_DB"] = str(copy)
    os.environ["NFL_SEASON"] = "2025"
    os.environ["NFL_WEEK"] = "14"
    os.environ.pop("NFL_MODEL_VERSION", None)
    sys.path.insert(0, str(REPO))
    import logging
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    import test_thresholds as tt
    import target_share_calc
    import model_v2 as mv

    norm = lambda p: os.path.normcase(os.path.realpath(p))
    temp, rdb = norm(os.environ["TEMP"]), norm(repo_db)
    for p in map(norm, [tt.engine.url.database, target_share_calc.engine.url.database]):
        if os.path.commonpath([p, temp]) != temp or p == rdb:
            fail(3, f"engine not inside TEMP: {p}")

    rep = Report()
    rep("# Model v2 back-test report")
    rep("")
    rep(f"Run: {stamp}. Output folder: `{out_dir}`. Seed {args.seed}. DB copy SHA256 before run: `{h0}`.")
    rep("")
    assert_fit_test(FIT_TEST)
    rep("FIT_TEST asserted: O/U fit 2025 wk4-13 < test wk14-16; TD lambda fit wk4-13, k/o fit wk14-15 < test wk16.")
    rep("")
    config = tt.read_config_from_file()
    thresholds = config["THRESHOLDS"]
    policy = {"margin": float(config["V2_EDGE_MARGIN"]), "min_games": int(config["V2_MIN_GAMES_FOR_FLAG"])}
    ctx = Ctx(tt, mv)

    if target:
        with tt.engine.connect() as conn:
            from sqlalchemy import text
            have = {r[0] for r in conn.execute(text(
                "SELECT DISTINCT week FROM player_weekly_stats WHERE season = 2026 AND season_type = 'regular'"))}
        for w in range(1, target[1]):
            if w not in have:
                fail(6, f"no 2026 stats for week {w}")

    # ---------------- case sets ----------------
    print("building case sets ...", file=sys.stderr)
    fold_a, td_a = ctx.proxy_cases(2025, FOLD_A, False)
    fold_b, td_b = ctx.proxy_cases(2025, FOLD_B, False)
    hold, _ = ctx.proxy_cases(2025, PROXY_HOLDOUT, False)
    p26, _ = ctx.proxy_cases(2026, PROXY_2026, True)
    # TD lambda0 uses TD counts per played target game
    def td_counts(cases, season):
        for c in cases:
            t = ctx.played_target(c["pid"], season, c["week"])
            c["y_count"] = t["rushing_tds"] + t["receiving_tds"]
    td_counts(td_a, 2025); td_counts(td_b, 2025)
    by_stat = lambda cases: {s: [c for c in cases if c["stat"] == s] for s in STATS}
    A, B, H, P26 = by_stat(fold_a), by_stat(fold_b), by_stat(hold), by_stat(p26)
    rep("## Case sets")
    rep("")
    rows = []
    for name, d in (("Proxy fold A (2025 wk4-9)", A), ("Proxy fold B (2025 wk10-13)", B),
                    ("Proxy hold-out (2025 wk14-17)", H), ("2026 proxy (wk2-7)", P26)):
        rows.append([name] + [len(d[s]) for s in STATS] + [sum(len(v) for v in d.values())])
    rep.table(["set"] + list(STATS) + ["total"], rows)
    rep("2026 proxy cases per week: " + ", ".join(f"wk{w} {sum(1 for c in p26 if c['week'] == w)}" for w in PROXY_2026))
    rep(f"TD proxy cases: fold A {len(td_a)}, fold B {len(td_b)}.")
    rep(f"Leak check: {len(ctx.hist)} histories, every row strictly before its target week (asserted).")
    rep("")

    # ---------------- B10.3 step 2: window ----------------
    rep("## Selection and fitting (2025 wk <= 13)")
    rep("")
    default_dist = {s: ("lognormal" if s in mv.YARDS_STATS else "negbin") for s in STATS}
    cand = []
    try:
        for W in CANDIDATE_WINDOWS:
            per = {}
            clips = 0
            nts = []
            for s in STATS:
                sp = stat_fit(mv, A[s], W, s, default_dist[s], nts)
                ll, br, n, cl, unp = score_cases(mv, B[s], sp, W)
                per[s] = ll
                clips += cl
            score = mean(per.values())
            cand.append({"window": W, "score": score, "per": per, "neff": mean_neff(mv, fold_b, W), "clips": clips,
                         "floor": ", ".join(n.split(":")[0] for n in nts if "floor" in n) or "-"})
    except FitError as e:
        fail(5, f"CV fit failed: {e}")
    best = min(c["score"] for c in cand)
    tied = [c for c in cand if c["score"] <= best + WINDOW_TIE]
    chosen = max(tied, key=lambda c: c["neff"])
    W = chosen["window"]
    rep("**Window candidates** (fold-B selection score = mean of the five per-stat log losses; fit on fold A). "
        f"Tie band {WINDOW_TIE}: candidates within it of the best go to the largest mean n_eff.")
    rep.table(["window", "score"] + list(STATS) + ["mean n_eff", "clips", "CV floor used", "tied", "chosen"],
              [[mv.window_label(c["window"]), f"{c['score']:.4f}"] + [f"{c['per'][s]:.4f}" for s in STATS]
               + [f"{c['neff']:.2f}", c["clips"], c["floor"], "yes" if c in tied else "", "**yes**" if c is chosen else ""]
               for c in cand])

    # ---------------- step 3: distribution ----------------
    chosen_sp = {}
    dist_rows = []
    for s in STATS:
        base = stat_fit(mv, A[s], W, s, default_dist[s])
        res = []
        for dist in mv.DIST_CHOICES[s]:
            sp = dict(base, dist=dist)
            if dist == "empirical_ratio":
                sp = with_ratios(mv, sp, A[s], W)
            ll, br, n, cl, unp = score_cases(mv, B[s], sp, W)
            res.append((ll, br, dist, sp, cl))
        bl = min(r[0] for r in res)
        pick = min((r for r in res if r[0] <= bl + DIST_TIE), key=lambda r: r[1])
        chosen_sp[s] = pick[3]
        for ll, br, dist, _, cl in res:
            dist_rows.append([s, dist, f"{ll:.4f}", f"{br:.4f}", cl, "**yes**" if dist == pick[2] else ""])
    rep("**Distribution per stat** (fold B, chosen by log loss; Brier breaks ties within 0.0005)")
    rep.table(["stat", "dist", "log loss", "Brier", "clips", "chosen"], dist_rows)

    # ---------------- step 4: blend ----------------
    blend_rows = []
    for s in STATS:
        sp = chosen_sp[s]
        if sp["dist"] in ("empirical_ratio", "poisson"):
            blend_rows.append([s, sp["dist"], "-", "-", "n/a (dist ignores CV)"])
            continue
        off = score_cases(mv, B[s], sp, W)[0]
        on = score_cases(mv, B[s], dict(sp, blend=True), W)[0]
        adopt = off - on >= BLEND_MIN_GAIN
        if adopt:
            chosen_sp[s] = dict(sp, blend=True)
        blend_rows.append([s, sp["dist"], f"{off:.4f}", f"{on:.4f}", "adopted" if adopt else "off"])
    rep("**Own-SD blend** (adopted only if fold-B log loss improves by >= 0.002)")
    rep.table(["stat", "dist", "log loss off", "log loss on", "result"], blend_rows)

    # ---------------- step 5: TD n0 ----------------
    lam0_a = td_lambda0(td_a)
    n0_rows = []
    best_n0 = None
    for n0 in N0_CHOICES:
        clips = [0]
        ll = mean(clip_logloss(mv.p_td(mv.td_lambda(c["t_values"], W, n0, lam0_a.get(c["position"], lam0_a["ALL"]))[0]),
                               c["y"], clips) for c in td_b)
        n0_rows.append([n0, f"{ll:.4f}", clips[0]])
        if best_n0 is None or ll < best_n0[1] - 1e-12:
            best_n0 = (n0, ll)
    n0 = best_n0[0]
    rep(f"**TD n0** (fold B log loss; lambda0 from fold A: {lam0_a})")
    rep.table(["n0", "log loss", "clips"], [r + (["**chosen**"] if r[0] == n0 else [""]) for r in n0_rows])

    # ---------------- step 6: stand-in k ----------------
    pairs_by = {}
    for s in STATS:
        sp = chosen_sp[s]
        pairs_by[s] = []
        for c in B[s]:
            p = model_p(mv, c, sp, W)
            if p is None:
                continue
            pairs_by[s].append((standin_market(mv, c, sp), p, c["over"]))
    pooled = [x for s in STATS for x in pairs_by[s]]
    k_global = best_k(pooled)[0]
    k_rows = []
    k_fit = {}
    for s in STATS:
        pr = pairs_by[s]
        if len(pr) < MIN_K_CASES:
            k_raw, src = k_global, f"global (only {len(pr)} cases)"
        else:
            k_raw, src = best_k(pr)[0], "per stat"
        k_fit[s] = min(k_raw, K_CAP)
        b_mkt = mean(brier(m, y) for m, _, y in pr)
        b_half = mean(brier(0.5, y) for _, _, y in pr)
        b_blend = mean(brier(m + k_fit[s] * (p - m), y) for m, p, y in pr)
        curve = " ".join(f"{k:.2f}:{mean(brier(m + k * (p - m), y) for m, p, y in pr):.4f}"
                         for k in (0, 0.05, 0.10, 0.15, 0.20, 0.25))
        k_rows.append([s, len(pr), f"{k_raw:.2f}", src, f"{k_fit[s]:.2f}", f"{b_mkt:.4f}", f"{b_half:.4f}",
                       f"{b_blend:.4f}", curve])
    rep(f"**Stand-in k** (fold B; stand-in market = P(Over) from the season mean; pooled k {k_global:.2f}; cap 0.25)")
    rep.table(["stat", "cases", "k (argmin)", "source", "k used", "Brier stand-in mkt", "Brier 0.5",
               "Brier blend", "fold-B Brier curve k:Brier"], k_rows)

    # ---------------- step 8: refit on wk4-13 ----------------
    fit_all = {s: A[s] + B[s] for s in STATS}
    test_stats = {}
    fit_notes = []
    for s in STATS:
        sp = stat_fit(mv, fit_all[s], W, s, chosen_sp[s]["dist"], fit_notes)
        if sp["dist"] == "empirical_ratio":
            sp = with_ratios(mv, sp, fit_all[s], W)
        sp["blend"] = chosen_sp[s]["blend"]
        sp["k"] = round(k_fit[s], 2)
        test_stats[s] = sp
    lam0 = td_lambda0(td_a + td_b)
    P = {"version": 2, "window": W, "stats": test_stats,
         "td": {"n0": n0, "lambda0": lam0, "k": 0.0, "o": DEFAULT_O_TD},
         "o_ou": DEFAULT_O_OU, "fitted_on": "proxy 2025 wk4-13; TD k/o: 2025 wk14-15 odds",
         "gate_label": "test parameters (pre-gate)"}
    mv.validate_params(P)
    review_cv6 = {"passing_yards": 0.39, "receptions": 0.65, "passing_tds": 0.83, "receiving_yards": 0.86,
                  "rushing_yards": 1.00}
    rows = []
    for s in STATS:
        sp = test_stats[s]
        cv6 = mv.cv(sp["a"], sp["b"], 6)
        red = []
        if abs(cv6 - review_cv6[s]) > 0.15:
            red.append("CV gap > 0.15")
        if sp["c"] in (0.8, 1.2):
            red.append("c at clamp")
        rows.append([s, sp["dist"], f"{sp['c']:.3f}", f"{sp['a']:.4f}", f"{sp['b']:.4f}", f"{cv6:.3f}",
                     f"{review_cv6[s]:.2f}", sp["blend"], f"{sp['k']:.2f}", ", ".join(red) or "-"])
    rep("**Test parameters** (refit on 2025 wk4-13 with the chosen configuration)")
    rep.table(["stat", "dist", "c", "a", "b", "CV(6)", "review CV(6)", "blend", "k", "red flags"], rows)
    rep(f"CV fit path per stat: {'; '.join(fit_notes)}.")
    rep(f"TD: n0 {n0}, lambda0 {lam0}.")
    rep("")

    # ---------------- step 7: k_TD and o_TD on 2025 wk14-15 TD odds ----------------
    def td_cases_from_rows(players, season, week):
        cases, names_matched = [], set()
        for g in players:
            for r in g["stats"]:
                if r["stat"] != "anytime_td":
                    continue
                for v in (g["player"], g["player"].replace(".", ""), g["player"].replace(" Jr.", ""),
                          g["player"].replace(" Sr.", "")):
                    names_matched.add(v)
                inv = []
                for book, pr in r["prices"].items():
                    for oc in ("Yes", "unknown"):
                        d = mv.valid_price(pr.get(oc))
                        if d:
                            inv.append(1 / d)
                            break
                t = ctx.played_target(g["player_id"], season, week)
                if t is None or not inv:
                    continue
                cases.append({"pid": g["player_id"], "week": week, "p_model": r["pRaw"]["model"],
                              "p_final": r["pRaw"]["final"], "p_mkt": r["pRaw"]["market"],
                              "inv": statistics.median(inv), "y": int(t["rushing_tds"] + t["receiving_tds"] >= 1)})
        return cases, names_matched

    def td_odds_names(season, week):
        from sqlalchemy import text
        with tt.engine.connect() as conn:
            return sorted(r[0][len("custom_"):] for r in conn.execute(text(
                "SELECT DISTINCT player_id FROM odds WHERE market = 'player_anytime_td' AND season = :s AND week = :w"),
                {"s": season, "w": week}) if r[0] and r[0].startswith("custom_"))

    def fit_td_market(weeks, params, label):
        cases, unmatched = [], []
        for w in weeks:
            players, _ = tt.evaluate_week(2025, w, "v2", config, params=params, adjustments=False)
            cs, matched = td_cases_from_rows(players, 2025, w)
            cases += cs
            unmatched += [n for n in td_odds_names(2025, w) if n not in matched]
        n_td = sum(c["y"] for c in cases)
        raw_ratio = (sum(c["inv"] for c in cases) / n_td) if n_td else float("nan")
        if n_td < MIN_TD_EVENTS:
            o = DEFAULT_O_TD
            o_src = f"fallback 1.25 (only {n_td} TDs < {MIN_TD_EVENTS}; raw ratio {raw_ratio:.3f})"
        else:
            o = min(max(raw_ratio, 1.0), 1.6)
            o_src = f"fitted {o:.3f} over {n_td} TDs"
        if len(cases) < MIN_TD_CASES:
            k, k_src = 0.0, f"0 (only {len(cases)} usable cases < {MIN_TD_CASES})"
        else:
            kk = best_k([(min(max(c["inv"] / o, 0.001), 0.999), c["p_model"], c["y"]) for c in cases])[0]
            k = min(kk, K_CAP)
            k_src = f"argmin {kk:.2f}, capped {k:.2f}, {len(cases)} cases"
        rep(f"**TD market fit ({label})**: usable player-weeks {len(cases)}, TDs {n_td}, o_TD {o_src}; k_TD {k_src}. "
            f"Unmatched odds names: {len(set(unmatched))}" + (f" (e.g. {', '.join(sorted(set(unmatched))[:20])})" if unmatched else ""))
        rep("")
        return o, k, cases

    P_td_fit = json.loads(json.dumps(P))
    o_td, k_td, _ = fit_td_market([14, 15], P_td_fit, "2025 wk14-15")
    P["td"]["o"] = round(o_td, 4)
    P["td"]["k"] = round(k_td, 2)
    mv.validate_params(P)
    (out_dir / "params_test.json").write_text(json.dumps(P, indent=1), encoding="utf-8")
    rep(f"`params_test.json` written to the output folder (o_ou {P['o_ou']}: no fit-week O/U row has both sides).")
    rep("")

    # ---------------- B10.4 real O/U test ----------------
    print("evaluating real test ...", file=sys.stderr)
    v1_rows, v2_rows, v2_line_rows, td_test = [], [], [], []
    v2_summaries = {}
    v2_players_by_week = {}
    void = defaultdict(int)
    v1_players = {}
    for w in REAL_TEST_WEEKS:
        p1, s1 = tt.evaluate_week(2025, w, "v1", config, include_unflagged=True, adjustments=False)
        for g in p1:
            v1_players.setdefault(w, set()).add(g["player_id"])
            for r in g["stats"]:
                t = ctx.played_target(g["player_id"], 2025, w)
                if t is None:
                    void["v1 void (DNP)"] += 1
                    continue
                y = t[r["stat"]]
                if y == r["line"]:
                    void["push"] += 1
                    continue
                v1_rows.append({"key": (g["player_id"], w, r["stat"], r["bookmaker"], r["line"]),
                                "pid": g["player_id"], "week": w, "stat": r["stat"], "line": r["line"],
                                "p": r["probabilityOver"] / 100, "over": int(y > r["line"]),
                                "rule": r["threshold_rule"], "price": next(iter(r["prices"].values()), None)})
        p2, s2 = tt.evaluate_week(2025, w, "v2", config, params=P, adjustments=False)
        v2_players_by_week[w] = p2
        v2_summaries[w] = {k: v for k, v in s2.items() if k != "model"}
        for g in p2:
            t = ctx.played_target(g["player_id"], 2025, w)
            for r in g["stats"]:
                if r["stat"] == "anytime_td":
                    if w == 16 and t is not None:
                        inv = [1 / d for pr in r["prices"].values() for d in
                               [mv.valid_price(pr.get("Yes", pr.get("unknown")))] if d]
                        if inv:
                            td_test.append({"p_final": r["pRaw"]["final"], "p_mkt": r["pRaw"]["market"],
                                            "p_model": r["pRaw"]["model"], "inv": statistics.median(inv),
                                            "y": int(t["rushing_tds"] + t["receiving_tds"] >= 1),
                                            "pid": g["player_id"], "flagged": r["flagged"], "price": r["price"]})
                    continue
                if t is None:
                    void["v2 void (DNP)"] += len(r["prices"])
                    continue
                y = t[r["stat"]]
                over = int(y > r["line"])
                lr = {"pid": g["player_id"], "week": w, "stat": r["stat"], "line": r["line"], "over": over, "y": y,
                      "nbooks": len(r["prices"]), "p_final": r["pRaw"]["final"], "p_model": r["pRaw"]["model"],
                      "p_mkt": r["pRaw"]["market"], "far": r["farLine"], "games": r["gamesUsed"],
                      "name": g["player"], "mu": r["player_value"]}
                v2_line_rows.append(lr)
                for book, pr in r["prices"].items():
                    price = pr.get("unknown", pr.get("Over", pr.get("Under")))
                    v2_rows.append(dict(lr, key=(g["player_id"], w, r["stat"], book, r["line"]), book=book,
                                        price=price))
    v1_by = {r["key"]: r for r in v1_rows}
    v2_by = {r["key"]: r for r in v2_rows}
    both = sorted(set(v1_by) & set(v2_by), key=lambda k: (k[1], str(k[0]), k[2], str(k[3]), k[4]))
    v1_only = sorted(set(v1_by) - set(v2_by), key=lambda k: (k[1], str(k[0]), k[2], str(k[3]), k[4]))
    v2_only = sorted(set(v2_by) - set(v1_by), key=lambda k: (k[1], str(k[0]), k[2], str(k[3]), k[4]))
    v1_pb = {(k[0], k[1], k[2], k[3]) for k in v1_by}
    v2_reason = defaultdict(int)
    for k in v2_only:
        if (k[0], k[1], k[2], k[3]) in v1_pb:
            v2_reason["v1 per-(player, stat, bookmaker) dedup kept another line"] += 1
        elif k[0] not in v1_players.get(k[1], set()):
            v2_reason["v1 skipped player (no in-season game / all-zero stats)"] += 1
        else:
            v2_reason["v1 skipped row (all-zero window or None probability)"] += 1
    v1_reason = defaultdict(int)
    for k in v1_only:
        v1_reason["v2 no row (no history, mu <= 0, model error or unsupported line)"] += 1

    def g1(rows, pkey):
        clips = [0]
        b = mean(brier(r[pkey], r["over"]) for r in rows)
        l = mean(clip_logloss(r[pkey], r["over"], clips) for r in rows)
        return b, l, clips[0]

    inter2 = [v2_by[k] for k in both]
    inter1 = [v1_by[k] for k in both]

    def eval_k(kzero):
        pk = "p_k0" if kzero else "p_final"
        for r in v2_rows + v2_line_rows:
            r["p_k0"] = mv.anchor(r["p_mkt"], r["p_model"], 0.0)
        b2, l2, c2 = g1(inter2, pk)
        g1_ok = b2 <= 0.25 + TOL and l2 <= math.log(2) + TOL
        diff_rows = [((r2["pid"], r2["week"], r2["stat"]), brier(r2[pk], r2["over"]) - brier(r1["p"], r1["over"]))
                     for r2, r1 in zip(inter2, inter1)]
        pt, lo, hi = cluster_bootstrap(diff_rows, mean, args.seed)
        g2_ok = hi is not None and hi < 0
        real_b = calib_rows([(r[pk], r["over"]) for r in one_row_per_stat(v2_line_rows)])
        return {"pk": pk, "b2": b2, "l2": l2, "clips": c2, "g1": g1_ok, "g2": g2_ok, "g2ci": (pt, lo, hi),
                "real_b": real_b}

    hold_items = []
    for c in hold:
        p = model_p(mv, c, test_stats[c["stat"]], W)
        if p is not None:
            hold_items.append((p, c["over"]))
    proxy_b = calib_rows(hold_items)

    # G5: 2026 proxy, v2 model-only vs v1 on cases both price
    g5_pairs, g5_skips = [], defaultdict(lambda: defaultdict(int))
    for c in p26:
        p2 = model_p(mv, c, test_stats[c["stat"]], W)
        p1, why = ctx.v1_proxy_prob(c, thresholds)
        if p1 is None:
            g5_skips[c["week"]][why] += 1
            continue
        if why:
            g5_skips[c["week"]][why] += 1
        if p2 is None:
            g5_skips[c["week"]]["v2 no probability"] += 1
            continue
        g5_pairs.append((c, p1, p2))
    b5_v2 = mean(brier(p2, c["over"]) for c, _, p2 in g5_pairs)
    b5_v1 = mean(brier(p1, c["over"]) for c, p1, _ in g5_pairs)
    g5_ok = b5_v2 < b5_v1
    g5_ci = cluster_bootstrap([((c["pid"], c["week"], c["stat"]), brier(p2, c["over"]) - brier(p1, c["over"]))
                               for c, p1, p2 in g5_pairs], mean, args.seed)

    def g3(real_b):
        m = n_checked(real_b) + n_checked(proxy_b)
        z = z_for_level(max(m, 1))
        return m, z

    fitted = eval_k(False)
    m_fit, z_fit = g3(fitted["real_b"])

    def g3_fails(real_b, z, quiet=True):
        sub = Report(quiet=True) if quiet else rep
        fr = calib_table(sub, "real", real_b, z)
        fp = calib_table(sub, "proxy", proxy_b, z)
        return fr, fp

    fr_fit, fp_fit = g3_fails(fitted["real_b"], z_fit)
    g3_real_ok, g3_proxy_ok = not fr_fit, not fp_fit
    triggers = [n for n, ok in (("G1", fitted["g1"]), ("G2", fitted["g2"]), ("G3-real", g3_real_ok)) if not ok]
    fallback = None
    if triggers:
        fallback = eval_k(True)
        m_k0, z_k0 = g3(fallback["real_b"])
        fr_k0, fp_k0 = g3_fails(fallback["real_b"], z_k0)
    # G4
    g4_v2 = mean(brier(c["p_final"], c["y"]) for c in td_test) if td_test else float("nan")
    g4_mkt = mean(brier(c["p_mkt"], c["y"]) for c in td_test) if td_test else float("nan")
    g4_raw = mean(brier(min(c["inv"], 0.999), c["y"]) for c in td_test) if td_test else float("nan")
    g4_ok = bool(td_test) and g4_v2 <= g4_mkt + TOL

    if not triggers:
        gate_ok = g3_proxy_ok and g5_ok
        final = fitted
        label = "gate passed" if gate_ok else None
    else:
        fb_ok = (fallback["g1"] and fallback["g2"] and not fr_k0 and not fp_k0 and g5_ok)
        gate_ok = fb_ok and g3_proxy_ok
        final = fallback
        label = ("gate passed, O/U fallback k = 0 (stats model added no measurable value over the line on the "
                 "held-out weeks)") if gate_ok else None
    if not gate_ok:
        reasons = []
        if not g3_proxy_ok:
            reasons.append("G3-proxy: " + "; ".join(f"{b} stated {s:.3f} outside [{w[0]:.3f}, {w[1]:.3f}]" for _, b, s, w in fp_fit))
        if not g5_ok:
            reasons.append(f"G5: v2 Brier {b5_v2:.4f} not below v1 {b5_v1:.4f} (by {b5_v2 - b5_v1:+.4f})")
        if triggers:
            if not fallback["g1"]:
                reasons.append(f"G1 at k=0: Brier {fallback['b2']:.4f}, log loss {fallback['l2']:.4f}")
            if not fallback["g2"]:
                reasons.append(f"G2 at k=0: CI upper {fallback['g2ci'][2]}")
            if fr_k0:
                reasons.append("G3-real at k=0: " + "; ".join(f"{b} stated {s:.3f}" for _, b, s, _ in fr_k0))
        label = "gate failed: " + " | ".join(reasons)
    if triggers:
        P0 = json.loads(json.dumps(P))
        for s in STATS:
            P0["stats"][s]["k"] = 0.0
        P0["gate_label"] = "test parameters (O/U fallback k = 0)"
        mv.validate_params(P0)
        (out_dir / "params_test_k0.json").write_text(json.dumps(P0, indent=1), encoding="utf-8")

    # ---------------- report: real test ----------------
    rep("## Real O/U test, 2025 wk14-16 (stored odds, held-out)")
    rep("")
    rep(f"Graded rows: v1 {len(v1_rows)}, v2 {len(v2_rows)} (per-bookmaker expansion), both {len(both)}, "
        f"v1-only {len(v1_only)}, v2-only {len(v2_only)}. Voids: {dict(sorted(void.items()))}.")
    rep(f"v2-only reasons: {dict(sorted(v2_reason.items()))}. v1-only reasons: {dict(sorted(v1_reason.items()))}.")
    rep("v2 evaluate_week counters: " + "; ".join(f"wk{w} {v}" for w, v in v2_summaries.items()))
    rep("")
    ystat = defaultdict(list)
    for k in both:
        ystat[v2_by[k]["stat"]].append(k)
    rows = []
    for s in list(STATS) + ["ALL"]:
        ks = both if s == "ALL" else ystat[s]
        if not ks:
            rows.append([s, 0] + ["-"] * 9)
            continue
        r2 = [v2_by[k] for k in ks]; r1 = [v1_by[k] for k in ks]
        c1, c2, c3 = [0], [0], [0]
        rows.append([s, len(ks), len({(r["pid"], r["week"], r["stat"]) for r in r2}), f"{mean(r['over'] for r in r2):.3f}",
                     f4(mean(brier(r['p'], r['over']) for r in r1)),
                     f4(mean(brier(r['p_model'], r['over']) for r in r2)),
                     f4(mean(brier(r['p_final'], r['over']) for r in r2)), "0.2500",
                     f4(mean(clip_logloss(r['p'], r['over'], c1) for r in r1)),
                     f4(mean(clip_logloss(r['p_model'], r['over'], c2) for r in r2)),
                     f4(mean(clip_logloss(r['p_final'], r['over'], c3) for r in r2))])
    rep("**Scores on the intersection row set** (Brier / log loss; baseline 50/50 log loss 0.6931)")
    rep.table(["stat", "rows", "unique player-stats", "over-rate", "Brier v1", "Brier v2 model-only", "Brier v2 final",
               "Brier 50/50", "LL v1", "LL v2 model-only", "LL v2 final"], rows)
    b_all, l_all, _ = g1(v2_rows, "p_final")
    rep(f"G1 on all v2 rows ({len(v2_rows)}): Brier {b_all:.4f}, log loss {l_all:.4f}.")
    rep("")
    # bootstrap CIs
    cl = lambda r: (r["pid"], r["week"], r["stat"])
    bs1 = cluster_bootstrap([(cl(r), brier(r["p_final"], r["over"]) - 0.25) for r in inter2], mean, args.seed)
    bs2 = fitted["g2ci"]
    bs3 = cluster_bootstrap([(cl(r), brier(r["p_final"], r["over"]) - brier(r["p_model"], r["over"])) for r in inter2],
                            mean, args.seed)
    rep("**Cluster bootstrap** (2,000 resamples over (player_id, week, stat) clusters, 95% percentile CI)")
    rep.table(["quantity", "point", "95% CI"],
              [["Brier(v2) - 0.25", f4(bs1[0]), f"[{f4(bs1[1])}, {f4(bs1[2])}]"],
               ["Brier(v2) - Brier(v1)", f4(bs2[0]), f"[{f4(bs2[1])}, {f4(bs2[2])}]"],
               ["Brier(v2) - Brier(v2 model-only)", f4(bs3[0]), f"[{f4(bs3[1])}, {f4(bs3[2])}]"]])
    rep(f"Log-loss clip counts: v2 final {fitted['clips']}, v1 {sum(1 for r in inter1 if r['p'] in (0, 1))} "
        "(v1 is clamped to [5%, 95%]).")
    rep("")

    rep("## Gate")
    rep("")
    rep("> " + HOLDOUT_DISCLOSURE)
    rep("")
    g3r_txt = lambda fails: "PASS" if not fails else "FAIL: " + "; ".join(
        f"{b} stated {s:.3f} vs [{w[0]:.3f}, {w[1]:.3f}]" for _, b, s, w in fails)
    gate_rows = [
        ["G1 Brier <= 0.25 and log loss <= ln 2 (intersection)", f"Brier {fitted['b2']:.4f}, LL {fitted['l2']:.4f}",
         "PASS" if fitted["g1"] else "FAIL"],
        ["G2 CI of Brier(v2) - Brier(v1) below 0", f"{f4(bs2[0])} [{f4(bs2[1])}, {f4(bs2[2])}]",
         "PASS" if fitted["g2"] else "FAIL"],
        [f"G3-real calibration (m = {m_fit}, z = {z_fit:.3f})", "see tables", g3r_txt(fr_fit)],
        [f"G3-proxy calibration, 2025 wk14-17 model-only (m = {m_fit})", "see tables", g3r_txt(fp_fit)],
        ["G4 TD Brier v2 <= de-vigged market (2025 wk16)", f"v2 {f4(g4_v2)} vs market {f4(g4_mkt)} (raw 1/d {f4(g4_raw)})",
         "PASS" if g4_ok else "FAIL (k_TD = 0 in production)"],
        ["G5 2026 proxy v2 model-only Brier < v1", f"v2 {b5_v2:.4f} vs v1 {b5_v1:.4f} ({len(g5_pairs)} cases)",
         "PASS" if g5_ok else "FAIL"],
    ]
    rep("**At the fitted k** " + "(" + ", ".join(f"{s} {test_stats[s]['k']:.2f}" for s in STATS) + ")")
    rep.table(["criterion", "value", "result"], gate_rows)
    if triggers:
        bsk = fallback["g2ci"]
        rep(f"**k = 0 fallback triggered by {', '.join(triggers)}** (pre-registered; only the fitted k and k = 0 are "
            "evaluated on the test set)")
        rep.table(["criterion", "value", "result"], [
            ["G1 at k = 0", f"Brier {fallback['b2']:.4f}, LL {fallback['l2']:.4f}", "PASS" if fallback["g1"] else "FAIL"],
            ["G2 at k = 0", f"{f4(bsk[0])} [{f4(bsk[1])}, {f4(bsk[2])}]", "PASS" if fallback["g2"] else "FAIL"],
            [f"G3-real at k = 0 (m = {m_k0}, z = {z_k0:.3f})", "see tables", g3r_txt(fr_k0)],
            [f"G3-proxy (m = {m_k0})", "see tables", g3r_txt(fp_k0)],
            ["G5 (k-independent)", f"v2 {b5_v2:.4f} vs v1 {b5_v1:.4f}", "PASS" if g5_ok else "FAIL"],
        ])
    rep(f"**Gate result: {label}**")
    rep("")
    rep("### Calibration tables (one row per player-week-stat; real test uses the line with the most books)")
    rep("")
    calib_table(rep, "v2 final, real test, fitted k", fitted["real_b"], z_fit)
    if triggers:
        calib_table(rep, "v2 final, real test, k = 0", fallback["real_b"], z_k0)
    v1_line = [dict(r, nbooks=1) for r in v1_rows]
    calib_table(rep, "v1, real test (one bookmaker row per player-stat)",
                calib_rows([(r["p"], r["over"]) for r in one_row_per_stat(v1_line)]), z_fit)
    calib_table(rep, "v2 model-only, proxy hold-out 2025 wk14-17", proxy_b, z_fit)
    if triggers or all(test_stats[s]["k"] < 0.05 for s in STATS):
        rep("**Plain-language result:** the page will show near-market probabilities and few or no O/U flags. "
            "That is the honest result: on the held-out weeks the stats model did not add measurable value over "
            "the bookmaker line" + (" (fallback triggered)." if triggers else " (fitted k < 0.05 for every stat)."))
        rep("")

    # ---------------- flags (assumed-price mode) ----------------
    rep("## Flags, hit rate and ROI on the real test")
    rep("")
    flags_table(mv, rep, v2_rows, policy["min_games"], "v2 at the fitted k, assumed-price mode")
    if triggers:
        flags_table(mv, rep, [dict(r, p_final=r["p_k0"]) for r in v2_rows], policy["min_games"],
                    "v2 at k = 0, assumed-price mode")
    v1f = [r for r in v1_rows if r["rule"] != "No Bet"]
    if v1f:
        wins = [(r["over"] if r["rule"] == "Over" else 1 - r["over"]) for r in v1f]
        lo, hi = wilson(sum(wins), len(wins), 1.96)
        roi = mean((r["price"] - 1) if wn else -1 for r, wn in zip(v1f, wins) if r["price"])
        uq = {}
        for r, wn in zip(v1f, wins):
            uq.setdefault((r["pid"], r["week"], r["stat"]), wn)
        ul, uh = wilson(sum(uq.values()), len(uq), 1.96)
        rep(f"v1 threshold flags: {len(v1f)} rows, hit {mean(wins):.3f} [{lo:.3f}, {hi:.3f}], ROI at stored price "
            f"{roi:+.3f} (side unknown, S5); unique {len(uq)}, hit {mean(uq.values()):.3f} [{ul:.3f}, {uh:.3f}].")
        rep("")
    td_flags = [c for c in td_test if c["flagged"]]
    rep(f"Anytime TD 2025 wk16 live flags (real Yes prices): {len(td_flags)}" + (
        f", hit {mean(c['y'] for c in td_flags):.3f}, ROI {mean((c['price'] - 1) if c['y'] else -1 for c in td_flags):+.3f}"
        if td_flags else "") + ".")
    rep("")

    # ---------------- proxy tables ----------------
    rep("## Proxy hold-out (2025 wk14-17) and 2026 proxy (wk2-7)")
    rep("")
    rows = []
    for setname, cases in (("hold-out 2025 wk14-17", hold), ("2026 proxy wk2-7", p26)):
        for s in list(STATS) + ["ALL"]:
            cs = cases if s == "ALL" else [c for c in cases if c["stat"] == s]
            pr = []
            for c in cs:
                p2 = model_p(mv, c, test_stats[c["stat"]], W)
                p1, _ = ctx.v1_proxy_prob(c, thresholds)
                if p2 is not None and p1 is not None:
                    pr.append((c, p1, p2))
            if not pr:
                continue
            c1, c2 = [0], [0]
            z = []
            for c, _, _ in pr:
                sp = test_stats[c["stat"]]
                wm = mv.window_mean(c["values"], W)
                mu = wm[0] * (1.0 if sp["dist"] == "empirical_ratio" else sp["c"])
                if mu > 0:
                    z.append((c["y"] - mu) / (mv.cv(sp["a"], sp["b"], wm[1]) * mu))
            rows.append([setname, s, len(cs), len(pr), f"{mean(c['over'] for c, _, _ in pr):.3f}",
                         f4(mean(brier(p1, c['over']) for c, p1, _ in pr)),
                         f4(mean(brier(p2, c['over']) for c, _, p2 in pr)), "0.2500",
                         f4(mean(clip_logloss(p1, c['over'], c1) for c, p1, _ in pr)),
                         f4(mean(clip_logloss(p2, c['over'], c2) for c, _, p2 in pr)), c2[0],
                         f"{statistics.pstdev(z):.2f}" if len(z) > 1 else "-"])
    rep.table(["set", "stat", "cases", "both priced", "over-rate", "Brier v1", "Brier v2 model-only", "Brier 50/50",
               "LL v1", "LL v2", "v2 clips", "SD(z) v2"], rows)
    rep("SD(z) = SD of (actual - mu_used) / (CV * mu_used) per case. Values above 1 mean individual cases spread more "
        "than the pooled CV implies: the pooled (ratio-of-sums) CV fit weights high-volume players most, so "
        "low-volume players' relative noise is understated. The calibration tables are the decision-relevant check.")
    rep(f"G5 bootstrap CI of Brier(v2) - Brier(v1) on the 2026 proxy: {f4(g5_ci[0])} [{f4(g5_ci[1])}, {f4(g5_ci[2])}] "
        "(reported, not required).")
    rep("v1 gaps on the 2026 proxy per week (v1 window stays inside 2026; 'fewer than 3 games' cases are still priced):")
    for w in PROXY_2026:
        rep(f"- wk{w}: {dict(sorted(g5_skips[w].items()))}")
    rep("")

    # ---------------- TD ----------------
    rep("## Anytime TD (2025 wk16 test)")
    rep("")
    if td_test:
        n_td = sum(c["y"] for c in td_test)
        rep(f"Cases {len(td_test)}, TDs {n_td}, implied overround sum(1/d)/sum(TD) = "
            f"{sum(c['inv'] for c in td_test) / max(n_td, 1):.3f}. o_TD used {P['td']['o']}, k_TD {P['td']['k']}.")
        rep(f"Brier: v2 final {g4_v2:.4f}, v2 model-only {mean(brier(c['p_model'], c['y']) for c in td_test):.4f}, "
            f"de-vigged market {g4_mkt:.4f}, raw 1/d {g4_raw:.4f}.")
        order = ["<0.10", "0.10-0.20", "0.20-0.30", "0.30-0.50", ">=0.50"]
        tb = {b: [] for b in order}
        for c in td_test:
            p = c["p_mkt"]
            b = order[0] if p < 0.1 else order[1] if p < 0.2 else order[2] if p < 0.3 else order[3] if p < 0.5 else order[4]
            tb[b].append((p, c["y"]))
        rep.table(["de-vigged P_mkt bucket", "n", "mean P_mkt", "observed"],
                  [[b, len(v), f"{mean(p for p, _ in v):.3f}", f"{mean(y for _, y in v):.3f}"]
                   for b, v in tb.items() if v])
    else:
        rep("No TD test cases.")
    rep("")

    # ---------------- fixed-case assertions ----------------
    rep("## Fixed-case assertions")
    rep("")
    p26w8, s26 = tt.evaluate_week(2026, 8, "v2", config, params=P, adjustments=False)
    jac_pid = ctx.resolve(2026, 8).get("Josh Jacobs")
    jh = ctx.history(jac_pid, 2026, 8) if jac_pid else []
    first6 = [(r["season"], r["week"]) for r in jh[:6]]
    exp6 = [(2026, 7), (2025, 17), (2025, 16), (2025, 15), (2025, 14), (2025, 13)]
    raw6 = mean(r["rushing_yards"] for r in jh[:6]) if jh else float("nan")
    rep(f"- A4 #8 Jacobs history (player_id {jac_pid}): first six {first6} -> "
        f"{'PASS' if first6 == exp6 else 'FAIL'}; raw last-6 mean {raw6:.2f} -> {'PASS' if abs(raw6 - 52.83) < 0.05 else 'FAIL'}")
    jrow = [r for g in p26w8 if g["player"] == "Josh Jacobs" for r in g["stats"]
            if r["stat"] == "rushing_yards" and r["line"] == 60.5]
    if jrow:
        r = jrow[0]
        wm = mv.window_mean([h["rushing_yards"] for h in jh], W)
        exp_games = wm[2]
        pu_final = r["probabilityUnder"] / 100
        pu_model = 1 - r["pRaw"]["model"]
        rep(f"- A4 #8 Jacobs rush 60.5: gamesUsed {r['gamesUsed']} (selected window uses {exp_games}) -> "
            f"{'PASS' if r['gamesUsed'] == exp_games else 'FAIL'}; mu_raw {r['muRaw']}, mu_used {r['player_value']}; "
            f"P_final(Under) {pu_final:.3f} <= 0.65 -> {'PASS' if pu_final <= 0.65 else 'FAIL'}; "
            f"P_model(Under) {pu_model:.3f}" + (" (red flag: > 0.80)" if pu_model > 0.80 else " (<= 0.80, as expected)")
            + f"; flagged {r['flagged']}, reason '{r['noFlagReason']}' -> "
            f"{'PASS' if not r['flagged'] and r['noFlagReason'] == 'no price' else 'FAIL'}")
    else:
        rep("- A4 #8 Jacobs rush 60.5 row: FAIL (row not found)")
    # A4 #10 drop rule on 2025 wk16
    for name, market, lines in (("Cooper Kupp", "player_receptions", [3.5]), ("Dallas Goedert", "player_receptions", [4.5]),
                                ("Matthew Stafford", "player_rush_attempts", [1.5, 0.5])):
        ent = tt.drop_outlier_lines(tt.collapse_odds(tt.get_odds_for_player(name, 2025, 16)), name, 2025, 16)
        have = sorted({e["line"] for e in ent if e["market"] == market})
        ok = all(l in have for l in lines)
        rep(f"- A4 #10 {name} {market} {lines} kept by drop_outlier_lines (2025 wk16): lines now {have} -> "
            f"{'PASS' if ok else 'FAIL'}")
    # far-line list: v2 rows vs independent re-computation
    far_v2, far_ind, far_detail = set(), set(), {}
    weeks_all = [(2025, w) for w in REAL_TEST_WEEKS] + [(2026, 8)]
    v2_by_week = {}
    for (season, w) in weeks_all:
        players = p26w8 if season == 2026 else v2_players_by_week[w]
        v2_by_week[(season, w)] = players
        for g in players:
            h = ctx.history(g["player_id"], season, w)
            ent = tt.drop_outlier_lines(tt.collapse_odds(tt.get_odds_for_player(g["player"], season, w)),
                                        g["player"], season, w)
            for r in g["stats"]:
                if r["farLine"]:
                    far_v2.add((season, w, g["player"], r["market"], r["line"]))
            for e in ent:
                stat = MARKET_INV.get(e["market"])
                if stat is None or e["line"] is None:
                    continue
                vals = [x[stat] for x in h]
                if not vals:
                    continue
                if W["type"] == "last_n":
                    used = vals[:W["n"]]
                    mu = sum(used) / len(used)
                else:
                    ws = [0.5 ** (j / W["half_life"]) for j in range(len(vals[:17]))]
                    mu = sum(a * b for a, b in zip(ws, vals[:17])) / sum(ws)
                sp = test_stats[stat]
                mu_used = mu * (1.0 if sp["dist"] == "empirical_ratio" else sp["c"])
                if mu_used <= 0:
                    continue
                gap = abs(e["line"] - mu_used)
                floor = 10.0 if "yds" in e["market"] else 2.0
                if gap / mu_used > 0.60 and gap >= floor:
                    k = (season, w, g["player"], e["market"], e["line"])
                    far_ind.add(k)
                    nbooks = sum(1 for x in ent if x["market"] == e["market"])
                    recent = vals[0]
                    if nbooks == 1:
                        cls = "alt/stale line (single book)"
                    elif abs(recent - e["line"]) < abs(mu_used - e["line"]) / 2:
                        cls = "role change (latest game near the line)"
                    elif nbooks >= 3:
                        cls = "role change (3+ books agree, history disagrees)"
                    else:
                        cls = "normal (two books, no recent support)"
                    far_detail[k] = (mu_used, len(vals[:W.get("n", 17)]), nbooks, cls)
    same = far_v2 == far_ind
    rep(f"- A4 #10 far-line exclusions: model_v2 {len(far_v2)} lines, independent re-computation {len(far_ind)} -> "
        f"{'PASS (identical)' if same else 'FAIL'}" + ("" if same else f"; only model_v2 {sorted(far_v2 - far_ind)}; "
                                                       f"only independent {sorted(far_ind - far_v2)}"))
    mins_lines = sorted(r["line"] for g in v2_by_week[(2025, 16)] if g["player"] == "Gardner Minshew"
                        for r in g["stats"] if r["stat"] == "passing_yards")
    mins_far = sorted(k[4] for k in far_ind if k[:4] == (2025, 16, "Gardner Minshew", "player_pass_yds"))
    med = statistics.median(mins_lines) if mins_lines else None
    rep(f"- A4 #10 Minshew 2025 wk16 pass yds (lines {mins_lines}, median {med}) all excluded: excluded {mins_far} -> "
        f"{'PASS' if mins_lines and mins_far == mins_lines else 'FAIL'}")
    pw = [r for g in v2_by_week[(2025, 16)] if g["player"] == "Parker Washington" for r in g["stats"]
          if r["stat"] == "receiving_yards" and r["line"] == 20.5]
    if pw:
        dev = abs(20.5 - pw[0]["player_value"]) / pw[0]["player_value"]
        if dev <= 0.60:
            rep(f"- A4 #10 Parker Washington 20.5 vs mu_used {pw[0]['player_value']} (dev {dev:.2f}) not excluded -> "
                f"{'PASS' if not pw[0]['farLine'] else 'FAIL'}")
        else:
            rep(f"- A4 #10 Parker Washington: dev {dev:.2f} > 0.60 with the selected window/c, assertion skipped")
    else:
        rep("- A4 #10 Parker Washington 20.5 row not found")
    rep("")
    rep("**Far-line exclusions (selected window and c), per line**")
    rep.table(["season", "week", "player", "market", "line", "mu_used", "games", "books", "class"],
              [[k[0], k[1], k[2], k[3], k[4], f"{far_detail[k][0]:.1f}", far_detail[k][1], far_detail[k][2],
                far_detail[k][3]] for k in sorted(far_ind)])
    pm = sorted({(k[0], k[1], k[2], k[3]) for k in far_ind})
    rep(f"Per player-market: {len(pm)} excluded. Design reference list (last 6, c = 1, median line per market): "
        + "; ".join(REFERENCE_FAR_LINES) + ". Differences come from the selected window and c_k and from the rule "
        "being applied per line rather than to the median line.")
    rep("")

    # ---------------- matchup experiment (diagnostic, after the gate) ----------------
    rep("## Matchup experiment (diagnostic only; run after the gate result was fixed)")
    rep("")
    if not args.matchup:
        rep("matchup experiment not run: no --matchup-experiment schedule file given.")
    else:
        try:
            matchup_experiment(rep, ctx, mv, args.matchup, B, chosen_sp, W, v2_line_rows, test_stats, args.seed)
        except Exception as e:
            rep(f"matchup experiment not run: {e}")
    rep("Weather is not tested: there is no weather data (weather_api returns nothing).")
    rep("")

    # ---------------- production parameters ----------------
    if args.write_params:
        if not gate_ok:
            (out_dir / "report.md").write_text("\n".join(rep.lines) + "\n", encoding="utf-8")
            fail(6, f"--write-params refused: {label}")
        write_production(rep, ctx, tt, mv, config, target, W, test_stats, chosen_sp, P, triggers, g4_ok,
                         v2_rows, label, fit_td_market, args.seed)

    rep("## Served page and performance")
    rep("")
    rep("(filled in from the served-page check)")
    rep("")
    (out_dir / "report.md").write_text("\n".join(rep.lines) + "\n", encoding="utf-8")
    h1 = sha256(repo_db)
    if h1 != h0:
        fail(4, f"REAL DB CHANGED during the run: {h0} -> {h1}")
    print(f"\nreal DB unchanged ({h1}). Report: {out_dir / 'report.md'}", file=sys.stderr)
    print(f"GATE: {label}", file=sys.stderr)


MARKET_INV = {v: k for k, v in MARKET.items()}


def matchup_experiment(rep, ctx, mv, sched_path, B, chosen_sp, W, v2_line_rows, test_stats, seed):
    from sqlalchemy import text
    from team_stats import MATCHUP_BETA
    sched = {int(k): v for k, v in json.load(open(sched_path, encoding="utf-8")).items()}
    opp = {}
    for w, games in sched.items():
        for g in games:
            opp[(g["home"], w)] = g["away"]
            opp[(g["away"], w)] = g["home"]
    tw = {}
    with ctx.tt.engine.connect() as conn:
        for r in conn.execute(text("""
            SELECT team, week, SUM(COALESCE(passing_yards,0)), SUM(COALESCE(receiving_yards,0)),
                   SUM(COALESCE(receptions,0)), SUM(COALESCE(rushing_yards,0))
            FROM player_weekly_stats WHERE season = 2025 AND season_type = 'regular' AND team IS NOT NULL
            GROUP BY team, week""")):
            tw[(r[0], int(r[1]))] = {"passing_yards": r[2], "receiving_yards": r[3], "receptions": r[4],
                                     "rushing_yards": r[5]}
    teams = sorted({t for t, _ in opp})
    cache = {}

    def allowed(team, week, stat):
        vals = [tw[(opp[(team, w)], w)][stat] for w in range(1, week) if (team, w) in opp and (opp[(team, w)], w) in tw]
        return mean(vals) if vals else None

    def factor(team, week, stat):
        beta = MATCHUP_BETA.get(stat, 0.0)
        o = opp.get((team, week))
        if not beta or not o:
            return 1.0
        key = (o, week, stat)
        if key not in cache:
            lg = [a for a in (allowed(t, week, stat) for t in teams) if a]
            a = allowed(o, week, stat)
            cache[key] = (a / mean(lg)) if a and lg else 1.0
        return 1.0 + beta * (cache[key] - 1.0)

    def p_with(case_values, line, stat, sp, f):
        wm = mv.window_mean(case_values, W)
        if wm is None:
            return None
        mu = wm[0] * (1.0 if sp["dist"] == "empirical_ratio" else sp["c"]) * f
        if mu <= 0:
            return None
        return mv.p_over_dist(sp["dist"], mu, mv.cv(sp["a"], sp["b"], wm[1]), line, sp.get("ratios"))

    rows, overall = [], []
    for s in STATS:
        diffs = []
        for c in B[s]:
            f = factor(c["team"], c["week"], s)
            p0 = p_with(c["values"], c["line"], s, chosen_sp[s], 1.0)
            p1 = p_with(c["values"], c["line"], s, chosen_sp[s], f)
            if p0 is None or p1 is None:
                continue
            d = clip_logloss(p1, c["over"]) - clip_logloss(p0, c["over"])
            diffs.append(((c["pid"], c["week"], s), d))
        overall += diffs
        pt, lo, hi = cluster_bootstrap(diffs, mean, seed)
        rows.append([s, len(diffs), f4(pt), f"[{f4(lo)}, {f4(hi)}]"])
    pt, lo, hi = cluster_bootstrap(overall, mean, seed)
    rows.append(["ALL", len(overall), f4(pt), f"[{f4(lo)}, {f4(hi)}]"])
    rep("Fold-B log-loss difference (with factor - without), fold-A parameters, cluster bootstrap 95% CI:")
    rep.table(["stat", "cases", "mean diff", "95% CI"], rows)
    with_f, without = [], []
    for r in v2_line_rows:
        t = ctx.played_target(r["pid"], 2025, r["week"])
        h = ctx.history(r["pid"], 2025, r["week"])
        sp = test_stats[r["stat"]]
        f = factor(t.get("team") if t else None, r["week"], r["stat"])
        p1 = p_with([x[r["stat"]] for x in h], r["line"], r["stat"], sp, f)
        if p1 is None:
            continue
        with_f.append(brier(mv.anchor(r["p_mkt"], p1, sp["k"]), r["over"]))
        without.append(brier(r["p_final"], r["over"]))
    rep(f"Diagnostic, not used for any decision: real-test Brier (one row per line) with factor {f4(mean(with_f))}, "
        f"without {f4(mean(without))} ({len(with_f)} lines).")
    if hi is not None and hi < 0:
        rep("Matchup factor shows an out-of-sample gain on fold B; recommend a follow-up build with a committed "
            "schedule source (2025 and 2026), a `matchup` params block and its own gate.")
    else:
        rep("No clear out-of-sample gain; matchup stays display-only.")


def write_production(rep, ctx, tt, mv, config, target, W, test_stats, chosen_sp, P, triggers, g4_ok,
                     v2_rows, label, fit_td_market, seed):
    T = target[1]
    rep(f"## Production parameters (--write-params, target 2026 wk{T})")
    rep("")
    a1, td1 = ctx.proxy_cases(2025, list(range(4, 18)), False)
    a2, _ = ctx.proxy_cases(2026, list(range(2, T)), True)
    allc = a1 + a2
    for c in td1:
        t = ctx.played_target(c["pid"], 2025, c["week"])
        c["y_count"] = t["rushing_tds"] + t["receiving_tds"]
    prod = json.loads(json.dumps(P))
    rows = []
    for s in STATS:
        cs = [c for c in allc if c["stat"] == s]
        try:
            sp = stat_fit(mv, cs, W, s, chosen_sp[s]["dist"])
        except FitError as e:
            fail(5, f"CV fit failed: {e}")
        if sp["dist"] == "empirical_ratio":
            sp = with_ratios(mv, sp, cs, W)
        sp["blend"] = chosen_sp[s]["blend"]
        if triggers:
            k, why = 0.0, "O/U fallback k = 0"
        else:
            pairs = [(standin_market(mv, c, sp), model_p(mv, c, sp, W), c["over"]) for c in cs]
            pairs = [p for p in pairs if p[1] is not None]
            k_stand = best_k(pairs)[0]
            real = [r for r in v2_rows if r["stat"] == s]
            k_real = best_k([(0.5, r["p_model"], r["over"]) for r in real])[0] if real else 0.0
            k = min(k_stand, k_real, test_stats[s]["k"], K_CAP)
            why = f"min(stand-in {k_stand:.2f}, real {k_real:.2f}, gated {test_stats[s]['k']:.2f}, 0.25)"
        sp["k"] = round(k, 2)
        prod["stats"][s] = sp
        rows.append([s, f"{sp['c']:.3f}", f"{sp['a']:.4f}", f"{sp['b']:.4f}", sp["dist"], sp["k"], why])
    rep.table(["stat", "c", "a", "b", "dist", "k", "rule"], rows)
    prod["td"]["lambda0"] = td_lambda0(td1)
    ptd = json.loads(json.dumps(prod))
    ptd["td"]["k"], ptd["td"]["o"] = 0.0, DEFAULT_O_TD
    o_td, k_td_fit, _ = fit_td_market([14, 15, 16], ptd, "production, 2025 wk14-16")
    prod["td"]["o"] = round(o_td, 4)
    prod["td"]["k"] = 0.0 if not g4_ok else round(min(k_td_fit, P["td"]["k"], K_CAP), 2)
    from sqlalchemy import text
    with tt.engine.connect() as conn:
        rs = conn.execute(text("""SELECT player_id, market, bookmaker, line, outcome, price FROM odds
            WHERE outcome IN ('Over', 'Under') AND (season < 2026 OR (season = 2026 AND week < :w))"""),
                          {"w": T}).fetchall()
    pairs = defaultdict(dict)
    for pid, market, book, line, oc, price in rs:
        if market in MARKET_INV:
            pairs[(pid, market, book, line)][oc] = price
    ovr = [1 / d["Over"] + 1 / d["Under"] for d in pairs.values() if "Over" in d and "Under" in d
           and mv.valid_price(d["Over"]) and mv.valid_price(d["Under"])]
    prod["o_ou"] = round(statistics.median(ovr), 4) if ovr else DEFAULT_O_OU
    rep(f"o_ou {prod['o_ou']} from {len(ovr)} two-way O/U rows before 2026 wk{T}"
        + ("" if ovr else " (none, fallback 1.064)") + f". TD: o {prod['td']['o']}, k {prod['td']['k']}"
        + ("" if g4_ok else " (G4 failed -> 0)") + ".")
    prod["gate_label"] = "passed, O/U fallback k = 0" if triggers else "passed"
    prod["fitted_on"] = (f"proxy 2025 wk4-17 + 2026 wk2-{T - 1}; O/U k: 2025 wk14-16 odds; TD: 2025 wk14-16 odds")
    mv.validate_params(prod)
    (REPO / "model_v2_params.json").write_text(json.dumps(prod, indent=1), encoding="utf-8")
    rep(f"Wrote `{REPO / 'model_v2_params.json'}` (gate_label '{prod['gate_label']}').")
    rep("")


if __name__ == "__main__":
    main()
