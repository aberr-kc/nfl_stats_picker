# teams.py - canonical NFL team table (abbreviation, full name, TeamRankings name)
#
# Exact lookups only. Sleeper `team` values use the abbreviations, odds
# `event_name` uses the full names ("<Home> vs <Away>"), and teamrankings.com
# stat pages use the short names.

TEAMS = [
    ("ARI", "Arizona Cardinals", "Arizona"),
    ("ATL", "Atlanta Falcons", "Atlanta"),
    ("BAL", "Baltimore Ravens", "Baltimore"),
    ("BUF", "Buffalo Bills", "Buffalo"),
    ("CAR", "Carolina Panthers", "Carolina"),
    ("CHI", "Chicago Bears", "Chicago"),
    ("CIN", "Cincinnati Bengals", "Cincinnati"),
    ("CLE", "Cleveland Browns", "Cleveland"),
    ("DAL", "Dallas Cowboys", "Dallas"),
    ("DEN", "Denver Broncos", "Denver"),
    ("DET", "Detroit Lions", "Detroit"),
    ("GB", "Green Bay Packers", "Green Bay"),
    ("HOU", "Houston Texans", "Houston"),
    ("IND", "Indianapolis Colts", "Indianapolis"),
    ("JAX", "Jacksonville Jaguars", "Jacksonville"),
    ("KC", "Kansas City Chiefs", "Kansas City"),
    ("LV", "Las Vegas Raiders", "Las Vegas"),
    ("LAC", "Los Angeles Chargers", "LA Chargers"),
    ("LAR", "Los Angeles Rams", "LA Rams"),
    ("MIA", "Miami Dolphins", "Miami"),
    ("MIN", "Minnesota Vikings", "Minnesota"),
    ("NE", "New England Patriots", "New England"),
    ("NO", "New Orleans Saints", "New Orleans"),
    ("NYG", "New York Giants", "NY Giants"),
    ("NYJ", "New York Jets", "NY Jets"),
    ("PHI", "Philadelphia Eagles", "Philadelphia"),
    ("PIT", "Pittsburgh Steelers", "Pittsburgh"),
    ("SF", "San Francisco 49ers", "San Francisco"),
    ("SEA", "Seattle Seahawks", "Seattle"),
    ("TB", "Tampa Bay Buccaneers", "Tampa Bay"),
    ("TEN", "Tennessee Titans", "Tennessee"),
    ("WAS", "Washington Commanders", "Washington"),
]

ABBR_TO_FULL = {abbr: full for abbr, full, _ in TEAMS}
FULL_TO_ABBR = {full: abbr for abbr, full, _ in TEAMS}
TEAMRANKINGS_TO_ABBR = {tr: abbr for abbr, _, tr in TEAMS}
ALL_ABBRS = [abbr for abbr, _, _ in TEAMS]


def parse_event_teams(event_name):
    """Return (abbr1, abbr2) for "<Full Name> vs <Full Name>", or None."""
    if not event_name or " vs " not in event_name:
        return None
    left, right = event_name.split(" vs ", 1)
    a, b = FULL_TO_ABBR.get(left.strip()), FULL_TO_ABBR.get(right.strip())
    if a is None or b is None:
        return None
    return a, b


def find_opponent(player_abbr, event_name):
    """Return the opponent's abbreviation if player_abbr is exactly one side of the event."""
    teams = parse_event_teams(event_name)
    if not teams or not player_abbr:
        return None
    if player_abbr == teams[0]:
        return teams[1]
    if player_abbr == teams[1]:
        return teams[0]
    return None
