# NFL Stat Picks

A small local web app that estimates the probability of NFL player-prop outcomes (passing, rushing and receiving yards, receptions, passing TDs, anytime TD) and flags bets where its estimate beats the best available price by more than 3 percentage points.

It pulls player stats from Sleeper, team stats from TeamRankings and game weather from Open-Meteo (all free), and player-prop odds from The Odds API (uses your own API credits). Everything runs on your computer and is stored in a local SQLite file.

> **Disclaimer.** This is a hobby / research project, not betting advice. In the back-test (2025 weeks 14-16, about 1,400 graded lines) the model's final probabilities scored a Brier score of 0.2485 against 0.25 for a coin flip, with a 95% interval that includes 0.25. In plain terms, it is roughly as accurate as the betting market itself, not better. Don't bet money you can't afford to lose.

## Contents

1. [Requirements](#requirements)
2. [Install](#install)
3. [Get your own Odds API key](#get-your-own-odds-api-key)
4. [First run](#first-run)
5. [Weekly workflow](#weekly-workflow)
6. [Reading the picks page](#reading-the-picks-page)
7. [How the model works](#how-the-model-works)
8. [Configuration reference](#configuration-reference)
9. [Sharing on your local network](#sharing-on-your-local-network)
10. [Validation and tests](#validation-and-tests)
11. [Project structure](#project-structure)
12. [Troubleshooting](#troubleshooting)

## Requirements

- Windows, macOS or Linux. Everything below was tested on Windows 11 with PowerShell. The macOS/Linux commands are the standard equivalents and are marked **untested**.
- **Python 3.12** (tested with 3.12.0). Python 3.11 should also work (`pandas==3.1.0` needs 3.11 or newer), but it was not tested.
- **git**.
- An internet connection (Sleeper, TeamRankings, Open-Meteo, The Odds API).
- Optional: **Node.js** (tested with v24) to run the two page checks in `tests/`. The app itself doesn't need it.

## Install

Run every command from the project folder. The database path is relative to it.

**Windows (PowerShell)**

```powershell
git clone <repo URL> nfl_stats_project
cd nfl_stats_project
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

If PowerShell refuses to run `Activate.ps1` ("running scripts is disabled"), allow it for the current window only and try again:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux (untested)**

```bash
git clone <repo URL> nfl_stats_project
cd nfl_stats_project
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

`requirements.txt` pins exact versions (SQLAlchemy 2.1.6, pandas 3.1.0, numpy 2.5.4, fastapi 0.162.0, uvicorn 0.54.0, requests 2.34.2, beautifulsoup4 4.15.0, python-dotenv 1.2.4). All of them install cleanly on Python 3.12 on Windows.

Activate the venv (`.\.venv\Scripts\Activate.ps1` or `source .venv/bin/activate`) in every new terminal before running the commands below.

## Get your own Odds API key

Everyone needs their **own** key. Don't share keys: the free plan is small and a shared key runs out fast.

1. Go to [the-odds-api.com](https://the-odds-api.com/) and choose a plan under "Get Access". At the time of writing the **Starter** plan is free and gives **500 credits per month**. Paid plans start at 20,000 credits for $30/month. Check the site for current prices.
2. Enter your email. The key arrives by email.
3. Open `.env` (the copy of `.env.example` you made during install) and put your key after `ODDS_API_KEYS=`:

   ```
   ODDS_API_KEYS=abc123yourkey
   ```

   You can list several keys separated by commas (`ODDS_API_KEYS=key1,key2`). They are tried in order, and when one runs out of quota the app moves on to the next one.

Without a key, everything works except **Fetch odds**, which shows "No Odds API keys configured. Set ODDS_API_KEYS in .env (see .env.example)."

**What costs credits.** Only fetching player-prop odds. The app calls The Odds API's event-odds endpoint once per game, asking for 9 markets (`player_pass_yds`, `player_pass_tds`, `player_receptions`, `player_reception_yds`, `player_rush_attempts`, `player_rush_yds`, `player_anytime_td`, `spreads`, `totals`) in one region. The Odds API charges 1 credit per market returned per region ([v4 docs](https://the-odds-api.com/liveapi/guides/v4/)), so each game costs **up to 9 credits per fetch**. A full 16-game week costs up to about 144 credits, so the free 500 credits cover roughly 3 full weeks (about 55 games) per month. Fetch once per slate, not every hour.

**What is free.** Sleeper player stats, the TeamRankings team-stat pages, Open-Meteo weather, and The Odds API's `/events` list (the free preview behind the Fetch odds confirmation; the v4 docs say it doesn't count against the quota).

**Region.** `odds_api.py` asks for the `au` region (Australian bookmakers such as Sportsbet, TAB and Neds), because that is where the original author bets. If you're in the US, change `"regions": "au"` to `"regions": "us"` in `fetch_event_odds` in `odds_api.py` (other options are `us2`, `uk`, `eu`). Keep **one** region: the cost is multiplied by the number of regions, and the cost estimate in the confirmation assumes one.

**Keep your key private.** `.env` is listed in `.gitignore`. Never commit it, paste it into an issue, or send it to anyone. The local database (`nfl_stats.db`) is also git-ignored because its `api_usage` table stores your key strings. If a key leaks, get a new one from The Odds API and stop using the old one.

## First run

**1. Load the stats history (once, free, about 40 seconds).**

```powershell
python save_to_db.py --all
```

This downloads every completed regular-season week of last season (weeks 1-18) and of the current season from Sleeper, and then refreshes the team stats from TeamRankings. It creates `nfl_stats.db` on first use. It is safe to run again: each week is replaced, never duplicated. On a test run in November 2026 it loaded 26 weeks (58,962 rows) in 36 seconds and ended with:

```
Done: 26 weeks requested, 58962 rows saved, weeks with 0 rows: none
```

Why the full history: the model uses each player's last 17 games actually played, across seasons, and won't flag a pick from fewer than 3 games. The weekly Refresh stats button only adds the newest week.

**2. Start the app.**

```powershell
python run_local.py
```

**3. Open http://localhost:8000.** Press Ctrl+C in the terminal to stop the app.

## Weekly workflow

The season and week come from Sleeper automatically (Sleeper's "week" is the current/upcoming week). The picks page has three buttons. Run them in order:

| Button | What it does | Cost | Terminal equivalent |
|---|---|---|---|
| **1. Refresh stats (free)** | Loads the last completed week from Sleeper and re-scrapes team stats from TeamRankings. | Free | `python save_to_db.py` then `python team_stats.py` |
| **2. Fetch odds (uses credits)** | First calls the free `/events` list, then asks you to confirm: number of upcoming games in the next `ODDS_DAYS_AHEAD` days, estimated credits (games x 9) and remaining quota. Only after you click OK does it download the odds. | Up to 9 credits per game | `python odds_api.py` (**spends credits with no confirmation**) |
| **3. Generate picks** | Runs the model on what's in the database. No API calls. Takes a few seconds to about 30 seconds. | Free | `python test_thresholds.py` (table) or `python test_thresholds.py --json` |

The last run of each step is shown under the buttons and saved in `refresh_state.json` (local only, git-ignored).

Things to know:

- **Odds window.** `ODDS_DAYS_AHEAD` in `pipeline_config.py` sets how many days ahead Fetch odds looks for games, starting now. The committed value is 2. On a Friday, use 4 so that Sunday and Monday games are included.
- **Season/week override.** If Sleeper is wrong or unreachable, pin both values for one terminal session, for example `$env:NFL_SEASON="2026"; $env:NFL_WEEK="10"` (PowerShell) or `export NFL_SEASON=2026 NFL_WEEK=10` (macOS/Linux, untested), or put them in `.env` for the web app. Set both or neither.
- **Avoid `python pipeline_config.py`.** It runs stats, odds and picks in one go and spends credits with no confirmation.
- The bulk `python save_to_db.py --all` is only needed once (or if you delete the database).

## Reading the picks page

Each card is one player and one market. The badge shows `EDGE +x pts` when at least one line is flagged, `No edge` when it has a price but no edge, or `No price` when no bookmaker price was fetched. Flagged rows are highlighted in green. Hover over an unflagged row to see why it wasn't flagged (for example "line far from player mean").

| Column | Meaning |
|---|---|
| **Weighted avg (games played)** | The model's expected value for the stat: a weighted average of the player's recent played games, slightly shrunk (see the model section). For anytime TD the column is `TD rate (λ/game)`, the expected TDs per game. |
| **Adjusted Stat / Adjustments** | Weather and matchup notes. **Display only**, they never change the probabilities or flags. These two columns only appear on a card when at least one line has an adjustment of 5% or more. |
| **Line** | The bookmaker line, e.g. 64.5 yards. |
| **Side** | `Over` or `Under` (or `Yes` for anytime TD), whichever has the larger edge. |
| **Price (book)** | The best decimal price for that side across bookmakers, and which book(s) offer it. |
| **Model %** | The stats model's probability for that side. |
| **Market %** | The bookmakers' probability with the margin removed (median across books that quote both sides). `(cross-book)` or `(one-sided, ÷1.064)` show a fallback was used; `no price` means none was available. |
| **Final %** | The blend the app actually uses: `Final = Market + k x (Model - Market)`. |
| **Edge (pts)** | `Final - 1 / price`, in percentage points. A row is flagged when this is above 3. |

**Worked example (passing yards, k = 0.25).** Over 245.5: Model 64%, Market 52%.
Final = 52 + 0.25 x (64 - 52) = **55%**. The best price is 1.95 at one book, which implies 1 / 1.95 = 51.3%.
Edge = 55 - 51.3 = **+3.7 pts**, which is above 3, so the row is flagged.

k is fitted per stat and capped at 0.25, so the model can move the market's probability by at most a quarter of the gap. That cap is deliberate: the market is hard to beat.

**Anytime TD.** The TD model's k is 0, so Final = Market. Any TD edge comes purely from one bookmaker offering a better price than the market's fair price. These rows show `(price only)` in the Edge column and `(best-price edge, model weight 0)` on the badge.

**Show unflagged markets (N).** By default only cards with a flagged line are shown. This button also shows the cards with no flag, so you can see every market the model checked.

**"No flagged players found."** There are no odds in the database for the current week yet. Run Fetch odds.

**"No picks with an edge above 3 pts. N markets evaluated; M have no side price..."** Odds were found but no line beats its price by more than 3 points. Use Show unflagged markets to see them. If many have no side price, fetch odds again closer to the games.

## How the model works

The live model is **v2** (`model_v2.py`, parameters in `model_v2_params.json`). In short:

1. **Games actually played.** Only games where the player played count (Sleeper's `gp > 0`). Weeks he missed are skipped, not counted as zero.
2. **Weighted average.** An exponentially weighted average (EWMA) of up to the last 17 played regular-season games, crossing into last season, with a half-life of 8 games (a game 8 games ago counts half as much as the latest). The result is multiplied by a per-stat factor c between 0.94 and 0.98, which corrects a small upward bias found in the back-test.
3. **Spread per stat.** The coefficient of variation is `CV^2 = a + b / n_eff`, so players with fewer games get a wider distribution. For rushing yards, the player's own standard deviation is mixed in once he has 6 or more games.
4. **Distribution per stat.** Passing and receiving yards use a log-normal, rushing yards a normal, receptions and passing TDs a negative binomial. P(Over 64.5) is P(X ≥ 65). Whole-number lines are skipped (a push is possible).
5. **Market anchoring.** The model probability is blended with the no-vig market probability: `Final = Market + k x (Model - Market)`, with k per stat up to 0.25 (currently passing yards 0.25, rushing yards 0.25, passing TDs 0.25, receiving yards 0.11, receptions 0.08, anytime TD 0).
6. **Flag rule.** Flag only if a price exists, the edge is more than **3 points**, the player has at least **3 games**, and the line isn't far from his average (more than 60% away and at least 10 yards or 2 catches/TDs). A bookmaker line more than 25% from the median line is dropped first as a likely stale or alternate line.
7. **Anytime TD.** A Gamma-Poisson estimate of TDs per game, shrunk toward a position average (QB, RB, WR, TE) with weight equal to 4 games. P(TD) = 1 - e^(-λ).

**Matchup and weather are display only.** They appear in the Adjustments column but are never used in Model %, Final %, edge or flags.

- **Matchup** (opponent's yards or completions allowed per game ÷ league average, scaled by 0.3) is shown for passing yards, receiving yards and receptions. It is **off for rushing yards**: a check of 888 running-back games (2025 and 2026) found good run defenses cost about 10% per carry, but backs get slightly more carries against them, so the net effect was +1 to +4 yards, which is indistinguishable from zero. Bookmaker lines already move with the matchup 3-4 times more than results do, and the model is anchored to those lines, so adding it again would double-count.
- **Weather** (Open-Meteo forecast at the home stadium at kickoff; domes and retractable roofs are neutral) adjusts for cold, wind, and rain or snow. It stays out of the model because the same check found its rushing bonuses weren't supported by 2025-2026 results and made the picks slightly less accurate.

**Model v1** (the original) used a 3-game average, fixed thresholds (e.g. 20 receiving yards over the line) and a normal-distribution probability. The back-test scored it clearly worse than v2 (Brier 0.294 vs 0.249). To switch back, set `MODEL_VERSION = 'v1'` in `pipeline_config.py` or `NFL_MODEL_VERSION=v1` in `.env`.

## Configuration reference

### `pipeline_config.py`

| Setting | Meaning |
|---|---|
| `SEASON`, `CURRENT_WEEK` | Worked out automatically. Priority: `NFL_SEASON`/`NFL_WEEK` env vars, then `SEASON_OVERRIDE`/`WEEK_OVERRIDE`, then Sleeper, then `FALLBACK_SEASON`/`FALLBACK_WEEK` (2026 / 8) if Sleeper is unreachable. |
| `ODDS_WEEK`, `COMPARISON_WEEK` | The current week (odds and picks). |
| `STATS_WEEK` | The last completed week (current week - 1). Used by Refresh stats. |
| `ODDS_DAYS_AHEAD` | Days ahead (from now) that Fetch odds looks for games. |
| `MODEL_VERSION` | `'v2'` (default) or `'v1'`. |
| `V2_EDGE_MARGIN` | Minimum edge to flag: `0.03` (3 points). |
| `V2_MIN_GAMES_FOR_FLAG` | Minimum played games to flag: `3`. |
| `THRESHOLDS` | v1 only: how far the average must beat the line. |
| `INCOMPLETE_DATA_PLAYERS` | Player names to skip. |

### Environment variables

`run_local.py` reads `.env` for the web app; real environment variables take priority. `ODDS_API_KEYS` is read from `.env` by every script. For the other variables in terminal scripts, set them in the shell.

| Variable | Default | Meaning |
|---|---|---|
| `ODDS_API_KEYS` | (none) | Your Odds API key(s), comma-separated, tried in order. |
| `HOST` | `127.0.0.1` | Interface the web app binds to. `0.0.0.0` shares it on your network. |
| `ALLOW_REMOTE_REFRESH` | off | `1` lets other computers use the refresh buttons. |
| `NFL_SEASON`, `NFL_WEEK` | from Sleeper | Pin the season and current week. Set both or neither. |
| `NFL_MODEL_VERSION` | `MODEL_VERSION` | `v1` or `v2`. |
| `NFL_STATS_DB` | `nfl_stats.db` | SQLite database file. |
| `NFL_MODEL_V2_PARAMS` | `model_v2_params.json` | Fitted model parameters. |
| `NFL_TEAM_STATS_PATH` | `team_stats_data.json` | Team stats for matchup notes. |
| `NFL_REFRESH_STATE` | `refresh_state.json` | Last-run info for the buttons. |
| `PYTHONIOENCODING` | (system) | Set to `utf-8` if the console can't print emoji (see Troubleshooting). |

`backtest.py` also uses the Windows `TEMP` folder for its database copy.

## Sharing on your local network

```powershell
python run_local.py --host 0.0.0.0
```

(or `HOST=0.0.0.0` in `.env`). The app prints the address to share, e.g. `http://192.168.1.20:8000`. Anyone on your network can then open the page and generate picks while it runs. There is no login, so only do this on a network you trust.

The **Refresh stats** and **Fetch odds** buttons only work from the computer running the app, because Fetch odds spends your credits. Other computers get "Refresh is only allowed from the computer running the server". To allow them, set `ALLOW_REMOTE_REFRESH=1` in `.env`. Your firewall may also ask to allow Python on port 8000.

## Validation and tests

**Unit tests** (no network, temporary databases, no credits):

```powershell
python -m unittest discover tests
```

Expected: `Ran 86 tests ... OK`.

**Page checks** (optional, needs Node.js). Start a second copy of the app on a spare port, then point the checks at it. Neither check spends credits: the refresh check answers every POST with a stub and only calls the free preview.

```powershell
python -m uvicorn app:app --host 127.0.0.1 --port 8012
# in a second terminal:
node tests\check_picks_dom.js http://127.0.0.1:8012
node tests\check_refresh_dom.js http://127.0.0.1:8012
```

Each prints `DOM CHECK PASSED` / `REFRESH DOM CHECK PASSED`.

`tests/live_refresh_server.py` and `tests/live_refresh_check.py` are a heavier end-to-end check of the refresh buttons. The server refuses to start unless `NFL_STATS_DB`, `NFL_TEAM_STATS_PATH` and `NFL_REFRESH_STATE` point at copies, and it blocks the paid odds call.

**Back-test** (`python backtest.py`). Fits and grades model v1 and v2 on a **copy** of your database under `%TEMP%\nfl_backtest\<timestamp>\` (your real database is checked by hash and never changed) and writes `report.md` there with Brier scores, log loss, calibration tables and a pass/fail gate. The evaluation weeks are fixed (2025 weeks 14-16), and it needs odds stored in the database for those weeks. On a fresh install there are none, so it runs (about 2 minutes) but grades 0 rows and reports "gate failed"; that is expected. The shipped `model_v2_params.json` was fitted on the original author's odds history, so don't use `--write-params` unless you have built up your own odds history.

## Project structure

| Path | What it is |
|---|---|
| `run_local.py` | Starts the web app on port 8000 (loads `.env`). |
| `app.py` | FastAPI app: the page, `/generate-picks`, the refresh endpoints and player/team lookups. |
| `index.html` | The whole front end (picks page, refresh buttons, player and matchup views). |
| `static/App.css` | Styles served under `/static`. |
| `refresh_jobs.py` | Background jobs behind the three buttons, odds preview, last-run state. |
| `pipeline_config.py` | Season/week detection and settings (see Configuration). |
| `save_to_db.py` | Saves Sleeper stats to the database (`--all` for the first-time load). |
| `fetch_stats.py` | Downloads weekly player stats and the player list from Sleeper. |
| `odds_api.py` | The Odds API client: free events list, paid event odds, key rotation, usage tracking. |
| `team_stats.py` | Scrapes TeamRankings team stats into `team_stats_data.json`; matchup notes. |
| `teams.py` | Team abbreviations and names. |
| `stadiums.py` | Home stadium location and roof type per team. |
| `weather_api.py` | Game weather from Open-Meteo. |
| `weather_adjustments.py` | Weather factors for the Adjustments column. |
| `models.py` | Database tables (SQLAlchemy). |
| `test_thresholds.py` | Builds the picks: loads history and odds, runs v1 or v2, adds adjustments. Also a command-line picks report. |
| `model_v2.py` | Model v2: weighted mean, distributions, market probability, anchoring, flag rule. |
| `model_v2_params.json` | Fitted v2 parameters. |
| `Odds_vs_Stats_Check.py` | Model v1 flag check. |
| `probability_calc.py` | Model v1 normal-distribution probability. |
| `target_share_calc.py` | Team totals and reception share, used by the v1 stats helpers. |
| `backtest.py` | Back-test and parameter fitting (see Validation). |
| `team_stats_data.json` | Latest scraped team stats (refreshed by Refresh stats). |
| `requirements.txt` | Pinned Python dependencies. |
| `.env.example` | Template for `.env` with every setting documented. |
| `.gitignore` | Keeps `.env`, databases, `refresh_state.json`, `.venv` and work notes out of git. |
| `tests/test_refresh.py` | Unit tests: stats saving, odds fetching, refresh jobs and API. |
| `tests/test_model_v2.py` | Unit tests: model v2 and v1. |
| `tests/check_picks_dom.js`, `tests/check_refresh_dom.js` | Page checks against a running app (Node.js). |
| `tests/live_refresh_server.py`, `tests/live_refresh_check.py` | End-to-end refresh check with the paid call blocked. |

Created locally and never committed: `.env`, `nfl_stats.db` (and any `*.db` backups), `refresh_state.json`, `.venv/`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'fastapi'` (or pandas, sqlalchemy...) | The venv isn't active. Run `.\.venv\Scripts\Activate.ps1` (or `source .venv/bin/activate`), or call `.\.venv\Scripts\python.exe` directly. |
| `UnicodeEncodeError: 'charmap' codec can't encode character` | The Windows console can't print the emoji in the log lines. Run `$env:PYTHONIOENCODING="utf-8"` in that terminal first (macOS/Linux: `export PYTHONIOENCODING=utf-8`, untested). |
| Generate picks says "No player stats in the database yet" | Run `python save_to_db.py --all` once. |
| "No flagged players found" or cards say `No price` | No odds (or no price for that side) for this week yet. Click Fetch odds, and check `ODDS_DAYS_AHEAD` covers the games you want. |
| Fetch odds says "No Odds API keys configured" | Put your key in `.env` (see [Get your own Odds API key](#get-your-own-odds-api-key)) and restart the app. |
| Fetch odds says "Events request failed for all keys" | The key in `.env` is wrong (or still the placeholder `your_key_1`). |
| Quota exhausted / "All API keys failed or quota exceeded" | Every key is out of credits. Existing odds are kept. Wait for the monthly reset, add another key to `ODDS_API_KEYS`, or upgrade the plan. |
| Port 8000 already in use | Stop the other program (`Get-NetTCPConnection -LocalPort 8000` shows its process ID), or start the app on another port: `python -m uvicorn app:app --host 127.0.0.1 --port 8001` and open http://localhost:8001. |
| Sleeper unreachable (stats refresh fails, week looks wrong) | The app falls back to season 2026 week 8. Set `NFL_SEASON` and `NFL_WEEK` (in `.env` for the app, or in the shell for scripts) and retry later. |
| `InsecureRequestWarning` lines during stats loads | Harmless; they come from the Sleeper requests in `fetch_stats.py`. |
| Matchup notes never appear | Team stats in `team_stats_data.json` are for another season, so matchup stays neutral. Click Refresh stats to re-scrape TeamRankings for the current season. |
