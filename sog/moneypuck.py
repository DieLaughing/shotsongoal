"""Advanced stats from MoneyPuck's open data (moneypuck.com/data.htm): expected goals, shot-attempt share and
goals saved above expected, for NHL player pages.

MoneyPuck's terms: free for non-commercial use, credit MoneyPuck.com wherever the numbers show (the player page links
it). We fetch the two season files listed on that page, at most every few hours, and keep a few numbers per player.
"""
from __future__ import annotations

import csv
import io

from curl_cffi.requests import AsyncSession

BASE = "https://moneypuck.com/moneypuck/playerData/seasonSummary"
CREDIT = "https://moneypuck.com"
_session: AsyncSession | None = None


async def get(url: str) -> str:
    global _session
    if _session is None:
        _session = AsyncSession(impersonate="chrome", timeout=40)
    r = await _session.get(url)
    r.raise_for_status()
    return r.text


async def fetch(season: str) -> dict:
    """season "20262027": MoneyPuck files it under its first year."""
    year = season[:4]
    skaters = await get(f"{BASE}/{year}/regular/skaters.csv")
    goalies = await get(f"{BASE}/{year}/regular/goalies.csv")
    return parse(skaters, goalies)


def _f(row: dict, key: str) -> float:
    try:
        return float(row.get(key) or 0)
    except ValueError:
        return 0.0


def _pct_rank(values: dict[int, float], higher_better: bool = True) -> dict[int, int]:
    """Each player's percentile (0-100) among `values`: 90 = better than 90% of the others."""
    ranked = sorted(values, key=lambda k: values[k], reverse=not higher_better)
    n = len(ranked)
    return {k: round(100 * i / (n - 1)) if n > 1 else 50 for i, k in enumerate(ranked)}


def parse(skaters_csv: str, goalies_csv: str) -> dict:
    """{str(player id): numbers}. Percentiles compare regulars only (at least a third of the most games played), so a
    call-up with one lucky game doesn't top the table."""
    rows: dict[int, dict] = {}
    for r in csv.DictReader(io.StringIO(skaters_csv)):
        pid, sit = int(r["playerId"]), r.get("situation")
        if sit not in ("all", "5on5"):
            continue
        s = rows.setdefault(pid, {"goalie": False})
        if sit == "all":
            s.update(gp=int(_f(r, "games_played")), xg=round(_f(r, "I_F_xGoals"), 1), goals=int(_f(r, "I_F_goals")),
                     attempts=int(_f(r, "I_F_shotAttempts")))
        else:
            s.update(xgf=round(_f(r, "onIce_xGoalsPercentage") * 100, 1), cf=round(_f(r, "onIce_corsiPercentage") * 100, 1))
    for r in csv.DictReader(io.StringIO(goalies_csv)):
        if r.get("situation") != "all":
            continue
        xga, ga, hd, hdg = _f(r, "xGoals"), _f(r, "goals"), _f(r, "highDangerShots"), _f(r, "highDangerGoals")
        rows[int(r["playerId"])] = {"goalie": True, "gp": int(_f(r, "games_played")), "xga": round(xga, 1), "ga": int(ga),
                                    "gsax": round(xga - ga, 1), "hd": int(hd),
                                    "hdsv": round(1 - hdg / hd, 3) if hd else None}
    for goalie in (False, True):
        group = {k: v for k, v in rows.items() if v["goalie"] is goalie and "gp" in v}
        most = max((v["gp"] for v in group.values()), default=0)
        regulars = {k: v for k, v in group.items() if v["gp"] >= most / 3}
        stats = ("gsax", "hdsv") if goalie else ("xg", "xgf", "cf")
        for stat in stats:
            ranks = _pct_rank({k: v[stat] for k, v in regulars.items() if v.get(stat) is not None})
            for k, pct in ranks.items():
                rows[k].setdefault("pct", {})[stat] = pct
    return {str(k): v for k, v in rows.items() if "gp" in v}
