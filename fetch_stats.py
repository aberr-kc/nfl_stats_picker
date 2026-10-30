# fetch_stats.py
import requests
import pandas as pd
from sqlalchemy import create_engine
from requests.exceptions import RequestException

engine = create_engine("sqlite:///nfl_stats.db")


def fetch_players_df():
    """
    Fetch all NFL players from Sleeper API and return as DataFrame.
    """
    url = "https://api.sleeper.app/v1/players/nfl"
    print(f"Fetching player metadata from {url}...")
    try:
        # amazonq-ignore-next-line
        resp = requests.get(url, timeout=30, verify=False)
        resp.raise_for_status()
    except RequestException as e:
        raise RequestException(f"Error fetching players: {e}")
    data = resp.json()
    df = pd.DataFrame(data.values())
    df["player_id"] = list(data.keys())

    # Keep only relevant columns
    df = df[["player_id", "full_name", "first_name", "last_name", "team", "position"]]
    df.rename(columns={"full_name": "player_name"}, inplace=True)

    # Add a combined display name for consistency
    df["player_display_name"] = df["first_name"].fillna("") + " " + df["last_name"].fillna("")
    df["player_display_name"] = df["player_display_name"].str.strip()

    return df


def fetch_weekly_stats_sleeper(year: int, week: int, season_type: str = 'regular', players_df=None) -> pd.DataFrame:
    """
    Fetch weekly stats for all players from Sleeper API and merge with player metadata.
    
    Args:
        year: Season year
        week: Week number (1-18 for regular, 1-4 for playoffs)
        season_type: 'regular' or 'playoffs'
        players_df: Optional pre-fetched players DataFrame
    
    Returns:
        DataFrame with cleaned + renamed stat columns.
    """
    if players_df is None:
        players_df = fetch_players_df()

    url = f"https://api.sleeper.app/v1/stats/nfl/{season_type}/{year}/{week}"
    print(f"Fetching NFL {season_type} stats for {year} Week {week} from {url}...")
    try:
        # amazonq-ignore-next-line
        resp = requests.get(url, timeout=30, verify=False)
        resp.raise_for_status()
    except RequestException as e:
        print(f"Error fetching stats: {e}")
        return pd.DataFrame()

    data = resp.json()
    if not data:
        print(f"No {season_type} stats returned for week {week}.")
        return pd.DataFrame()

    # Convert JSON dict (player_id -> stats) to DataFrame
    stats_df = pd.DataFrame(data.values())
    stats_df["player_id"] = list(data.keys())
    stats_df["season"] = year
    stats_df["week"] = week
    stats_df["season_type"] = season_type

    # --- Map Sleeper stat keys into expected schema ---
    mapping = {
        "pass_yd": "passing_yards",
        "pass_td": "passing_tds",
        "rush_yd": "rushing_yards",
        "rush_td": "rushing_tds",
        "rec_yd": "receiving_yards",
        "rec_td": "receiving_tds",
        "rec": "receptions",
    }
    for sleeper_key, our_key in mapping.items():
        if sleeper_key in stats_df.columns:
            stats_df.rename(columns={sleeper_key: our_key}, inplace=True)
        else:
            stats_df[our_key] = 0.0  # ensure column exists

    # Merge with player metadata
    merged_df = stats_df.merge(
        players_df,
        how="left",
        on="player_id",
        suffixes=("", "_meta")
    )

    required_cols = [
        "player_id", "player_name", "player_display_name", "team", "position",
        "season", "week", "season_type", "gp", "passing_yards", "passing_tds",
        "rushing_yards", "rushing_tds",
        "receiving_yards", "receiving_tds", "receptions"
    ]
    for col in required_cols:
        if col not in merged_df.columns:
            if col == "season_type":
                merged_df[col] = season_type
            elif col not in ["player_name", "player_display_name", "team", "position"]:
                merged_df[col] = 0
            else:
                merged_df[col] = ""

    # Fill NaNs with zeros for numeric stats
    numeric_cols = merged_df.select_dtypes(include="number").columns
    merged_df[numeric_cols] = merged_df[numeric_cols].fillna(0)

    print(f"Retrieved {len(merged_df)} player {season_type} stats rows.")
    return merged_df[required_cols]  # return only cleaned columns
