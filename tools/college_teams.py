"""Rebuild sog/data/college.json: every men's and women's college hockey team ESPN lists, with its conference and a
colour for its badge. ESPN gives no team colours for college hockey, so each one is the main colour of the team's
logo. Run it once a season (new programs, conference moves), check the diff, commit.

    .venv/bin/python tools/college_teams.py
"""
from __future__ import annotations

import io
import json
import sys
from collections import Counter
from pathlib import Path

from curl_cffi import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sog import ncaa  # noqa: E402

OUT = ROOT / "sog" / "data" / "college.json"
LOGO = "https://a.espncdn.com/i/teamlogos/ncaa/500/{id}.png"
# ESPN has no women's conferences at all. 2026-27 women's D-I, by ESPN's school name; recheck each season.
WOMENS_CONF = {
    "HE": ["Boston College", "Boston University", "UConn", "Holy Cross", "Maine", "Merrimack", "New Hampshire",
           "Northeastern", "Providence", "Vermont"],
    "ECAC": ["Brown", "Clarkson", "Colgate", "Cornell", "Dartmouth", "Harvard", "Princeton", "Quinnipiac", "Rensselaer",
             "St. Lawrence", "Union", "Yale"],
    "WCHA": ["Bemidji State", "Minnesota", "Minnesota Duluth", "Minnesota State", "Minnesota St", "Ohio State", "St. Cloud State",
             "St. Thomas-Minnesota", "Wisconsin"],
    "AHA": ["Lindenwood", "Mercyhurst", "Penn State", "RIT", "Robert Morris", "Syracuse"],
    "NEWHA": ["Assumption", "Franklin Pierce", "Long Island University", "Post", "Sacred Heart", "Saint Anselm",
              "Saint Michael's", "Stonehill"],
}


def logo_colour(png: bytes) -> tuple[str, bool]:
    """The logo's most common strong colour (white, near-black and see-through pixels don't count), and whether it's
    light enough to need dark text. Falls back to the darkest common colour for black-and-white logos."""
    img = Image.open(io.BytesIO(png)).convert("RGBA").resize((64, 64))
    counts = Counter()
    for r, g, b, a in img.get_flattened_data():
        if a < 200:
            continue
        counts[(r // 24 * 24 + 12, g // 24 * 24 + 12, b // 24 * 24 + 12)] += 1
    strong = [(n, c) for c, n in counts.items() if max(c) - min(c) > 40 and sum(c) < 680]
    pick = max(strong)[1] if strong else min((c for c in counts if counts[c] > 20), key=sum, default=(80, 80, 80))
    r, g, b = (min(255, v) for v in pick)
    light = 0.299 * r + 0.587 * g + 0.114 * b > 170
    return f"#{r:02X}{g:02X}{b:02X}", light


def main() -> None:
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    colours = {t["id"]: (t["color"], t["light"]) for lg in old.values() for t in lg}
    out = {}
    for lg in ncaa.LEAGUES:
        teams = requests.get(f"{ncaa.SITE}/{ncaa.PATH[lg]}/teams?limit=400", impersonate="chrome").json()
        stand = requests.get(f"{ncaa.STANDINGS}/{ncaa.PATH[lg]}/standings", impersonate="chrome").json()
        conf, group, listed = {}, {}, []
        for c in stand.get("children") or []:
            group[str(c.get("id"))] = c.get("abbreviation")
            for e in (c.get("standings") or {}).get("entries") or []:
                conf[str(e["team"]["id"])] = c.get("abbreviation")
                listed.append(e["team"])
        listed += [e["team"] for e in (stand.get("standings") or {}).get("entries") or []]   # the women: one table
        teams_list = teams["sports"][0]["leagues"][0]["teams"]
        known = {str(x["team"]["id"]) for x in teams_list}
        # Some schools are in the standings (and on scoreboards) under an id the team list doesn't have; that id is the
        # one their games use, so it replaces a same-named list entry (Minnesota State women: 24059, not 2364).
        extra = [t for t in listed if str(t["id"]) not in known]
        places = {t.get("location") for t in extra}
        teams_list = [x for x in teams_list if x["team"].get("location") not in places] + [{"team": t} for t in extra]
        by_school = {s: c for c, schools in WOMENS_CONF.items() for s in schools} if lg == "ncaaw" else {}
        rows = []
        for x in teams_list:
            t = x["team"]
            tid = str(t["id"])
            if tid not in colours:
                try:
                    colours[tid] = logo_colour(requests.get(LOGO.format(id=tid), impersonate="chrome").content)
                except Exception as exc:
                    print(f"no logo for {t['displayName']}: {exc!r}", file=sys.stderr)
                    colours[tid] = ("#555555", False)
            if tid not in conf and group:   # not in the standings yet (no games played): ask the team's page
                g = requests.get(f"{ncaa.SITE}/{ncaa.PATH[lg]}/teams/{tid}", impersonate="chrome").json()["team"].get("groups") or {}
                if group.get(str(g.get("id"))):
                    conf[tid] = group[str(g["id"])]
            if t.get("shortDisplayName") in by_school:
                conf[tid] = by_school[t["shortDisplayName"]]
            color, light = colours[tid]
            rows.append({"id": tid, "code": t.get("abbreviation") or "", "school": t.get("shortDisplayName") or t["location"],
                         "full": t.get("displayName"), "conf": conf.get(tid),
                         "color": color, "light": light})
        rows.sort(key=lambda r: r["school"])
        out[lg] = rows
        print(f"{lg}: {len(rows)} teams, {sum(1 for r in rows if r['conf'])} with a conference")
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
