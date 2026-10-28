"""Where to watch a game in the US or Canada, for one person's local teams, services and country.

US rules, first match wins:
1. A US national broadcast with no home/away channels = national exclusive: everyone watches that.
2. One of your local teams is playing: its own channel (blacked out on ESPN+ for you), else the national one.
3. Not your local team, but a national network carries it alongside the local channels: that network
   (ESPN+ blacks out national games).
4. Otherwise it's out of market for you: ESPN+.

Canada (country CA; networks.yaml `canada`), first match wins:
1. No Canadian broadcaster listed (US teams only): out of market, Sportsnet+ Premium.
2. A national network (Sportsnet, Sportsnet+, Prime, TVA Sports): no blackouts anywhere in Canada. A game only TVA
   Sports has (in French) is out of market in English, unless you have TVA Sports.
3. One of your local (home-region) teams' regional channels: TSN, RDS or a Sportsnet regional.
4. Another region's game: blacked out on TV for you, so Sportsnet+ Premium.
English channels come before French ones unless you only have the French service.
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
    """Every service anyone can tick, each with its country (Settings shows the person's country's)."""
    return {**{k: {**v, "country": "US"} for k, v in config()["services"].items()},
            **{k: {**v, "country": "CA"} for k, v in config()["canada"]["services"].items()}}


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


def watch_for(game: dict, local: list[str] | None = None, have: list[str] | None = None, country: str | None = None) -> dict:
    local = set(DEFAULT_LOCAL if local is None else local)
    have_set = set(have or [])
    if country == "CA":
        return _canada(game, local, have_set)
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


# ---- college -------------------------------------------------------------------------------------
def college(game: dict, have: list[str] | None = None, country: str | None = None) -> dict:
    """College games stream wherever ESPN lists them, with no blackouts. The first listed stream the person has
    leads; ESPN+ and B1G+ are US services, so in Canada nothing is claimed either way."""
    cfg, svcs = config().get("college") or {}, config()["services"]
    have_set = set(have or [])
    nets = game.get("networks") or []
    if not nets:
        return {"network": None, "app": None, "why": "No stream listed yet", "service": None, "have": None, "url": None}
    nets = sorted(nets, key=lambda n: (cfg.get(n) or {}).get("service") not in have_set)
    links, seen = [], set()
    for n in nets:
        info = cfg.get(n) or {}
        url = info.get("url") or (svcs.get(info.get("service")) or {}).get("url")
        app = info.get("app") or n
        if url and app not in seen:
            seen.add(app)
            links.append({"name": app, "url": url})
    first = cfg.get(nets[0]) or {}
    service = first.get("service")
    ca = country == "CA"
    return {"network": nets[0], "app": first.get("app") or nets[0], "service": service,
            "why": "US streams; may not play in Canada" if ca else ("Streaming" if len(nets) == 1 else f"Also on {', '.join(nets[1:])}"),
            "have": None if ca or not service or have is None else service in have_set, "url": links[0]["url"] if links else None,
            "links": links[:2]}


# ---- Canada --------------------------------------------------------------------------------------
def _ca_result(network: str | None, info: dict, why: str, have: set[str]) -> dict:
    svcs = config()["canada"]["services"]
    carried = info.get("services") or []
    service = next((x for x in carried if x in have), carried[0] if carried else None)
    url = (svcs.get(service) or {}).get("url")
    return {"network": network, "app": info.get("app") or network, "why": why, "service": service,
            "have": any(x in have for x in carried) if carried else None, "url": url,
            "links": [{"name": info.get("app") or network, "url": url}] if url else []}


def _ca_pick(nets: list[str], have: set[str]) -> str:
    """English before French, then the first one the person has."""
    known = config()["canada"]["networks"]
    nets = sorted(nets, key=lambda n: bool(known.get(n, {}).get("french")))
    return next((n for n in nets if set(known.get(n, {}).get("services") or []) & have), nets[0])


def _canada(game: dict, local: set[str], have: set[str]) -> dict:
    cfg = config()["canada"]
    away, home = game["away"]["abbr"], game["home"]["abbr"]
    ca = [b for b in game.get("broadcasts") or [] if b.get("country") == "CA"]
    if not ca:
        return _ca_result(None, cfg["out_of_market"], "Out of market (no Canadian broadcast)", have)
    national = [b["network"] for b in ca if b["market"] == "N"]
    french = lambda n: cfg["networks"].get(n, {}).get("french")
    has_french = any(set(cfg["networks"].get(n, {}).get("services") or []) & have for n in national if french(n))
    if national and all(map(french, national)) and not has_french:
        # Only TVA Sports has it (in French): in English it's an out-of-market game.
        return _ca_result(None, cfg["out_of_market"], f"Out of market in English · {cfg['networks'][national[0]]['app']} in French", have)
    if national:
        n = _ca_pick(national, have)
        why = {"SN+": "Monday Night Hockey · streaming only", "Prime": "Wednesday Night Hockey"}.get(n, "National broadcast")
        return _ca_result(n, cfg["networks"].get(n) or {}, why, have)
    mine = home if home in local else away if away in local else None
    own = [b["network"] for b in ca if b["market"] == ("H" if mine == home else "A")] if mine else []
    if own:
        n = _ca_pick(own, have)
        return _ca_result(n, cfg["networks"].get(n) or {}, f"{mine} regional broadcast", have)
    return _ca_result(None, cfg["out_of_market"], "Regional game outside your region", have)
