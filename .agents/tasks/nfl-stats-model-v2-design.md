# NFL player-prop model v2: requirements and technical design

Branch `model-v2` (HEAD `56f0092`, same commit as `math-bugfixes`, no new commits; re-verified 2026-10-30 before this revision). Status: **revision 3**, answering the round-2 design review (`nfl-stats-model-v2-design-review.json`, CHANGES_REQUESTED, 0 HIGH, 5 MEDIUM, 9 NIT). No code has been written. Part D lists the round-1 findings and Part E the round-2 findings, each with its resolution.

Inputs:

- `nfl-stats-math-review.md`: findings S1-S10 and J1-J8, recommendations #8, #9, #11-#14 and #18, and the back-test tables.
- `nfl-stats-math-bugfixes.md` and `nfl-stats-bugfixes-review.md`: what is already fixed (player_id keying, `week <` window, `gp` DNP filter, `outcome` column, 25% outlier rule, display-only matchup factor with beta, picked-side sort).
- Current sources: `test_thresholds.py`, `Odds_vs_Stats_Check.py`, `probability_calc.py`, `pipeline_config.py`, `models.py`, `app.py:420-439`, `index.html:759-958`, `team_stats.py`, `target_share_calc.py`.
- The review's scripts in `%TEMP%\nflmath\`. `backtest.py`, `improved.py`, `teamfx.py`, `boot.py` and `sched2025.json` are all still present.
- Read-only queries against `nfl_stats.db` (`mode=ro` URI) made for this design on 2026-10-30. Results are quoted below.

- `nfl-stats-model-v2-design-review.md` / `.json`: the round-2 review of revision 2. Every finding is resolved in this revision (Part E). The round-1 findings were resolved in revision 2 (Part D).

Nothing in this design calls The Odds API. Part C lists what revision 1 changed from the earlier draft. Part D lists the responses to the round-1 review, Part E the responses to the round-2 review.

---

# Part A. Requirements

## A1. Summary

On honest data, the picks page shows probabilities that score worse than a coin flip: Brier 0.291, against 0.250 for "always 50%". Its flagged picks hit 47%, against a break-even of about 53%. v2 replaces the probability model and the flag rule. The goal is calibrated probabilities and a small number of flags that have a real edge after the bookmaker's vig. The goal is not more flags or a higher-looking hit rate. If the stats model adds nothing over the market, the fitted market weight k goes to 0. The page then shows near-market probabilities and flags nothing. That is an acceptable result, and the report must say so plainly.

v1 (today's 3-game average with fixed yard thresholds) stays available behind one switch, so the two can be compared. A back-test harness committed to the repo is the acceptance gate.

### Data facts that shape the design (measured 2026-10-30, read-only)

| Fact | Value | Consequence |
|---|---|---|
| Stats in DB | 2025 regular wk1-17 (38,528 rows), 2026 wk1-7 (15,865 rows), `gp` populated on all of them (0 NULL) | The window can cross from 2026 into 2025. 2025 has no prior season in the DB. |
| Odds rows | 2025 wk14: 352 rows, 1 game. wk15: 359, 1 game. wk16: 3,312, 15 games. 2026 wk8: 390, 1 game (unplayed) | Only 2025 wk14-16 can be graded. There are no real odds before wk14. |
| `odds.outcome` | NULL on **all** 4,413 rows (legacy) | No stored Over/Under pair exists. Every O/U row has an unknown side until the user re-fetches odds. |
| Prop lines | All half-point. 0 integer lines in any player market | Pushes can't happen on current data. |
| `player_anytime_td` | 2,341 rows, `line` NULL, prices 1.35-46.0 | The stored price is the Yes price. A No price for most players would be below about 1.3, and the minimum stored is 1.35. |
| Anytime-TD implied overround (measured for revision 2, read-only, odds name matched to `player_display_name`, played games only) | 2025 wk14-15: 45 usable player-weeks (20 void or unmatched), Σ median(1/d) = 8.12 against 7 TDs, ratio 1.16. wk16: 331 usable, 69.73 against 59 TDs, ratio 1.18 | The Yes price carries roughly 16-18% margin, so 1/price must be de-vigged before it is used as P_mkt (B5). Seven events in the fit weeks is far too few to estimate the ratio, so the fit falls back to a fixed value (B10.3 step 7). The wk16 figure is test data and is not used for fitting. |
| `player_rush_attempts` | 143 odds rows, but `player_weekly_stats` has **no rushing-attempts column** (columns: passing_yards, passing_tds, rushing_yards, rushing_tds, receiving_yards, receiving_tds, receptions, gp) | Can't be modelled or graded without new data. Out of scope (A5). |
| Single-book player-markets (5 O/U markets, all stored weeks) | 89 single-book, 390 multi-book | The far-line rule (B9) must be measured on both. |
| Parker Washington 2025 wk16 | Ladbrokes 20.5 at 1.88. Honest last-6-played mean **48.8** (wk 9-15: 90, 33, 20, 71, 26, 53) | The "mean ~75" in the brief is the leaky 3-game mean that included wk16 (26 + 53 + 145). See B9. |
| Josh Jacobs (5850), 2026 wk8 | Last 6 played games before wk8: 2026 wk7 36, then 2025 wk17 3, wk16 36, wk15 73, wk14 86, wk13 83, so μ = 52.8 | Crossing seasons replaces the one-game window. |

## A2. Functional requirements

**FR1. Mean.** For each player and stat, μ comes from the player's most recent regular-season games actually played (`gp > 0`, with the existing NULL-gp fallback). The games must come strictly before the target (season, week). They are ordered by (season, week) descending, cross into the previous season when needed, and are keyed on `player_id`. Out-of-sample validation chooses the window (last N, or EWMA), and a per-stat mean-bias factor is fitted (B2).

**FR2. Dispersion.** One rule gives σ for every player: σ = CV_k(n_eff) · μ, with per-stat pooled parameters fitted only on prior data. There is no special case for s = 0. Fewer games give a wider distribution, never a narrower one.

**FR3. Distributions.** Yards use a log-normal or pooled empirical distribution. Receptions and pass TDs use a negative binomial or Poisson. P(Over) = P(X ≥ ⌈L⌉). Out-of-sample log loss chooses the family for each stat (B4).

**FR4. Market anchoring.** P_final = P_mkt + k_k · (P_model − P_mkt). k_k is fitted on held-out data and capped at 0.25. P_mkt is set by price coverage:

- Both sides priced by the same book: the no-vig probability (normalize 1/d_over and 1/d_under to sum to 1), median across books.
- Both sides priced, but only by different books: the cross-book no-vig probability from the median 1/d of each side.
- One side priced: median 1/price of that side divided by a fitted per-family overround factor o (de-vigged). The raw 1/price overstates the priced side and would inflate edge (B5).
- No side known (all legacy O/U rows): 0.5, and the row is marked "no market price". Such rows never flag.

**FR5. Flag rule.** edge = P_final(side) − 1/price(side), which is the edge against the actual price including vig. A row is flagged only when all three hold:

- the side's price is known and the market source is not "none"
- edge > V2_EDGE_MARGIN (0.03)
- no exclusion applies (B5 and B9)

Rows that are not flagged are still returned, with their probabilities and a reason.

**FR6. Anytime TD.** Add `player_anytime_td`. λ comes from recent (rush TD + rec TD) per game played, shrunk toward a position prior. P(≥1) = 1 − e^(−λ). Anchoring and the edge rule are the same as for O/U, against the Yes price, with the one-sided anchor de-vigged by o_TD.

**FR7. Errors are not coin flips (bug #9).** `probability_calc.calculate_probability` logs the exception and returns `None`. Callers skip `None` rows instead of showing 50/50. v2 does the same.

**FR8. Outlier lines.**

- Multi-book drop: count markets (`COUNT_MARKETS`: receptions, pass TDs, rush attempts) drop a line only when rel > 0.25 **and** |L − median| > 1.0 (strictly greater). Yards markets keep the 25% rule.
- Far-line exclusion: a line far from the player's v2 mean (B9) is kept and shown but excluded from flagging, and the exclusion is logged. This applies to single-book and multi-book lines (see C, change 2).

**FR9. Matchup and weather stay display-only in v2.** They don't feed μ in this build. The optional matchup experiment in B10.6 is diagnostic only: it runs after the gate, never changes the gated or written parameters, and its result is reported whether it helps or not. If it shows a clear out-of-sample gain, the report recommends a follow-up build (A5).

**FR10. Switch.** `MODEL_VERSION` in `pipeline_config.py` takes `'v1'` or `'v2'` and selects the live model. v1 behaves as today, apart from bug fix FR7 and the FR8 multi-book tweak. The value is committed as `'v1'`. It is switched to `'v2'` in a separate commit, and only after the gate passes and production parameters are written (A4 #15).

**FR11. Back-test harness.** `backtest.py` at the repo root runs v1 and v2 on a DB copy in `$env:TEMP`, never on the real DB. It fits only on data before the evaluated weeks and produces the report in B10.5.

**FR12. API and page.**

- Each pick shows the model probability, the market probability (or "no price"), the final probability, the price and the edge in points.
- Picks are sorted by edge.
- Duplicate bookmaker rows collapse to one row per line, with the best price per side.
- "Player Avg (3)" becomes "Avg (last N played)".
- The existing display-only adjustment details stay.
- Verification uses the served page, not just a code read.

## A3. Non-functional requirements

- **Safety.** The harness refuses to run unless every DB engine it uses resolves inside `$env:TEMP`. There are no Odds API calls and no writes to `nfl_stats.db`. This design makes no schema change and no DB write, so no new DB backup is needed. The existing `nfl_stats.backup-20261030-143034.db` (10,027,008 bytes) stays. If an implementer finds a DB write is needed after all, they stop and ask, then take a timestamped backup and verify its size first.
- **No new dependencies.** Only stdlib `math`, plus the existing `pandas`, `numpy`, `SQLAlchemy` and `fastapi`. scipy is **not** added. The normal CDF uses `math.erf`, and the NB and Poisson pmfs use `math.lgamma`.
- **Determinism.** The bootstrap uses a fixed seed (20261030). The harness gives identical output on identical data.
- **Performance.** `/generate-picks` in v2 is no slower than v1 on 2026 wk8 (42 s today). v2 does one history query per player and skips `target_share_calc`, whose output nothing reads.
- **Reproducibility.** Fitted parameters live in a committed JSON file that records the data ranges they were fitted on.
- **Git.** No worktree. No merge, push or history rewrite. Commits go on `model-v2` only.

## A4. Acceptance criteria

`backtest.py` measures the gate on held-out data. Fit and test weeks are defined per market family (B10.2, `FIT_TEST`):

- **O/U:** parameters (window, c, CV, distribution, stand-in k) are fitted on 2025 wk4-13. The test is the real stored odds of 2025 wk14-16.
- **Anytime TD:** λ0 and n0 are fitted on 2025 wk4-13. k_TD and the overround o_TD are fitted on the real TD odds of 2025 wk14-15. The test is 2025 wk16.

G1, G2, G3 and G5 are blocking. G4 resolves itself: a failure sets k_TD = 0.

**Grading row set.** Each v2 (market, line) row is expanded to one graded row per bookmaker at that line (B10.4). G1, G2 and the v1-vs-v2 calibration tables use the intersection of the v1-graded and v2-graded keys (player_id, week, stat, bookmaker, line). The report states the v1-only, v2-only and both counts, and also gives G1 on all v2 rows.

**Scoring.** Log loss clips each probability to [1e-6, 1 − 1e-6] in scoring only (B10.4). The report gives the clip count per candidate.

1. **G1.** On the O/U real test, v2 Brier ≤ 0.2500 and v2 log loss ≤ ln 2 = 0.6931, each with a 1e-9 tolerance.
   - **k = 0 fallback (pre-registered).** The fallback triggers when **any** k-dependent blocking criterion fails at the fitted O/U k: G1, G2, or the real-test half of G3. The harness then re-evaluates once with k = 0 for all five O/U stats (P_final = P_mkt, which is 0.5 on every legacy row) and re-checks G1, G2, G3 (both halves) and G5. At k = 0, G1 holds exactly and G3-real is a single "0.50 (tie)" bucket. If all re-checked criteria pass, the gate passes with the label **"O/U fallback k = 0"**. The report states plainly that the stats model added no measurable value over the line on the held-out weeks, names the criterion that triggered the fallback, and gives its value at the fitted k.
   - G3's proxy half and G5 use v2 model-only probabilities, which don't depend on k. A failure in either fails the gate with no fallback.
   - Only two O/U k settings may ever be evaluated on the test set: the fitted k and 0. With the fallback, `--write-params` writes k = 0 for every O/U stat and skips the B10.7 #2 production k rule for O/U.
   - G2 at k = 0 compares Brier 0.2500 against v1. With v1 at about 0.291 it is expected to pass, and the bootstrap still decides.
2. **G2.** v2 is clearly better than v1: the 95% cluster-bootstrap CI of Brier(v2) − Brier(v1), on the intersection row set, lies entirely below 0. The math review measured v1 at 0.291. The harness re-measures it on the current code.
3. **G3.** Calibration on one row per (player, week, stat), using the line with the most books (ties go to the lower line).
   - The favoured side is Over when P_final_over ≥ 0.5. Rows with |P_final_over − 0.5| < 1e-9 form their own bucket, "0.50 (tie)", which is checked against the observed Over rate.
   - The check runs on the real test with v2 final probabilities, and on the 2025 wk14-17 proxy hold-out with **v2 model-only** probabilities (no market exists there). Both halves are blocking.
   - **Family-wise level (Bonferroni).** Let m be the total number of buckets with ≥ 30 rows across both halves. For every such bucket, the mean stated probability must lie inside the Wilson interval of the observed hit rate at two-sided level 1 − 0.05/m, that is z = Φ⁻¹(1 − 0.025/m) (for example z = 2.64 at m = 6, z = 2.69 at m = 7). Running m separate 95% tests would fail a perfectly calibrated model with probability 1 − 0.95^m, about 26-30% at m = 6-7.
   - The report shows both the 95% and the Bonferroni interval for every bucket. A bucket outside its 95% interval is listed as a red flag even when it passes.
   - m is fixed by the bucket counts before any comparison is made. At the k = 0 re-check, m is recomputed for the bucket set at k = 0.
   - z is computed by bisection on `math.erf` (no scipy).
4. **G4.** Anytime TD: v2 Brier on 2025 wk16 is ≤ the Brier of the de-vigged P_mkt alone (median 1/d ÷ o_TD). The report also gives the Brier of raw median 1/price. The cases are the `player_anytime_td` rows that `evaluate_week(2025, 16, "v2", ..., adjustments=False)` returns, so odds-to-player matching is the live name-variant matching (B10.3 step 7). If G4 fails, the production parameters get k_TD = 0 and the report says so.
5. **G5.** On the 2026 proxy (wk2-7, B10.2), v2 model-only Brier beats v1 for overall O/U, using `params_test.json` (fitted on 2025 wk4-13). It is a point-estimate comparison on the cases where both models give a probability. The cluster-bootstrap CI is reported but not required. v1's window stays inside the target season (`get_recent_3_game_stats_by_id` filters `season = :year`) and prices from a single game through its `len(rows) == 1` path (std 0). The report therefore states how many cases v1 couldn't price (no 2026 played game before the target) and how many it priced from fewer than 3 games, per week.
6. Bug #8: a unit test shows that receptions [6,6,7] give P(Over 4.5) ≥ [6,6,6], and that the two differ by less than 0.05.
7. Small n widens, never narrows:
   - For every stat in the fitted parameters, CV_k(1) > CV_k(3) > CV_k(6) (strict, because b_k ≥ a_k > 0).
   - For the **normal** family at the same μ and line, |P(n = 1) − 0.5| < |P(n = 6) − 0.5|.
   - For receptions with negbin, μ = 6, L = 4.5 and synthetic a = b = 0.362, P(n = 1) is closer to 0.5 than P(n = 6).
   - No test asserts "closer to 0.5" for log-normal or negbin with L > μ. There the widening is mean-preserving, the median falls, and P(Over) correctly moves away from 0.5 (review finding 6: log-normal 0.266 → 0.255, negbin 0.367 → 0.352).
8. Josh Jacobs, 2026 wk8, rushing yards 60.5, on a DB copy, through `evaluate_week(..., adjustments=False)`:
   - The history query returns ≥ 6 played games, the first six being 2026 wk7 and 2025 wk17, 16, 15, 14, 13. Their raw mean is 52.8 (asserted on the raw history, independent of the selected window).
   - `gamesUsed` equals the selected window's game count (min(N, available) for last N; the number of rows used for EWMA). With last 6 it is 6, five of them from 2025.
   - The report gives μ_raw for the selected window and μ_used = c·μ_raw separately.
   - P_final(Under) ≤ 0.65 (hard check).
   - P_model(Under) ≤ 0.80 is expected with last 6 (the review computed about 0.72 with log-normal and CV_rush(6) = 1.0). It depends on the selected window, so a value above 0.80 is reported as a red flag with its inputs, but it does not change the pre-registered window choice.
   - The row isn't flagged (legacy row, `marketSource = "none"`, reason "no price").
9. Bug #9: a unit test that forces an exception in `calculate_probability` gets `None` and an ERROR log record. `check_stat_against_odds` drops that row.
10. Outlier rules:
    - The harness computes the far-line exclusion list on all stored odds with the **selected** window and c_k. It asserts that list equals an independent re-computation of B9's rule inside the harness (a second implementation from the raw history and lines, not a call to `model_v2`). It reports the list per line and per player-market. The design's reference list (last 6, c = 1, B9: 6 single-book and 10 multi-book player-markets) is printed alongside, and differences are explained. The report classifies each exclusion as role change, alt/stale line, or normal.
    - Gardner Minshew 2025 wk16 passing yards 213.5 (μ_raw 7.3) is excluded. It stays excluded for any c in [0.8, 1.2] and any candidate window, because he has only 3 played games before wk16.
    - Parker Washington 20.5: with μ_used giving dev ≤ 0.60 (last 6 with c = 1 gives μ 48.8, dev 0.58), the line is asserted **not** excluded. If the selected window and c push dev above 0.60 (for example c = 1.2 gives μ_used 58.6, dev 0.65), the assertion is skipped and the report explains the change.
    - The one-unit and half-unit count-market drops listed in math-bugfixes are no longer dropped: Kupp receptions 3.5 vs 2.5, Goedert receptions 4.5 vs 3.5, and Stafford rush attempts 1.5/0.5.
11. Leak-free:
    - For every case, the harness asserts that the maximum (season, week) of the history rows is below the target.
    - For each family in `FIT_TEST` (B10.2), it asserts that every fit (season, week) is before every test (season, week) and that no (season, week) is in both.
12. Real DB untouched: the SHA256 of `nfl_stats.db` is identical before and after the harness run and the served-page check.
13. Served page, run on 127.0.0.1 port 8001 (any free port other than 8000), with `NFL_STATS_DB` pointing at a temp copy, `NFL_MODEL_VERSION=v2` and `NFL_MODEL_V2_PARAMS=<OUT>\params_test.json`, for 2025 wk16 and 2026 wk8. The repo `model_v2_params.json` is never written for this check:
    - A Node DOM check passes. It runs the served `index.html` functions on the served `/generate-picks` JSON.
    - Headers show "Avg (last N played)" and Model % / Market % / Final % / Price / Edge.
    - No (player, stat, line) appears twice.
    - Cards are in non-increasing edge order, with flagged cards first.
    - Rows with no side price show "no price" and are never flagged.
    - A headless Edge screenshot is saved.
14. With `MODEL_VERSION = 'v1'`, the output for 2026 wk8 matches the v1 baseline captured **before the first code edit** (B12, "v1 baseline"): `$env:TEMP\nfl_backtest\baseline\v1_2026wk8.json`, same flagged rows and probabilities. The comparison runs the edited code on its own DB copy with `NFL_SEASON=2026`, `NFL_WEEK=8`, `NFL_MODEL_VERSION=v1`. The only allowed differences are rows that FR7 or the FR8 multi-book tweak change, and they are listed with the rule that changed each. The comparison reads the baseline list and the edited output's `players` array (if the edited CLI prints the envelope), and compares per (player, stat, bookmaker, line): `threshold_rule`, `probabilityOver`, `probabilityUnder`, `player_value`.
15. If any blocking criterion still fails after the pre-registered k = 0 fallback (A4 #1), or G3-proxy or G5 fails (no fallback applies), `MODEL_VERSION` stays `'v1'`, `--write-params` isn't run, and the report states which criterion failed and by how much. A gate passed through the fallback is a pass: v2 ships with O/U k = 0, and the report and the page's model info say so ("O/U fallback k = 0").

## A5. Out of scope

- `player_rush_attempts`. There is no attempts column. Adding one needs a schema change plus a Sleeper `rush_att` backfill of the real DB, so it is backlogged. v2 ignores the market, as v1 does.
- Re-fetching odds (paid API) and any change to odds ingestion. Real Over/Under prices appear only after the user re-fetches.
- Weather data, game script, opportunity and target share (they stay unused or display-only), and implied team totals.
- Stake sizing (Kelly), playoffs, and the standalone `qb_*_prediction.py` scripts.
- Feeding a matchup factor into μ. The B10.6 experiment is diagnostic only. Shipping a factor would need a committed schedule source (including 2026), a `matchup` params block, an opponent input to `evaluate_player`, and its own gate, so it is a follow-up build if the diagnostic recommends it.

### Assumptions

- **Legacy prices.** Legacy anytime-TD prices are Yes prices (minimum 1.35, and AU books quote Yes only). Legacy O/U prices belong to an unknown side.
- **Sleeper `player_id` is stable across seasons.** A player who changed teams keeps their 2025 games in the 2026 window. This is accepted, and the far-line rule and market anchoring limit the damage.
- **DNP is a void.** If a player doesn't play in the target week, the bet is voided and refunded. Those cases are excluded from grading.

---

# Part B. Technical design

## B0. Overview

A new pure module, `model_v2.py`, holds every v2 calculation: window mean, dispersion, distributions, market probability, anchoring, edge, flag decision, far-line rule and anytime TD. It has no DB access. That makes it unit-testable, and it lets the live path and the harness share one implementation.

`test_thresholds.py` gains three things: one leak-free cross-season history query, a dispatch on `MODEL_VERSION`, and `evaluate_week()`. The v1 code stays in place.

Fitted numbers live in `model_v2_params.json`: the window, mean-bias factors, CV parameters, the distribution per stat, k per stat and the TD prior. Only `backtest.py --write-params` writes that file. Policy numbers (edge margin, minimum games to flag) live in `pipeline_config.py`.

`backtest.py` copies the DB to `$env:TEMP` and points every engine at the copy through a new `NFL_STATS_DB` env var. It builds the proxy and real-odds case sets, then selects and fits the O/U model on 2025 wk4-13 only (TD k and overround on wk14-15, tested on wk16). Finally it grades v1, v2 and the baselines on held-out data.

Live code finds the parameters at `NFL_MODEL_V2_PARAMS` (default: `model_v2_params.json` next to `test_thresholds.py`), so the served-page check can point v2 at the harness's `params_test.json` without writing the repo file.

The API returns every evaluated market with a `flagged` boolean and the probability breakdown. `index.html` shows flagged cards first, sorted by edge, and puts unflagged rows behind a toggle.

**Technology stack (locked):**

- Python 3 from the project `.venv`
- stdlib `math`, `statistics`, `sqlite3`, `json`, `logging`, `hashlib`, `random`, `unittest`
- the existing SQLAlchemy, pandas, numpy and FastAPI/uvicorn
- vanilla JS in `index.html`
- Node 24 for the DOM check
- headless Microsoft Edge for the screenshot

No new packages.

## B1. Files

| File | Change |
|---|---|
| `model_v2.py` | **New.** Pure functions (B2-B9), `load_params()`, `ParamsError`. |
| `model_v2_params.json` | **New.** Written only by `backtest.py --write-params`, after the gate passes. |
| `backtest.py` | **New** harness (B10). It ports the logic of `%TEMP%\nflmath\backtest.py` (proxy construction) and `boot.py` (cluster bootstrap) and doesn't import them. Those scripts stay untouched. |
| `tests/__init__.py`, `tests/test_model_v2.py` | **New** unittest suite (B12). |
| `tests/check_picks_dom.js` | **New** Node DOM check of the served page (B12). |
| `pipeline_config.py` | Add `MODEL_VERSION = 'v1'` (switched in a later commit, FR10), `V2_EDGE_MARGIN = 0.03` and `V2_MIN_GAMES_FOR_FLAG = 3`. |
| `probability_calc.py` | Bug #9: the bare `except` at line 58 becomes `except Exception: logger.exception(...); return None`. The `None`-input guard at lines 7-8 returns `None` instead of 50/50. `add_probability_to_flagged` sets `None` and has no callers. Nothing else changes, so v1 stays frozen. |
| `Odds_vs_Stats_Check.py` | v1 only. When `calculate_probability` returns `None`, the row is skipped and counted, through an optional `errors: list` argument. A new `include_unflagged=False` argument lets the harness get v1 probabilities for every line. Unflagged rows get `threshold_rule = "No Bet"`. |
| `test_thresholds.py` | `DB_PATH` honors `NFL_STATS_DB`. `MODEL_V2_PARAMS_PATH` honors `NFL_MODEL_V2_PARAMS`. `read_config_from_file` applies the `NFL_MODEL_VERSION` override after `exec`. New: `get_played_history()`, the count-market tweak in `drop_outlier_lines` (plus `print` → `logger.info`), `evaluate_week()`, `get_picks_with_model()`, `get_model_info()`, and the v2 dispatch in the CLI. `get_flagged_players_json_updated()` becomes a wrapper over `get_picks_with_model()`. |
| `target_share_calc.py` | `DB_PATH` honors `NFL_STATS_DB`, so the v1 path in the harness doesn't read the real DB. |
| `app.py` | The engine at line 32 honors `NFL_STATS_DB`. `/generate-picks` calls `get_picks_with_model()`, adds the `model` object, and returns `success: false` when v2 parameters are invalid. |
| `index.html` | v2 rendering, labels, edge sort, flagged-first ordering, unflagged toggle, "±0%" fix (B11). |

`NFL_STATS_DB` default: in every file it falls back to today's relative `nfl_stats.db`, so normal use is unchanged. `models.py` isn't imported by v2, the harness or `app.py`, so its `create_all` and migrations never run against either DB from this work.

## B2. Mean and history window (FR1)

`test_thresholds.get_played_history(conn, player_id, season, week, max_games=17)` returns a list of dicts, most recent first:

```sql
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
```

This is the only history query v2 uses, live or in the harness. It owns the leak-free invariant: within the target season only weeks before the target count, and earlier seasons are allowed. The harness re-asserts the invariant for every case (A4 #11). The query reuses the existing `PLAYED_FILTER`. NULL stat values are read as 0.

`model_v2.window_mean(values, window)`:

- `{"type": "last_n", "n": N}`: arithmetic mean of the first N values. n_eff is the number of values used.
- `{"type": "ewma", "half_life": h, "max_games": 17}`: weights w_j = 0.5^(j/h), with j = 0 for the most recent game. μ = Σ w_j x_j / Σ w_j and n_eff = (Σ w_j)² / Σ w_j².
- No values: returns `None`. The market is skipped and logged at DEBUG ("no played history").

**Mean-bias factor.** μ_used = c_k · μ, where c_k = Σ y_i / Σ μ̂_i over the fit cases, clamped to [0.8, 1.2]. It is a single unbiasedness correction per stat, fitted on thousands of cases, so it isn't a selection step. It corrects systematic regression to the mean in a short window. The `empirical_ratio` distribution already includes this bias in its ratios, so it uses c_k = 1. The fitted c_k values are reported. A value at a clamp bound is reported as a red flag.

**Candidate windows,** chosen in B10.3 step 2: last N ∈ {3, 4, 6, 8, 10, 17} and EWMA h ∈ {2, 3, 4, 6, 8}.

- The selection score is the unweighted mean of the five per-stat mean log losses on fold B (each stat counts equally, whatever its case count).
- The window is the candidate with the lowest fold-B selection score. Candidates within 0.001 of the best score are tied, and the tie goes to the candidate with the largest mean n_eff on fold B (the longest window). No candidate is privileged.
- Last 6 stays in the candidate list. The report prints every candidate's score.
- The window is global, one for all stats. Per-stat windows multiply the selection degrees of freedom for little expected gain.

If μ ≤ 0 for a stat, the market is skipped (DEBUG). Examples are a receiver with 0 rushing yards, or a QB with net negative rushing. This matches v1's "all zeros → skip" at `Odds_vs_Stats_Check.py:69-72`.

## B3. Dispersion: one rule (FR2, fixes bug #8)

CV_k(n_eff)² = a_k + b_k / n_eff, and σ = CV_k(n_eff) · μ_used.

**Why this form.** The variance of an outcome around an estimated mean is the game-to-game variance plus the error in the estimated mean, and with iid games the second term is σ²/n. The 1/n term therefore widens the distribution for small samples and keeps every n on one formula. The rule doesn't depend on the sample SD s, so [6,6,6] and [6,6,7] differ only through μ, which removes the inversion.

The widening is mean-preserving. For the symmetric normal family it always moves P toward 0.5. For the skewed families (log-normal, negbin) a wider distribution has a lower median, so when the line is above μ, P(Over) can move slightly **away** from 0.5 as n falls. That is correct under the model, and the tests assert only what holds (A4 #7). The one-game Jacobs case is fixed mainly by the cross-season window (6 games, μ 52.8 instead of one 2026 game), not by the widening.

**Fit** (in `backtest.py`, on fit data only). For each fit case i, with prediction μ̂_i > 0 (after c_k) and actual y_i:

1. Regress r_i = ((y_i − μ̂_i)/μ̂_i)² on [1, 1/n_eff,i] by weighted least squares, with weights μ̂_i². This weighting is equivalent to a ratio-of-sums CV, the same estimator as the review's pooled CV.
2. If the fitted b_k < a_k, set b_k = a_k and refit a_k with b fixed to a. This is the iid floor: small n must widen by at least the theoretical amount.
3. If a_k ≤ 0, or the stat has fewer than 50 fit cases, the fit is fatal. The harness exits with code 5 and names the stat.

**Expected magnitude.** The review's pooled CVs at n = 6 were pass yds 0.39, receptions 0.65, pass TD 0.83, rec yds 0.86 and rush yds 1.00. The fitted CV_k(6) should land near these. A gap above 0.15 is reported as a red flag.

**Optional own-SD blend** (candidate in B10.3 step 4): σ² = (1 − w)·CV_k(n_eff)²μ² + w·s_own². Here w = n/(n + 10), and s_own is the sample SD (ddof = 1) of the last up-to-17 played games. The blend applies only when n ≥ 6. It is adopted for a stat only if fold-B log loss improves by ≥ 0.002. Otherwise it is off, which is the expected outcome.

## B4. Distributions (FR3)

Every function returns P(Over) = P(X ≥ ⌈L⌉) for a half-point line L > 0.

| Name | Applies to | P(Over) |
|---|---|---|
| `lognormal` | yards | s² = ln(1 + CV²), m = ln μ − s²/2, P = 1 − Φ((ln L − m)/s). Yards are integers and L is a half-point, so P(X > L) = P(X ≥ ⌈L⌉). |
| `empirical_ratio` | yards | Pooled ratios R_k = {y_i/μ̂_i} from the fit set. P = (#{r ∈ R_k : r·μ > L} + 0.5)/(\|R_k\| + 1). It ignores n_eff and is a candidate because skew may not be log-normal. The ratio list is stored in the params file: at most 2,000 values per stat, evenly sub-sampled by quantile. |
| `normal` | yards, counts | P = 1 − Φ((L − μ)/(CV·μ)). Baseline candidate only. |
| `negbin` | counts | Var = CV²μ². If Var ≤ μ (under-dispersed), use Poisson(μ). Otherwise r = μ²/(Var − μ), p = r/(r + μ) and P = 1 − Σ_{j<⌈L⌉} pmf(j), with the pmf computed through `lgamma`. |
| `poisson` | counts | P = 1 − Σ_{j<⌈L⌉} e^(−μ) μ^j / j!. Ignores the CV fit. |

Candidates per stat:

- Yards (`passing_yards`, `receiving_yards`, `rushing_yards`): lognormal, empirical_ratio, normal.
- Counts (`receptions`, `passing_tds`): negbin, poisson, normal.

The distribution for each stat is chosen by fold-B log loss (B10.3 step 3). Brier breaks ties within 0.0005.

P(Under) = 1 − P(Over), because there are no integer lines (A1). If an integer line ever appears, `model_v2` returns `None` for that row with reason "integer line not supported" (INFO). Such a line is never silently mispriced.

Input guards: L must be finite and > 0, and μ must be > 0. Otherwise the result is `None`, with a DEBUG log line.

## B5. Market probability, anchoring and edge (FR4, FR5)

**Price validation** happens at the trust boundary, where DB rows enter `model_v2`.

- A price must be a float with 1.01 ≤ price ≤ 1000. Anything else (NULL, ≤ 1.0, non-numeric) is treated as missing, with a WARNING once per (player, market, bookmaker).
- An outcome must be `Over`, `Under`, `Yes`, `No` or NULL. Other values are ignored, with a WARNING.
- For O/U markets, a NULL outcome (`prices["unknown"]` from `collapse_odds`) means the side is unknown.
- For `player_anytime_td`, a NULL outcome means Yes (A5 assumption).

**Collapse.** `test_thresholds.collapse_odds` already builds one entry per (market, bookmaker, line) with a `prices` dict. `model_v2.group_lines(entries)` groups those entries by (market, line) and records:

- `books_both`: the books that priced both sides (Over and Under, or Yes and No) at this line.
- `valid[side]`: the list of (book, price) pairs with a valid price for that side.
- `best[side]`: for each side with at least one valid price, the highest decimal price and the list of books offering it.
- `unknown_books`: the books whose only price at this line is `"unknown"`.

**`"unknown"` prices never enter P_mkt or `best`.** They are kept in `prices` for display only. (`collapse_odds` already ignores a book's `unknown` rows when that same book has outcome rows for the market. This rule covers another book's legacy row at the same line.) A line whose only prices are `"unknown"` is `"none"`.

**P_mkt, by coverage** (`marketSource`):

1. `"no-vig"`: `books_both` is non-empty. For each such book, q_o = 1/d_o, q_u = 1/d_u and p_book = q_o/(q_o + q_u). P_mkt_over is the median of p_book across `books_both`. The median resists a single book's alt pricing. Anytime TD lands here when both Yes and No are priced by a book (possible after a re-fetch).
   - 1b. `"no-vig (cross-book)"`: `books_both` is empty, but both sides have at least one valid price, from different books. q_o = median over `valid[Over]` of 1/d, q_u = median over `valid[Under]` of 1/d, and P_mkt_over = q_o/(q_o + q_u).
2. `"one-sided (de-vigged)"`: exactly one side has a valid price at this line, from any number of books. P_mkt(side) = median over those books of (1/d) ÷ o_family, clamped to [0.001, 0.999], and P_mkt(other side) = 1 − P_mkt(side). The overround factor o comes from the params file:
   - `o_td` for `player_anytime_td`, fitted in B10.3 step 7. On today's data every TD row lands here, priced on Yes.
   - `o_ou` for the five O/U markets: the median over all `books_both` rows in the fit data of (1/d_o + 1/d_u). There are no such rows in today's data, so it falls back to 1.064 (review S5: both sides at the median price 1.88).

   Raw 1/d includes the book's margin and overstates the priced side. Because P_final rises with P_mkt, a raw anchor would **raise** the edge on that side. Dividing by o removes that bias. The row carries `marketSource = "one-sided (de-vigged)"` and `overround = o`, and the page shows them as, for example, "16.0% (one-sided, de-vigged ÷1.25)". A one-sided O/U line is the typical shape of an alt or milestone listing, and its de-vigged price says far more than 0.5 would. A 50% prior would also be wrong for TD, whose typical prices of 5.0-21.0 imply 20% to 5%.
3. `"none"`: no valid side price. This covers every legacy O/U row. P_mkt_over = 0.5, and the page shows "no price (50% assumed)". The 0.5 fallback is justified because stored main lines went Over 50.0% of the time in 2025 wk14-16 (review, section 3). These rows can never flag (`decide_flag` rule 2).

**Anchoring:** P_final = P_mkt + k_k · (P_model − P_mkt), with k_k from the params file (0 ≤ k ≤ 0.25). This is a convex combination, so P_final lies in [0, 1] and P_final_over + P_final_under = 1.

**Edge** for each side with a known best price d: edge = P_final(side) − 1/d.

- `side`: the priced side with the larger edge when at least one side has a price. Otherwise, the side with the larger P_final.
- `edgePts` = round(100·edge, 1), or `null` when the side has no price.
- The edge is measured against the **best** price, while P_mkt uses the **median** book. So the edge includes any gap between the best and the median book (line shopping). That gain is real only if the user can bet at the best book, and the page names that book.
- `edgeSource`: `"price only"` when the row's k (k_k for its O/U stat, k_TD for anytime TD) is 0, otherwise `"model + price"`. With k = 0 the edge is P_mkt − 1/d_best, so any flag comes purely from one book's price being better than the median book's no-vig probability. That can be a real edge, but it isn't a model pick, and the page labels it as such (B11). `decide_flag` treats both sources the same: the user asked for real edges after vig, and line shopping against a de-vigged consensus is one. On today's legacy O/U data a k = 0 row can't flag (`marketSource = "none"`); this matters once Over/Under prices are re-fetched.

**Flag decision.** `model_v2.decide_flag` is the single owner of the "never flag without a known side price" invariant, so the frontend can't get it wrong. It runs these checks in order, and the first one that fails becomes `noFlagReason`:

1. Model error: `"model error"`.
2. No valid price for the chosen side, **or** `marketSource == "none"`: `"no price"`. **This applies to every current legacy O/U row, so live O/U flags will be zero until odds are re-fetched. Only anytime TD can flag on today's data.**
3. Games used < `V2_MIN_GAMES_FOR_FLAG` (3): `"fewer than 3 games"`. The 1/n widening already handles the probability. This rule stops flags that would rest on a CV fit extrapolated below the fit data, which has n ≥ 3. It doesn't apply to anytime TD, whose prior shrinkage covers small n (B6). The report states how many flags it removed.
4. Far-line exclusion (B9): `"line far from player mean"`.
5. edge ≤ `V2_EDGE_MARGIN`: `"edge below 3.0 pts"`.
6. Otherwise `flagged = true`.

**Margin.** The margin is 3.0 points, fixed for the gate, and **is not tuned on the test set.** The harness reports flags, hit rate and ROI at margins of 2, 3 and 5 as a labelled sensitivity diagnostic. The margin changes only after weeks with real Over/Under prices have been graded.

**Worked examples.**

- Harness assumed-price mode (legacy row, P_mkt = 0.5, price 1.88, B10.4). Flagging needs 0.5 + k(P_model − 0.5) − 0.532 > 0.03. At k = 0.25 that means P_model > 0.748. Few flags are expected. With the O/U fallback k = 0 no O/U row can flag at all (0.5 − 0.532 < 0).
- Anytime TD, one book Yes at 5.0, o_td = 1.25, k_td = 0.25, P_model = 0.20: P_mkt = 0.20/1.25 = 0.16, P_final = 0.16 + 0.25·0.04 = 0.17, edge = 0.17 − 0.20 = −0.03. Not flagged. With the raw 1/d anchor the edge would have been 0.00, three points higher.
- For a TD Yes flag at k_td = 0.25 and one book at price d, the edge is 0.75·(1/d)/o + 0.25·P_model − 1/d > 0.03. With o = 1.25 this needs P_model > 1.6·(1/d) + 0.12. At 5.0 that is P_model > 0.44, more than double the market. TD flags will be rare, as they should be.

## B6. Anytime TD (FR6)

The outcome per game is t = rushing_tds + receiving_tds. Passing TDs don't count.

λ = (Σ_window t + n0·λ0_pos) / (n + n0), using the same window as B2. For EWMA, the weighted sum and n_eff replace Σ and n.

- λ0_pos is the pooled mean of t per played game in the fit data for the player's position: QB, RB, WR or TE. Any other position uses the pooled all-position value.
- n0 ∈ {0, 1, 2, 4, 8} is chosen by fold-B log loss.

λ is clamped to ≥ 1e-6, so a zero-TD history with n0 = 0 never gives P = 0 exactly. P_model(Yes) = 1 − e^(−λ). The prior shrinkage is the Gamma-Poisson posterior mean. It keeps a player with one game and one TD from getting 63%, and it serves as this market's small-n rule.

The player's position comes from the most recent history row. Anchoring and edge follow B5, against the best Yes price. The far-line rule doesn't apply, because there is no line.

Grading: a case counts as a TD when t ≥ 1 in the target week. It is void when gp is 0 or the row is missing.

## B7. Model output contract

`model_v2.evaluate_player(player_name, history, odds_entries, params, policy) -> (rows, counters)`.

- `history` is the output of `get_played_history`.
- `odds_entries` is the output of `drop_outlier_lines(collapse_odds(...))`.
- `policy` is {margin, min_games}.

It returns one row per (market, line) for the five O/U stats and `player_anytime_td`:

| Field | Meaning |
|---|---|
| `model_version` | `"v2"` |
| `player_name`, `stat`, `market`, `line` (null for TD) | |
| `player_value` | μ_used, 1 decimal |
| `gamesUsed` | Number of played games in the window |
| `side` / `threshold_rule` | `Over`, `Under` or `Yes`. `threshold_rule` is kept for the existing chip and sort code. |
| `probModelOver`, `probMarketOver`, `probFinalOver` | %, 1 decimal. `probMarketOver` is null when `marketSource = "none"`. |
| `probModel`, `probMarket`, `probFinal` | The same, for `side` |
| `probabilityOver`, `probabilityUnder` | Final probabilities, kept so old consumers still work |
| `marketSource` | `"no-vig"`, `"no-vig (cross-book)"`, `"one-sided (de-vigged)"` or `"none"` |
| `overround` | o used for a one-sided anchor, else null |
| `price`, `bookmaker`, `bookmakers` | Best price for `side`, the first book at that price, all books at that price |
| `impliedProb` | 100/price, or null |
| `edgePts` | Points, or null |
| `edgeSource` | `"price only"` when the row's k is 0, else `"model + price"` (B5) |
| `flagged`, `noFlagReason` | |
| `prices` | All books' prices at this line: {book: {outcome: price}} |
| `adjustmentDetails`, `adjusted<Stat>` | Display only. Filled by the existing `apply_adjustments_to_flagged`, applied to all v2 rows. |

**Anytime TD row:** `stat = "anytime_td"`, `market = "player_anytime_td"`, `line = null`, `side = threshold_rule = "Yes"`, `player_value` = λ (2 decimals), `gamesUsed` = games in the window. `probModelOver`, `probMarketOver` and `probFinalOver` hold P(Yes). Far-line fields don't apply. The card title is "ANYTIME TD" and the average column header for this row is "TD rate (λ/game)".

`counters` holds `markets_evaluated`, `skipped_no_history`, `skipped_mu_le_0`, `model_errors`, `unsupported_line`, `no_price` and `excluded_far_line`.

## B8. Live integration

**`test_thresholds.py`**

- `DB_PATH = "sqlite:///" + os.getenv("NFL_STATS_DB", "nfl_stats.db")`. The same pattern goes into `target_share_calc.py` and the `app.py` engine.
- `MODEL_V2_PARAMS_PATH = os.getenv("NFL_MODEL_V2_PARAMS", str(Path(__file__).resolve().parent / "model_v2_params.json"))`. A missing file raises `ParamsError("not found: <path>")`.
- `read_config_from_file()` keeps its `exec` and then, if `NFL_MODEL_VERSION` is set, overrides `config["MODEL_VERSION"]` with it. Validation of both values happens in `evaluate_week` (B14).
- `evaluate_week(season, week, model_version, config, params=None, adjustments=True)`:
  - **Before the player loop, outside any per-player `try`:** validate `model_version` and the policy values (B14). For v2, call `model_v2.load_params(MODEL_V2_PARAMS_PATH)` unless `params` is passed in (the harness passes its in-memory test parameters). `ParamsError` and `ValueError` propagate to the caller, so a bad file can never be swallowed by the per-player `except Exception: continue` and turn into `success: true` with no players.
  - It then loops over `resolve_player_ids`:
  - **Both versions** skip names in `INCOMPLETE_DATA_PLAYERS`, as v1 does today (`test_thresholds.py:374`).
  - **v1** runs today's code: `get_recent_3_game_stats_by_id` → its `has_meaningful_stats` skip → `check_stat_against_odds(include_unflagged=...)`.
  - **v2** runs `get_played_history` → `drop_outlier_lines(collapse_odds(get_odds_for_player(name, season, week)))` → `model_v2.evaluate_player`. v2 drops the `has_meaningful_stats` skip: the per-market μ ≤ 0 skip (B2) covers the same all-zero case, market by market. Odds matching stays the live `get_odds_for_player` name-variant lookup (periods, Jr., Sr.).
  - **Both**, when `adjustments=True`, then call `compute_adjustments` (display only) and `apply_adjustments_to_flagged`. For v2, `compute_adjustments` receives `{"avg": {stat: μ_used}}`, so "Adjusted" = μ × factor. The harness passes `adjustments=False`.
  - It returns `(players, summary)`. `summary` holds the counters from B7 summed over players, plus `summary["model"] = get_model_info(config, params)`, so the params load once per call and the model info comes from the same params the rows used.
- `get_picks_with_model() -> (players, model)`: **new**. It reads the config (with the `NFL_MODEL_VERSION` override), takes season and week from it (`SEASON`, `COMPARISON_WEEK`), calls `evaluate_week(...)` and returns `(players, summary["model"])`. For v2, `players` holds **all** rows, flagged or not, grouped as today ({player, matchup, stats}). For v1 it holds flagged rows only, as today.
- `get_flagged_players_json_updated()` keeps its signature and becomes a wrapper: `return get_picks_with_model()[0]`. Existing callers are unchanged.
- `get_model_info(config, params)`:
  - v1 (params is `None`): returns `{"version": "v1"}` and nothing else.
  - v2: returns {version: "v2", window_label (e.g. "last 6 played" or "weighted, half-life 4 games"), window_n (N for last N; `null` for EWMA), edge_margin_pts, min_games_for_flag, params_fitted_on, gate_label (from params, e.g. "passed" or "passed, O/U fallback k = 0"), ou_k_all_zero (bool: k_k = 0 for all five O/U stats), td_k_zero (bool)}.
- CLI `__main__` (v2) prints `Player, Stat, Line, Side, Avg(last N), Model%, Market%, Final%, Price, Edge, Flagged/Reason`. `--json` prints the same JSON as the API. Logs go to stderr, so `--json` output stays valid.

**`app.py` `/generate-picks`**

- Imports `get_picks_with_model` instead of `get_flagged_players_json_updated` (`app.py:424-425`), calls `players, model = get_picks_with_model()`, and returns `{"success": true, "players": players, "count": len(players), "model": model}`. There is no second config exec or params load in `app.py`.
- It catches `model_v2.ParamsError` **explicitly**, before the existing generic `except Exception`. When `load_params` raises it (file missing, invalid or out of range), the endpoint returns `{"success": false, "error": "Model v2 parameters invalid: <reason>. Run backtest.py --write-params or set MODEL_VERSION='v1'."}` and logs at ERROR.
- An unknown `MODEL_VERSION` gives `success: false` with the error `"MODEL_VERSION must be 'v1' or 'v2'"` (ERROR).

**`model_v2.load_params(path)`** validates:

- `version == 2`.
- `window` has one of the two shapes, with integer N in [1, 17] or h in [1, 17].
- For each of the five stats:
  - 0.8 ≤ c ≤ 1.2
  - a > 0 and b ≥ a
  - `dist` is in the allowed set for the stat type
  - 0 ≤ k ≤ 0.25
  - an `empirical_ratio` list is present when that dist is chosen
- For TD: n0 ≥ 0, λ0 per position in (0, 2), 0 ≤ k_td ≤ 0.25, and 1.0 ≤ o_td ≤ 1.6.
- `o_ou` (the O/U overround) in [1.0, 1.6].
- `fitted_on` and `gate_label` are non-empty strings.

The file is read once per request. This is cheap and consistent with `read_config_from_file` re-reading the config on every request.

## B9. Outlier rules (FR8)

**Far-line exclusion** (v2 only, inside `model_v2`). It applies to every O/U line, single-book or multi-book. For each line L, with dev = |L − μ_used|/μ_used and gap = |L − μ_used|, the line is excluded from flagging when:

- Yards markets: dev > 0.60 **and** gap ≥ 10 yards.
- Count markets: dev > 0.60 **and** gap ≥ 2.0.

The purpose is to stop flags in either of two situations. One is an alt or stale line. The other is a change the model can't see, such as a backup becoming the starter. In both, a large model "edge" against the line is spurious. The excluded row is still returned, with its probabilities and `noFlagReason`. Each exclusion is logged at INFO: `Excluded far line: <player> <market> <line> (<n_books> books) vs mean <μ> over <n> games (wk <w> <season>)`.

Evidence for the rule (revision 1's read-only measurement, last-6 played mean, c = 1, all stored weeks). The counts are **player-markets**, and each value shown is the **median line across books** against the mean. The rule itself is applied per line, so the number of excluded lines can differ from the number of excluded player-markets (for example, Ferguson's books quote 17.5, 19.5, 20.5 and 20.5, median 20.0; Tremayne's 2026 wk8 books quote 2.5 and 5.5, median 4.0). This list is a reference only. A4 #10 asserts the list computed with the selected window and c.

- **Single-book,** 89 player-markets, 6 excluded:
  - Dissly rec yds 0.5 vs 10.8
  - Singletary rec yds 5.5 vs 16.5
  - I. Williams rec yds 28.5 vs 13.8
  - Estime rush 30.5 vs 5.5
  - Hull rush 25.5 vs 10.3
  - Hooper rec yds 5.5 vs 16.2
- **Multi-book,** 390 player-markets, 10 excluded:
  - Gardner Minshew pass yds 213.5 vs 7.3 (a backup starting; his window holds 3 relief appearances)
  - Tank Bigsby rush 6.5 vs 27.3
  - Thielen rec yds 15.5 vs 4.3
  - Ferguson 20.0 vs 6.3
  - DJ Moore 49.5 vs 27.3
  - Dike 30.5 vs 18.7
  - Tipton 24.5 vs 7.8
  - D. Douglas 15.5 vs 40.0
  - 2026 wk8: M. Evans 5.5 vs 17.5 and Tremayne 4.0 vs 19.2
- **Why the absolute floors are needed:** without them, the 60% rule would also exclude normal low-volume lines, such as Singletary receptions 0.5 vs 1.7, Vidal receptions 0.5 vs 1.5, and many 0.5-1.5 reception lines for players averaging under 1.
- **Parker Washington:** with the honest window his mean is 48.8, so dev is 0.58 and the line is **not** excluded. His 20.5 at 1.88 has a two-way-looking price, and he has had 16-, 20-, 26- and 29-yard games this season. On today's data the line can't flag live anyway, because its side is unknown. In the harness's assumed-price mode it may flag, and the report lists it.

**Multi-book drop tweak** (shared, so it affects v1 and v2). In `drop_outlier_lines`, markets in `COUNT_MARKETS = {"player_receptions", "player_pass_tds", "player_rush_attempts"}` drop a line only when rel > 0.25 **and** |L − median| > 1.0 (strictly greater). Yards markets keep the 25% rule. The existing stderr `print` becomes `logger.info` with the same text.

```python
if market in COUNT_MARKETS:
    drop = rel > OUTLIER_MAX_DEVIATION and abs(e["line"] - median) > 1.0
else:
    drop = rel > OUTLIER_MAX_DEVIATION
```

Under this rule Cooper Kupp receptions 3.5 vs 2.5 (gap 1.0), Dallas Goedert receptions 4.5 vs 3.5 (gap 1.0) and Matthew Stafford rush attempts 1.5/0.5 (gap 0.5) are all kept on the 2025 wk16 data.

The harness lists every drop and exclusion for 2025 wk14-16 and 2026 wk8 (A4 #10).

## B10. Validation protocol: `backtest.py`

### B10.1 Safety and setup

0. `REPO = Path(__file__).resolve().parent`, then `os.chdir(REPO)`. `read_config_from_file()` opens the relative `'pipeline_config.py'`, and the `NFL_STATS_DB` default is relative, so the harness must not depend on the caller's working directory. All repo paths below are built from `REPO`.
1. Resolve `OUT = $env:TEMP\nfl_backtest\<YYYYMMDD-HHMMSS>\` and create it.
2. Record the SHA256 of the repo's `nfl_stats.db`.
3. Copy the DB with the sqlite3 backup API from a `mode=ro` URI connection. This is safe while the user's server on port 8000 holds the file. A failed copy is fatal (exit 2).
4. Set `os.environ["NFL_STATS_DB"]` to the copy **before** importing `test_thresholds` or `target_share_calc`.
   Also before those imports, set `NFL_SEASON=2025` and `NFL_WEEK=14`. These fixed values exist only so that `pipeline_config` never calls Sleeper. No harness computation reads `SEASON`, `CURRENT_WEEK` or `COMPARISON_WEEK` from the config: the harness passes season and week explicitly to every call, and the production target comes from `--production-target` (B10.7). The harness is offline and deterministic.
5. After the imports, run the path guard on `test_thresholds.engine.url.database` and `target_share_calc.engine.url.database`:
   ```python
   norm = lambda p: os.path.normcase(os.path.realpath(p))
   temp, repo_db = norm(os.environ["TEMP"]), norm(REPO / "nfl_stats.db")
   for p in map(norm, dbs):
       if os.path.commonpath([p, temp]) != temp or p == repo_db: exit(3)
   ```
   The harness calls `evaluate_week(..., adjustments=False)`, so `compute_adjustments`, `team_stats` and `weather_api` aren't exercised. (They would be harmless: they use only the `test_thresholds` engine and `team_stats_data.json`, and `weather_api` makes no network call.)
6. At the end, re-hash the repo DB. A mismatch exits 4 with a loud message.

CLI: `python backtest.py [--out DIR] [--seed 20261030] [--matchup-experiment SCHEDULE_JSON] [--write-params --production-target SEASON-WEEK]`, for example `python backtest.py --write-params --production-target 2026-8`.

- The exit code is 0 only if every step ran.
- The gate result is printed and written to the report. It isn't encoded in the exit code, because a failed gate is a valid outcome to report.
- `--write-params` refuses to write, with exit 6, when a blocking gate criterion failed.
- `--production-target` is required with `--write-params` and ignored without it. Validation, all exit 6 with the message shown, before any fitting starts:
  - missing: `"--production-target SEASON-WEEK required"`
  - not of the form `<int>-<int>`, season not 2026, or week outside [2, 18]: `"invalid --production-target <value>"`
  - the DB copy lacks regular-season `player_weekly_stats` rows for any 2026 week in [1, target − 1]: `"no 2026 stats for week <w>"`, naming the first missing week.

### B10.2 Case sets

Every grading case requires the target-week row to have gp > 0 (otherwise it is void). Duplicate-name players are excluded through `resolve_player_ids`.

| Set | Weeks | Line | Purpose |
|---|---|---|---|
| **Proxy fold A** | 2025 wk4-9 | floor(mean of prior 2025 played games) + 0.5. Needs ≥ 3 prior played games and a prior mean ≥ MINS: rec yds 25, rush yds 25, pass yds 150, receptions 2.0, pass TD 0.8 (the review's `backtest.py:216`) | Fit c, CV, ratios, λ0 |
| **Proxy fold B** | 2025 wk10-13 | same | Select window, distribution, blend and n0. Fit stand-in k |
| **Fit set (final)** | 2025 wk4-13 | same | Refit c, CV, ratios and λ0 with the chosen configuration → test parameters |
| **Real test, O/U** | 2025 wk14-16 | stored odds | **Held-out gate** (G1-G3) |
| **TD market fit** | 2025 wk14-15 | stored anytime-TD odds | Fit k_TD and o_TD (B10.3 step 7) |
| **Real test, TD** | 2025 wk16 | stored anytime-TD odds | G4 |
| **Proxy hold-out** | 2025 wk14-17 | proxy | Extra out-of-sample check (G3) |
| **2026 proxy** | 2026 wk2-7 | floor(mean of the last up-to-17 played games before the target, crossing into 2025) + 0.5. Needs ≥ 3 such games and a mean ≥ MINS | G5 |

The review's ~4,500 proxy cases covered 2025 wk4-17. **This design fits only on wk4-13** before the gate, because the wk14-16 proxy outcomes are the same games as the real test, and fitting on them would leak. The production refit (B10.7) uses wk4-17 once the gate has been evaluated.

The 2026 proxy line uses the cross-season mean so that wk2-7 can be covered, as the brief asks. The report states the realised case counts per week.

Fit and test ranges are declared once per market family and asserted per family (A4 #11):

```python
FIT_TEST = {
    "ou": {"fit": [(2025, w) for w in range(4, 14)],
           "test": [(2025, 14), (2025, 15), (2025, 16)]},
    "td": {"fit_lambda": [(2025, w) for w in range(4, 14)],
           "fit_k_overround": [(2025, 14), (2025, 15)],
           "test": [(2025, 16)]},
}
# per family: max(all fit weeks) < min(test weeks), and no (season, week) in both
```

The 2025 wk14-17 proxy hold-out and the 2026 proxy are evaluation-only sets and are never used for fitting before the gate. The O/U and TD families share 2025 wk14-15 only in the sense that O/U is tested there and TD is fitted there. Those are different markets with different parameters, so there is no leak.

TD proxy: all QB, RB, WR and TE player-weeks in the same week ranges with ≥ 3 prior played games. The outcome is t ≥ 1, and there is no line.

### B10.3 Selection and fitting steps (2025 wk ≤ 13, except TD step 7)

All log losses here use the scoring clip from B10.4.

1. Build the fold A and fold B cases with full histories (up to 17 games) through `get_played_history`.
2. **Window.** For each candidate window, fit (c_k, a_k, b_k) on fold A with the default distribution (lognormal for yards, negbin for counts). Score the unweighted mean of the five per-stat mean log losses on fold B. The window is the candidate with the lowest fold-B selection score. Candidates within 0.001 of the best score are tied, and the tie goes to the candidate with the largest mean n_eff on fold B (the longest window). No candidate is privileged. The report prints every candidate's score.
3. **Distribution** per stat, given the window: fit on A, score on B, choose by log loss.
4. **Own-SD blend** per stat: adopted only if fold-B log loss improves by ≥ 0.002.
5. **TD n0:** fit λ0 on A, then choose n0 on B by log loss.
6. **Stand-in k per stat** (fold B). The proxy has no market, so the harness builds a stand-in: P_mkt_proxy = P(Over) under the chosen distribution for the stat, with μ = μ_season·c_k and σ from CV_k(n_season), using the fold-A (c_k, a_k, b_k). μ_season is the player's mean over all prior played games in the same history the proxy line was built from, and n_season is their count. For `empirical_ratio` it uses the fold-A ratios with c = 1, as in B2. Then k_k = argmin over k ∈ {0, 0.01, …, 1} of Brier(P_mkt_proxy + k(P_model − P_mkt_proxy)).
   - A stat with fewer than 300 fold-B cases uses the global k (all stats pooled).
   - Cap: k_k = min(k_k, 0.25).
   - Bookmakers know more than a season mean (line MAE 32.9 vs 35.4 for the 3-game mean in the review), so the stand-in k is **heuristically** expected to be at or above the real k. This is not proven: the stand-in anchor is not the 0.5 anchor used on the real test. The pre-registered k = 0 fallback (A4 #1) covers the case where it is too high.
   - The report gives the fold-B Brier of P_mkt_proxy alone, of 0.5, and of the blend at the chosen k, plus the fold-B Brier curve over k ∈ {0, 0.05, …, 0.25}, so a reader can see how strong the stand-in anchor was.
7. **k_TD and o_TD** (family `td`, fit weeks 2025 wk14-15). The TD proxy has no market, so both come from the **real** anytime-TD odds of 2025 wk14-15, all before the wk16 test. The cases are the `player_anytime_td` rows returned by `evaluate_week(2025, w, "v2", config, params=P, adjustments=False)` for w = 14, 15, so the odds-to-player matching is exactly the live `get_odds_for_player` name-variant matching (periods, Jr., Sr.). P is the step-8 refit (wk4-13) with k_TD = 0 and o_TD = 1.25; the harness computes the step-8 refit of c, CV, ratios and λ0 first, then runs this step, then writes the file. k_TD and o_TD in P affect only P_mkt and P_final, never P_model. The harness reads P_model(Yes) from `probModelOver` and recomputes the median Yes 1/d from the row's `prices`. The outcome comes from the target-week row of the matched `player_id`; void player-weeks (gp = 0 or no row) are dropped. The report gives the count of distinct `player_anytime_td` odds names in those weeks that no returned row matched, with up to 20 example names. Revision 2 measured 45 usable player-weeks and 7 TDs with a direct name match; the counts from the live matching are reported and may differ slightly.
   - **o_TD:** Σ median(1/d) ÷ Σ 1[t ≥ 1] over usable player-weeks, clamped to [1.00, 1.60]. If the fit weeks contain fewer than 20 observed TDs, the estimate is too noisy (a ratio over 7 events has a relative SE near 40%), so o_TD = 1.25 (WARNING, reported with the raw ratio). On today's data this fallback triggers. 1.25 was fixed by the review before any TD overround was measured, and it is above the measured 1.16-1.18, so it errs toward fewer Yes flags.
   - **k_TD:** argmin over k ∈ {0, 0.01, …, 1} of Brier(P_mkt + k(P_model − P_mkt)) with the de-vigged P_mkt = median(1/d) ÷ o_TD, then capped at 0.25. If there are fewer than 20 usable cases, k_TD = 0 (WARNING). The fit is noisy at this sample size, and the report says so. G4 decides whether it survives.
8. Refit c, CV, ratios and λ0 on the full fit set (wk4-13) with the chosen configuration. Set o_ou per B5 (1.064 on today's data, since no fit-week row has both sides). These are the **test parameters**, written to `OUT\params_test.json` (never to the repo), with `gate_label = "test parameters (pre-gate)"` and `fitted_on = "proxy 2025 wk4-13; TD k/o: 2025 wk14-15 odds"`, so `load_params` accepts the file for the served-page check. If the k = 0 fallback is triggered, the harness also writes `OUT\params_test_k0.json` (same file with k_k = 0 for the five O/U stats and `gate_label = "test parameters (O/U fallback k = 0)"`), and the served-page check uses whichever file matches the gate result.

### B10.4 Evaluation

On the real test set, each model is evaluated row by row at (player, week, stat, bookmaker, line), as in the review, so the v1 figure of 0.291 is comparable:

- **v1**: `compute_player_stats` + `calculate_probability` on every line, through `check_stat_against_odds(include_unflagged=True)` over today's `get_recent_3_game_stats_by_id`. Each returned row already carries one bookmaker.
- **v2**: `model_v2` with the test parameters. P_mkt = 0.5 for all legacy O/U rows (`marketSource = "none"`). **Per-bookmaker expansion:** each v2 (market, line) row is expanded into one graded row per bookmaker in its `prices` at that line (including `unknown` legacy prices, which are what the stored rows are). All expanded rows carry the same probabilities.
- **Baselines**: 50/50 for O/U. For TD, the de-vigged P_mkt (median 1/d ÷ o_TD); raw median 1/d is also reported.
- **v1 on proxy sets** (2025 wk14-17 proxy hold-out and 2026 proxy, which have synthetic lines and no odds rows): v1 is `check_stat_against_odds(name, get_recent_3_game_stats_by_id(season, pid, week), [{"market": MARKET[stat], "line": L, "bookmaker": "proxy", "prices": {}}], THRESHOLDS, include_unflagged=True)`. Cases it skips (no in-season game, all-zero window, `None` probability) are counted per week and excluded from the G5 comparison set.

**Row set.** G1, G2 and the v1-vs-v2 calibration tables use the intersection of v1-graded and v2-graded keys (player_id, week, stat, bookmaker, line). The report states the counts of v1-only, v2-only and both, with the skip reasons on each side (v1: all-zero window, `None` probability, its per-(player, stat, bookmaker) dedup; v2: no history, μ ≤ 0, model error, unsupported line). G1 is additionally reported on all v2 rows.

**Scoring clip.** Log loss uses p_c = min(max(p, 1e-6), 1 − 1e-6). The clip is applied in scoring only, and live probabilities are unchanged. The harness counts clipped predictions per candidate and per model and reports them. Brier is computed on the unclipped p.

**k = 0 fallback.** If G1, G2 or the real-test half of G3 fails at the fitted O/U k, the harness re-runs the v2 O/U evaluation once with k = 0 for all five stats and re-checks G1, G2, G3 (both halves) and G5 (A4 #1). G3-proxy and G5 don't depend on k, so a failure in either is final and doesn't trigger the fallback. Both results appear in the report. No other k is ever evaluated on the test set.

**Order of evaluation.** The gate (G1-G5, with the fallback if triggered) is evaluated and its result is fixed before any optional diagnostic runs. The matchup experiment (B10.6) runs only after that and can't change the gate result or the written parameters.

For flags, hit rate and ROI on the test set, the harness uses an **assumed-price mode**: for each legacy O/U row, `backtest.py` builds a synthetic copy in which the stored price is taken as the price of the side being evaluated, `marketSource = "assumed (harness)"`, and P_mkt stays at 0.5. It then calls the unchanged `model_v2.decide_flag` on that copy, so rules 1 and 3-5 apply exactly as live. `model_v2` has no bypass parameter. Every such table is labelled "side of stored price unknown (S5)". Live code never does this.

Unique picks are one per (player, week, stat): the row with the largest edge. v1 unique picks follow the review's rule, which is the first flagged row per player-stat.

### B10.5 Report

The report is written to `OUT\report.md` and printed. The implementer copies it to `.agents/tasks/nfl-stats-model-v2-validation.md`.

It covers the five O/U stats, overall O/U and anytime TD, on the real test, the proxy hold-out and the 2026 proxy. For each, it reports:

- n rows, n unique player-stats, and the over-rate.
- Brier and log loss for v1, v2 model-only (k = 1), v2 final, and the baseline.
- Calibration tables for v2 final and v1, with one row per (player, week, stat) as in G3. Favoured-side buckets are "0.50 (tie)", [0.50, 0.55), [0.55, 0.60), [0.60, 0.70) and [0.70, 1.00], each with n, mean stated, observed, the Wilson 95% interval and the Bonferroni interval (A4 #3), plus m and its z, and a red-flag marker on buckets outside their 95% interval.
- Flags (rows and unique), hit rate with Wilson 95% CI, mean stated P of the picked side, mean edge, and ROI at the assumed price (real test only, with the caveat). These are shown at margins of 2, 3 and 5. **3 is the gate value.** The other two are labelled diagnostic.
- Cluster bootstrap: 2,000 resamples over (player_id, week, stat) clusters, with percentile 95% CIs for Brier(v2) − 0.25, Brier(v2) − Brier(v1), and Brier(v2) − Brier(v2 model-only).
- Diagnostics:
  - the fold-B k curve and stand-in anchor Briers from B10.3 step 6 (no k curve is computed on the test set, because only the fitted k and 0 may be evaluated there)
  - log-loss clip counts per candidate and per model (B10.4)
  - the v1-only / v2-only / both row counts with skip reasons (B10.4)
  - o_TD (fitted or fallback, with the raw ratio and TD count), o_ou, and the TD Brier with raw versus de-vigged anchors
  - SD(z) of standardized residuals for v2 (target about 1)
  - fitted c_k and CV_k(6), compared with the review's values
  - flags removed by the min-games rule
  - the full drop and exclusion list with classifications
  - TD P_mkt calibration, and the implied TD overround (Σ 1/d ÷ Σ outcomes)
- The chosen configuration, with the fold-B score of every candidate, so a reviewer can see how close the choices were.
- The gate table G1-G5 with PASS/FAIL and the numbers, at the fitted k and, if the fallback was triggered, at k = 0, with the criterion that triggered it. The final line states one of: "gate passed", "gate passed, O/U fallback k = 0 (stats model added no measurable value over the line on the held-out weeks)", or "gate failed: <criterion> by <amount>".
- **Hold-out disclosure,** printed in the report next to the G1/G2 table: "2025 wk14-16 is not a pristine hold-out. The math review already used those weeks to compare 3 against 6 games, normal against log-normal, and model weights up to 0.25. The k cap 0.25 is kept as a fixed policy cap that can only move probabilities toward the market. G5 (the 2026 proxy) and G3-proxy are the checks with no prior exposure."
- `/generate-picks` wall time for v1 and v2 on the 2026 wk8 copy, from the served-page check (B12). If v2 is more than 1.2× slower than v1, it is listed as a red flag (A3).
- When the fallback was triggered or the fitted k is below 0.05 for every stat, a plain-language paragraph says that the page will show near-market probabilities and few or no O/U flags, and that this is the honest result.

### B10.6 Matchup experiment (optional, diagnostic only)

`--matchup-experiment <schedule.json>` takes the review's ESPN schedule format (`%TEMP%\nflmath\sched2025.json`, which is present). The harness never fetches it, and it isn't committed.

The experiment runs v2 with μ′ = μ_used·(1 + β(f_pit − 1)). f_pit is the opponent's point-in-time yards allowed (completions allowed for receptions) before the target week, divided by the league average, computed from the DB copy. β comes from `team_stats.MATCHUP_BETA`: 0.3 for passing yards, receiving yards and receptions, and 0 for rushing.

**The experiment is diagnostic only.** It runs after the gate result is fixed (B10.4, "Order of evaluation"). It never changes the parameters that the gate evaluates, `params_test.json`, or what `--write-params` writes, and it has no adoption rule. Live v2 keeps matchup display-only in this build whatever the result (FR9).

The report gives:

- the fold-B cluster-bootstrap 95% CI of the per-case log-loss difference (with factor − without), per stat and overall, as the evidence
- labelled "diagnostic, not used for any decision": the real-test Brier with and without the factor
- a recommendation line. If the overall fold-B CI lies entirely below 0, it reads: "Matchup factor shows an out-of-sample gain on fold B; recommend a follow-up build with a committed schedule source (2025 and 2026), a `matchup` params block and its own gate." Otherwise: "No clear out-of-sample gain; matchup stays display-only."

Without the schedule file, the report says "matchup experiment not run" and gives the reason.

Weather isn't tested, because there is no weather data (`weather_api` returns nothing). The report states this.

### B10.7 Production parameters (`--write-params`, only after the gate passes)

Let T be the week from `--production-target 2026-T` (validated in B10.1). `CURRENT_WEEK` from the config is never used here.

1. Refit c, CV, ratios and λ0 on all proxy data before the production target: 2025 wk4-17 plus 2026 wk2-(T − 1), with the 2026 proxy line rule from B10.2. The window, distribution and blend choices stay **as selected in B10.3** and aren't re-selected.
2. Production k_k = min(stand-in k fitted on all proxy data, k fitted on the real 2025 wk14-16 O/U odds with P_mkt = 0.5, k_k evaluated by the gate, 0.25). Using the test weeks here is legitimate, because the gate has already been evaluated and 2026 is the target. Including the gate-evaluated k bounds the shipped value by one the gate actually saw, so production k can only be equal to or lower than the tested k. **If the gate passed through the O/U fallback, this step is skipped and k_k = 0 for all five O/U stats.**
3. o_TD is refit on 2025 wk14-16 TD odds with the same rule and the same 20-TD minimum (revision 2 measured 1.18 over 66 TDs across the three weeks, so the fit is expected to be used). k_TD = min(fit on 2025 wk14-16 TD odds with that de-vigged anchor, k_TD evaluated by the gate, 0.25), or 0 if G4 failed. The TD cases come from `evaluate_week` rows, as in B10.3 step 7.
3b. `o_ou` = median of (1/d_o + 1/d_u) over `books_both` O/U rows in weeks strictly before the production target, else 1.064. The count is reported.
4. Write `model_v2_params.json` with `gate_label` set to the gate result and a `fitted_on` string that lists the ranges, for example `"proxy 2025 wk4-17 + 2026 wk2-7; O/U k: 2025 wk14-16 odds; TD: 2025 wk14-16 odds"` for T = 8. This is the only repo file the harness writes, and it is written to the repo root only (never via `NFL_MODEL_V2_PARAMS`).
5. A separate commit then sets `MODEL_VERSION = 'v2'` (FR10).

## B11. Frontend (`index.html`)

**Detect v2:** `lastModel?.version === 'v2'`, set from `data.model` in the `/generate-picks` response. v1 payloads (`model` = `{"version": "v1"}`, or absent from an older server) render exactly as today.

**State and call plumbing.** Today `generatePicks()` (lines 655-697) calls `formatPicksFromJSON(players)` (line 684), which calls `formatPlayerStatSection(player, matchup, statType, stats)`; neither receives the model info. The v2 code adds module state next to `allPicks`/`currentPage` (lines 651-652) and passes `model` explicitly:

```js
let showUnflagged = false;
let lastPlayers = [];
let lastModel = null;                       // data.model from /generate-picks; null or {version:'v1'} for v1

function formatPicksFromJSON(players, model) { ... }        // model may be null (v1 path unchanged)
function formatPlayerStatSection(player, matchup, statType, stats, model) { ... }

function renderPicks() {                    // called by generatePicks() and by the toggle button
  const picksContainer = document.getElementById('picks-container');
  allPicks = formatPicksFromJSON(lastPlayers, lastModel);
  currentPage = 0;
  if (lastModel?.version === 'v2' && allPicks.length === 0) {
    picksContainer.innerHTML = zeroFlagMessage(lastPlayers, lastModel) + toggleButtonHtml();
  } else {
    displayPicksPage();                     // for v2, displayPicksPage prepends toggleButtonHtml() and the k = 0 note
  }
}

function toggleUnflagged() { showUnflagged = !showUnflagged; renderPicks(); }
```

- `generatePicks()` sets `lastPlayers = data.players || []` and `lastModel = data.model || null`, resets `showUnflagged = false`, and calls `renderPicks()`. It keeps its `players.length === 0` "No flagged players found." branch, which can now only fire for v1 (v2 returns every evaluated row) or for a v2 week with no evaluated markets at all.
- `toggleButtonHtml()` returns "" for v1. For v2 it returns a button `onclick="toggleUnflagged()"` labelled "Show unflagged markets (N)" or "Hide unflagged markets", where N is the number of cards with no flagged row.
- `zeroFlagMessage(players, model)` returns: "No picks with an edge above {model.edge_margin_pts} pts. X markets evaluated; Y have no side price (re-fetch odds to get Over/Under prices)." X = number of returned v2 rows, Y = rows with `marketSource === 'none'` or `price === null`, both computed client-side.
- With `showUnflagged = true` and 0 flagged cards, `allPicks` is non-empty, so `displayPicksPage()` runs and the toggle button reads "Hide unflagged markets".

**Cards** (`formatPicksFromJSON`, lines 759-803):

- Group by player and stat, as now.
- Card sort key: any flagged row (descending), then the maximum `edgePts` (descending, nulls last), then the maximum `probFinal` (descending).
- With `showUnflagged = false`, only cards with at least one flagged row are returned; with `true`, all cards are returned in the same order.
- When `model.ou_k_all_zero` is true, a one-line note above the cards says: "Over/Under probabilities follow the market (the stats model showed no measurable edge in validation)."
- Card header badge: `EDGE +4.1 pts`, `No price` or `No edge`. When the row behind the badge has `edgeSource === 'price only'`, the badge is followed by "(best-price edge, model weight 0)".

**Table** (`formatPlayerStatSection`, lines 861-958). v2 columns: Stat | `Avg (last N played)` | Adjusted Stat | Adjustments | Line | Side | Price (book) | Model % | Market % | Final % | Edge (pts).

- N comes from `model.window_n`. For EWMA the header is "Weighted avg (games played)".
- The average cell shows μ, plus "(n = k)" when `gamesUsed` is below the window N.
- Market % shows "no price" when `marketSource === 'none'`. For `"one-sided (de-vigged)"` it appends "(one-sided, ÷o)" using the row's `overround`, and for `"no-vig (cross-book)"` it appends "(cross-book)".
- Anytime-TD rows (`stat === 'anytime_td'`) use the card title "ANYTIME TD", show "-" for Line, and use the header "TD rate (λ/game)" in place of the average column.
- Edge shows "-" for null, and appends "(price only)" when `edgeSource === 'price only'`. On rows that aren't flagged, a `title` tooltip shows `noFlagReason`.
- `formatPlayerStatSection` reads `model.window_n` and the `model.version` check from its new `model` argument, never from a global.
- Rows within a card sort by `edgePts` descending, nulls last.
- The API already returns one row per line, so there is no client-side dedup.

**Adjustment details** are unchanged, except that changePct === 0 renders "±0%" instead of "-0%".

**Escaping:** the new text fields from the API (`bookmaker`, `bookmakers`, `noFlagReason`, `marketSource`, `edgeSource`) go through a small `escapeHtml()` helper. Existing interpolations are left as they are (out of scope).

## B12. Testing

**Unit tests** (`.venv\Scripts\python.exe -m unittest discover tests`, no DB, no network), in `tests/test_model_v2.py`:

- `window_mean`: last_n and EWMA values, and n_eff = n for equal weights.
- CV rule: CV(1) > CV(3) > CV(6) strictly for a, b > 0. The fit helper enforces b ≥ a on synthetic data.
- Bug #8: receptions [6,6,6] vs [6,6,7] at 4.5 (A4 #6).
- Small n (A4 #7): normal family, same μ and line, n = 1 is closer to 0.5 than n = 6. Negbin receptions μ = 6, L = 4.5, a = b = 0.362: n = 1 is closer to 0.5 than n = 6. A documenting test also checks that log-normal μ 50, L 60.5, a = b = 0.6 gives P(Over) lower at n = 1 than at n = 6 (about 0.255 vs 0.266), so nobody later "fixes" that correct behaviour.
- Distributions:
  - log-normal median = μ/√(1 + CV²)
  - negbin falls back to Poisson when Var ≤ μ
  - Poisson P(≥2 | λ = 1.667) = 0.496 (the review's pass-TD example)
  - P_over + P_under = 1
- Market probability:
  - de-vig of (1.87, 1.95) gives 0.5105
  - the median across books
  - one side priced at 1.25 with o = 1.064 gives P_mkt(side) = 0.80/1.064 = 0.752 with "one-sided (de-vigged)" and `overround = 1.064`
  - TD de-vig (review finding 1): one book Yes at 5.0, o_td = 1.25, k = 0.25, P_model = 0.20 gives P_mkt = 0.16, P_final = 0.17, edge = −0.03, not flagged
  - mixed coverage: book A Over only at 1.90, book B Under only at 1.95 gives "no-vig (cross-book)" with P_mkt_over = (1/1.90)/((1/1.90) + (1/1.95)) = 0.5065
  - an `unknown` price from book C next to book A's Over is ignored for P_mkt and `best`
  - only `unknown` prices gives 0.5 with "none"
  - `decide_flag` returns "no price" for `marketSource == "none"` even when a `best` price is (wrongly) present on the row
- Anchoring: k = 0 gives P_mkt, and k = 0.25 gives the expected value. Edge sign and units are correct.
- `decide_flag`: every reason, in order. A missing price never flags, even with a huge model edge.
- Far-line rule:
  - Minshew (213.5 vs 7.3), Estime (30.5 vs 5.5) and D. Douglas (15.5 vs 40.0) are excluded.
  - Parker Washington (20.5 vs 48.8), Singletary receptions (0.5 vs 1.7) and pass TD 0.5 vs 1.6 are kept.
- TD: λ shrinkage, 1 − e^(−λ), and the λ ≥ 1e-6 clamp with n0 = 0 and a zero-TD history.
- Scoring clip helper: log loss of p = 0 with outcome 1 is finite (−ln 1e-6) and increments the clip count.
- Wilson and Bonferroni helpers (they live in `backtest.py`; the test imports them, and importing `backtest` must not run the harness, so all work sits under `main()`): z for 1 − 0.05/m returns 1.960 at m = 1 and 2.638 ± 0.001 at m = 6. Wilson interval for 30/50 at z = 1.96 is (0.462, 0.724) ± 0.001, and is strictly wider at the m = 6 z.
- `edgeSource`: a row with k = 0 and a two-way price gets `"price only"`; with k = 0.1, `"model + price"`. A k = 0 row whose best price beats the median no-vig probability by more than the margin is flagged, and carries `"price only"`.
- `get_model_info(config, None)` for v1 returns exactly `{"version": "v1"}`.
- `load_params` rejects a missing key, k = 0.3, a < 0, c = 1.5, o_td = 1.7 and o_ou = 0.9. A missing file raises `ParamsError("not found: …")`.
- `evaluate_week` with an invalid params file raises `ParamsError` before any player is processed (it is not swallowed by the per-player `try`).
- `probability_calc` returns `None` and logs on a forced exception (A4 #9).
- `drop_outlier_lines` count-market boundary (synthetic entries): a line with gap exactly 1.0 from the median is KEPT; a line with gap 1.5 and rel > 0.25 (for example 4.5 against a median of 3.0) is DROPPED.

**Integration** (DB copy):

- `backtest.py` end to end: A4 #1-5 and #10-12.
- `drop_outlier_lines` on the 2025 wk16 copy: Kupp's receptions 3.5 (vs 2.5), Goedert's receptions 4.5 (vs 3.5) and Stafford's rush attempts 1.5/0.5 are all KEPT (strict count-market rule, B9).
- Jacobs 2026 wk8 (A4 #8), through `evaluate_week(..., adjustments=False)` on the copy.
- `evaluate_week` v2 on the 2026 wk8 copy returns no rows for any name in `INCOMPLETE_DATA_PLAYERS`, and `summary["model"]["version"] == "v2"`.
- `app.py` `/generate-picks` with `NFL_MODEL_V2_PARAMS` pointing at a missing file returns `success: false` with the "Model v2 parameters invalid" message (FastAPI `TestClient` against a DB copy, or the served-page run).

**Served page:**

1. Copy the DB to `$env:TEMP\nfl_backtest\served.db` (sqlite3 backup API from a `mode=ro` source). Check that port 8001 is free (`Get-NetTCPConnection -LocalPort 8001` returns nothing; otherwise use the next free port above 8001). Start `.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8001` with these env vars: `NFL_STATS_DB` = that copy, `NFL_SEASON`/`NFL_WEEK` = 2025/16 (then restart with 2026/8), `NFL_MODEL_VERSION=v2`, and `NFL_MODEL_V2_PARAMS=<OUT>\params_test.json` (or `<OUT>\params_test_k0.json` when the gate passed through the k = 0 fallback, B10.3 step 8). The repo `model_v2_params.json` is never written for this. Leave any user server on 8000 alone. Stop the 8001 server afterwards.
2. `node tests/check_picks_dom.js http://127.0.0.1:8001` fetches `/` and `/generate-picks`. It extracts `formatPicksFromJSON`, `formatPlayerStatSection`, `renderPicks`, `zeroFlagMessage`, `toggleButtonHtml`, `toggleUnflagged` and `escapeHtml` from the served HTML, the way the earlier `check_sort.js` did, and declares `showUnflagged`, `lastPlayers`, `lastModel`, `allPicks` and `currentPage` in the evaluation context. It also declares `dismissedPlayers = new Set()` (read by `formatPlayerStatSection`) and `PICKS_PER_PAGE = 10` (read by `displayPicksPage`), and stubs `setTimeout = () => 0` (or defines `renderPlayerGameInfo = () => {}`) in the evaluation context, so the delayed game-info call can't throw a `ReferenceError` from a timer after the script runs. It stubs `document.getElementById('picks-container')` with an object whose `innerHTML` it reads, stubs `displayPicksPage` to write `toggleButtonHtml() + allPicks.join('')` into that object, and gives a minimal `document` stub for the `setTimeout` game-info call. It sets `lastPlayers = data.players` and `lastModel = data.model` from the served JSON, then:
   - calls `renderPicks()` with `showUnflagged = false`, then `toggleUnflagged()`, and asserts the A4 #13 items in both states, plus: with `false` no unflagged-only card is rendered, with `true` every returned card is rendered.
   - if the served data has 0 flagged rows (expected for 2026 wk8 O/U), asserts the container shows the zero-flag message with the margin from `model.edge_margin_pts` and the toggle button, and not "Page 1 of 0".
   - when `data.model.ou_k_all_zero` is true, asserts the k = 0 note is rendered, and that every rendered `price only` row shows "(price only)".
   - prints `DOM CHECK PASSED`.
3. The script also writes the rendered first page of cards, with the served CSS inlined, to `$env:TEMP\nfl_backtest\picks_render.html`. The implementer runs `msedge --headless=new --disable-gpu --window-size=1400,2000 --screenshot=<OUT>\picks.png file:///…/picks_render.html` and records the path in the report.
3b. **Performance (A3).** Record the `/generate-picks` wall time for v1 and v2 on the 2026 wk8 copy and put both in the report. If v2 is more than 1.2× slower than v1, list it as a red flag.
4. Run v1 for 2026 wk8 with the edited code (`NFL_MODEL_VERSION=v1`, `NFL_STATS_DB` = a temp copy, `NFL_SEASON=2026`, `NFL_WEEK=8`, `python test_thresholds.py --json`) and compare it with `baseline\v1_2026wk8.json` (A4 #14).

**v1 baseline (first implementation step, before any file is edited).** HEAD has no `NFL_STATS_DB` and reads relative paths, so the baseline runs the HEAD code from its own directory:

1. Create `$env:TEMP\nfl_backtest\baseline\`. For every tracked `.py` file and `index.html` (`git -C <repo> ls-files "*.py" index.html`), write `git show 56f0092:<file>` there, keeping subdirectories. Copy `team_stats_data.json` the same way if it is tracked.
2. Copy the DB to `baseline\nfl_stats.db` with the sqlite3 backup API from a `mode=ro` source.
3. In that directory, with `NFL_SEASON=2026` and `NFL_WEEK=8` (so no Sleeper call), run `c:\code\nfl_stats_project-master\.venv\Scripts\python.exe test_thresholds.py --json` and save stdout to `baseline\v1_2026wk8.json`. The HEAD v1 path makes no Odds API call: it reads stored odds from the DB (`test_thresholds.py:203`), and `odds_api` isn't imported. The comparison excludes `adjustmentDetails` and the `adjusted*` keys, because `evaluate_week` may call the display adjustments in a different order from HEAD's CLI path. No network call happens on this path.
4. Check that the file parses as JSON and record its row count and SHA256 in the validation report. If the run fails, stop and report; don't start editing without a baseline.

`NFL_MODEL_VERSION` is a verification-only override. It is validated like `MODEL_VERSION` ('v1' or 'v2'), and an invalid value fails the request (B13). It lets the served-page check exercise v2 without committing the switch before the gate passes.

## B13. Error handling

| Operation | Failure | Recoverable? | Caller receives | Log |
|---|---|---|---|---|
| `load_params` | Missing file, bad JSON, schema or range violation | Fatal for v2 requests | `ParamsError(reason)` → API `success: false` with the message | ERROR |
| `MODEL_VERSION` / `NFL_MODEL_VERSION` read | Not 'v1'/'v2' | Fatal for the request | API `success: false` | ERROR |
| `V2_EDGE_MARGIN` / `V2_MIN_GAMES_FOR_FLAG` | Missing or out of range (B14) | Fatal for v2 requests | API `success: false` | ERROR |
| `resolve_player_ids` | SQLAlchemyError | Fatal for the request | Raised from `evaluate_week`; `app.py` returns `success: false, error: "Database error: <msg>"` | ERROR |
| `get_played_history` | SQLAlchemyError | Recoverable per player | `None` → player skipped, `skipped_db_error` counter | WARNING (player_id, error) |
| History empty / μ ≤ 0 | Normal | Recoverable | Market skipped (no row) | DEBUG |
| Price invalid / outcome unknown | Bad data | Recoverable | Price treated as missing → that side unpriced, `marketSource` downgraded | WARNING once per (player, market, book) |
| Integer or non-positive line | Unsupported | Recoverable | Row dropped, `unsupported_line` counter | INFO |
| Any exception inside `model_v2` per market | Bug or bad data | Recoverable | Market skipped, `model_errors` += 1, never shown as 50/50 | ERROR with traceback, player, market, line |
| `calculate_probability` (v1) | Any exception, or None inputs | Recoverable | `None` → `check_stat_against_odds` drops the row | ERROR (`logger.exception`) |
| `compute_adjustments` | Any exception | Recoverable | Rows without adjustment details (as today) | WARNING (today a `print`; changed to the logger) |
| Harness DB copy / path guard / hash mismatch | Copy failed, engine not in TEMP, real DB changed | Fatal | Exit 2 / 3 / 4 | ERROR to stderr |
| Harness CV fit | a_k ≤ 0 or < 50 fit cases for a stat | Fatal | Exit 5, naming the stat | ERROR |
| Harness `--write-params` with a failed gate | Blocking criterion failed | Fatal for that step | Exit 6, no file written | ERROR |
| Harness k_TD fit | < 20 usable TD player-weeks | Recoverable | k_TD = 0, reported | WARNING |
| Harness o_TD fit | < 20 observed TDs in the fit weeks | Recoverable | o_TD = 1.25, reported with the raw ratio | WARNING |
| Harness k-dependent gate criterion at fitted k | G1 (Brier > 0.25 or log loss > ln 2), G2 (CI not below 0) or G3-real (a bucket outside its Bonferroni interval) fails | Recoverable (pre-registered) | One re-evaluation with O/U k = 0, re-checking G1, G2, G3 (both halves) and G5; gate label records it and the triggering criterion | WARNING, and stated in the report |
| Harness G3-proxy or G5 | Fails (k-independent) | Fatal for the gate | Gate failed, no fallback; `MODEL_VERSION` stays 'v1' | WARNING, and stated in the report |
| Harness `--production-target` | Missing, malformed, out of range, or a 2026 week below the target has no stats | Fatal for `--write-params` | Exit 6, no file written, message names the problem | ERROR |
| Harness log loss at p = 0 or 1 | Tail underflow, zero λ | Recoverable | Clipped to [1e-6, 1 − 1e-6] in scoring; clip count reported | none per row; count in the report |
| `evaluate_week` params/policy load | `ParamsError`, invalid version or policy | Fatal for the request | Raised before the player loop; `app.py` catches `ParamsError` explicitly and returns `success: false` | ERROR |
| Harness matchup schedule | Missing or unreadable | Recoverable | Experiment skipped, reason in the report | WARNING |

Each request writes one INFO summary line: players checked, markets evaluated, flagged, no_price, excluded_far_line, model_errors, skipped_db_error.

## B14. Input validation summary

| Input | Required | Type / limits | On failure |
|---|---|---|---|
| `odds.price` | Optional per side | float, 1.01 ≤ p ≤ 1000 | Treated as missing (WARNING) |
| `odds.line` (O/U) | Required | finite float > 0, not an integer | Row dropped (INFO) |
| `odds.line` (TD) | Ignored | n/a | n/a |
| `odds.outcome` | Optional | Over/Under/Yes/No/NULL | Unknown values ignored (WARNING). NULL on O/U means unknown side. NULL on TD means Yes |
| Stat values | Optional | float. NULL → 0. Negative yards allowed | n/a |
| `gp` | Optional | NULL uses the existing any-stat fallback | n/a |
| `MODEL_VERSION`, `NFL_MODEL_VERSION` | Required / optional | 'v1' or 'v2' | Request fails (ERROR) |
| `V2_EDGE_MARGIN` | Required in v2 | float in [0, 0.2] | Request fails (ERROR) |
| `V2_MIN_GAMES_FOR_FLAG` | Required in v2 | int in [1, 17] | Request fails (ERROR) |
| `model_v2_params.json` | Required in v2 | Schema in B8 | `ParamsError` |
| `NFL_MODEL_V2_PARAMS` | Optional | Path to a params JSON. Default: `model_v2_params.json` next to `test_thresholds.py`. Used by the served-page check to point at `<OUT>\params_test.json` | Missing file → `ParamsError("not found: <path>")`; invalid file → `ParamsError(reason)` |
| `NFL_SEASON` / `NFL_WEEK` | Optional (live), set by the harness | int season, int week 1-18 | Existing `pipeline_config` behaviour (falls back to overrides, then Sleeper) |
| `NFL_STATS_DB` | Optional | path. The harness requires it under TEMP | Harness exit 3 |
| Harness `--matchup-experiment` | Optional | Readable JSON in the sched2025 format | Experiment skipped, reason in the report |
| Harness `--production-target` | Required with `--write-params` | `SEASON-WEEK`, season 2026, week int in [2, 18], 2026 stats present for wk1-(week − 1) | Exit 6 (B10.1) |

## B15. Invariant ownership

| Invariant | Owner | Why there |
|---|---|---|
| History strictly before the target (season, week), played games only | `test_thresholds.get_played_history` (SQL). The harness re-asserts it | One query serves live use and the back-test, so they can't diverge |
| Parameters fitted only on weeks before the test, per market family | `backtest.py` (`FIT_TEST` plus per-family assertion) | Only the harness fits |
| Only the fitted k and k = 0 are ever evaluated on the O/U test set; the fallback triggers on any k-dependent blocking criterion (G1, G2, G3-real) | `backtest.py` (fallback is a single pre-registered branch) | Prevents tuning k on the test set while keeping the honest k = 0 outcome reachable |
| The gate result is fixed before any diagnostic (matchup experiment, margin sensitivity) runs, and diagnostics never change gated or written parameters | `backtest.py` (evaluation order in B10.4) | Stops test-set results from selecting between models |
| Shipped k ≤ the k the gate evaluated (per O/U stat and for TD) | `backtest.py --write-params` (min rule, B10.7 #2-3) | The live model never uses more model weight than was validated |
| Production fit range is set by `--production-target`, never by the config's `CURRENT_WEEK` | `backtest.py` argument validation | The harness pins `NFL_WEEK` to 2025 wk14 only to avoid Sleeper |
| One-sided anchors are de-vigged; `unknown` prices never anchor or price a flag | `model_v2.group_lines` / market-probability function, with o range-checked by `load_params` | The anchor decides edge, so it is owned where edge is computed |
| 0 ≤ P ≤ 1, Over + Under = 1, 0 ≤ k ≤ 0.25 | `model_v2` (convex combination) and `load_params` (range check) | Pure functions, unit-tested |
| Never flag without a known side price, with `marketSource == "none"`, or on a far line | `model_v2.decide_flag` | Server-side, so no client can show an unpriced flag |
| Real DB never written by validation | `backtest.py` path guard and hash check, plus the `NFL_STATS_DB` indirection in all three engines | Defence in depth at the only place that runs experiments |
| One row per (player, stat, line) | `model_v2.group_lines` | Dedup at the source, so the frontend needs none |
| v2 live only after the gate passes | Committed `MODEL_VERSION = 'v1'`. `--write-params` refuses on a failed gate. The served-page check uses `NFL_MODEL_V2_PARAMS`/`NFL_MODEL_VERSION` instead of the repo file | Prevents shipping an unvalidated model |
| Invalid params fail the request instead of returning an empty success | `evaluate_week` loads params before the player loop; `app.py` catches `ParamsError` explicitly | The per-player `except Exception: continue` would otherwise swallow it |

## B16. Risks and expected outcome

- **The real test is small.** It has about 420 player-stats, 85% of them from wk16. The math review's best result was Brier 0.2504 with k = 0.25, just above G1's 0.2500. The expected outcome is a v2 Brier of about 0.248-0.251 at the fitted k, so the pre-registered O/U fallback k = 0 (triggered by G1, G2 or G3-real) is a likely result. In that case v2 ships with near-market O/U probabilities (exactly 0.5 on legacy rows) and no O/U flags, and the report says plainly that the stats model added no measurable value over the line. That is still a large improvement on v1, whose probabilities score 0.291, worse than a coin flip.
- **The O/U test weeks are not pristine.** 2025 wk14-16 is not a pristine hold-out. The math review already used those weeks to compare 3 against 6 games, normal against log-normal, and model weights up to 0.25. The k cap 0.25 is kept as a fixed policy cap that can only move probabilities toward the market. G5 (the 2026 proxy) and G3-proxy are the checks with no prior exposure. The report prints this paragraph next to the G1/G2 table (B10.5).
- **The stand-in k for O/U is a heuristic** (B10.3 step 6), not a proven upper bound. The k = 0 fallback and the production minimum rule (which includes the gate-evaluated k) both push k down, never up.
- **One-sided anchors depend on the overround factor.** o_TD falls back to 1.25 for the test parameters because the fit weeks hold only 7 TDs. If the true overround is nearer the measured 1.16-1.18, the anchor is slightly low on Yes, which makes Yes flags slightly harder. That errs toward fewer flags. Production refits o_TD on 66 TDs.
- **Line shopping is inside the edge.** The edge is against the best price while P_mkt uses the median book, so part of a flag's edge can come from one book being generous. The page names the book.
- **Live today,** every O/U row is legacy, so live O/U flags stay at zero until odds are re-fetched. Only anytime TD can flag. The page message says this explicitly.
- **The far-line rule** excludes some lines that are normal but reflect a role change the model can't see. This is intended: the row is still shown, it just isn't flagged.

---

# Part C. Revision 1: changes from the earlier draft

This section records the corrections revision 1 made while checking the draft against the code and data. Items 3 and 10 were revised again in revision 2 (Part D, findings 1, 6 and 7).

1. **Parker Washington premise corrected.** The draft and the brief said his mean was ~75 and that a 60% single-book rule catches the 20.5 line. That 74.7 was the *leaky* 3-game mean, which included the wk16 game itself (145 yards). His honest last-6-played mean is 48.8 (dev 0.58), so the 60% rule doesn't catch him. The rule wasn't tuned to catch him, because that would mean fitting a threshold to one anecdote. A4 #10 now asserts the measured exclusion list instead.
2. **Far-line rule extended to multi-book lines,** with absolute floors (10 yards / 2.0 units). Measurement showed the biggest risk is a consensus line that the model can't explain, such as Gardner Minshew 213.5 passing yards against a mean of 7.3 from relief appearances. A k ≤ 0.25 blend would still flag that Under with a large edge. Single-book-only exclusion would miss it. The floors stop normal low-volume lines from being excluded (measured above).
3. **One-sided O/U prices are anchored on their price,** the same treatment as anytime TD, instead of 0.5. A one-sided line is the typical shape of an alt or milestone listing, and 0.5 would invent edge there. Legacy NULL-outcome rows still use 0.5 and never flag, as the brief requires. (Revision 2 de-vigs this anchor by the overround factor o; see finding 1.)
4. **`MODEL_VERSION` is committed as `'v1'`,** and switched only after the gate passes and production params are written. The draft both added `'v2'` and said v2 must stay off if the gate fails. `NFL_MODEL_VERSION` lets the served-page check exercise v2 beforehand.
5. **Gate blocking rules made explicit.** G1, G2, G3 and G5 are blocking. G4 resolves itself by setting k_TD = 0.
6. **`NFL_STATS_DB` also applies to `target_share_calc.py` and `app.py`.** The v1 path calls `target_share_calc`, which has its own engine on the real DB, and the served page uses `app.py`'s engine for other endpoints. Without this, "the harness never opens the real DB" was false.
7. **The 2026 proxy covers wk2-7** (brief item c), using a cross-season prior mean for the proxy line. The draft's in-season rule started it at wk4. G5 compares only cases both models can price and reports v1's gaps.
8. **A per-stat mean-bias factor c_k was added.** It corrects regression to the mean and skew bias in short windows (review J2: actuals fell below the 3-game mean 57-60% of the time for yards). One parameter per stat, fitted on fold A and range-checked.
9. **Calibration (G3) is measured on one row per (player, week, stat).** Six books share one outcome, so per-row Wilson CIs would be too narrow.
10. **Jacobs acceptance made meaningful.** "P_final < 0.65" holds automatically when k ≤ 0.25. The criterion now checks the cross-season window (6 games, 5 from 2025, μ = 52.8) and P_model(Under) ≤ 0.80.
11. **No new DB backup.** This design makes no schema change and no DB write. The existing backup `nfl_stats.backup-20261030-143034.db` (10,027,008 bytes) stays, and the stop-and-ask rule applies if a write turns out to be needed.
12. **Line references and section numbers fixed.** The `probability_calc.py` bare `except` is at line 58. `index.html` functions are at 759 and 861. The draft's "D2-D10" references are now B-section numbers.

---

# Part D. Revision 2: responses to the design review

Round-1 review of revision 1 (CHANGES_REQUESTED, 2 HIGH, 8 MEDIUM, 10 NIT; its JSON has since been replaced by the round-2 review). Every finding was addressed in revision 2. None was backlogged or ignored. Revision 3 refined findings 2 and 9 further (Part E, findings 1 and 9).

| # | Sev. | Response | Where |
|---|---|---|---|
| 1 | HIGH | **Addressed.** One-sided anchor is now median(1/d) ÷ o_family. o_TD is fitted on 2025 wk14-15 alongside k_TD, clamped to [1.0, 1.6]. Refinement: the fit also needs ≥ 20 observed TDs, because revision 2 measured only 7 TDs in those weeks (ratio 1.16, relative SE near 40%), so the test parameters use the review's pre-measurement fallback 1.25. o_ou comes from `books_both` rows, else 1.064. `load_params` validates both. k_TD and the G4 baseline use the de-vigged anchor, and raw 1/price is also reported. The "conservative" claim is removed, and the line-shopping effect is stated. The review's unit test is added. | FR4, FR6, B5, B7, B8, B10.3 #7, B10.7 #3, B12, B13, B16 |
| 2 | HIGH | **Addressed.** Pre-registered G1 fallback: one re-evaluation at O/U k = 0, then G2, G3 and G5 are re-run. A pass is labelled "O/U fallback k = 0", reported plainly, written to params as `gate_label`, and shown on the page. Only the fitted k and 0 may be evaluated on the test set. The test-set k curve diagnostic was removed for the same reason and moved to fold B. | A4 #1, #15, B10.4, B10.5, B10.7 #2, B11, B15, B16 |
| 3 | MED | **Addressed.** `FIT_TEST` defines fit and test weeks per family (O/U: fit wk4-13, test wk14-16; TD: λ wk4-13, k/o wk14-15, test wk16), asserted per family. The A4 intro is reworded. | A4 intro, A4 #11, B10.2, B10.3 |
| 4 | MED | **Addressed.** Each v2 row is expanded to one graded row per bookmaker. G1, G2 and calibration use the intersection of keys (player_id, week, stat, bookmaker, line). v1-only, v2-only and both counts are reported with skip reasons, and G1 is also given on all v2 rows. | A4 intro, B10.4, B10.5 |
| 5 | MED | **Addressed.** Ties go to Over in a "0.50 (tie)" bucket. Proxy-holdout G3 uses v2 model-only and is blocking. G5 uses `params_test.json`, point estimate, CI reported. | A4 #3, #5 |
| 6 | MED | **Addressed.** A4 #7 now tests CV(1) > CV(3) > CV(6), the closer-to-0.5 property for the normal family, and the negbin μ = 6, L = 4.5 case. Revision 2 re-checked the review's numbers (log-normal 0.266 → 0.255, negbin 0.592 → 0.523). A documenting test pins the correct log-normal behaviour. B3 is reworded, and it now says the cross-season window, not widening, fixes Jacobs. | A4 #7, B3, B12 |
| 7 | MED | **Addressed.** Jacobs asserts the raw last-6 history (52.8), ties `gamesUsed` to the selected window, and reports μ_used separately. The P_model ≤ 0.80 check depends on the window, so it is a reported red flag rather than a hard check. P_final ≤ 0.65 stays hard. The exclusion list is asserted against an independent re-computation with the selected window and c, reported per line and per player-market. Parker's assertion applies only when dev ≤ 0.60. B9 values are labelled as median lines. | A4 #8, #10, B9 |
| 8 | MED | **Addressed.** The scoring clip is [1e-6, 1 − 1e-6], applied to log loss only, with clip counts reported. TD λ is clamped to ≥ 1e-6. | A4 intro, B6, B10.3, B10.4, B12, B13 |
| 9 | MED | **Addressed.** `NFL_MODEL_V2_PARAMS` (default: repo-root `model_v2_params.json`). The served-page check points it at `<OUT>\params_test.json` and sets `NFL_MODEL_VERSION=v2`, and it never writes the repo file. Added to B14. | B0, B1, B8, B12, B14, A4 #13 |
| 10 | MED | **Addressed.** Added rule 1b "no-vig (cross-book)". `unknown` prices never enter P_mkt or `best`. `decide_flag` also refuses `marketSource == "none"`. Unit tests are added for the A-Over/B-Under case and for an ignored `unknown`. | B5, B12, B15 |
| 11 | NIT | **Addressed.** Called a heuristic. The fold-B Brier of P_mkt_proxy, of 0.5 and of the blend are reported. | B10.3 #6, B16 |
| 12 | NIT | **Addressed.** `evaluate_week(..., adjustments=True)`, with the harness passing `False`. | B8, B10.1 #5, B12 |
| 13 | NIT | **Addressed.** Path guard uses normcase(realpath) plus commonpath against TEMP, and rejects the repo DB. | B10.1 #5 |
| 14 | NIT | **Addressed.** TD row fields are defined, with the header "TD rate (λ/game)" and the card title "ANYTIME TD". | B7, B11 |
| 15 | NIT | **Addressed.** The harness sets `NFL_SEASON`/`NFL_WEEK` before any config read and passes season and week explicitly. | B10.1 #4, B14 |
| 16 | NIT | **Addressed.** Selection score = unweighted mean of the five per-stat mean log losses on fold B. | B2, B10.3 #2 |
| 17 | NIT | **Addressed.** Params and policy are loaded once in `evaluate_week` before the player loop, outside any per-player `try`, and `app.py` catches `ParamsError` explicitly. A unit test and an integration test cover this. | B8, B12, B13, B15 |
| 18 | NIT | **Addressed.** X and Y are computed client-side from the returned v2 rows. | B11 |
| 19 | NIT | **Addressed.** Module-level `let showUnflagged = false;`, defined by `check_picks_dom.js`, with both states tested. | B11, B12 |
| 20 | NIT | **Addressed.** Anytime TD uses rule 1 when a book prices both Yes and No. | B5 |

**Deviation from the brief, kept deliberately.** Brief decision 4 says to use P_mkt = 0.5 when only one side is priced. This design uses the de-vigged price of that side instead. A 0.5 anchor against a one-sided long price (for example 4.0, so 1/d = 0.25) would create about 25 points of fake edge, and anytime TD is always one-sided on today's data. The review agreed with this deviation (finding 1, "Note on the brief"). Rows with no known side (all legacy O/U rows and all current 2026 wk8 rows) use 0.5, are marked "no market price", and never flag, as the brief requires.

**Deviation from the brief, kept deliberately.** Brief decision 8 expects the >60% single-book rule to catch Parker Washington's wk16 Ladbrokes 20.5 against a "mean ~75". The ~75 was the leaky 3-game mean that included wk16 itself. His honest mean is 48.8 (dev 0.58), so the rule does not catch him, and it is not tuned to (Part C #1).

**Deviation from the brief, kept deliberately.** Brief decision 5 says to start the edge margin at 3 points and tune it on validation data. The only graded real-price data is 2025 wk14-16 (about 420 player-stats, 85% from one week, side of the stored price unknown). Tuning the margin there would fit it to noise and to the test set. The margin is fixed at 3.0 for the gate, and margins 2 and 5 are reported as a labelled sensitivity diagnostic (B5, B10.5). It is re-tuned only after weeks with real Over/Under prices are graded.

---

# Part E. Revision 3: responses to the round-2 design review

Review: `nfl-stats-model-v2-design-review.json` / `.md` (round 2, CHANGES_REQUESTED, 0 HIGH, 5 MEDIUM, 9 NIT). Every finding is addressed. None is backlogged or ignored. Before editing, revision 3 re-checked the code facts the findings rely on: `generatePicks()` at `index.html:655-697` passes only `players` to `formatPicksFromJSON` (line 684); `app.py:424-425` imports and calls `get_flagged_players_json_updated()`; `test_thresholds.py:62` has the `len(rows) == 1` single-game path and line 374 the `has_meaningful_stats` / `INCOMPLETE_DATA_PLAYERS` skip; `get_odds_for_player` (line 182) tries the period/Jr./Sr. name variants at lines 195-197; `pipeline_config.py:47` sets `CURRENT_WEEK` from `NFL_WEEK`.

| # | Sev. | Response | Where |
|---|---|---|---|
| 1 | MED | **Addressed.** The k = 0 fallback now triggers when any k-dependent blocking criterion fails at the fitted k (G1, G2, or G3-real). It re-checks G1, G2, G3 (both halves) and G5 at k = 0. G3-proxy and G5 are k-independent, so their failure is final. Still only two k values are evaluated on the test set. | A4 #1, #15, B10.4, B10.5, B13, B15, B16 |
| 2 | MED | **Addressed.** G3 uses a Bonferroni level 1 − 0.05/m, with m = buckets with ≥ 30 rows across both halves (z = 2.64 at m = 6). The report shows 95% and Bonferroni intervals and lists 95% misses as red flags. Unit tests cover the z and Wilson helpers at m = 1 and m = 6. | A4 #3, B10.5, B12 |
| 3 | MED | **Addressed.** The matchup experiment is diagnostic only: it runs after the gate result is fixed, never changes gated or written params, has no adoption rule, and labels the real-test Brier as a diagnostic. If the fold-B CI is entirely below 0, the report recommends a follow-up build (committed schedule source, `matchup` params block, own gate). | FR9, A5, B10.4, B10.6, B15 |
| 4 | MED | **Addressed.** `--production-target SEASON-WEEK` is required with `--write-params`, validated (season 2026, week 2-18, 2026 stats present for every earlier week), exit 6 on failure. The harness pins `NFL_SEASON=2025`, `NFL_WEEK=14` only to stop the Sleeper call, and no harness computation reads `CURRENT_WEEK`. `fitted_on` example given. | B10.1, B10.7, B13, B14, B15 |
| 5 | MED | **Addressed.** `lastPlayers`/`lastModel`/`showUnflagged` module state; `formatPicksFromJSON(players, model)`; `formatPlayerStatSection(..., model)`; `renderPicks()` handles the zero-flag message and the toggle; `zeroFlagMessage`, `toggleButtonHtml`, `toggleUnflagged` specified. Python side: `evaluate_week` puts `summary["model"]`; new `get_picks_with_model()` used by `app.py`; `get_flagged_players_json_updated()` becomes a wrapper; v1 model info is `{"version": "v1"}`. The DOM check extracts the new functions, stubs the container and `displayPicksPage`, and asserts the zero-flag path. | B1, B8, B11, B12 |
| 6 | NIT | **Addressed.** P_mkt_proxy uses μ_season·c_k, CV_k(n_season) with the fold-A (c, a, b) and the chosen distribution (empirical ratios with c = 1). | B10.3 #6 |
| 7 | NIT | **Addressed.** Production k_k and k_TD include the gate-evaluated k in the min. | B10.7 #2-3, B15 |
| 8 | NIT | **Addressed.** A v1 baseline is captured as the first implementation step from `git show 56f0092:<file>` plus a DB copy in `$env:TEMP\nfl_backtest\baseline\`, saved as `v1_2026wk8.json`. A4 #14 compares against it; display-adjustment details are excluded from the comparison because TeamRankings data can change between runs. | A4 #14, B12 |
| 9 | NIT | **Addressed.** `params_test.json` sets `fitted_on = "proxy 2025 wk4-13; TD k/o: 2025 wk14-15 odds"`. A `params_test_k0.json` variant is written when the fallback triggers, so the served-page check exercises the model that passed. | B10.3 #8, B12 |
| 10 | NIT | **Addressed.** B10.1 step 0 is `os.chdir(REPO)`, with `REPO = Path(__file__).resolve().parent`. | B10.1 |
| 11 | NIT | **Addressed.** TD fit cases and G4 cases are built from `evaluate_week(..., adjustments=False)` rows, so they use the live name-variant matching. The count of unmatched odds names is reported. | A4 #4, B10.3 #7, B10.7 #3 |
| 12 | NIT | **Addressed.** v2 keeps the `INCOMPLETE_DATA_PLAYERS` skip and drops `has_meaningful_stats` (per-market μ ≤ 0 covers it). An integration test checks the skip. | B8, B12 |
| 13 | NIT | **Addressed.** A4 #5 now says v1 prices from a single in-season game; the report gives counts of cases v1 couldn't price and cases priced from fewer than 3 games. | A4 #5 |
| 14 | NIT | **Addressed.** Rows get `edgeSource` (`"price only"` when the row's k = 0). The page shows "(best-price edge, model weight 0)" next to the badge and "(price only)" in the Edge cell. Flagging is unchanged, since a de-vigged consensus beaten by one book's price is a real edge after vig. | B5, B7, B11, B12 |

---

# Part F: round-3 resolutions

Review: `nfl-stats-model-v2-design-review.md` (round 3, CHANGES_REQUESTED, 0 HIGH, 2 MEDIUM, 7 NIT). Every finding is applied as the review proposed. Nothing else changed.

| # | Sev. | Resolution | Where |
|---|---|---|---|
| 1 | MED | **Strict count-market rule.** Count markets drop a line only when rel > 0.25 and \|L − median\| > 1.0 (strictly greater); yards keep the 25% rule. Pseudocode added. Kupp 3.5 vs 2.5, Goedert 4.5 vs 3.5 and Stafford 1.5/0.5 are all kept. A4 #10 now says "the one-unit and half-unit count-market drops". B12 asserts all three are KEPT on the 2025 wk16 copy, and a synthetic boundary unit test pins gap 1.0 kept and gap 1.5 with rel > 0.25 (4.5 vs median 3.0) dropped. | FR8, B9, A4 #10, B12 |
| 2 | MED | **(a) No privileged window.** The window is the lowest fold-B selection score; candidates within 0.001 of the best are tied and the tie goes to the largest mean n_eff on fold B (longest window). Last 6 stays a candidate and every score is printed. **(b) Hold-out disclosure** added to B10.5 (printed next to the G1/G2 table) and B16: 2025 wk14-16 was already used by the math review; the k cap 0.25 is a fixed policy cap; G5 and G3-proxy have no prior exposure. | B2, B10.3 #2, B10.5, B16 |
| 3 | NIT | `check_picks_dom.js` declares `dismissedPlayers = new Set()` and `PICKS_PER_PAGE = 10`, and stubs `setTimeout = () => 0` (or defines `renderPlayerGameInfo = () => {}`). | B12 served page #2 |
| 4 | NIT | A4 #14 compares the baseline list against the edited output's `players` array per (player, stat, bookmaker, line) on `threshold_rule`, `probabilityOver`, `probabilityUnder`, `player_value`. | A4 #14 |
| 5 | NIT | Exclusion rationale replaced: `adjustmentDetails` and `adjusted*` keys are excluded because `evaluate_week` may call display adjustments in a different order from HEAD's CLI path; no network call happens on this path. | B12 v1 baseline #3 |
| 6 | NIT | Production `o_ou` = median of (1/d_o + 1/d_u) over `books_both` O/U rows in weeks strictly before the production target, else 1.064; count reported. | B10.7 #3b |
| 7 | NIT | v1 on proxy sets is called through `check_stat_against_odds` with a synthetic `proxy` entry; skipped cases are counted per week and excluded from G5. | B10.4 |
| 8 | NIT | The served-page check records `/generate-picks` wall time for v1 and v2 on the 2026 wk8 copy; v2 > 1.2× v1 is a red flag. | B12 served page #3b, B10.5 |
| 9 | NIT | B13 row added: `resolve_player_ids` SQLAlchemyError is fatal for the request; `app.py` returns `success: false, error: "Database error: <msg>"`; ERROR. | B13 |
