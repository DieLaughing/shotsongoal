"""Player photos and team logos, served from the app's own address (/img/...).

Logos go out as one stylesheet (/img/logos.css: every team's logo as a small WebP data URL, plus dark-background
versions where they differ), so turning logos on costs one ~75 KB download the phone then keeps, not a request and a
pop-in per team on every page. NHL logos come from ESPN's PNGs: the NHL's own are SVGs of up to 35 KB each.

The leagues' originals are big (an NHL headshot is ~80 KB), so each one is downloaded once, shrunk to the sizes the
app draws as WebP (a few KB), kept on disk and sent with a long cache life: the phone and Cloudflare keep them too, so
a page full of faces costs a few KB once and nothing after. A photo that doesn't exist is remembered for a day.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import logging
import time
from pathlib import Path

from curl_cffi.requests import AsyncSession
from PIL import Image

SIZES = (96, 192)              # pixels: twice the 48 and 96 px the app draws, for sharp phone screens
PHOTO_TTL = 7 * 86400          # rosters change; a traded player's new photo comes under his new team anyway
LOGO_TTL = 30 * 86400
MISS_TTL = 86400
NHL_PHOTO = "https://assets.nhle.com/mugs/nhl/{season}/{team}/{pid}.png"
PWHL_PHOTO = "https://assets.leaguestat.com/pwhl/240x240/{pid}.jpg"
NHL_LOGO = "https://a.espncdn.com/i/teamlogos/nhl/{folder}/{code}.png"   # 500 = light backgrounds, 500-dark = dark
ESPN_CODE = {"LAK": "la", "NJD": "nj", "SJS": "sj", "TBL": "tb", "UTA": "utah"}   # ESPN's own abbreviations
LOGO_SIZE = 56   # a badge draws its logo 22 px tall (34 px on big ones): sharp enough, ~1.4 KB each
LOGO_WEBP = {"quality": 75, "alpha_quality": 60, "method": 6}
PWHL_LOGO = "https://assets.leaguestat.com/pwhl/logos/{tid}.png"
log = logging.getLogger("sog.images")


class Missing(Exception):
    pass


class Images:
    def __init__(self, root: Path, season, fallback=None):
        """`season()` gives the NHL season id ("20262027"); `fallback(pid)` an NHL headshot URL from somewhere else
        (the player's own page) for when this season's photo isn't up yet."""
        self.root = root
        self.season = season
        self.fallback = fallback
        self.locks: dict[str, asyncio.Lock] = {}
        self.slots = asyncio.Semaphore(4)   # downloads at once: a new page full of faces shouldn't hammer the leagues
        self._session: AsyncSession | None = None

    async def _get(self, url: str) -> bytes:
        if self._session is None:
            self._session = AsyncSession(impersonate="chrome", timeout=20)
        async with self.slots:
            r = await self._session.get(url)
        if r.status_code in (403, 404):
            raise Missing(url)
        r.raise_for_status()
        return r.content

    @staticmethod
    def _fresh(path: Path, ttl: int) -> bool:
        try:
            return time.time() - path.stat().st_mtime < ttl
        except FileNotFoundError:
            return False

    async def _cached(self, path: Path, ttl: int, make) -> Path | None:
        """`path` if it's fresh, else made by `make()` (writes it; raises Missing when there's nothing to make)."""
        miss = path.with_suffix(".miss")
        if self._fresh(path, ttl):
            return path
        if self._fresh(miss, MISS_TTL):
            return None
        async with self.locks.setdefault(str(path), asyncio.Lock()):
            if self._fresh(path, ttl):
                return path
            try:
                await make()
                return path
            except Missing:
                path.parent.mkdir(parents=True, exist_ok=True)
                miss.touch()
                return None
            except Exception as exc:   # a league hiccup: an old copy beats nothing
                log.warning("image %s failed: %r", path.name, exc)
                return path if path.exists() else None

    async def photo(self, league: str, team: str, pid: int, size: int) -> Path | None:
        folder = self.root / "p" / league / team

        async def make():
            if league == "nhl":
                try:
                    raw = await self._get(NHL_PHOTO.format(season=self.season(), team=team, pid=pid))
                except Missing:
                    url = await self.fallback(pid) if self.fallback else None
                    if not url:
                        raise
                    raw = await self._get(url)
            else:
                raw = await self._get(PWHL_PHOTO.format(pid=pid))
            await asyncio.to_thread(_shrink, raw, folder, str(pid))
        return await self._cached(folder / f"{pid}-{size}.webp", PHOTO_TTL, make)

    async def nhl_logo(self, abbr: str, variant: str) -> Path | None:
        folder, name = self.root / "logo", f"{abbr}-{variant}"

        async def make():
            code = ESPN_CODE.get(abbr, abbr.lower())
            raw = await self._get(NHL_LOGO.format(folder="500-dark" if variant == "dark" else "500", code=code))
            await asyncio.to_thread(_shrink, raw, folder, name, (LOGO_SIZE,), LOGO_WEBP)
        return await self._cached(folder / f"{name}-{LOGO_SIZE}.webp", LOGO_TTL, make)

    async def pwhl_logo(self, key: str, tid: int) -> Path | None:
        folder = self.root / "logo"

        async def make():
            raw = await self._get(PWHL_LOGO.format(tid=tid))
            await asyncio.to_thread(_shrink, raw, folder, key, (LOGO_SIZE,), LOGO_WEBP)
        return await self._cached(folder / f"{key}-{LOGO_SIZE}.webp", LOGO_TTL, make)


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _shrink(raw: bytes, folder: Path, name: str, sizes=SIZES, webp=None) -> None:
    """Every size from one download: squared up (photos already are), transparency kept."""
    img = Image.open(io.BytesIO(raw))
    img = img.convert("RGBA")
    if img.width != img.height:
        side = max(img.size)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
        img = square
    for size in sizes:
        out = io.BytesIO()
        img.resize((size, size), Image.LANCZOS).save(out, "WEBP", **(webp or {"quality": 80, "method": 4}))
        _write(folder / f"{name}-{size}.webp", out.getvalue())


async def logos_css(imgs: Images, nhl: list[str], pwhl: dict[str, int]) -> Path | None:
    """Build (or reuse) logos.css: `.mark.lg-BOS` rules with the logo as the background. A team whose logo can't be
    had gets no rule, so it keeps its badge."""
    path = imgs.root / "logos.css"
    if Images._fresh(path, LOGO_TTL):
        return path
    async with imgs.locks.setdefault(str(path), asyncio.Lock()):
        if Images._fresh(path, LOGO_TTL):
            return path
        jobs = [imgs.nhl_logo(a, v) for a in nhl for v in ("light", "dark")] + [imgs.pwhl_logo(k, t) for k, t in pwhl.items()]
        got = await asyncio.gather(*jobs, return_exceptions=True)
        light, dark = [], []
        rule = '.mark.lg-{k}{{background:url("{u}") center/contain no-repeat;color:transparent}}'
        for i, abbr in enumerate(nhl):
            lp, dp = got[2 * i], got[2 * i + 1]
            if isinstance(lp, Path):
                light.append(rule.format(k=abbr, u=_data_url(lp)))
                if isinstance(dp, Path) and dp.read_bytes() != lp.read_bytes():
                    dark.append(f'.mark.lg-{abbr}{{background-image:url("{_data_url(dp)}")}}')
        for j, key in enumerate(pwhl):
            pp = got[2 * len(nhl) + j]
            if isinstance(pp, Path):
                light.append(rule.format(k=key, u=_data_url(pp)))
        if not light:
            return path if path.exists() else None
        css = "\n".join(light) + "\n@media (prefers-color-scheme: dark) {\n" + "\n".join(dark) + "\n}\n"
        _write(path, css.encode())
        return path


def css_version(path: Path) -> str | None:
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()[:10]
    except FileNotFoundError:
        return None


def _data_url(path: Path) -> str:
    return "data:image/webp;base64," + base64.b64encode(path.read_bytes()).decode()
