"""iCalendar feed of a person's teams. Calendar apps poll it; UIDs stay stable so updates replace entries."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .teams import ALL

GAME_LENGTH = timedelta(hours=2, minutes=45)


def _esc(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545: lines over 75 octets continue on the next line with a leading space."""
    if len(line.encode()) <= 75:
        return line
    parts, chunk = [], b""
    for ch in line:
        b = ch.encode()
        if len(chunk) + len(b) > (75 if not parts else 74):
            parts.append(chunk.decode())
            chunk = b""
        chunk += b
    parts.append(chunk.decode())
    return "\r\n ".join(parts)


def _name(abbr: str) -> str:
    return ALL[abbr][1] if abbr in ALL else abbr


def build(games: list[dict], base_url: str, title: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Shots on Goal//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(title)}",
             "X-WR-CALDESC:Hockey games from Shots on Goal", "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
             "X-PUBLISHED-TTL:PT6H"]
    for g in games:
        if not g.get("start"):
            continue
        start = datetime.fromisoformat(g["start"].replace("Z", "+00:00"))
        a, h = g["away"], g["home"]
        summary = f"{_name(a['abbr'])} at {_name(h['abbr'])}"
        if g["state"] == "final" and a.get("score") is not None:
            extra = f" ({g['outcome']})" if g.get("outcome") not in (None, "REG") else ""
            summary += f" · Final {a['score']}-{h['score']}{extra}"
        elif g["state"] == "postponed":
            summary += " · Postponed"
        w = g.get("watch") or {}
        desc = []
        if g["state"] != "final" and w.get("network"):
            desc.append(f"Watch: {w['app']} ({w['why']})")
        elif g["state"] != "final":
            desc.append(w.get("why") or "")
        lg = g.get("league") or "nhl"
        desc.append(f"{base_url}/#/{ {'nhl': 'game', 'pwhl': 'pgame'}.get(lg, f'cgame/{lg}') }/{g['id']}")
        lines += ["BEGIN:VEVENT", f"UID:{g.get('league', 'nhl')}-{g['id']}@shotsongoal", f"DTSTAMP:{stamp}",
                  f"DTSTART:{start:%Y%m%dT%H%M%SZ}", f"DTEND:{start + GAME_LENGTH:%Y%m%dT%H%M%SZ}",
                  f"SUMMARY:{_esc(summary)}", f"DESCRIPTION:{_esc(chr(10).join(x for x in desc if x))}",
                  f"LOCATION:{_esc(g.get('venue') or '')}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
