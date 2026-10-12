"""The 32 clubs. Colours stand in for logos (no official NHL marks on the site); approximate is fine."""
from __future__ import annotations

TEAMS = {
    "ANA": ("Anaheim", "Ducks", "#F47A38"),
    "BOS": ("Boston", "Bruins", "#FFB81C"),
    "BUF": ("Buffalo", "Sabres", "#003087"),
    "CAR": ("Carolina", "Hurricanes", "#CE1126"),
    "CBJ": ("Columbus", "Blue Jackets", "#002654"),
    "CGY": ("Calgary", "Flames", "#C8102E"),
    "CHI": ("Chicago", "Blackhawks", "#CF0A2C"),
    "COL": ("Colorado", "Avalanche", "#6F263D"),
    "DAL": ("Dallas", "Stars", "#006847"),
    "DET": ("Detroit", "Red Wings", "#CE1126"),
    "EDM": ("Edmonton", "Oilers", "#FF4C00"),
    "FLA": ("Florida", "Panthers", "#C8102E"),
    "LAK": ("Los Angeles", "Kings", "#A2AAAD"),
    "MIN": ("Minnesota", "Wild", "#154734"),
    "MTL": ("Montréal", "Canadiens", "#AF1E2D"),
    "NJD": ("New Jersey", "Devils", "#CE1126"),
    "NSH": ("Nashville", "Predators", "#FFB81C"),
    "NYI": ("New York", "Islanders", "#00539B"),
    "NYR": ("New York", "Rangers", "#0038A8"),
    "OTT": ("Ottawa", "Senators", "#DA1A32"),
    "PHI": ("Philadelphia", "Flyers", "#F74902"),
    "PIT": ("Pittsburgh", "Penguins", "#FCB514"),
    "SEA": ("Seattle", "Kraken", "#99D9D9"),
    "SJS": ("San Jose", "Sharks", "#006D75"),
    "STL": ("St. Louis", "Blues", "#002F87"),
    "TBL": ("Tampa Bay", "Lightning", "#002868"),
    "TOR": ("Toronto", "Maple Leafs", "#00205B"),
    "UTA": ("Utah", "Mammoth", "#69B3E7"),
    "VAN": ("Vancouver", "Canucks", "#00205B"),
    "VGK": ("Vegas", "Golden Knights", "#B4975A"),
    "WPG": ("Winnipeg", "Jets", "#041E42"),
    "WSH": ("Washington", "Capitals", "#C8102E"),
}

# PWHL teams, keyed "PW-<code>" because several codes also exist in the NHL. Colours come from each team's
# logo (the league publishes no list); the Fleet uses the sea green from its own logo. Expansion teams show
# as their city until nicknames are announced.
PWHL = {
    "PW-BOS": ("Boston", "Fleet", "#163F36"),
    "PW-MIN": ("Minnesota", "Frost", "#6C4E9B"),
    "PW-MTL": ("Montréal", "Victoire", "#0E2A47"),
    "PW-NY": ("New York", "Sirens", "#00A9A5"),
    "PW-OTT": ("Ottawa", "Charge", "#A01830"),
    "PW-TOR": ("Toronto", "Sceptres", "#E8B70B"),
    "PW-SEA": ("Seattle", "Torrent", "#085058"),
    "PW-VAN": ("Vancouver", "Goldeneyes", "#104078"),
    "PW-DET": ("Detroit", "Detroit", "#C85050"),
    "PW-HAM": ("Hamilton", "Hamilton", "#580810"),
    "PW-VGS": ("Las Vegas", "Las Vegas", "#707030"),
    "PW-SJ": ("San Jose", "San Jose", "#F09040"),
}

# Light colours need dark text on top of them.
LIGHT = {"BOS", "NSH", "PIT", "SEA", "UTA", "LAK", "VGK", "PW-TOR", "PW-SJ"}
ALL = {**TEAMS, **PWHL}


def league_of(key: str) -> str:
    return "pwhl" if key.startswith("PW-") else "nhl"


def as_list() -> list[dict]:
    return [{"abbr": a, "code": a.removeprefix("PW-"), "league": league_of(a), "place": p, "name": n, "color": c,
             "light": a in LIGHT} for a, (p, n, c) in ALL.items()]
