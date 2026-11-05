# Verification log: Open-Meteo weather source

Python: `c:\code\nfl_stats_project-master\.venv\Scripts\python.exe` (`$py` below). Temp scripts lived in
`%TEMP%\nflweather\` and were deleted afterwards (not in the repo). Run on 2026-11-06 (local, UTC+10).
Code commits: `5715d3b` (commence_time), `8103fc1` (weather source).

## 0. Baseline and backup

- DB backup: `nfl_stats.backup-20261106-084735.db` (copy of `nfl_stats.db` before any change).
- Baseline picks: `$env:NFL_SEASON='2026'; $env:NFL_WEEK='9'; $py test_thresholds.py --json > %TEMP%\nflweather\weather_baseline.json` -> starts with `{"success": true, "players": [...`, 380 players / 1084 rows.
- Week 8 baseline: `$env:NFL_WEEK='8'; $py %TEMP%\nflbug\run_picks.py <repo> w8_before.json` -> `28 players, 106 rows`.
- Tests: `$py -m unittest discover tests` -> `Ran 82 tests ... OK`.
- Note: while this step ran, another workflow committed `334287d..9f4751a` (save_to_db, index.html, README weekly workflow, tests/live_refresh_*). None of those touch the files changed here; only this step's files were staged.

## 1. py_compile

```
$py -m py_compile models.py odds_api.py stadiums.py weather_api.py test_thresholds.py backfill_commence_times.py
py_compile exit 0          (no output)
```

## 2. Migration, stadium table, tests

```
$py -c "import models, sqlite3; print([r[1] for r in sqlite3.connect(str(models.DB_PATH)).execute('PRAGMA table_info(odds)')])"
['id', 'player_id', 'event_id', 'event_name', 'bookmaker', 'market', 'line', 'price', 'season', 'week', 'retrieved_at', 'season_type', 'outcome', 'commence_time']

$py -c "import stadiums, teams; assert set(stadiums.STADIUMS)==set(teams.ALL_ABBRS); assert all(s[3] in stadiums.ROOF_TYPES for s in stadiums.STADIUMS.values()); print(len(stadiums.STADIUMS))"
32

$py -m unittest discover tests
Ran 82 tests in 0.861s
OK
```

## 3. Kickoff backfill (free /events only, 0 credits)

`$py backfill_commence_times.py` (excerpt):
```
28 events listed by /events
Baltimore Ravens vs Jacksonville Jaguars 2026-11-06T01:15:00Z: 564 rows updated
Atlanta Falcons vs Cincinnati Bengals 2026-11-08T14:30:00Z: 414 rows updated
... (12 more 2026 wk9 games) ...
Chicago Bears vs Tampa Bay Buccaneers 2026-11-09T01:20:00Z: 411 rows updated
Minnesota Vikings vs Buffalo Bills 2026-11-10T01:15:00Z: 0 rows updated
... (week 10-11 games, no odds rows yet: 0 rows) ...
4983 odds rows updated
```
Per (season, week): distinct events vs events with commence_time:
`[(2025, 14, 1, 0), (2025, 15, 1, 0), (2025, 16, 15, 0), (2026, 8, 1, 0), (2026, 9, 14, 14)]`.
All 14 week-9 events got a kickoff; older weeks are not listed by `/events` and stay NULL. No paid Odds API call was made.

## 4. Direct get_weather_for_game checks (temp script `check_weather.py`, live Open-Meteo)

Endpoints and units checked live first: forecast `https://api.open-meteo.com/v1/forecast` and archive
`https://archive-api.open-meteo.com/v1/archive` both 200, `hourly_units` = `°C`, `km/h`, `wmo code`.

```
(a) NE home 2026-11-08T21:25Z: {'temperature': 9.4, 'wind_speed': 19.7, 'conditions': 'Partly cloudy', 'available': True, 'note': None}
    url: https://api.open-meteo.com/v1/forecast params: {'latitude': 42.0909, 'longitude': -71.2643, 'hourly': 'temperature_2m,wind_speed_10m,weather_code', 'start_date': '2026-11-08', 'end_date': '2026-11-08', 'timezone': 'GMT'} UA: {'User-Agent': 'nfl-stats-project/1.0 (weather display adjustment)'} timeout: 10
    (f) HTTP calls for 2 identical lookups: 1 | same result: True
(b) DET home (dome): {'temperature': None, 'wind_speed': None, 'conditions': None, 'available': False, 'note': 'Indoor stadium (Ford Field), no weather adjustment'}
    HTTP called: False
(b2) ATL home (retractable): {..., 'available': False, 'note': 'Indoor stadium (Mercedes-Benz Stadium), no weather adjustment'}
(c) GB home 2025-12-21T18:00Z: {'temperature': -10.5, 'wind_speed': 10.4, 'conditions': 'Clear', 'available': True, 'note': None}
    url: https://archive-api.open-meteo.com/v1/archive
LOG WARNING weather_api: Weather unavailable for CHI at 2026-11-09T01:00:00+00:00 (Soldier Field): forced offline
(d) CHI home, network forced down: {'temperature': None, 'wind_speed': None, 'conditions': None, 'available': False, 'note': 'Weather unavailable (adjustment disabled)'}
    HTTP attempts for 2 lookups: 1
LOG WARNING weather_api: Weather: no usable kickoff time for 'Green Bay Packers vs Carolina Panthers' (commence_time=None)
LOG WARNING weather_api: Weather: home stadium unknown for event 'Foo vs Bar'
(e1) commence_time=None: {..., 'available': False, 'note': 'No kickoff time stored for this game (weather adjustment disabled)'}
(e2) 'Foo vs Bar': {..., 'available': False, 'note': 'Home stadium unknown (weather adjustment disabled)'}
factors 'Rain showers' 5C 20km/h: {'passing_yards': 0.7866, 'receiving_yards': 0.7866, 'rushing_yards': 1.0506, 'receptions': 0.85652}
factors 'Drizzle' 12C 5km/h: {'passing_yards': 1.0, 'receiving_yards': 1.0, 'rushing_yards': 1.0, 'receptions': 1.0}
factors None: {'passing_yards': 1.0, 'receiving_yards': 1.0, 'rushing_yards': 1.0, 'receptions': 1.0}
ALL CHECKS PASSED
```
(d) used `mock.patch.object(weather_api.requests, "get", side_effect=requests.ConnectionError(...))`: no exception, neutral result, the failure was cached (second call made no request). "Rain showers" triggers the precipitation factor (0.92 × 0.95 × 0.90 = 0.7866 for passing: windy × cold × rain); "Drizzle" does not, as designed.

## 5. Pipeline on existing data, display-only proof, request count

Temp runner `run_weather_picks.py` = `run_picks.py` plus a counting wrapper on `weather_api.requests.get`;
`--neutral-weather` replaces `weather_api.get_weather_for_game` with an always-neutral stub. Temp
`compare.py` strips `adjusted*` keys and `adjustmentDetails` and compares everything else, plus
`probabilityOver` / `probabilityUnder` / `threshold_rule` row by row.

### 2026 week 9 (kickoffs stored)

```
$env:NFL_SEASON='2026'; $env:NFL_WEEK='9'
$py run_weather_picks.py <repo> w9_after.json
WROTE w9_after.json: 380 players, 1084 rows, 55s
Open-Meteo requests: 10        (all forecast API; SEA, CAR, KC, WAS, BAL, MIA, SF, CHI, NE, PHI)
$py run_weather_picks.py <repo> w9_neutral.json --neutral-weather
WROTE w9_neutral.json: 380 players, 1084 rows, 44s
Open-Meteo requests: 0

$py compare.py w9_after.json w9_neutral.json
players 380/380, rows 1084/1084
rows checked for ('probabilityOver', 'probabilityUnder', 'threshold_rule'): 1084
differences outside adjusted*/adjustmentDetails: 0

$py compare.py w9_after.json weather_baseline.json      (pre-change baseline)
players 380/380, rows 1084/1084
rows checked for ('probabilityOver', 'probabilityUnder', 'threshold_rule'): 1084
differences outside adjusted*/adjustmentDetails: 0
```
Request count: 10 requests for 1084 rows = one per outdoor home stadium/kickoff hour (cache hit for every other player). 0 weather warnings in stderr.

Weather line per matchup (from `adjustmentDetails.explanation`):
```
Atlanta Falcons vs Cincinnati Bengals: Indoor stadium (Mercedes-Benz Stadium), no weather adjustment
Baltimore Ravens vs Jacksonville Jaguars: 19.8°C, 4.3km/h wind
Carolina Panthers vs Denver Broncos: 17.4°C, 7.9km/h wind
Chicago Bears vs Tampa Bay Buccaneers: 13.1°C, 15.3km/h wind (windy)
Indianapolis Colts vs Dallas Cowboys: Indoor stadium (Lucas Oil Stadium), no weather adjustment
Kansas City Chiefs vs New York Jets: 17.7°C, 13.5km/h wind
Los Angeles Chargers vs Houston Texans: Indoor stadium (SoFi Stadium), no weather adjustment
Miami Dolphins vs Detroit Lions: 28.8°C, 15.5km/h wind (windy)
New England Patriots vs Green Bay Packers: 9.4°C, 19.7km/h wind (cold, windy)
New Orleans Saints vs Cleveland Browns: Indoor stadium (Caesars Superdome), no weather adjustment
Philadelphia Eagles vs New York Giants: 15.7°C, 22.7km/h wind (windy)
San Francisco 49ers vs Las Vegas Raiders: 22.1°C, 8.3km/h wind
Seattle Seahawks vs Arizona Cardinals: 12.9°C, 15.1km/h wind (windy)
Washington Commanders vs Los Angeles Rams: 16.0°C, 20.3km/h wind (windy)
```

### 2026 week 8 (as in the earlier bug-fix verification; kickoff not stored)

```
$env:NFL_WEEK='8'
$py run_weather_picks.py <repo> w8_after.json               -> 28 players, 106 rows; Open-Meteo requests: 0
$py run_weather_picks.py <repo> w8_neutral.json --neutral-weather -> 28 players, 106 rows; Open-Meteo requests: 0
compare w8_after vs w8_neutral: rows checked 106, differences outside adjusted*/adjustmentDetails: 0
compare w8_after vs w8_before (pre-change): rows checked 106, differences: 0
Green Bay Packers vs Carolina Panthers: No kickoff time stored for this game (weather adjustment disabled)
```
stderr: exactly one `WARNING:weather_api:Weather: no usable kickoff time for 'Green Bay Packers vs Carolina Panthers' ...` for the whole run.

### Served app

`$py -m uvicorn app:app --host 127.0.0.1 --port 8001` (background, no NFL_* env vars), `GET /` 200,
`GET /generate-picks` 200, `success: true`, 380 players, log `Generating picks for Season=2026, Week=9, model=v2`.
Weather lines identical to the week-9 list above. `compare.py served vs w9_neutral`: 1084 rows, 0 differences.
No tracebacks or weather warnings in the server log. Server stopped; nothing listens on 8001.

## 6. Scope

`git diff --stat 9f4751a..8103fc1`: `models.py`, `odds_api.py`, `test_thresholds.py`, `weather_api.py`,
`README.md`, new `stadiums.py`, new `backfill_commence_times.py`. `probability_calc.py`, `model_v2.py`,
`weather_adjustments.py`, `team_stats.py` unchanged. The `weather` DB table was not touched.
