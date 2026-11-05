# Model v2 back-test report

Run: 20261105-202149. Output folder: `C:\Users\andre\AppData\Local\Temp\nfl_backtest\final`. Seed 20261030. DB copy SHA256 before run: `0b705bf2e0fa5fe1b405dad15ba52068d9c20a45d1412d35c3bddf1ddb3ee3cc`.

FIT_TEST asserted: O/U fit 2025 wk4-13 < test wk14-16; TD lambda fit wk4-13, k/o fit wk14-15 < test wk16.

## Case sets

| set | passing_yards | receiving_yards | rushing_yards | receptions | passing_tds | total |
|---|---|---|---|---|---|---|
| Proxy fold A (2025 wk4-9) | 147 | 546 | 271 | 698 | 140 | 1802 |
| Proxy fold B (2025 wk10-13) | 101 | 378 | 190 | 504 | 101 | 1274 |
| Proxy hold-out (2025 wk14-17) | 112 | 389 | 207 | 523 | 105 | 1336 |
| 2026 proxy (wk2-7) | 170 | 627 | 301 | 770 | 169 | 2037 |

2026 proxy cases per week: wk2 357, wk3 346, wk4 357, wk5 339, wk6 328, wk7 310
TD proxy cases: fold A 1902, fold B 1377.
Leak check: 7572 histories, every row strictly before its target week (asserted).

## Selection and fitting (2025 wk <= 13)

**Window candidates** (fold-B selection score = mean of the five per-stat log losses; fit on fold A). Tie band 0.001: candidates within it of the best go to the largest mean n_eff.
| window | score | passing_yards | receiving_yards | rushing_yards | receptions | passing_tds | mean n_eff | clips | CV floor used | tied | chosen |
|---|---|---|---|---|---|---|---|---|---|---|---|
| last 3 played | 0.7416 | 0.7335 | 0.6973 | 0.8331 | 0.6698 | 0.7742 | 3.00 | 1 | passing_yards, receiving_yards, rushing_yards, receptions, passing_tds |  |  |
| last 4 played | 0.7094 | 0.7142 | 0.6724 | 0.7695 | 0.6657 | 0.7250 | 3.99 | 0 | passing_yards, receiving_yards, rushing_yards, receptions, passing_tds |  |  |
| last 6 played | 0.6928 | 0.7003 | 0.6730 | 0.7318 | 0.6658 | 0.6933 | 5.89 | 0 | rushing_yards, receptions, passing_tds |  |  |
| last 8 played | 0.6834 | 0.6907 | 0.6531 | 0.7132 | 0.6730 | 0.6869 | 7.63 | 0 | rushing_yards, receptions, passing_tds |  |  |
| last 10 played | 0.6797 | 0.6806 | 0.6538 | 0.7030 | 0.6754 | 0.6856 | 8.70 | 0 | rushing_yards, receptions, passing_tds |  |  |
| last 17 played | 0.6805 | 0.6841 | 0.6553 | 0.7043 | 0.6752 | 0.6834 | 8.91 | 0 | rushing_yards, receptions, passing_tds |  |  |
| weighted, half-life 2 games | 0.6880 | 0.6878 | 0.6582 | 0.7379 | 0.6501 | 0.7063 | 5.21 | 0 | rushing_yards, receptions, passing_tds |  |  |
| weighted, half-life 3 games | 0.6791 | 0.6802 | 0.6487 | 0.7183 | 0.6522 | 0.6960 | 6.60 | 0 | rushing_yards, receptions, passing_tds |  |  |
| weighted, half-life 4 games | 0.6766 | 0.6782 | 0.6466 | 0.7107 | 0.6554 | 0.6919 | 7.39 | 0 | rushing_yards, receptions, passing_tds | yes |  |
| weighted, half-life 6 games | 0.6758 | 0.6779 | 0.6468 | 0.7054 | 0.6603 | 0.6885 | 8.14 | 0 | rushing_yards, receptions, passing_tds | yes |  |
| weighted, half-life 8 games | 0.6762 | 0.6785 | 0.6479 | 0.7039 | 0.6634 | 0.6871 | 8.46 | 0 | rushing_yards, receptions, passing_tds | yes | **yes** |

**Distribution per stat** (fold B, chosen by log loss; Brier breaks ties within 0.0005)
| stat | dist | log loss | Brier | clips | chosen |
|---|---|---|---|---|---|
| passing_yards | lognormal | 0.6785 | 0.2428 | 0 | **yes** |
| passing_yards | empirical_ratio | 0.7009 | 0.2540 | 0 |  |
| passing_yards | normal | 0.6900 | 0.2485 | 0 |  |
| receiving_yards | lognormal | 0.6479 | 0.2278 | 0 | **yes** |
| receiving_yards | empirical_ratio | 0.6505 | 0.2290 | 0 |  |
| receiving_yards | normal | 0.6725 | 0.2397 | 0 |  |
| rushing_yards | lognormal | 0.7039 | 0.2550 | 0 |  |
| rushing_yards | empirical_ratio | 0.6968 | 0.2517 | 0 |  |
| rushing_yards | normal | 0.6922 | 0.2495 | 0 | **yes** |
| receptions | negbin | 0.6634 | 0.2355 | 0 | **yes** |
| receptions | poisson | 0.6646 | 0.2361 | 0 |  |
| receptions | normal | 0.6702 | 0.2390 | 0 |  |
| passing_tds | negbin | 0.6871 | 0.2471 | 0 | **yes** |
| passing_tds | poisson | 0.6919 | 0.2494 | 0 |  |
| passing_tds | normal | 0.7278 | 0.2666 | 0 |  |

**Own-SD blend** (adopted only if fold-B log loss improves by >= 0.002)
| stat | dist | log loss off | log loss on | result |
|---|---|---|---|---|
| passing_yards | lognormal | 0.6785 | 0.6794 | off |
| receiving_yards | lognormal | 0.6479 | 0.6490 | off |
| rushing_yards | normal | 0.6922 | 0.6894 | adopted |
| receptions | negbin | 0.6634 | 0.6631 | off |
| passing_tds | negbin | 0.6871 | 0.6889 | off |

**TD n0** (fold B log loss; lambda0 from fold A: {'QB': 0.192547, 'RB': 0.335556, 'WR': 0.186717, 'TE': 0.184584, 'ALL': 0.221872})
| n0 | log loss | clips |
|---|---|---|
| 0 | 0.6193 | 541 |  |
| 1 | 0.3993 | 0 |  |
| 2 | 0.3933 | 0 |  |
| 4 | 0.3928 | 0 | **chosen** |
| 8 | 0.3981 | 0 |  |

**Stand-in k** (fold B; stand-in market = P(Over) from the season mean; pooled k 1.00; cap 0.25)
| stat | cases | k (argmin) | source | k used | Brier stand-in mkt | Brier 0.5 | Brier blend | fold-B Brier curve k:Brier |
|---|---|---|---|---|---|---|---|---|
| passing_yards | 101 | 1.00 | global (only 101 cases) | 0.25 | 0.2455 | 0.2500 | 0.2445 | 0.00:0.2455 0.05:0.2453 0.10:0.2451 0.15:0.2449 0.20:0.2447 0.25:0.2445 |
| receiving_yards | 378 | 1.00 | per stat | 0.25 | 0.2313 | 0.2500 | 0.2302 | 0.00:0.2313 0.05:0.2311 0.10:0.2308 0.15:0.2306 0.20:0.2304 0.25:0.2302 |
| rushing_yards | 190 | 1.00 | global (only 190 cases) | 0.25 | 0.2490 | 0.2500 | 0.2486 | 0.00:0.2490 0.05:0.2489 0.10:0.2488 0.15:0.2487 0.20:0.2487 0.25:0.2486 |
| receptions | 504 | 1.00 | per stat | 0.25 | 0.2409 | 0.2500 | 0.2394 | 0.00:0.2409 0.05:0.2406 0.10:0.2403 0.15:0.2400 0.20:0.2397 0.25:0.2394 |
| passing_tds | 101 | 1.00 | global (only 101 cases) | 0.25 | 0.2433 | 0.2500 | 0.2442 | 0.00:0.2433 0.05:0.2435 0.10:0.2437 0.15:0.2438 0.20:0.2440 0.25:0.2442 |

**Test parameters** (refit on 2025 wk4-13 with the chosen configuration)
| stat | dist | c | a | b | CV(6) | review CV(6) | blend | k | red flags |
|---|---|---|---|---|---|---|---|---|---|
| passing_yards | lognormal | 0.974 | 0.0983 | 0.1789 | 0.358 | 0.39 | False | 0.25 | - |
| receiving_yards | lognormal | 0.925 | 0.3903 | 0.3903 | 0.675 | 0.86 | False | 0.25 | CV gap > 0.15 |
| rushing_yards | normal | 1.005 | 0.3098 | 0.3098 | 0.601 | 1.00 | True | 0.25 | CV gap > 0.15 |
| receptions | negbin | 0.942 | 0.2826 | 0.2826 | 0.574 | 0.65 | False | 0.25 | - |
| passing_tds | negbin | 0.951 | 0.5252 | 0.5252 | 0.783 | 0.83 | False | 0.25 | - |

CV fit path per stat: passing_yards: unconstrained; receiving_yards: b < a -> floor b = a; rushing_yards: b < a -> floor b = a; receptions: b < a -> floor b = a; passing_tds: b < a -> floor b = a.
TD: n0 4, lambda0 {'QB': 0.171429, 'RB': 0.322785, 'WR': 0.188791, 'TE': 0.145369, 'ALL': 0.208295}.

**TD market fit (2025 wk14-15)**: usable player-weeks 46, TDs 7, o_TD fallback 1.25 (only 7 TDs < 20; raw ratio 1.213); k_TD argmin 0.00, capped 0.00, 46 cases. Unmatched odds names: 14 (e.g. Calvin Austin III, Cedrick Wilson Jr., Los Angeles Chargers D/ST, Los Angeles Chargers Defense, Miami Dolphins D/ST, Miami Dolphins Defense, Ollie Gordon II, Oronde Gadsden II, Philadelphia Eagles D/ST, Philadelphia Eagles Defense, Pittsburgh Steelers D/ST, Pittsburgh Steelers Defense, Scott Miller, Tre Harris)

`params_test.json` written to the output folder (o_ou 1.064: no fit-week O/U row has both sides).

## Real O/U test, 2025 wk14-16 (stored odds, held-out)

Graded rows: v1 1386, v2 1387 (per-bookmaker expansion), both 1385, v1-only 1, v2-only 2. Voids: {'v1 void (DNP)': 4, 'v2 void (DNP)': 4}.
v2-only reasons: {'v1 skipped row (all-zero window or None probability)': 2}. v1-only reasons: {'v2 no row (no history, mu <= 0, model error or unsupported line)': 1}.
v2 evaluate_week counters: wk14 {'players_checked': 2737, 'flagged': 1, 'skipped_db_error': 0, 'v1_probability_errors': 0, 'markets_evaluated': 92, 'skipped_no_history': 0, 'skipped_mu_le_0': 0, 'model_errors': 0, 'unsupported_line': 0, 'no_price': 66, 'excluded_far_line': 2}; wk15 {'players_checked': 2743, 'flagged': 1, 'skipped_db_error': 0, 'v1_probability_errors': 0, 'markets_evaluated': 103, 'skipped_no_history': 0, 'skipped_mu_le_0': 0, 'model_errors': 0, 'unsupported_line': 0, 'no_price': 78, 'excluded_far_line': 1}; wk16 {'players_checked': 2759, 'flagged': 8, 'skipped_db_error': 0, 'v1_probability_errors': 0, 'markets_evaluated': 1055, 'skipped_no_history': 1, 'skipped_mu_le_0': 3, 'model_errors': 0, 'unsupported_line': 0, 'no_price': 676, 'excluded_far_line': 13}

**Scores on the intersection row set** (Brier / log loss; baseline 50/50 log loss 0.6931)
| stat | rows | unique player-stats | over-rate | Brier v1 | Brier v2 model-only | Brier v2 final | Brier 50/50 | LL v1 | LL v2 model-only | LL v2 final |
|---|---|---|---|---|---|---|---|---|---|---|
| passing_yards | 188 | 33 | 0.511 | 0.2877 | 0.2595 | 0.2463 | 0.2500 | 0.7987 | 0.7146 | 0.6857 |
| receiving_yards | 481 | 153 | 0.466 | 0.3111 | 0.2695 | 0.2499 | 0.2500 | 0.8600 | 0.7616 | 0.6929 |
| rushing_yards | 262 | 76 | 0.515 | 0.2838 | 0.2522 | 0.2465 | 0.2500 | 0.7727 | 0.7010 | 0.6860 |
| receptions | 304 | 132 | 0.510 | 0.2918 | 0.2708 | 0.2507 | 0.2500 | 0.8086 | 0.7425 | 0.6945 |
| passing_tds | 150 | 32 | 0.560 | 0.2695 | 0.2426 | 0.2459 | 0.2500 | 0.7630 | 0.6789 | 0.6850 |
| ALL | 1385 | 426 | 0.501 | 0.2940 | 0.2623 | 0.2485 | 0.2500 | 0.8134 | 0.7306 | 0.6901 |

G1 on all v2 rows (1387): Brier 0.2486, log loss 0.6903.

**Cluster bootstrap** (2,000 resamples over (player_id, week, stat) clusters, 95% percentile CI)
| quantity | point | 95% CI |
|---|---|---|
| Brier(v2) - 0.25 | -0.0015 | [-0.0053, 0.0024] |
| Brier(v2) - Brier(v1) | -0.0455 | [-0.0670, -0.0265] |
| Brier(v2) - Brier(v2 model-only) | -0.0138 | [-0.0259, -0.0027] |

Log-loss clip counts: v2 final 0, v1 0 (v1 is clamped to [5%, 95%]).

## Gate

> 2025 wk14-16 is not a pristine hold-out. The math review already used those weeks to compare 3 against 6 games, normal against log-normal, and model weights up to 0.25. The k cap 0.25 is kept as a fixed policy cap that can only move probabilities toward the market. G5 (the 2026 proxy) and G3-proxy are the checks with no prior exposure.

**At the fitted k** (passing_yards 0.25, receiving_yards 0.25, rushing_yards 0.25, receptions 0.25, passing_tds 0.25)
| criterion | value | result |
|---|---|---|
| G1 Brier <= 0.25 and log loss <= ln 2 (intersection) | Brier 0.2485, LL 0.6901 | PASS |
| G2 CI of Brier(v2) - Brier(v1) below 0 | -0.0455 [-0.0670, -0.0265] | PASS |
| G3-real calibration (m = 6, z = 2.638) | see tables | PASS |
| G3-proxy calibration, 2025 wk14-17 model-only (m = 6) | see tables | PASS |
| G4 TD Brier v2 <= de-vigged market (2025 wk16) | v2 0.1244 vs market 0.1244 (raw 1/d 0.1247) | PASS |
| G5 2026 proxy v2 model-only Brier < v1 | v2 0.2427 vs v1 0.2712 (1970 cases) | PASS |

**Gate result: gate passed**

### Calibration tables (one row per player-week-stat; real test uses the line with the most books)

**v2 final, real test, fitted k** (Bonferroni z = 2.638)
| bucket | n | mean stated | observed | Wilson 95% | Bonferroni | check |
|---|---|---|---|---|---|---|
| 0.50 (tie) | 0 | - | - | - | - | - |
| [0.50, 0.55) | 343 | 0.523 | 0.554 | [0.501, 0.606] | [0.483, 0.623] | PASS |
| [0.55, 0.60) | 72 | 0.568 | 0.556 | [0.441, 0.665] | [0.403, 0.698] | PASS |
| [0.60, 0.70) | 13 | 0.618 | 0.615 | [0.355, 0.823] | [0.285, 0.865] | not checked (< 30) |
| [0.70, 1.00] | 0 | - | - | - | - | - |

**v1, real test (one bookmaker row per player-stat)** (Bonferroni z = 2.638)
| bucket | n | mean stated | observed | Wilson 95% | Bonferroni | check |
|---|---|---|---|---|---|---|
| 0.50 (tie) | 1 | 0.500 | 0.000 | [0.000, 0.793] | [0.000, 0.874] | not checked (< 30) |
| [0.50, 0.55) | 78 | 0.529 | 0.564 | [0.454, 0.669] | [0.417, 0.701] | PASS |
| [0.55, 0.60) | 79 | 0.580 | 0.481 | [0.374, 0.589] | [0.340, 0.625] | PASS |
| [0.60, 0.70) | 129 | 0.651 | 0.434 | [0.352, 0.520] | [0.325, 0.550] | FAIL (red flag: outside 95%) |
| [0.70, 1.00] | 140 | 0.814 | 0.536 | [0.453, 0.616] | [0.425, 0.643] | FAIL (red flag: outside 95%) |

**v2 model-only, proxy hold-out 2025 wk14-17** (Bonferroni z = 2.638)
| bucket | n | mean stated | observed | Wilson 95% | Bonferroni | check |
|---|---|---|---|---|---|---|
| 0.50 (tie) | 0 | - | - | - | - | - |
| [0.50, 0.55) | 305 | 0.524 | 0.557 | [0.501, 0.612] | [0.482, 0.630] | PASS |
| [0.55, 0.60) | 276 | 0.574 | 0.540 | [0.481, 0.598] | [0.461, 0.617] | PASS |
| [0.60, 0.70) | 626 | 0.650 | 0.618 | [0.580, 0.655] | [0.566, 0.668] | PASS |
| [0.70, 1.00] | 129 | 0.729 | 0.636 | [0.550, 0.714] | [0.520, 0.738] | PASS (red flag: outside 95%) |

## Flags, hit rate and ROI on the real test

**v2 at the fitted k, assumed-price mode** (side of stored price unknown (S5); the stored price is assumed to be the price of the side evaluated, so a long price is credited to whichever side is picked; ROI at that assumed price is not evidence of profit)
| margin | flag rows | row hit [95% CI] | unique picks | unique hit [95% CI] | mean stated P | mean edge (pts) | ROI (assumed price) | removed by min-games |
|---|---|---|---|---|---|---|---|---|
| 2 pts (diagnostic) | 288 | 0.559 [0.501, 0.615] | 145 | 0.566 [0.484, 0.643] | 0.544 | 5.9 | +0.170 | 2 |
| 3 pts (gate value) | 219 | 0.557 [0.491, 0.621] | 121 | 0.562 [0.473, 0.647] | 0.546 | 6.6 | +0.176 | 2 |
| 5 pts (diagnostic) | 109 | 0.550 [0.457, 0.641] | 68 | 0.529 [0.412, 0.643] | 0.546 | 8.6 | +0.170 | 1 |

v1 threshold flags: 335 rows, hit 0.501 [0.448, 0.555], ROI at stored price -0.049 (side unknown, S5); unique 92, hit 0.467 [0.369, 0.569].

Anytime TD 2025 wk16 live flags (real Yes prices): 8, hit 0.250, ROI +0.594.

## Proxy hold-out (2025 wk14-17) and 2026 proxy (wk2-7)

| set | stat | cases | both priced | over-rate | Brier v1 | Brier v2 model-only | Brier 50/50 | LL v1 | LL v2 | v2 clips | SD(z) v2 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| hold-out 2025 wk14-17 | passing_yards | 112 | 112 | 0.527 | 0.2949 | 0.2647 | 0.2500 | 0.8056 | 0.7233 | 0 | 1.20 |
| hold-out 2025 wk14-17 | receiving_yards | 389 | 388 | 0.392 | 0.2883 | 0.2410 | 0.2500 | 0.8015 | 0.6760 | 0 | 1.20 |
| hold-out 2025 wk14-17 | rushing_yards | 207 | 207 | 0.449 | 0.2800 | 0.2503 | 0.2500 | 0.7775 | 0.6938 | 0 | 1.20 |
| hold-out 2025 wk14-17 | receptions | 523 | 521 | 0.374 | 0.2687 | 0.2331 | 0.2500 | 0.7569 | 0.6591 | 0 | 1.16 |
| hold-out 2025 wk14-17 | passing_tds | 105 | 104 | 0.442 | 0.2898 | 0.2470 | 0.2500 | 0.8029 | 0.6868 | 0 | 1.16 |
| hold-out 2025 wk14-17 | ALL | 1336 | 1332 | 0.409 | 0.2800 | 0.2418 | 0.2500 | 0.7808 | 0.6770 | 0 | 1.18 |
| 2026 proxy wk2-7 | passing_yards | 170 | 162 | 0.549 | 0.2974 | 0.2663 | 0.2500 | 0.8171 | 0.7267 | 0 | 1.04 |
| 2026 proxy wk2-7 | receiving_yards | 627 | 615 | 0.393 | 0.2722 | 0.2386 | 0.2500 | 0.7707 | 0.6703 | 0 | 1.30 |
| 2026 proxy wk2-7 | rushing_yards | 301 | 294 | 0.381 | 0.2793 | 0.2509 | 0.2500 | 0.7854 | 0.6949 | 0 | 1.17 |
| 2026 proxy wk2-7 | receptions | 770 | 744 | 0.437 | 0.2622 | 0.2402 | 0.2500 | 0.7353 | 0.6729 | 0 | 1.32 |
| 2026 proxy wk2-7 | passing_tds | 169 | 155 | 0.426 | 0.2670 | 0.2313 | 0.2500 | 0.7467 | 0.6547 | 0 | 1.08 |
| 2026 proxy wk2-7 | ALL | 2037 | 1970 | 0.423 | 0.2712 | 0.2427 | 0.2500 | 0.7614 | 0.6784 | 0 | 1.26 |

SD(z) = SD of (actual - mu_used) / (CV * mu_used) per case. Values above 1 mean individual cases spread more than the pooled CV implies: the pooled (ratio-of-sums) CV fit weights high-volume players most, so low-volume players' relative noise is understated. The calibration tables are the decision-relevant check.
G5 bootstrap CI of Brier(v2) - Brier(v1) on the 2026 proxy: -0.0284 [-0.0384, -0.0188] (reported, not required).
v1 gaps on the 2026 proxy per week (v1 window stays inside 2026; 'fewer than 3 games' cases are still priced):
- wk2: {'all-zero window or None probability': 22, 'fewer than 3 games': 327, 'no in-season game': 8}
- wk3: {'all-zero window or None probability': 10, 'fewer than 3 games': 332, 'no in-season game': 4}
- wk4: {'all-zero window or None probability': 1, 'fewer than 3 games': 35, 'no in-season game': 1}
- wk5: {'fewer than 3 games': 21, 'no in-season game': 5}
- wk6: {'all-zero window or None probability': 1, 'fewer than 3 games': 10, 'no in-season game': 6}
- wk7: {'all-zero window or None probability': 6, 'fewer than 3 games': 7, 'no in-season game': 3}

## Anytime TD (2025 wk16 test)

Cases 333, TDs 59, implied overround sum(1/d)/sum(TD) = 1.197. o_TD used 1.25, k_TD 0.0.
Brier: v2 final 0.1244, v2 model-only 0.1258, de-vigged market 0.1244, raw 1/d 0.1247.
| de-vigged P_mkt bucket | n | mean P_mkt | observed |
|---|---|---|---|
| <0.10 | 121 | 0.056 | 0.033 |
| 0.10-0.20 | 95 | 0.144 | 0.147 |
| 0.20-0.30 | 63 | 0.247 | 0.286 |
| 0.30-0.50 | 50 | 0.367 | 0.400 |
| >=0.50 | 4 | 0.532 | 0.750 |


## Fixed-case assertions

- A4 #8 Jacobs history (player_id 5850): first six [(2026, 7), (2025, 17), (2025, 16), (2025, 15), (2025, 14), (2025, 13)] -> PASS; raw last-6 mean 52.83 -> PASS
- A4 #8 Jacobs rush 60.5: gamesUsed 16 (selected window uses 16) -> PASS; mu_raw 55.86, mu_used 56.2; P_final(Under) 0.515 <= 0.65 -> PASS; P_model(Under) 0.559 (<= 0.80, as expected); flagged False, reason 'no price' -> PASS
- A4 #10 Cooper Kupp player_receptions [3.5] kept by drop_outlier_lines (2025 wk16): lines now [2.5, 3.5] -> PASS
- A4 #10 Dallas Goedert player_receptions [4.5] kept by drop_outlier_lines (2025 wk16): lines now [3.5, 4.5] -> PASS
- A4 #10 Matthew Stafford player_rush_attempts [1.5, 0.5] kept by drop_outlier_lines (2025 wk16): lines now [0.5, 1.5] -> PASS
- A4 #10 far-line exclusions: model_v2 17 lines, independent re-computation 17 -> PASS (identical)
- A4 #10 Minshew 2025 wk16 pass yds (lines [208.5, 212.5, 214.5, 215.5, 220.5], median 214.5) all excluded: excluded [208.5, 212.5, 214.5, 215.5, 220.5] -> PASS
- A4 #10 Parker Washington 20.5 vs mu_used 37.7 (dev 0.46) not excluded -> PASS

**Far-line exclusions (selected window and c), per line**
| season | week | player | market | line | mu_used | games | books | class |
|---|---|---|---|---|---|---|---|---|
| 2025 | 14 | Omarion Hampton | player_receptions | 1.5 | 4.0 | 5 | 4 | role change (3+ books agree, history disagrees) |
| 2025 | 14 | Tank Bigsby | player_rush_yds | 5.5 | 16.3 | 12 | 2 | normal (two books, no recent support) |
| 2025 | 15 | Adam Thielen | player_reception_yds | 15.5 | 5.2 | 12 | 2 | normal (two books, no recent support) |
| 2025 | 16 | Audric Estime | player_rush_yds | 30.5 | 6.0 | 4 | 1 | alt/stale line (single book) |
| 2025 | 16 | Evan Hull | player_rush_yds | 25.5 | 10.3 | 3 | 1 | alt/stale line (single book) |
| 2025 | 16 | Gardner Minshew | player_pass_yds | 208.5 | 7.8 | 3 | 6 | role change (3+ books agree, history disagrees) |
| 2025 | 16 | Gardner Minshew | player_pass_yds | 212.5 | 7.8 | 3 | 6 | role change (3+ books agree, history disagrees) |
| 2025 | 16 | Gardner Minshew | player_pass_yds | 214.5 | 7.8 | 3 | 6 | role change (3+ books agree, history disagrees) |
| 2025 | 16 | Gardner Minshew | player_pass_yds | 215.5 | 7.8 | 3 | 6 | role change (3+ books agree, history disagrees) |
| 2025 | 16 | Gardner Minshew | player_pass_yds | 220.5 | 7.8 | 3 | 6 | role change (3+ books agree, history disagrees) |
| 2025 | 16 | Isaiah Williams | player_reception_yds | 28.5 | 11.6 | 12 | 1 | alt/stale line (single book) |
| 2025 | 16 | Mason Tipton | player_reception_yds | 23.5 | 4.4 | 13 | 2 | normal (two books, no recent support) |
| 2025 | 16 | Mason Tipton | player_reception_yds | 25.5 | 4.4 | 13 | 2 | normal (two books, no recent support) |
| 2025 | 16 | Michael Carter | player_rush_yds | 45.5 | 23.3 | 10 | 2 | role change (latest game near the line) |
| 2025 | 16 | Michael Carter | player_rush_yds | 46.5 | 23.3 | 10 | 2 | role change (latest game near the line) |
| 2025 | 16 | Terrance Ferguson | player_reception_yds | 20.5 | 10.1 | 12 | 4 | role change (3+ books agree, history disagrees) |
| 2026 | 8 | Savion Williams | player_reception_yds | 24.5 | 13.3 | 14 | 3 | role change (3+ books agree, history disagrees) |

Per player-market: 11 excluded. Design reference list (last 6, c = 1, median line per market): single-book: Dissly rec yds 0.5 vs 10.8; single-book: Singletary rec yds 5.5 vs 16.5; single-book: I. Williams rec yds 28.5 vs 13.8; single-book: Estime rush 30.5 vs 5.5; single-book: Hull rush 25.5 vs 10.3; single-book: Hooper rec yds 5.5 vs 16.2; multi-book: Gardner Minshew pass yds 213.5 vs 7.3; multi-book: Tank Bigsby rush 6.5 vs 27.3; multi-book: Thielen rec yds 15.5 vs 4.3; multi-book: Ferguson 20.0 vs 6.3; multi-book: DJ Moore 49.5 vs 27.3; multi-book: Dike 30.5 vs 18.7; multi-book: Tipton 24.5 vs 7.8; multi-book: D. Douglas 15.5 vs 40.0; multi-book (2026 wk8): M. Evans 5.5 vs 17.5; multi-book (2026 wk8): Tremayne 4.0 vs 19.2. Differences come from the selected window and c_k and from the rule being applied per line rather than to the median line.

## Matchup experiment (diagnostic only; run after the gate result was fixed)

Fold-B log-loss difference (with factor - without), fold-A parameters, cluster bootstrap 95% CI:
| stat | cases | mean diff | 95% CI |
|---|---|---|---|
| passing_yards | 101 | -0.0062 | [-0.0253, 0.0147] |
| receiving_yards | 378 | 0.0007 | [-0.0041, 0.0056] |
| rushing_yards | 190 | 0.0000 | [0.0000, 0.0000] |
| receptions | 504 | 0.0005 | [-0.0035, 0.0047] |
| passing_tds | 101 | 0.0000 | [0.0000, 0.0000] |
| ALL | 1274 | -0.0001 | [-0.0028, 0.0026] |

Diagnostic, not used for any decision: real-test Brier (one row per line) with factor 0.2478, without 0.2479 (816 lines).
No clear out-of-sample gain; matchup stays display-only.
Weather is not tested: there is no weather data (weather_api returns nothing).

## Production parameters (--write-params, target 2026 wk8)

| stat | c | a | b | dist | k | rule |
|---|---|---|---|---|---|---|
| passing_yards | 0.984 | 0.1082 | 0.1792 | lognormal | 0.25 | min(stand-in 1.00, real 0.35, gated 0.25, 0.25) |
| receiving_yards | 0.942 | 0.4166 | 0.4166 | lognormal | 0.11 | min(stand-in 1.00, real 0.11, gated 0.25, 0.25) |
| rushing_yards | 0.984 | 0.3238 | 0.3238 | normal | 0.25 | min(stand-in 0.65, real 0.45, gated 0.25, 0.25) |
| receptions | 0.952 | 0.3051 | 0.3051 | negbin | 0.08 | min(stand-in 1.00, real 0.08, gated 0.25, 0.25) |
| passing_tds | 0.951 | 0.5153 | 0.6687 | negbin | 0.25 | min(stand-in 0.55, real 0.81, gated 0.25, 0.25) |

**TD market fit (production, 2025 wk14-16)**: usable player-weeks 379, TDs 66, o_TD fitted 1.199 over 66 TDs; k_TD argmin 0.22, capped 0.22, 379 cases. Unmatched odds names: 85 (e.g. Arizona Cardinals D/ST, Arizona Cardinals Defense, Atlanta Falcons D/ST, Atlanta Falcons Defense, Baltimore Ravens D/ST, Baltimore Ravens Defense, Brian Thomas Jr, Buffalo Bills D/ST, Buffalo Bills Defense, CJ Dippre, Calvin Austin III, Carolina Panthers D/ST, Carolina Panthers Defense, Cedrick Wilson Jr., Chicago Bears D/ST, Chicago Bears Defense, Chigoziem Okonkwo, Chris Rodriguez Jr., Cincinnati Bengals D/ST, Cincinnati Bengals Defense)

o_ou 1.064 from 0 two-way O/U rows before 2026 wk8 (none, fallback 1.064). TD: o 1.1987, k 0.0.
Wrote `C:\code\nfl_stats_project-master\model_v2_params.json` (gate_label 'passed').

## Served page and performance

Served on 127.0.0.1 (never port 8000; the script picks the first free port from 8001) with `NFL_STATS_DB` = a sqlite3 backup copy in `%TEMP%\nfl_backtest\served.db`. Test runs used `NFL_MODEL_VERSION=v2` and `NFL_MODEL_V2_PARAMS=%TEMP%\nfl_backtest\dev2\params_test.json` (identical to this run's params_test.json; the gate passed without the fallback, so no params_test_k0.json). The production run used the committed switch and the repo `model_v2_params.json` with both overrides unset.

| run | /generate-picks wall time | players / rows / flagged | DOM check | screenshot |
|---|---|---|---|---|
| 2025 wk16, v2 test params | 23.5 s | 379 / 1055 / 8 (all anytime TD, price-only) | DOM CHECK PASSED (8 flagged cards; 746 cards with the toggle) | `dev2\picks_2025wk16_v2.png` (521,771 bytes) |
| 2026 wk8, v2 test params | 21.7 s | 28 / 106 / 0 | DOM CHECK PASSED (zero-flag message "No picks with an edge above 3 pts. 106 markets evaluated; 78 have no side price"; 69 cards with the toggle) | `dev2\picks_2026wk8_v2.png` (539,840 bytes) |
| 2026 wk8, v1 | 39.1 s | 6 / 55 / (v1 rows are its flags) | n/a (v1 render unchanged) | - |
| 2026 wk8, production (committed v2 + repo params) | 21.2 s | 28 / 106 / 0 | DOM CHECK PASSED | `final\picks_2026wk8_repo.png` (542,015 bytes) |

v2 is 0.55x the v1 wall time on 2026 wk8 (21.7 s vs 39.1 s), so no performance red flag. On every run `GET /` returned 200 and `/static/nfl_stats.db`, `/static/.env`, `/nfl_stats.db`, `/.env` returned 404. Every server was stopped afterwards.

Josh Jacobs 2026 wk8 rushing 60.5: v1 prices it from one 2026 game (36 yards) as 88.7% Under. v2 (production params) uses 16 played games across 2026 and 2025 (weighted mean 55.0), model Under 57.5%, final Under 51.9%, market "no price", not flagged ("no price").


## Acceptance checklist (A4)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | G1 Brier <= 0.25 and LL <= ln 2 | PASS | Brier 0.2485, LL 0.6901 on 1,385 intersection rows (all 1,387 v2 rows: 0.2486 / 0.6903). Fallback not triggered |
| 2 | G2 bootstrap CI of Brier(v2) - Brier(v1) below 0 | PASS | -0.0455 [-0.0670, -0.0265] |
| 3 | G3 calibration, Bonferroni m = 6, z = 2.638 | PASS | real and proxy tables above; red flag: proxy [0.70, 1.00] bucket stated 0.729 vs observed 0.636 is outside its 95% interval (inside Bonferroni) |
| 4 | G4 TD v2 <= de-vigged market | PASS | 0.1244 vs 0.1244 (k_TD = 0, so v2 equals the market) |
| 5 | G5 2026 proxy v2 < v1 | PASS | 0.2427 vs 0.2712 on 1,970 cases; CI -0.0284 [-0.0384, -0.0188] |
| 6 | Bug #8 [6,6,7] >= [6,6,6], diff < 0.05 | PASS | `TestModelCore.test_bug8_receptions` |
| 7 | Small n widens | PASS | `test_cv_widens_with_small_n`, `test_normal_small_n_closer_to_half`, `test_negbin_small_n_closer_to_half`, `test_lognormal_widening_documented`; fitted b >= a for every stat |
| 8 | Jacobs 2026 wk8 | PASS | history first six 2026 wk7, 2025 wk17-13, raw mean 52.83; gamesUsed 16 = EWMA rows used; P_final(Under) 0.515 <= 0.65; P_model(Under) 0.559 (no red flag); not flagged, "no price" |
| 9 | Bug #9 | PASS | `TestV1Fixes.test_exception_returns_none_and_logs`, `test_check_drops_row_on_probability_error` |
| 10 | Outlier rules | PASS | far-line list identical to the independent re-computation (17 lines); all five Minshew wk16 lines excluded; Parker Washington kept (dev 0.46); Kupp 3.5, Goedert 4.5, Stafford 1.5/0.5 kept; boundary unit tests `TestOutlierRule` |
| 11 | Leak-free | PASS | every history asserted before its target; FIT_TEST asserted per family |
| 12 | Real DB untouched | PASS | SHA256 0B705BF2...3EE3CC before and after the harness runs and the served checks |
| 13 | Served page | PASS | DOM CHECK PASSED for 2025 wk16 and 2026 wk8; screenshots above |
| 14 | v1 parity on 2026 wk8 | PASS | 55/55 rows identical to the pre-edit baseline on threshold_rule, probabilityOver/Under, player_value (`checks\item7.py`) |
| 15 | Ship decision | PASS | gate passed without fallback; `model_v2_params.json` written by `--write-params --production-target 2026-8`, committed before the separate `MODEL_VERSION = 'v2'` commit |