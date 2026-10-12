"""The Wire: trades and roster moves (ESPN), headlines (ESPN, Sportsnet) and insider posts (Bluesky).

Every item comes out in one shape: {id, kind, time, title, text, url, source, teams, image, league}.
kind = move | news | insider. teams = team keys (NHL "BOS", PWHL "PW-BOS"), used for favourites and team pages.
PWHL items come from women's hockey outlets and a separate Bluesky list, and are tagged with PWHL names only.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime
from html import unescape

from curl_cffi.requests import AsyncSession

from .teams import PWHL, TEAMS

ESPN = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl"
SPORTSNET = "https://www.sportsnet.ca/hockey/nhl/feed/"
THN_WOMEN = "https://thehockeynews.com/womens/.rss/full/"
ICE_GARDEN = "https://www.theicegarden.com/feed"

# Checked 2026-10-11: the league, its teams and the outlets that cover it, all posting within the last month
# (the players' association since September). There are no PWHL insider mirrors as there are for the NHL.
PWHL_INSIDERS = [
    ("thepwhl.com", "PWHL"),
    ("bostonfleet.com", "Boston Fleet"),
    ("pwhlcharge.bsky.social", "Ottawa Charge"),
    ("pwhlsceptres.bsky.social", "Toronto Sceptres"),
    ("pwhlgoldeneyes.bsky.social", "Vancouver Goldeneyes"),
    ("pwhl--detroit.bsky.social", "PWHL Detroit"),
    ("pwhl-sanjose.bsky.social", "PWHL San Jose"),
    ("thehockeynewsw.bsky.social", "The Hockey News – Women's"),
    ("theicegarden.bsky.social", "The Ice Garden"),
    ("avapwhl.bsky.social", "365HockeyGirl"),
    ("pwhlpa.bsky.social", "PWHL Players' Association"),
]
BSKY = "https://public.api.bsky.app/xrpc"

# Checked 2026-10-11: each had posted within the week. The big three (Friedman, LeBrun, Seravalli) stayed on X;
# on Bluesky they exist only as fan-run mirror bots that repost their tweets.
DEFAULT_INSIDERS = [
    ("notfriedgehnic.bsky.social", "Elliotte Friedman (mirror)"),
    ("notpierrevlebrun.bsky.social", "Pierre LeBrun (mirror)"),
    ("notfrankseravalli.bsky.social", "Frank Seravalli (mirror)"),
    ("nhltradealert.bsky.social", "NHL Trade Alert"),
    ("puckpedia.com", "PuckPedia"),
    ("dailyfaceoff.bsky.social", "Daily Faceoff"),
    ("downgoesbrown.bsky.social", "Sean McIndoe"),
    ("russohockey.bsky.social", "Michael Russo"),
    ("murphyslaw74.bsky.social", "Jimmy Murphy"),
    ("ty-anderson.bsky.social", "Ty Anderson (Bruins)"),
    ("mattyports.bsky.social", "Matt Porter (Bruins)"),
    ("bruinsnhlbot.bsky.social", "Bruins (mirror)"),
]

# ESPN uses its own abbreviations and team ids.
ESPN_ABBR = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "UTAH": "UTA"}
ESPN_ID = {"25": "ANA", "1": "BOS", "2": "BUF", "7": "CAR", "29": "CBJ", "3": "CGY", "4": "CHI", "17": "COL",
           "9": "DAL", "5": "DET", "6": "EDM", "26": "FLA", "8": "LAK", "30": "MIN", "10": "MTL", "11": "NJD",
           "27": "NSH", "12": "NYI", "13": "NYR", "14": "OTT", "15": "PHI", "16": "PIT", "124292": "SEA",
           "18": "SJS", "19": "STL", "20": "TBL", "21": "TOR", "129764": "UTA", "22": "VAN", "37": "VGK",
           "28": "WPG", "23": "WSH"}

# Words that mean a team in free text. Case-sensitive, whole words.
# City names count too, except New York (two teams). "Wild" alone is too common a word.
NICKNAMES = {abbr: [name] + ([] if place == "New York" else [place]) for abbr, (place, name, _) in TEAMS.items()}
NICKNAMES["MIN"] = ["Minnesota"]
for abbr, extra in {"MTL": ["Habs"], "TOR": ["Leafs"], "CAR": ["Canes"], "COL": ["Avs"], "OTT": ["Sens"],
                    "NYI": ["Isles"], "PIT": ["Pens"], "TBL": ["Bolts"], "NSH": ["Preds"], "VGK": ["Knights"],
                    "DET": ["Wings"], "CBJ": ["Jackets"], "UTA": ["Utah Hockey Club"]}.items():
    NICKNAMES[abbr] += extra
_TEAM_RE = [(abbr, re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b|\(" + abbr + r"\)"))
            for abbr, words in NICKNAMES.items()]

# PWHL names: nickname, city, and "PWHL <city>" for the expansion teams that don't have nicknames yet.
PWHL_WORDS = {k: sorted({place, f"PWHL {place}"} | ({name} if name != place else set())) for k, (place, name, _) in PWHL.items()}
_PWHL_RE = [(k, re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b")) for k, words in PWHL_WORDS.items()]

# A mixed women's-sports feed: a city alone ("New York Liberty") isn't a PWHL story; a nickname or the league is.
_PWHL_STORY = re.compile(r"\b(?:PWHL|" + "|".join(re.escape(n) for _, (p, n, _c) in PWHL.items() if n != p) + r")\b")

_session: AsyncSession | None = None


async def _get(url: str, **params):
    global _session
    if _session is None:
        _session = AsyncSession(impersonate="chrome", timeout=20)
    r = await _session.get(url, params=params or None, allow_redirects=True)
    r.raise_for_status()
    return r


def teams_in(text: str, league: str = "nhl") -> list[str]:
    patterns = _PWHL_RE if league == "pwhl" else _TEAM_RE
    return [abbr for abbr, rx in patterns if rx.search(text or "")]


def _iso(ts: str | None) -> str | None:
    """ESPN writes 2026-10-11T07:00Z; Bluesky adds microseconds. Normalise to ...:SSZ."""
    if not ts:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(:\d{2})?", ts)
    return f"{m.group(1)}{m.group(2) or ':00'}Z" if m else None


# ---- parsers -----------------------------------------------------------------------
def parse_moves(data: dict) -> list[dict]:
    out = []
    for t in data.get("transactions") or []:
        team = (t.get("team") or {})
        abbr = ESPN_ABBR.get(team.get("abbreviation"), team.get("abbreviation"))
        text = (t.get("description") or "").strip()
        if not text:
            continue
        digest = hashlib.sha1(text.encode()).hexdigest()[:10]
        out.append({"id": f"move:{abbr}:{t.get('date')}:{digest}", "kind": "move", "league": "nhl",
                    "time": _iso(t.get("date")), "title": None, "text": text, "url": None, "source": "ESPN",
                    "teams": [abbr] if abbr in TEAMS else [], "image": None,
                    "trade": bool(re.search(r"\b(traded|acquired)\b", text, re.I))})
    return out


def parse_espn_news(data: dict) -> list[dict]:
    out = []
    for a in data.get("articles") or []:
        if a.get("type") not in ("Story", "HeadlineNews"):
            continue  # skip video clips and the auto-written preview/recap ESPN makes for every game
        teams = [ESPN_ID[str(c.get("teamId"))] for c in a.get("categories") or []
                 if c.get("type") == "team" and str(c.get("teamId")) in ESPN_ID]
        out.append({"id": f"espn:{a.get('id')}", "kind": "news", "league": "nhl", "time": _iso(a.get("published")),
                    "title": a.get("headline"), "text": a.get("description"),
                    "url": re.sub(r"^http:", "https:", ((a.get("links") or {}).get("web") or {}).get("href") or ""),
                    "source": "ESPN" + (" (ESPN+)" if a.get("premium") else ""),
                    "teams": sorted(set(teams)), "image": ((a.get("images") or [{}])[0]).get("url")})
    return out


def _strip_html(s: str) -> str:
    return unescape(re.sub(r"<[^>]+>", " ", s or "")).split("The post ")[0].strip()


def parse_rss(xml: str, source: str, league: str = "nhl") -> list[dict]:
    root = ET.fromstring(xml)
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = re.sub(r"\s+", " ", _strip_html(item.findtext("description") or ""))[:300]
        try:
            time = parsedate_to_datetime(item.findtext("pubDate")).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            time = None
        if title and link:
            out.append({"id": f"rss:{link}", "kind": "news", "time": time, "title": unescape(title), "text": desc,
                        "url": link, "source": source, "teams": teams_in(f"{title} {desc}", league), "image": None,
                        "league": league})
    return out


def parse_bsky(data: dict, handle: str, label: str, league: str = "nhl") -> list[dict]:
    out = []
    for item in data.get("feed") or []:
        if item.get("reason"):
            continue  # reposts of someone else
        post = item.get("post") or {}
        rec = post.get("record") or {}
        if rec.get("reply"):
            continue
        text = (rec.get("text") or "").strip()
        rkey = (post.get("uri") or "").rsplit("/", 1)[-1]
        embed = post.get("embed") or {}
        ext = embed.get("external") or (embed.get("media") or {}).get("external") or {}
        image = None
        for img in (embed.get("images") or (embed.get("media") or {}).get("images") or []):
            image = img.get("thumb")
            break
        if not text and not ext:
            continue
        out.append({"id": f"bsky:{post.get('uri')}", "kind": "insider", "time": _iso(rec.get("createdAt")),
                    "title": None, "text": text, "url": f"https://bsky.app/profile/{handle}/post/{rkey}",
                    "source": label, "teams": teams_in(f"{text} {ext.get('title', '')}", league), "image": image, "league": league,
                    "link": {"title": ext.get("title"), "url": ext.get("uri")} if ext.get("uri") else None})
    return out


# ---- fetchers ------------------------------------------------------------------------
async def fetch_moves() -> list[dict]:
    return parse_moves((await _get(f"{ESPN}/transactions", limit=100)).json())


async def fetch_espn_news() -> list[dict]:
    return parse_espn_news((await _get(f"{ESPN}/news", limit=50)).json())


async def fetch_sportsnet() -> list[dict]:
    return parse_rss((await _get(SPORTSNET)).text, "Sportsnet")


async def fetch_bsky(handle: str, label: str, league: str = "nhl") -> list[dict]:
    r = await _get(f"{BSKY}/app.bsky.feed.getAuthorFeed", actor=handle, limit=30, filter="posts_no_replies")
    return parse_bsky(r.json(), handle, label, league)


async def fetch_pwhl_news() -> list[dict]:
    """The Hockey News' women's section (mostly PWHL) and The Ice Garden (all women's sports: keep only
    stories naming a PWHL team or the league)."""
    thn = parse_rss((await _get(THN_WOMEN)).text, "The Hockey News", "pwhl")
    try:
        garden = [i for i in parse_rss((await _get(ICE_GARDEN)).text, "The Ice Garden", "pwhl")
                  if _PWHL_STORY.search(f"{i['title']} {i['text']}")]
    except Exception:
        garden = []
    return thn + garden


async def check_handle(handle: str) -> dict | None:
    """The profile behind a handle, or None if Bluesky doesn't know it."""
    try:
        p = (await _get(f"{BSKY}/app.bsky.actor.getProfile", actor=handle)).json()
    except Exception:
        return None
    return {"handle": p.get("handle"), "name": p.get("displayName") or p.get("handle")}
