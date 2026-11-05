# team_stats.py - team stats from teamrankings.com per-stat pages, and the
# display-only matchup factor built on them.
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from teams import ALL_ABBRS, TEAMRANKINGS_TO_ABBR

logger = logging.getLogger(__name__)

TEAM_STATS_PATH = Path(os.getenv("NFL_TEAM_STATS_PATH") or (Path(__file__).resolve().parent / "team_stats_data.json"))

BASE_URL = "https://www.teamrankings.com/nfl/stat/"
# TeamRankings page slug -> key stored in team_stats_data.json
STAT_PAGES = {
    "rushing-yards-per-game": "rush_yards_game",
    "passing-yards-per-game": "pass_yards_game",
    "opponent-rushing-yards-per-game": "opp_rush_yards_game",
    "opponent-passing-yards-per-game": "opp_pass_yards_game",
    "completions-per-game": "completions_game",
    "opponent-completions-per-game": "opp_completions_game",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) nfl-stats-personal/1.0"}
TIMEOUT = 20
REQUEST_DELAY_S = 2

# Matchup factor strength: f' = 1 + beta * (f - 1), display only.
# Betas from .agents/tasks/nfl-stats-math-review.md, finding S4 and
# recommendation #15: fitted on 2025 weeks 5-17 the best beta was
# rushing -0.02, receiving 0.24, passing 0.36, receptions 0.32.
MATCHUP_BETA = {
    "passing_yards": 0.3,
    "receiving_yards": 0.3,
    "receptions": 0.3,
    "rushing_yards": 0.0,
}
# Opponent stat each player stat is compared against (receptions use completions allowed).
MATCHUP_STAT_KEY = {
    "passing_yards": "opp_pass_yards_game",
    "receiving_yards": "opp_pass_yards_game",
    "receptions": "opp_completions_game",
    "rushing_yards": "opp_rush_yards_game",
}
MATCHUP_STAT_LABEL = {
    "opp_pass_yards_game": "pass yds allowed/game",
    "opp_completions_game": "completions allowed/game",
    "opp_rush_yards_game": "rush yds allowed/game",
}


def _parse_float(text):
    try:
        return float(text.replace(",", ""))
    except (AttributeError, ValueError):
        return None


def scrape_stat_page(slug, season):
    """Return ({abbr: float}, data_as_of) for one TeamRankings stat page.

    Reads the column whose header equals the season year. Raises on any
    unexpected page shape so a partial result is never saved.
    """
    url = BASE_URL + slug
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=False)
    if resp.status_code != 200:
        raise RuntimeError(f"{url} returned HTTP {resp.status_code}")
    soup = BeautifulSoup(resp.content, "html.parser")
    table = soup.select_one("table.tr-table")
    if table is None:
        raise RuntimeError(f"{url}: no table.tr-table")
    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    if str(season) not in headers or "Team" not in headers:
        raise RuntimeError(f"{url}: no '{season}' column (headers: {headers})")
    team_idx, value_idx = headers.index("Team"), headers.index(str(season))

    values = {}
    for row in table.select("tbody tr"):
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) <= max(team_idx, value_idx):
            continue
        name = cells[team_idx]
        abbr = TEAMRANKINGS_TO_ABBR.get(name)
        if abbr is None:
            raise RuntimeError(f"{url}: unknown team name '{name}'")
        value = _parse_float(cells[value_idx])  # '--' or blank -> None (missing)
        if value is not None:
            values[abbr] = value

    option = soup.select_one("select#date option[selected]")
    data_as_of = option.get("value") if option else None
    return values, data_as_of


def update_all_team_stats(season=None, output_path=TEAM_STATS_PATH):
    """Scrape all STAT_PAGES and save team_stats_data.json.

    The file is only replaced when all 32 teams have every key. On any
    failure the existing file is left untouched and None is returned.
    """
    if season is None:
        from pipeline_config import SEASON
        season = SEASON
    output_path = Path(output_path)

    teams = {abbr: {} for abbr in ALL_ABBRS}
    data_as_of = None
    try:
        for i, (slug, key) in enumerate(STAT_PAGES.items()):
            if i:
                time.sleep(REQUEST_DELAY_S)
            print(f"Fetching {BASE_URL}{slug} ...")
            values, as_of = scrape_stat_page(slug, season)
            data_as_of = data_as_of or as_of
            for abbr, value in values.items():
                teams[abbr][key] = str(value)
    except Exception as e:
        logger.error(f"Team stats scrape failed, keeping existing {output_path.name}: {e}")
        return None

    missing = [f"{abbr}:{key}" for abbr in ALL_ABBRS for key in STAT_PAGES.values()
               if _parse_float(teams[abbr].get(key)) is None]
    if missing:
        logger.error(f"Team stats incomplete ({len(missing)} missing, e.g. {missing[:5]}), "
                     f"keeping existing {output_path.name}")
        return None

    payload = {
        "season": season,
        "data_as_of": data_as_of,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "teamrankings.com per-stat pages",
        "teams": teams,
    }
    tmp = output_path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, output_path)
    print(f"Saved {len(teams)} teams for {season} (data as of {data_as_of}) to {output_path}")
    return payload


def _load_file():
    try:
        with open(TEAM_STATS_PATH, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def load_saved_team_stats():
    """Return {abbr: stats} from team_stats_data.json ({} if missing/invalid)."""
    data = _load_file()
    if "teams" in data:
        return data["teams"]
    return data  # legacy flat format


def load_team_stats_meta():
    """Return season / data_as_of / scraped_at (season None for a legacy file)."""
    data = _load_file()
    return {
        "season": data.get("season") if "teams" in data else None,
        "data_as_of": data.get("data_as_of"),
        "scraped_at": data.get("scraped_at"),
    }


def get_team_stats_for_player(team_abbreviation):
    """Get team stats from saved data ({} = no data)."""
    return load_saved_team_stats().get(team_abbreviation, {})


def _league_mean(saved_stats, key):
    values = [v for v in (_parse_float(s.get(key)) for s in saved_stats.values()) if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def get_league_averages():
    """League averages from saved data (None when there is no data)."""
    saved_stats = load_saved_team_stats()
    return {
        'rush_yards_game': _league_mean(saved_stats, 'rush_yards_game'),
        'pass_yards_game': _league_mean(saved_stats, 'pass_yards_game'),
    }


def get_league_defensive_averages():
    """League defensive averages from saved data (None when there is no data)."""
    saved_stats = load_saved_team_stats()
    return {
        'opp_rush_yards_game': _league_mean(saved_stats, 'opp_rush_yards_game'),
        'opp_pass_yards_game': _league_mean(saved_stats, 'opp_pass_yards_game'),
        'opp_completions_game': _league_mean(saved_stats, 'opp_completions_game'),
    }


def get_matchup_factor(stat_name, opponent_abbr, season):
    """Display-only matchup factor for a player stat vs an opponent defense.

    factor = 1 + beta * (raw - 1), raw = opponent allowed / league mean.
    Neutral (1.0) when beta is 0, the data is for another season, or data is missing.
    """
    result = {"factor": 1.0, "raw_factor": None, "beta": MATCHUP_BETA.get(stat_name),
              "opp_value": None, "league_value": None, "explanation": ""}
    beta = MATCHUP_BETA.get(stat_name)
    key = MATCHUP_STAT_KEY.get(stat_name)
    if beta is None or key is None:
        result["explanation"] = f"no matchup adjustment for {stat_name}"
        return result
    if beta == 0:
        result["explanation"] = f"{stat_name.split('_')[0]} matchup adjustment disabled (beta=0)"
        return result
    data_season = load_team_stats_meta()["season"]
    if data_season != season:
        result["explanation"] = f"team stats are for {data_season}, not {season} (no adjustment)"
        return result
    saved = load_saved_team_stats()
    opp_value = _parse_float((saved.get(opponent_abbr) or {}).get(key))
    league_value = _league_mean(saved, key)
    if opp_value is None or not league_value:
        result["explanation"] = f"no data for {opponent_abbr} {key} (no adjustment)"
        return result
    raw = opp_value / league_value
    result.update({
        "factor": 1 + beta * (raw - 1),
        "raw_factor": raw,
        "opp_value": opp_value,
        "league_value": league_value,
        "explanation": (f"vs {opponent_abbr} defense ({opp_value} vs {league_value} league avg "
                        f"{MATCHUP_STAT_LABEL[key]}, scaled x{beta})"),
    })
    return result


def build_adjustment(stat_name, original_value, weather_factor, weather_text, opponent_abbr, season):
    """Adjusted value and explanation for display. Never feeds the flag rule or probability."""
    m = get_matchup_factor(stat_name, opponent_abbr, season)
    team_factor = m["factor"]
    original = float(original_value)
    combined = weather_factor * team_factor
    # Only components that change the value (|pct| >= 0.05) are listed, so neutral
    # weather and the beta = 0 rushing matchup never show.
    components = []
    for label, factor, text in (("Weather", weather_factor, weather_text),
                                ("Matchup", team_factor, m["explanation"])):
        pct = round((factor - 1) * 100, 1)
        if abs(pct) >= 0.05:
            components.append({"label": label, "pct": pct, "text": text})
    return {
        "original": original,
        "adjusted": round(original * combined, 1),
        "changePct": round((combined - 1) * 100, 1),
        "teamFactor": team_factor,
        "weatherFactor": weather_factor,
        "components": components,
        "explanation": "<br>".join(f'<strong>{c["label"]} {c["pct"]:+.1f}%</strong><br>'
                                   f'&nbsp;&nbsp;&nbsp;&nbsp;{c["text"]}' for c in components),
        "teamExplanation": m["explanation"],
    }


def display_team_stats(team_stats):
    """Display team stats"""
    if not team_stats:
        print("    No team stats available")
        return
    
    rush_value = team_stats.get('rush_yards_game', 'N/A')
    pass_value = team_stats.get('pass_yards_game', 'N/A')
    opp_pass_value = team_stats.get('opp_pass_yards_game', 'N/A')
    opp_rush_value = team_stats.get('opp_rush_yards_game', 'N/A')
    print(f"    Team Statistics:")
    print(f"      Rush Yards/Game: {rush_value}")
    print(f"      Pass Yards/Game: {pass_value}")
    print(f"      Opp Pass Yards/Game: {opp_pass_value}")
    print(f"      Opp Rush Yards/Game: {opp_rush_value}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = update_all_team_stats()
    if result is None:
        print("Scrape failed; team_stats_data.json was not changed.")
        raise SystemExit(1)
    print(f"season={result['season']} data_as_of={result['data_as_of']} teams={len(result['teams'])}")
    for abbr in ("CHI", "JAX", "SEA"):
        print(abbr, result["teams"][abbr])
