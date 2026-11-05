# NFL player-prop model v2: final report

## Verdict

- **Accuracy.** On the held-out 2025 wk14-16 lines (1,385 graded bookmaker rows), v2's probabilities score Brier 0.2485 and log loss 0.6901. A coin flip scores 0.2500 / 0.6931 and the old model (v1) scores 0.2940 / 0.8134. v2 is clearly better than v1: the 95% cluster-bootstrap interval for the Brier difference is [-0.067, -0.027]. Against 50/50 the gain is small and not statistically certain (Brier(v2) - 0.25 = -0.0015, 95% CI [-0.0053, +0.0024]).
- **Calibration.** v2's stated probabilities match observed hit rates in every checked bucket. v1 said 65% and 81% where the observed rates were 43% and 54%.
- **v2 against the market.** On today's data this can't be measured properly. Every stored Over/Under price is a legacy row whose side is unknown, so "the market" is a 50% stand-in. With that stand-in, the fitted model weight k = 0.25 helps (G1 passes). G4 compares the anytime-TD model with real Yes prices: it found no value over the de-vigged price, so the TD model weight is 0 and TD probabilities equal the market.
- **MODEL_VERSION.** Switched to `'v2'` in commit `0e68b31`. The pre-registered gate passed at the fitted k, without the k = 0 fallback. All six criteria G1-G5 pass.
- **Expected flags per week.**
  - **Now, with the stored odds:** 0 Over/Under flags. These rows have no side price, and v2 never flags without one. The served 2026 wk8 page shows "No picks with an edge above 3 pts. 106 markets evaluated; 78 have no side price".
  - **Anytime TD:** a few line-shopping flags per busy week, only when one book's Yes price beats the de-vigged median. 2025 wk16 had 15 games and produced 8 such flags. 2026 wk8 produced 0.
  - **After you re-fetch two-way prices:** expect a small number of O/U flags. With k ≤ 0.25 a flag needs the stats model to disagree with the no-vig market by roughly 20+ points. That is the intended behaviour: flags only on a real edge after vig.

## What was implemented

- `model_v2.py` (pure, stdlib only) contains:
  - a cross-season window mean
  - one dispersion rule, CV² = a + b/n_eff, with b ≥ a
  - log-normal, empirical, normal, negative-binomial and Poisson tails, all computed as P(X ≥ ⌈L⌉)
  - no-vig market probability: per-book, cross-book, one-sided de-vigged by o, or "none" → 0.5 and never flagged
  - anchoring P_final = P_mkt + k(P_model − P_mkt)
  - edge measured against the best vig-inclusive price
  - a flag rule with ordered reasons
  - a far-line exclusion
  - an anytime-TD model: shrunk λ, P = 1 − e^−λ
  - params validation
- `test_thresholds.py` gained:
  - `get_played_history`, a leak-free query keyed on player_id
  - the strict count-market drop rule (gap > 1.0 and rel > 0.25)
  - `evaluate_week` with v1/v2 dispatch, `get_model_info` and `get_picks_with_model`
  - `NFL_STATS_DB`, `NFL_MODEL_V2_PARAMS` and `NFL_MODEL_VERSION` overrides
  - a JSON CLI envelope
- Bug #9: `probability_calc.py` logs the exception and returns `None`. `check_stat_against_odds` skips that row and records it.
- `app.py` `/generate-picks` returns `model`, and returns `success: false` with a clear message for invalid v2 params, a bad `MODEL_VERSION` or a DB error.
- `index.html` (v2 only; the v1 render is unchanged):
  - Columns: Model %, Market % (or "no price"), Final %, Price (book), Edge (pts).
  - Cards: flagged first, then sorted by edge. Each row shows the best price per side, with the books offering it.
  - Labels: the average column reads "Avg (last N played)", or "Weighted avg (games played)" for the EWMA window that was selected. The TD column reads "TD rate (λ/game)".
  - Controls and notes: an unflagged toggle and a zero-flag message.
  - Fix: a 0% adjustment now shows "±0%".
- `backtest.py`: the reusable harness. It works only on a sqlite3 backup copy in `%TEMP%\nfl_backtest\<timestamp>\`, with a path guard (exit 3) and a SHA256 check of the real DB (exit 4).
- `tests/test_model_v2.py` holds 59 unit tests, including the count-market boundary (gap 1.0 kept; 4.5 against a median of 3.0 dropped). `tests/check_picks_dom.js` is the served-page DOM check.

## Chosen parameters and why

All choices were made on proxy data from 2025 wk4-13 only: fold A wk4-9 for fitting, fold B wk10-13 for selection.

- **Window: EWMA, half-life 8 games.** EWMA h = 4, 6 and 8 scored within 0.001 of the best fold-B score: 0.6766, 0.6758 and 0.6762 against 0.6758. The tie rule gives the longest effective window (n_eff 8.46). Last 6 scored 0.6928 and last 3 scored 0.7416.
- **Distributions:**
  - pass yds: log-normal
  - rec yds: log-normal
  - rush yds: normal, with the own-SD blend (blend log loss 0.6894 against 0.6922 without)
  - receptions: negative binomial
  - pass TDs: negative binomial
- **Mean-bias c:** 0.94-0.98. Short-window means overstate the next game slightly.
- **Test k = 0.25 for every stat.** The fold-B stand-in argmin was 1.0, capped at 0.25.
- **Production k** (B10.7 min rule):
  - pass yds 0.25
  - rec yds 0.11
  - rush yds 0.25
  - receptions 0.08
  - pass TDs 0.25

  Rec yds and receptions were cut by the k fitted on the real wk14-16 lines.
- **TD:**
  - n0 = 4
  - λ0: QB 0.19, RB 0.33, WR 0.18, TE 0.15
  - o_TD = 1.199 in production (fitted on 66 TDs). The test parameters used the 1.25 fallback (7 TDs).
  - k_TD = 0: the fit-week argmin was 0, and G4 showed no gain.
- **o_ou = 1.064 (fallback).** No stored row has both Over and Under prices.
- **Policy:** edge margin 3.0 pts and at least 3 games. Both are fixed, not tuned on the test set.

## Validation (full tables in `.agents/tasks/nfl-stats-model-v2-validation.md`)

> 2025 wk14-16 is not a pristine hold-out. The math review already used those weeks to compare 3 against 6 games, normal against log-normal, and model weights up to 0.25. The k cap 0.25 is kept as a fixed policy cap that can only move probabilities toward the market. G5 (the 2026 proxy) and G3-proxy are the checks with no prior exposure.

| Gate (fitted k = 0.25) | Value | Result |
|---|---|---|
| G1 Brier ≤ 0.25, LL ≤ ln 2 | 0.2485, 0.6901 | PASS |
| G2 CI of Brier(v2) − Brier(v1) | −0.0455 [−0.0670, −0.0265] | PASS |
| G3-real calibration (m = 6, z = 2.638) | [0.50,0.55) 0.523 vs 0.554; [0.55,0.60) 0.568 vs 0.556 | PASS |
| G3-proxy, 2025 wk14-17 model-only | 4 buckets inside Bonferroni ([0.70,1.00] 0.729 vs 0.636 is a 95% red flag) | PASS |
| G4 TD v2 vs de-vigged market (wk16, 333 cases) | 0.1244 vs 0.1244 (raw 1/d 0.1247) | PASS (k_TD = 0) |
| G5 2026 proxy, v2 model-only vs v1 (1,970 cases) | 0.2427 vs 0.2712 | PASS |

| Real test, intersection | Brier | Log loss |
|---|---|---|
| v1 | 0.2940 | 0.8134 |
| v2 model-only (k = 1) | 0.2623 | 0.7306 |
| v2 final | 0.2485 | 0.6901 |
| 50/50 | 0.2500 | 0.6931 |

- **Bootstrap CIs** (2,000 resamples over 426 player-week-stat clusters):
  - Brier(v2) − 0.25: [−0.0053, +0.0024]
  - Brier(v2) − Brier(v1): [−0.0670, −0.0265]
  - Brier(v2) − Brier(v2 model-only): [−0.0259, −0.0027]
- **Flags at 3 pts, assumed-price mode** (side of the stored price unknown, S5): 219 rows / 121 unique. Hit rate 0.557 [0.491, 0.621] by row and 0.562 [0.473, 0.647] unique. The +0.176 ROI is not evidence of profit, because each stored price is credited to whichever side is picked.
- **v1 flags:** 335 rows, hit 0.501 [0.448, 0.555], ROI −0.049.
- **Matchup experiment** (diagnostic only): overall fold-B log-loss change −0.0001 [−0.0028, 0.0026]. No gain, so matchup stays display-only.
- **Served page and timing:**
  - DOM check passed on 2025 wk16 and 2026 wk8, and again with the committed switch and repo params.
  - `/generate-picks` on 2026 wk8: v1 39.1 s, v2 21.7 s.
  - `/static/nfl_stats.db` and `/static/.env` return 404.
  - Josh Jacobs 2026 wk8 rush 60.5 was 88.7% Under in v1 (from one game). v2 shows 51.9% Under (16 games, mean 55.0), not flagged.
- **v1 parity:** with `MODEL_VERSION = 'v1'`, the 2026 wk8 output matches the pre-edit baseline: 55 of 55 rows identical.
- **Deviation from the design:** `fit_cv` refits on the b = a floor when the unconstrained intercept is ≤ 0, instead of exiting 5. One candidate window's fold-A passing-yards fit, on 147 cases, gave a = −0.008. The final fits are recorded in the report: pass yds unconstrained, the other four stats on the floor.

## Commits on model-v2 (on top of 7f6f127; not pushed)

`3433b04` bug #9 · `bf03a41` MODEL_VERSION switch + env overrides · `d2cee5e` count-market rule + history query · `8a4e083` model_v2 core · `d988805` market/edge/flag/TD · `1c99bb2` evaluate_week · `1d73ecc` /generate-picks · `8eeaaef` frontend · `d5b09dd` backtest.py · `3fff8b9` DOM check · `a07846b` production params · `0e68b31` switch to v2 · plus the docs commit with this report.

## DB backups

No schema change and no real-DB write was made, so no new backup was needed. The existing backup is `nfl_stats.backup-20261030-143034.db` (10,027,008 bytes). `nfl_stats.db` SHA256 `0B705BF2E0FA5FE1B405DAD15BA52068D9C20A45D1412D35C3BDDF1DDB3EE3CC` was unchanged before and after every run.

## How to switch v1 / v2

- Permanent: set `MODEL_VERSION = 'v1'` or `'v2'` in `pipeline_config.py`. v2 reads `model_v2_params.json` in the repo root.
- One run or one server: `$env:NFL_MODEL_VERSION='v1'` before `python run_local.py` or uvicorn. `NFL_MODEL_V2_PARAMS` points v2 at another params file.

## Limitations

- No stored Over/Under price has a known side, so O/U market anchoring and edges can't be tested against real two-way prices yet. Live O/U flags will stay at 0 until you re-fetch odds.
- The real test is small: 426 player-stats, most of them from wk16. v2's gain over 50/50 is within noise.
- The pooled CV understates spread for low-volume players. SD(z) on the proxies is 1.16-1.32.
- TD flags are line shopping (model weight 0). They are real only if you can bet at the named book.
- `player_rush_attempts` isn't modelled, because there is no attempts column.
- About 85 TD odds names didn't match a player: D/ST entries and suffix variants such as "III" and "Jr" without the period.

## Next steps

1. Re-fetch odds with the current code, so that Over and Under prices are stored by outcome.
2. Collect odds every week, including closing lines, so future tests use real two-way prices.
3. Re-run `python backtest.py --matchup-experiment <schedule>` weekly. When new weeks with two-way prices exist, refit with `--write-params --production-target 2026-<week>`, and revisit the 3-pt margin only on those graded weeks.
