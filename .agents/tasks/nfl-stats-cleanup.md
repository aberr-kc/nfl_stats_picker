# NFL Stats Cleanup: Report

Branch `cleanup`, created from `refresh-buttons` (HEAD `efc5655`). Nothing was merged or pushed, and no history was rewritten. The two uncommitted user changes (`pipeline_config.py` with ODDS_DAYS_AHEAD=4, `team_stats_data.json` fresh scrape) were never staged or modified. `git diff --stat` for them is identical before and after (2 files, 164 insertions, 164 deletions).

Plan followed: `.agents/tasks/nfl-stats-cleanup-plan.md` (first iteration; no review file existed).

## Commits on `cleanup`

```
> git log --oneline refresh-buttons..cleanup
762cce8 chore: stop tracking node_modules and .idea
a263f1e chore: remove abandoned React/Next/Vite scaffolding and stale notes
c7d3902 chore: remove unwired prototype modules and example config
2464901 chore: remove one-off data scripts that have already been applied
26ac1c7 chore: remove debug and one-off inspection scripts
```
plus the commit that adds this report (`docs: cleanup report`).

## Removed tracked files (`git rm`, recoverable from history)

Before deleting, every name was searched with `git grep` across tracked files (excluding `.agents/` notes). No in-use module, test, or the frontend imports, runs, or links any of them.

| File | Commit | Reason |
|---|---|---|
| `debug_adjustments.py`, `debug_buf.py`, `debug_db.py`, `debug_scrape.py`, `debug_test_thresholds.py` | 26ac1c7 | Ad-hoc debug scripts, no references |
| `check_db.py`, `check_kelce.py`, `inspect_db.py`, `Odds_DB_Check.py` | 26ac1c7 | One-off DB inspectors, no code references (only historical `.agents` notes) |
| `test_george_pickens.py` | 26ac1c7 | Root-level one-off script; `unittest discover tests` never runs it; no references |
| `add_more_completions.py`, `add_phi_completions.py` | 2464901 | One-off data patches, no references |
| `backfill_gp.py` | 2464901 | Job done: 0 NULL `gp` rows in seasons 2025 (38,528 rows) and 2026 (17,945 rows). The only NULL-gp rows are 144 junk rows with NULL season/week, which the script filters out and can't fix |
| `backfill_commence_times.py` | 2464901 | Can't update any row: current week 2026 wk9 has 0 NULL `commence_time` (6,107 rows); the remaining NULLs are past weeks, and the free `/events` endpoint it uses only lists upcoming/live games. New odds saves already store the value |
| `qb_passing_prediction.py`, `qb_prediction_clean.py` | c7d3902 | Unwired prototypes, no references |
| `game_script_adjustment.py`, `opportunity_adjustment.py` | c7d3902 | Only referenced by each other, `backup_working_version.py`, README and a stale summary. `test_thresholds.py` doesn't import them |
| `playoff_config_example.py` | c7d3902 | Example config, never imported |
| `run_pipeline.py` | c7d3902 | 10-line wrapper around `pipeline_config.run_pipeline()`; README documents `python pipeline_config.py` |
| `React_App.js`, `create_react_app.bat`, `create_nextjs_app.bat`, `create_vite_app.bat` | a263f1e | Abandoned frontend scaffolding; the app serves `index.html` |
| `backup_working_version.py` | a263f1e | Old manual backup script, superseded by git |
| `DELETE_DUPLICATE_FILE.txt` | a263f1e | Refers to `test_thresholds_new.py`, which no longer exists |
| `FINAL_FRONTEND_DISPLAY.md`, `FRONTEND_ADJUSTMENTS_SUMMARY.md`, `OPPORTUNITY_IMPLEMENTATION_SUMMARY.md`, `SEPARATE_STATS_SUMMARY.md`, `WORKING_VERSION_NOTES.md` | a263f1e | Stale pre-git notes, no references |
| `node_modules/` (4,256 files) | 762cce8 | Index only (`git rm -r --cached`). Jest toolchain with no `package.json`; the DOM tests use only Node built-ins. Already covered by `.gitignore` (`node_modules/`). Folder moved to the archive |
| `.idea/` (8 files) | 762cce8 | Index only (`git rm -r --cached`). `.idea/` added to `.gitignore`. **Folder left on disk** |

Edits that go with the deletions (comments/docs only, no code change):
- `models.py`: two comments no longer point at the deleted backfill scripts (2464901).
- `README.md`: the weather "Kickoff time" bullet no longer mentions `backfill_commence_times.py` (2464901); removed the `test_thresholds_new.py` (never existed), `opportunity_adjustment.py` and `game_script_adjustment.py` file lines, the "Game Script" and "Variance Scaling" bullets, and the "Game Script Adjustments" section, all of which described the deleted modules (c7d3902).
- `.gitignore`: added `.idea/` (762cce8).

## Archive (untracked / ignored files, moved, not deleted)

Folder: `C:\code\nfl_stats_archive-20261106` (relative paths kept).

| Item | Size |
|---|---|
| `node_modules\` | 4,256 files, 22,758,539 bytes |
| `backup_latest\` | 7 files, 127,951 bytes (old copies of app.py, index.html, etc. + BACKUP_INFO.md) |
| `backup_working_20251121_103323\` | 1 file, 1,466 bytes (old pipeline_config.py) |
| `backup_working_20251121_103343.zip` | 2,091,571 bytes |
| `backup_working_20251121_113506.zip` | 2,092,805 bytes |
| `nfl_stats.backup-20261030-090659.db` | 10,027,008 bytes |
| `nfl_stats.backup-20261030-111454.db` | 10,027,008 bytes |
| `nfl_stats.backup-20261030-143034.db` | 10,027,008 bytes |
| `nfl_stats.backup-20261105-205227.db` | 10,027,008 bytes |
| `.agents\tasks\runlocal.err.log` | 358 bytes |
| `.agents\tasks\runlocal.out.log` | 205 bytes |
| `.agents\tasks\server.err.log` | 240 bytes |
| `.agents\tasks\server.out.log` | 16,230 bytes |

All 13 moves succeeded (none locked). Kept in the repo folder: the newest backup `nfl_stats.backup-20261106-084735.db`, plus `nfl_stats.db`, `.env`, `.venv\`, `refresh_state.json` (untouched), `.idea\`, `__pycache__\`.

After the moves, `git status --short --ignored` (excluding untracked `.agents/tasks/*.md|*.json`) shows only:
```
 M pipeline_config.py
 M team_stats_data.json
!! .env
!! .idea/
!! .venv/
!! __pycache__/
!! nfl_stats.backup-20261106-084735.db
!! nfl_stats.db
!! refresh_state.json
!! tests/__pycache__/
```

## Kept, needs your decision

- `static/App.css`: `index.html` doesn't link it (the page uses inline styles), so its CSS is unused. It is the only file keeping `static/` in git, and `app.py` mounts `StaticFiles(directory="static")`, which fails at startup if the folder is missing (e.g. on a fresh clone). Delete it only together with the `/static` mount in `app.py`.
- `README.md` "Matchup Adjustments" and "Adjusted Statistics Formula" still describe matchup as a plain multiplier on pass and rush yards. The code now applies a display-only, shrunk matchup factor (`team_stats.MATCHUP_BETA`). This text doesn't reference a deleted file, so I left it; it may be worth rewriting.

## Report only (not changed)

- DB table `player_stats` still exists next to `player_weekly_stats` (legacy, unused by the app).
- The `weather` table contains test rows.
- 144 `player_weekly_stats` rows have NULL season, week and gp.
- 4,413 past-week `odds` rows (2025 wk14: 352, wk15: 359, wk16: 3,312; 2026 wk8: 390) have NULL `commence_time`; those games get no weather adjustment and the free `/events` endpoint can't fill them.

Schema and data are unchanged by this cleanup.

## Verification (run after all deletions and moves)

Python: `c:\code\nfl_stats_project-master\.venv\Scripts\python.exe` (`$py`). All commands from the repo root.

### 1. No remaining references (`git --no-pager grep -n -F <name> -- ':!.agents'`)

```
debug_adjustments: 0 hits        debug_buf: 0 hits             debug_db: 0 hits
debug_scrape: 0 hits             debug_test_thresholds: 0 hits check_db: 0 hits
check_kelce: 0 hits              inspect_db: 0 hits            Odds_DB_Check: 0 hits
test_george_pickens: 0 hits      add_more_completions: 0 hits  add_phi_completions: 0 hits
backfill_gp: 0 hits              backfill_commence_times: 0 hits
qb_passing_prediction: 0 hits    qb_prediction_clean: 0 hits   game_script_adjustment: 0 hits
opportunity_adjustment: 0 hits   playoff_config_example: 0 hits
run_pipeline: 2 hits
  pipeline_config.py:84:def run_pipeline():
  pipeline_config.py:109:    run_pipeline()
backup_working_version: 0 hits   React_App: 0 hits             create_react_app: 0 hits
create_nextjs_app: 0 hits        create_vite_app: 0 hits       DELETE_DUPLICATE_FILE: 0 hits
FINAL_FRONTEND_DISPLAY: 0 hits   FRONTEND_ADJUSTMENTS_SUMMARY: 0 hits
OPPORTUNITY_IMPLEMENTATION_SUMMARY: 0 hits                     SEPARATE_STATS_SUMMARY: 0 hits
WORKING_VERSION_NOTES: 0 hits    test_thresholds_new: 0 hits
node_modules: 1 hit   .gitignore:9:node_modules/
backup_latest: 0 hits            backup_working_2025: 0 hits
```
The two `run_pipeline` hits are the function inside `pipeline_config.py`, not the deleted `run_pipeline.py`. Historical mentions remain only in old task reports (`.agents/tasks/nfl-stats-bugfixes-verification.md`, `nfl-stats-health-fixes.md`, `nfl-stats-weather-source-verification.md`, `nfl-stats-weather-source.md`), which were kept as instructed.

### 2. Compile and import

```
> $f = git --no-pager ls-files '*.py'; & $py -m py_compile @f
files: Odds_vs_Stats_Check.py app.py backtest.py fetch_stats.py model_v2.py models.py odds_api.py pipeline_config.py probability_calc.py refresh_jobs.py run_local.py save_to_db.py stadiums.py target_share_calc.py team_stats.py teams.py test_thresholds.py tests/__init__.py tests/live_refresh_check.py tests/live_refresh_server.py tests/test_model_v2.py tests/test_refresh.py weather_adjustments.py weather_api.py
py_compile exit=0

> $env:NFL_STATS_DB="$env:TEMP\nfl_cleanup_import.db"; & $py -c "import app, refresh_jobs, pipeline_config, test_thresholds, backtest; print('imports OK')"
imports OK
import exit=0
```
`NFL_STATS_DB` pointed at a temp file so the import-time `create_all()` in `models.py` didn't touch the real DB.

### 3. Unit tests

```
> $py -m unittest discover tests
Ran 82 tests in 0.930s
OK
exit=0
```
(Baseline before any deletion: `Ran 82 tests in 0.826s`, `OK`.)

### 4. Live server on port 8011 (user's server on 8000 left alone)

Setup: `$env:TEMP\nfl_cleanup\` holds a copy of `nfl_stats.db` (made with `sqlite3` `.backup()` from a read-only connection), `team_stats_data.json` and `refresh_state.json`. `NFL_STATS_DB`, `NFL_TEAM_STATS_PATH`, `NFL_REFRESH_STATE` pointed at those copies. The server was `tests\live_refresh_server.py --port 8011` (paid `call_odds_api` blocked, `fetch_event_odds` mocked), started through a small temp wrapper (`$env:TEMP\nfl_cleanup\run_verify.py`, not in the repo) that also replaced `odds_api._get_free_events` with a canned one-game response. As a result, The Odds API was never contacted, not even the free `/events` endpoint. No refresh POST endpoint was called (the refresh DOM test answers every POST with an in-process stub).

Server log:
```
VERIFY models.DB_PATH=C:\Users\andre\AppData\Local\Temp\nfl_cleanup\nfl_stats.db
VERIFY app engine=C:\Users\andre\AppData\Local\Temp\nfl_cleanup\nfl_stats.db
VERIFY team_stats.TEAM_STATS_PATH=C:\Users\andre\AppData\Local\Temp\nfl_cleanup\team_stats_data.json
VERIFY refresh state=C:\Users\andre\AppData\Local\Temp\nfl_cleanup\refresh_state.json
VERIFY paid call blocked, fetch_event_odds mocked
INFO:     Uvicorn running on http://127.0.0.1:8011 (Press CTRL+C to quit)
VERIFY free /events mocked (no network)      (x5, from the preview GETs)
INFO:test_thresholds:evaluate_week v2 2026 wk9: players checked 2659, markets evaluated 1287, flagged 45, no_price 0, excluded_far_line 22, model_errors 0, skipped_db_error 0, v1_probability_errors 0
```
No POST requests appear in the server log.

HTTP GETs:
```
GET / -> 200 text/html; charset=utf-8 80042 bytes
GET /static/App.css -> 200 text/css; charset=utf-8 4406 bytes
GET /refresh/status -> 200 application/json 1327 bytes
GET /generate-picks -> 200 1395634 bytes   (JSON keys: success, players, count, model)
```

DOM checks:
```
> node tests\check_picks_dom.js http://127.0.0.1:8011     (exit 0)
/generate-picks 28.4s: 382 players, 1287 rows, 45 flagged, model {"version":"v2","window_label":"weighted, half-life 8 games","window_n":null,"edge_margin_pts":3,"min_games_for_flag":3,"params_fitted_on":"proxy 2025 wk4-17 + 2026 wk2-7; O/U k: 2025 wk14-16 odds; TD: 2025 wk14-16 odds","gate_label":"passed","ou_k_all_zero":false,"td_k_zero":true}
showUnflagged=false: 25 cards (10 on page 1), 60 rows; showUnflagged=true: 809 cards (10 on page 1), 1287 rows
adjustment columns: shown on 324 of 809 cards, hidden on 485
render written to C:\Users\andre\AppData\Local\Temp\nfl_backtest\picks_render.html
DOM CHECK PASSED

> node tests\check_refresh_dom.js http://127.0.0.1:8011   (exit 0)
(a) real preview: 1 games, 9 est. credits, quota 2500; confirm shown 1x; POSTs 0
    confirm text: "Fetch odds for 1 upcoming games (next 4 days)?\n  Buffalo Bills @ Kansas City Chiefs (07/11/2026, 10:14:16 am)\n\nEstimated cost: up to 9 credits (1 games × 9 markets × 1 region).\nRemaining quota: 2500 credits (live).\n\nThis spends paid Odds API credits."
(b) confirmed fake flow: POST {"confirm_games":2}, 3 status polls, status-odds="Last run: 05/11/2026, 10:00:00 pm · ✓ 2/2 games, 18 credits, 0 left"
(c) 409 -> "Another refresh (stats) is already running."; 403 -> "Refresh is only allowed from the computer running the server (set ALLOW_REMOTE_REFRESH=1 to allow LAN use)."
REFRESH DOM CHECK PASSED
```
"(a) real preview" is the test's own label. Here the server's `/events` was the canned mock (1 fake game, mock quota), so the numbers don't reflect the live Odds API.

Shutdown: both 8011 processes stopped; `Get-NetTCPConnection -State Listen -LocalPort 8011` → 0 listeners. Env vars removed.

### 5. User's server and working tree

```
user server GET / on 8000 -> 200        (run_local.py, auto-reloaded after the deletions; GET only)
> git --no-pager diff --stat
 pipeline_config.py   |   2 +-
 team_stats_data.json | 326 +++++++++++++++++++++++++--------------------------
 2 files changed, 164 insertions(+), 164 deletions(-)
> git status --short   (excluding untracked .agents/tasks/*.md|*.json)
 M pipeline_config.py
 M team_stats_data.json
> Test-Path nfl_stats.db, .env, refresh_state.json, nfl_stats.backup-20261106-084735.db, .venv, .idea
True True True True True True
```

## How to restore something

- A deleted tracked file: `git checkout refresh-buttons -- <file>` (e.g. `git checkout refresh-buttons -- backfill_gp.py`), then commit it.
- Re-track `.idea/`: remove the `.idea/` line from `.gitignore`, then `git add .idea`.
- Anything archived: copy it back from `C:\code\nfl_stats_archive-20261106\<same relative path>`, e.g. `Copy-Item -Recurse C:\code\nfl_stats_archive-20261106\backup_latest c:\code\nfl_stats_project-master\`. `node_modules` is not needed by any test; if you want it back, copy the folder (it stays ignored by git).
