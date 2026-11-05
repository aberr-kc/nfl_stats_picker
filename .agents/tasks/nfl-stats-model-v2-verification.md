# Model v2 implementation evidence

## Item 0. Preflight

- Branch: `model-v2` (HEAD `7f6f127`).
- `git status --short`: only untracked `.agents/tasks/*` files.
- Existing backup `nfl_stats.backup-20261030-143034.db`: 10,027,008 bytes.
- H0 = SHA256(`nfl_stats.db`) = `0B705BF2E0FA5FE1B405DAD15BA52068D9C20A45D1412D35C3BDDF1DDB3EE3CC`.
- `%TEMP%\nflmath\sched2025.json` exists.

## Item 1. v1 baseline (HEAD 56f0092 code, before any edit)

- `git archive 56f0092 -- '*.py' index.html team_stats_data.json static` extracted to `%TEMP%\nfl_backtest\baseline`, DB copied via sqlite3 backup from a `mode=ro` URI.
- `NFL_SEASON=2026 NFL_WEEK=8 python test_thresholds.py --json` (35.3 s): parses as `list 6 55` (6 players, 55 flagged rows).
- SHA256(`v1_2026wk8.json`) = `536D18BDF88E1F597EF092E2ED6DA9CD88277DD73A24A8D47E5844AE87E004E0`.

## Items 2-6

- `.venv\Scripts\python.exe -m unittest discover tests`: 53 tests OK after item 7 (4, 7, 13, 30, 48 after items 2-6).
- `import model_v2` leaves pandas and scipy unimported.

## Item 7. evaluate_week integration (`%TEMP%\nfl_backtest\checks\item7.py`, DB copy `item7.db`)

- (a) A4 #14 v1 parity: `NFL_MODEL_VERSION=v1 python test_thresholds.py --json` (40.7 s) vs baseline: 55 rows each, 0 baseline-only, 0 edited-only, 0 changed on threshold_rule/probabilityOver/probabilityUnder/player_value. PASS. (No 2026 wk8 row is touched by FR7 or the count-market rule.)
- (b) v2 smoke with dev params (last 6, c = 1, k = 0.25, not fitted): 26.3 s, 28 players, 106 rows, 0 flagged, no_price 78, excluded_far_line 2, model_errors 0. Josh Jacobs rush 60.5: gamesUsed 6, mean 52.8, P_model(Over) 28.1% (Under 71.9%), final Under 55.5%, marketSource none, reason "no price". With Jacobs in INCOMPLETE_DATA_PLAYERS: 0 Jacobs rows. PASS.
