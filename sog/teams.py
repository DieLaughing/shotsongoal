"""The 32 clubs. Colours stand in for logos (no official NHL marks on the site); approximate is fine."""
from __future__ import annotations

import json
from pathlib import Path

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

# NHL divisions (for grouping team pickers; standings carry the live ones). The PWHL has none.
DIVISIONS = {
    "Atlantic": ["BOS", "BUF", "DET", "FLA", "MTL", "OTT", "TBL", "TOR"],
    "Metropolitan": ["CAR", "CBJ", "NJD", "NYI", "NYR", "PHI", "PIT", "WSH"],
    "Central": ["CHI", "COL", "DAL", "MIN", "NSH", "STL", "UTA", "WPG"],
    "Pacific": ["ANA", "CGY", "EDM", "LAK", "SEA", "SJS", "VAN", "VGK"],
}
DIVISION_OF = {a: d for d, teams in DIVISIONS.items() for a in teams}

# Light colours need dark text on top of them.
LIGHT = {"BOS", "NSH", "PIT", "SEA", "UTA", "LAK", "VGK", "PW-TOR", "PW-SJ"}

# College teams, keyed "CM-<ESPN id>" (men) / "CW-<ESPN id>" (women): sog/data/college.json, from
# tools/college_teams.py. (place, name, colour) like the others, with the school as the name: mascots repeat.
COLLEGE_INFO = {f"{prefix}{t['id']}": {**t, "league": lg}
                for lg, prefix in (("ncaam", "CM-"), ("ncaaw", "CW-"))
                for t in json.loads((Path(__file__).resolve().parent / "data" / "college.json").read_text())[lg]}
COLLEGE = {k: ("", t["school"], t["color"]) for k, t in COLLEGE_INFO.items()}
ALL = {**TEAMS, **PWHL, **COLLEGE}


def league_of(key: str) -> str:
    return "pwhl" if key.startswith("PW-") else "ncaam" if key.startswith("CM-") else "ncaaw" if key.startswith("CW-") else "nhl"


def as_list() -> list[dict]:
    out = [{"abbr": a, "code": a.removeprefix("PW-"), "league": league_of(a), "place": p, "name": n, "color": c,
            "light": a in LIGHT, "div": DIVISION_OF.get(a)} for a, (p, n, c) in {**TEAMS, **PWHL}.items()]
    return out + [{"abbr": k, "code": t["code"], "league": t["league"], "place": "", "name": t["school"], "full": t["full"],
                   "color": t["color"], "light": t["light"], "div": t["conf"]} for k, t in COLLEGE_INFO.items()]
