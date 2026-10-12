"""Where to watch a game in the US, for one person's local teams and services.

Rules, first match wins:
1. A US national broadcast with no home/away channels = national exclusive: everyone watches that.
2. One of your local teams is playing: its own channel (blacked out on ESPN+ for you), else the national one.
3. Not your local team, but a national network carries it alongside the local channels: that network
   (ESPN+ blacks out national games).
4. Otherwise it's out of market for you: ESPN+.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

DATA = Path(__file__).resolve().parent / "data" / "networks.yaml"
# Home-market teams for people who haven't chosen yet (their games are blacked out on national streams).
# SOG_DEFAULT_LOCAL=BOS for a group in New England; empty = none.
DEFAULT_LOCAL = [t.strip().upper() for t in os.environ.get("SOG_DEFAULT_LOCAL", "").split(",") if t.strip()]


@lru_cache(maxsize=1)
def config() -> dict:
    return yaml.safe_load(DATA.read_text())


def services() -> dict:
    return config()["services"]


def _pick_national(nets: list[str], have: set[str]) -> str:
    """Several national networks can carry one game (TNT + truTV + HBO Max). Prefer one the person has."""
    national = config()["national"]
    for n in nets:
        if national.get(n, {}).get("service") in have:
            return n
    return nets[0]


def _result(network: str, why: str, have: set[str], regional: bool = False) -> dict:
    cfg = config()
    if regional:
        info = cfg["regional"].get(network) or {}
        app, service = info.get("app") or network, "regional"
    else:
        info = cfg["national"].get(network) or {}
        app, service = info.get("app") or network, info.get("service")
    svc = cfg["services"].get(service) if service else None
    url = info.get("url") or (svc or {}).get("url")
    links = ([{"name": app, "url": url}] if url else []) + list((svc or {}).get("also") or [])
    return {"network": network, "app": app, "why": why, "service": service,
            "have": (service in have) if svc else None, "url": url, "links": links}


def watch_for(game: dict, local: list[str] | None = None, have: list[str] | None = None) -> dict:
    local = set(DEFAULT_LOCAL if local is None else local)
    have_set = set(have or [])
    national_cfg = config()["national"]
    away, home = game["away"]["abbr"], game["home"]["abbr"]
    us = [b for b in game.get("broadcasts") or [] if b.get("country") == "US"]
    regional = {"H": [b["network"] for b in us if b["market"] == "H"],
                "A": [b["network"] for b in us if b["market"] == "A"]}
    national = [b["network"] for b in us if b["market"] == "N"]
    real_national = [n for n in national if not national_cfg.get(n, {}).get("not_exclusive")]

    if not us:
        return {"network": None, "app": None, "why": "No US broadcast listed yet", "service": None,
                "have": None, "url": None}
    if national and not regional["H"] and not regional["A"]:
        return _result(_pick_national(real_national or national, have_set), "National exclusive", have_set)

    mine = home if home in local else away if away in local else None
    if mine:
        own = regional["H"] if mine == home else regional["A"]
        if own:
            return _result(own[0], f"{mine} local broadcast · blacked out on ESPN+", have_set, regional=True)
        if real_national:
            return _result(_pick_national(real_national, have_set), "National broadcast", have_set)
        return {"network": None, "app": None, "why": f"{mine} game with no local listing", "service": None,
                "have": None, "url": None}

    if real_national:
        return _result(_pick_national(real_national, have_set), "National broadcast · blacked out on ESPN+", have_set)
    return _result("ESPN+", "Out of market", have_set)
