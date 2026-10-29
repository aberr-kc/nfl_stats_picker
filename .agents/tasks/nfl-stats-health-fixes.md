# NFL stats project: health fixes report

All five fixes you approved are done on the `health-fixes` branch and passed review. The app starts, serves the page, and runs `/generate-picks` against 2026 data. Nothing has been merged or pushed. Three steps are left for you (see "What you still need to do").

## What changed

**H1. Dependencies.** A `.venv` virtual environment is created and git-ignored. `requirements.txt` now pins the eight direct dependencies with exact versions: SQLAlchemy, pandas, numpy, fastapi, uvicorn, requests, beautifulsoup4 and python-dotenv. The last three were missing before, so a fresh install could not run the app. `import app, bs4, dotenv, numpy` succeeds in the venv.

**C1. Security.**
- **a. API keys.** The five Odds API keys are gone from `odds_api.py`. They now load from a git-ignored `.env` file (`ODDS_API_KEYS`, comma-separated) via python-dotenv. `.env.example` shows the format with placeholders. If no keys are set, the module logs a warning, and `call_odds_api` raises a clear error before making any HTTP call. A check found 0 tracked files containing a key.
- **b. Static files.** `/static` used to serve the whole project folder, including the database, `.env` and source code. It now serves only the new `static/` folder. `App.css` moved there.
- **c. Bind address.** `run_local.py` now listens on `127.0.0.1` by default. To share on your LAN, use `--host 0.0.0.0` or set `HOST=0.0.0.0`. The "Share with friends" URL and a warning print only in that case.
- **d. Paths.** `app.py` and `models.py` now use absolute paths based on the file location, so running from another folder no longer serves the wrong files or creates a stray empty database.

**C2. Database schema.** The `odds` and `weather` tables were missing the `season_type` column that the code expects, which caused `no such column` errors. `models.py` now adds the column on import if it is missing, using `DEFAULT 'regular'`. It is safe to run repeatedly. The migration was applied to the real DB after a backup. All 4,023 existing odds rows are now marked `regular`. `Odds_DB_Check.py` no longer crashes; it prints player IDs instead of names, because the model has no player relationship.

**H2. Season and week.** `pipeline_config.py` no longer hardcodes 2025 / week 14. It picks the season and week in this order:
1. `NFL_SEASON` and `NFL_WEEK` environment variables (both must be set)
2. `SEASON_OVERRIDE` / `WEEK_OVERRIDE` in the file (both must be set)
3. Sleeper's live NFL state (5-second timeout)
4. Fallback: 2026, week 8

The odds and comparison week is the current week, and the stats week is the week before it. `test_thresholds.py` logs which season, week and source it used. Hardcoded years were also updated in `save_to_db.py`, `inspect_db.py` (now with bound query parameters) and `index.html` (the season dropdown offers 2026, selected, and 2025).

**H4. Weather stub.** `weather_api.py` used to return fake −4 °C weather for every game. It now returns "no data", and `weather_adjustments.py` returns neutral 1.0 factors with the text "No weather data (adjustment disabled)". The cold, wind and rain rules are still there for a real weather source later.

## Commits on `health-fixes`

On top of `fdab363`, oldest first:

| Hash | Message |
|---|---|
| `2b14cb4` | chore: add venv ignore, beautifulsoup4/numpy/python-dotenv, pin dependency versions (H1) |
| `78885cb` | fix: disable hardcoded weather stub, use neutral factors when no data (H4) |
| `a77522a` | fix: add idempotent season_type migration for odds and weather tables (C2) |
| `8fc060c` | fix: load Odds API keys from .env instead of source (C1a) |
| `0de48b5` | fix: serve only static/ folder instead of project root (C1b) |
| `2c5c75b` | fix: run_local binds 127.0.0.1 by default, LAN sharing opt-in (C1c) |
| `3250703` | fix: mount only static/ folder instead of project root (C1b, part 2) |
| `2c064bf` | feat: derive season/week from Sleeper, update hardcoded years (H2) |
| `3fd9f88` | chore: record end-to-end verification of health fixes |

This report is committed on top of these.

## Database backup

Before any change touched the DB, it was copied to `nfl_stats.backup-20261030-090659.db` in the project folder. The backup is 10,027,008 bytes, the same as the original, and the SHA256 hashes matched. It is git-ignored by the `*.db` rule.

## 2026 data loaded

**7 weeks** (weeks 1–7) of 2026 regular-season stats, **15,865 rows** in total:

| Week | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| Rows | 2,331 | 2,352 | 2,357 | 2,386 | 2,241 | 2,103 | 2,095 |

The 2025 data is unchanged at 38,528 rows. No odds were fetched, so no paid quota was used.

## Verification

The server ran from the venv with `uvicorn app:app --host 127.0.0.1 --port 8000` and listened on 127.0.0.1 only.

| Check | Result |
|---|---|
| `GET /` | 200 text/html, page contains "NFL STAT PICKS" and the 2026 option |
| `GET /static/App.css` | 200 text/css (4,406 bytes) |
| `GET /static/odds_api.py` | 404 |
| `GET /static/nfl_stats.db` | 404 |
| `GET /static/.env` | 404 |
| `GET /static/pipeline_config.py` | 404 |
| `GET /players` | 200 application/json |
| `GET /generate-picks` | 200 `{"success":true,"players":[],"count":0}`, took 289 s |

**0 picks is expected.** There are no 2026 odds in the DB yet, so no player can be compared against a line. Picks will appear after you fetch odds (step 3 below).

The server log confirmed the right season and week:
- `Generating picks for Season=2026, Week=8 (config source: sleeper)`
- `DEBUG: Checked 2638 players, 470 had stats, 0 had odds, 0 flagged`
- 0 `no such column` errors in either log

After the server stopped, port 8000 was free. `python run_local.py` with no flags listened on `127.0.0.1:8000` and printed the loopback-only hint.

`py_compile` passed (exit 0) for all 11 touched Python files: `app.py`, `run_local.py`, `odds_api.py`, `models.py`, `Odds_DB_Check.py`, `pipeline_config.py`, `test_thresholds.py`, `save_to_db.py`, `inspect_db.py`, `weather_api.py` and `weather_adjustments.py`.

Season/week config was also checked for the other paths. Env override `NFL_SEASON=2025 NFL_WEEK=16` gave 2025 / stats week 15 / week 16 (source `env`). With Sleeper forced to fail, it gave 2026 / week 8 (source `fallback`).

## What you still need to do

1. **Rotate all five Odds API keys** at the-odds-api.com, then put the new ones in `.env` as `ODDS_API_KEYS=key1,key2,...`. The old keys are no longer in the code, but anyone with the repo can still read them in git history (commit `fdab363` and earlier). They are also stored in full in the `api_usage` DB table and in the git-ignored `backup_*` copies of `odds_api.py`. This branch does not rewrite history.
2. **Merge `health-fixes`** into your main branch when you're happy with it. Nothing has been merged or pushed.
3. **Fetch odds for the current week** to get picks, for example with `.\.venv\Scripts\python.exe pipeline_config.py`. This uses paid Odds API quota, which is why it wasn't run here. Do it after step 1, with the new keys.

## Smaller issues the review noted (not fixed)

- Every `/generate-picks` request calls Sleeper to work out the week. If Sleeper is down, each request waits up to 5 seconds before using the fallback.
- The code ignores Sleeper's `season_type`. In the offseason, preseason or playoffs, it may pick a week that doesn't match the regular-season data. If that happens, set `NFL_SEASON` and `NFL_WEEK`.
- `inspect_db.py` still opens the DB with a relative path, so run it from the project folder.
- `index.html` still requests `fix_columns.js`, which doesn't exist. This was already the case before and was out of scope.
