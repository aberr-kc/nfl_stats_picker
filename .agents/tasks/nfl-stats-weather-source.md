# Weather source (Open-Meteo): final report

Branch `refresh-buttons`, not pushed. Commits:
- `5715d3b` feat: store odds commence_time on ingestion and backfill it from free /events
- `8103fc1` feat: Open-Meteo weather at the home stadium for the display-only adjustment
- docs commit with this report and `nfl-stats-weather-source-verification.md` (evidence log)

## What was built

- **`stadiums.py`**: all 32 home stadiums with lat/lon and roof type (`open`, `dome`, `retractable`). SoFi counts as `dome`.
- **`weather_api.get_weather_for_game(event_name, commence_time)`**, using [Open-Meteo](https://open-meteo.com) with no API key:
  - Home team = first name in the odds `event_name`. The DB format is `"<Home> vs <Away>"`, built by `odds_api` from the API's `home_team`/`away_team`, and parsed with `teams.parse_event_teams`.
  - Dome and retractable roofs return the neutral result with `"Indoor stadium (<name>), no weather adjustment"` and make no HTTP call.
  - Kickoff dates from 7 days ago onward use the forecast API; older dates use the archive API, so past weeks get real weather once their kickoff is stored. The request asks for one UTC day of hourly `temperature_2m` (°C), `wind_speed_10m` (km/h) and `weather_code`, then takes the hour nearest kickoff.
  - WMO codes map to strings that `weather_adjustments` matches. Rain, freezing rain, showers, thunderstorms and snow contain "rain"/"snow". Clear, cloudy, fog and drizzle do not. Unknown codes become `"Unknown"`, so temperature and wind still apply.
  - HTTPS with a 10 s timeout and a User-Agent header. Results are cached in memory per (home team, kickoff hour), guarded by a lock: archive results last for the process lifetime, forecasts for 1 hour, failures for 10 minutes.
  - Any failure returns the neutral result (values None, `available` False) with a `note` and a logged warning. This covers network errors, HTTP errors, null data, unknown teams and a missing kickoff time. Warnings for uncached cases are logged once per event. The function never raises.
- **`test_thresholds.py`**: `commence_time` is passed from the odds rows to the weather call. When the result has a `note`, the explanation shows that note.
- **README**: Weather section.

Weather is still display only. It changes the "Adjusted" value and its explanation. `probability_calc`, the flag rule, `model_v2.py` and the thresholds and magnitudes in `weather_adjustments.py` are unchanged. On 2026 week 9 (1084 rows) and week 8 (106 rows), `probabilityOver`, `probabilityUnder` and `threshold_rule` matched a weather-forced-neutral run and the pre-change baseline exactly.

## Kickoff-time decision

The kickoff time was not stored anywhere. I chose the least invasive option: a nullable `odds.commence_time TEXT` column holding the Odds API `commence_time` (ISO UTC). It follows the existing `ensure_odds_outcome_column` migration pattern. `odds_api.save_odds` now stores it on every odds fetch at no extra cost. Rows saved before the column existed are filled by `backfill_commence_times.py`, which calls only the free `/events` endpoint (0 credits). That run updated 4983 rows, covering all 14 events in 2026 week 9. `/events` lists only upcoming and live games, so older weeks (2025 wk14-16, 2026 wk8) stay NULL and show "No kickoff time stored for this game", which is neutral. I rejected re-fetching odds (it costs credits) and guessing kickoff from the week number (wrong for Thursday and Monday games).

## Verification summary

Full commands and outputs are in `.agents/tasks/nfl-stats-weather-source-verification.md`.
- `py_compile` passed on all 6 changed or new .py files. `unittest discover tests` passed 82/82, the same as before.
- Direct checks:
  - (a) NE home on 2026-11-08 (forecast): 9.4 °C, 19.7 km/h, Partly cloudy. Two identical calls made 1 HTTP request.
  - (b) DET dome: indoor note, no HTTP call.
  - (c) GB on 2025-12-21 (archive): -10.5 °C, 10.4 km/h, Clear.
  - (d) Forced `ConnectionError`: neutral result, no exception, 1 warning, and the failure was cached.
- 2026 week 9 pipeline: 10 Open-Meteo requests for 380 players and 1084 rows, one per outdoor game. The 10 outdoor games show real temperature and wind, and the 4 indoor games (ATL, IND, LAC, NO) show the indoor note. The served `/generate-picks` output matched.

## Limitations

- **Neutral-site and international games** can't be detected, because the Odds API event data has no venue. They use the designated home team's stadium. Week 9's Atlanta vs Cincinnati game at 14:30 UTC looks like an international game. It got the Atlanta indoor note, so it was neutral either way, but an outdoor "home" team abroad would get the wrong city's weather. I added no guessing heuristic.
- Odds rows saved before this change, for games no longer listed by `/events`, have no kickoff time and stay neutral. New fetches store it.
- Retractable roofs are always treated as closed (neutral), because the roof state is not known.
- Forecasts beyond about 14 days return HTTP 400, which gives the neutral result. Very recent past days can be null in the archive, which also gives neutral. The forecast API covers the last 7 days to avoid that gap.
- Forecasts are cached for 1 hour on a long-running server, and the cache is per process.
- The old `weather` DB table (19 rows in F/mph from an earlier script) is not read or changed.

## J6 threshold recommendation (not implemented)

`nfl-stats-math-review.md` section J6 says the magnitudes and thresholds look aggressive. "Windy" starts at 15 km/h (a light breeze) and takes -8% off passing. The rules also multiply: very cold × very windy × rain gives -29.6% passing. Real data now shows this matters. In week 9, 6 of 10 outdoor games crossed the 15 km/h "windy" threshold, and NE vs GB also got the "cold" penalty at 9.4 °C. I recommend raising the wind thresholds to about 25 km/h (windy) and 40 km/h (very windy), and shrinking or removing the < 10 °C cold penalty, ideally calibrated against backtests once past kickoffs are stored. I did not change the thresholds, because that changes what users see.
