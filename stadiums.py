# stadiums.py - home stadium per team, used for game weather (weather_api.py)
#
# STADIUMS = {abbr: (stadium_name, lat, lon, roof)}, keyed by the abbreviations
# in teams.py. Coordinates are the home stadium; city-level accuracy is enough
# for weather. Roof is "open", "dome" (fixed roof, including SoFi's translucent
# roof) or "retractable". Any roof other than "open" gets no weather adjustment,
# because the roof state at kickoff is not known.
#
# Update when a team moves: Buffalo's new Highmark Stadium is across the road
# (same coordinates are fine), Tennessee's new domed stadium is due 2027 and
# Cleveland plans a domed stadium.
#
# Known limitation: neutral-site and international games (London, Germany,
# Mexico City, Brazil, ...) cannot be detected from the Odds API event data
# (it has no venue), so they use the designated home team's stadium.

ROOF_TYPES = ("open", "dome", "retractable")

STADIUMS = {
    "ARI": ("State Farm Stadium", 33.5276, -112.2626, "retractable"),
    "ATL": ("Mercedes-Benz Stadium", 33.7554, -84.4009, "retractable"),
    "BAL": ("M&T Bank Stadium", 39.2780, -76.6227, "open"),
    "BUF": ("Highmark Stadium", 42.7738, -78.7870, "open"),
    "CAR": ("Bank of America Stadium", 35.2258, -80.8528, "open"),
    "CHI": ("Soldier Field", 41.8623, -87.6167, "open"),
    "CIN": ("Paycor Stadium", 39.0955, -84.5161, "open"),
    "CLE": ("Huntington Bank Field", 41.5061, -81.6995, "open"),
    "DAL": ("AT&T Stadium", 32.7473, -97.0945, "retractable"),
    "DEN": ("Empower Field at Mile High", 39.7439, -105.0201, "open"),
    "DET": ("Ford Field", 42.3400, -83.0456, "dome"),
    "GB": ("Lambeau Field", 44.5013, -88.0622, "open"),
    "HOU": ("NRG Stadium", 29.6847, -95.4107, "retractable"),
    "IND": ("Lucas Oil Stadium", 39.7601, -86.1639, "retractable"),
    "JAX": ("EverBank Stadium", 30.3239, -81.6373, "open"),
    "KC": ("GEHA Field at Arrowhead Stadium", 39.0489, -94.4839, "open"),
    "LV": ("Allegiant Stadium", 36.0909, -115.1833, "dome"),
    "LAC": ("SoFi Stadium", 33.9535, -118.3392, "dome"),
    "LAR": ("SoFi Stadium", 33.9535, -118.3392, "dome"),
    "MIA": ("Hard Rock Stadium", 25.9580, -80.2389, "open"),
    "MIN": ("U.S. Bank Stadium", 44.9737, -93.2581, "dome"),
    "NE": ("Gillette Stadium", 42.0909, -71.2643, "open"),
    "NO": ("Caesars Superdome", 29.9511, -90.0812, "dome"),
    "NYG": ("MetLife Stadium", 40.8135, -74.0745, "open"),
    "NYJ": ("MetLife Stadium", 40.8135, -74.0745, "open"),
    "PHI": ("Lincoln Financial Field", 39.9008, -75.1675, "open"),
    "PIT": ("Acrisure Stadium", 40.4468, -80.0158, "open"),
    "SF": ("Levi's Stadium", 37.4030, -121.9700, "open"),
    "SEA": ("Lumen Field", 47.5952, -122.3316, "open"),
    "TB": ("Raymond James Stadium", 27.9759, -82.5033, "open"),
    "TEN": ("Nissan Stadium", 36.1665, -86.7713, "open"),
    "WAS": ("Northwest Stadium", 38.9076, -76.8645, "open"),
}


def get_stadium(abbr):
    """(stadium_name, lat, lon, roof) for a team abbreviation, or None."""
    return STADIUMS.get(abbr)
