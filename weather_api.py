"""Game weather from Open-Meteo (https://open-meteo.com), free, no API key.

- Upcoming and recent games use the forecast API, older games the historical
  archive API, so re-running past weeks gets real weather.
- Values are for the hour nearest kickoff (odds.commence_time, ISO UTC):
  temperature_2m in Celsius, wind_speed_10m in km/h, weather_code (WMO) mapped
  to a condition string that weather_adjustments matches ('rain' / 'snow').
- Location is the HOME team's stadium (stadiums.py); the home team is the first
  name in the odds event_name ("<Home> vs <Away>").
- Dome and retractable-roof stadiums get no weather (neutral, no HTTP call).
- Known limitation: neutral-site and international games can't be detected from
  the odds data (no venue), so they use the designated home team's stadium.
- Results are cached in memory per (home team, kickoff hour): archive results
  for the process lifetime, forecasts for 1 hour, failures for 10 minutes.
- Display only: the result feeds the "Adjusted" value and its explanation,
  never the flag rule or the probability.
- Any problem (network, missing data, unknown team, no kickoff time) returns the
  neutral no-data result (values None, available False) and logs a warning.
  get_weather_for_game never raises.
"""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

from stadiums import get_stadium
from teams import parse_event_teams

logger = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
USER_AGENT = "nfl-stats-project/1.0 (weather display adjustment)"
TIMEOUT_S = 10
FORECAST_TTL_S = 3600
FAILURE_TTL_S = 600
FORECAST_PAST_DAYS = 7  # kickoff within the last 7 days or later -> forecast API

# WMO weather codes -> condition strings. weather_adjustments applies the
# precipitation penalty when the string contains 'rain' or 'snow'. Drizzle is
# deliberately not precipitation (light drizzle isn't worth -10% passing).
WMO_CONDITIONS = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog", 48: "Fog",
    51: "Drizzle", 53: "Drizzle", 55: "Drizzle",
    56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Rain", 63: "Rain", 65: "Rain",
    66: "Freezing rain", 67: "Freezing rain",
    71: "Snow", 73: "Snow", 75: "Snow",
    77: "Snow grains",
    80: "Rain showers", 81: "Rain showers", 82: "Rain showers",
    85: "Snow showers", 86: "Snow showers",
    95: "Thunderstorm with rain",
    96: "Thunderstorm with rain and hail", 99: "Thunderstorm with rain and hail",
}

NOTE_NO_KICKOFF = "No kickoff time stored for this game (weather adjustment disabled)"
NOTE_UNKNOWN_STADIUM = "Home stadium unknown (weather adjustment disabled)"
NOTE_UNAVAILABLE = "Weather unavailable (adjustment disabled)"

_CACHE = {}  # (home_abbr, kickoff_iso) -> (result, expires_at or None for no expiry)
_WARNED = set()  # (reason, event_name) already logged, so uncached cases warn once
_LOCK = threading.Lock()


def _neutral(note):
    return {"temperature": None, "wind_speed": None, "conditions": None,
            "available": False, "note": note}


def _warn_once(reason, event_name, message, *args):
    with _LOCK:
        if (reason, event_name) in _WARNED:
            return
        _WARNED.add((reason, event_name))
    logger.warning(message, *args)


def _parse_kickoff(commence_time):
    """Aware UTC datetime rounded to the nearest hour, or None."""
    if not commence_time or not isinstance(commence_time, str):
        return None
    try:
        dt = datetime.fromisoformat(commence_time.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    dt = dt.astimezone(timezone.utc)
    rounded = dt.replace(minute=0, second=0, microsecond=0)
    if dt - rounded >= timedelta(minutes=30):
        rounded += timedelta(hours=1)
    return rounded


def _use_forecast(kickoff):
    return kickoff.date() >= (datetime.now(timezone.utc) - timedelta(days=FORECAST_PAST_DAYS)).date()


def _fetch_hour(lat, lon, kickoff):
    """(temperature C, wind km/h, weather_code) at the kickoff hour. Raises on any problem."""
    url = FORECAST_URL if _use_forecast(kickoff) else ARCHIVE_URL
    day = kickoff.strftime("%Y-%m-%d")
    params = {"latitude": lat, "longitude": lon,
              "hourly": "temperature_2m,wind_speed_10m,weather_code",
              "start_date": day, "end_date": day, "timezone": "GMT"}
    resp = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S)
    if resp.status_code != 200:
        raise ValueError(f"HTTP {resp.status_code} from {url}: {resp.text[:200]}")
    data = resp.json()
    if data.get("error"):
        raise ValueError(f"error from {url}: {data.get('reason')}")
    hourly = data["hourly"]
    i = hourly["time"].index(kickoff.strftime("%Y-%m-%dT%H:00"))
    temp, wind = hourly["temperature_2m"][i], hourly["wind_speed_10m"][i]
    code = hourly.get("weather_code", [None] * len(hourly["time"]))[i]
    if temp is None or wind is None:
        raise ValueError(f"no temperature/wind for {kickoff.isoformat()} from {url}")
    return float(temp), float(wind), code


def get_weather_for_game(event_name, commence_time):
    """Weather at the home stadium at kickoff.

    Always returns {temperature, wind_speed, conditions, available, note};
    note is set (and the values are None) when there is no weather to apply.
    """
    try:
        teams = parse_event_teams(event_name)
        stadium = get_stadium(teams[0]) if teams else None
        if not stadium:
            _warn_once("stadium", event_name, "Weather: home stadium unknown for event %r", event_name)
            return _neutral(NOTE_UNKNOWN_STADIUM)
        home = teams[0]
        name, lat, lon, roof = stadium
        if roof != "open":
            return _neutral(f"Indoor stadium ({name}), no weather adjustment")
        kickoff = _parse_kickoff(commence_time)
        if kickoff is None:
            _warn_once("kickoff", event_name, "Weather: no usable kickoff time for %r (commence_time=%r)",
                       event_name, commence_time)
            return _neutral(NOTE_NO_KICKOFF)

        key = (home, kickoff.isoformat())
        now = time.time()
        with _LOCK:
            hit = _CACHE.get(key)
        if hit and (hit[1] is None or hit[1] > now):
            return dict(hit[0])

        try:
            temp, wind, code = _fetch_hour(lat, lon, kickoff)
            result = {"temperature": round(temp, 1), "wind_speed": round(wind, 1),
                      "conditions": WMO_CONDITIONS.get(code, "Unknown"), "available": True, "note": None}
            expires = now + FORECAST_TTL_S if _use_forecast(kickoff) else None
        except Exception as e:
            logger.warning("Weather unavailable for %s at %s (%s): %s", home, kickoff.isoformat(), name, e)
            result = _neutral(NOTE_UNAVAILABLE)
            expires = now + FAILURE_TTL_S
        with _LOCK:
            _CACHE[key] = (result, expires)
        return dict(result)
    except Exception as e:  # never break the picks request path
        logger.warning("Weather lookup failed for %r: %s", event_name, e)
        return _neutral(NOTE_UNAVAILABLE)


def clear_cache():
    """Drop cached weather results (and the once-only warning memory)."""
    with _LOCK:
        _CACHE.clear()
        _WARNED.clear()
