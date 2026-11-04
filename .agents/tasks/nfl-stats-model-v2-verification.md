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
