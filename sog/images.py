"""Player photos and team logos, served from the app's own address (/img/...).

The leagues' originals are big (an NHL headshot is ~80 KB), so each one is downloaded once, shrunk to the sizes the
app draws as WebP (a few KB), kept on disk and sent with a long cache life: the phone and Cloudflare keep them too, so
a page full of faces costs a few KB once and nothing after. A photo that doesn't exist is remembered for a day.
"""
from __future__ import annotations

import asyncio
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
NHL_LOGO = "https://assets.nhle.com/logos/nhl/svg/{abbr}_{variant}.svg"   # "dark" is drawn for dark backgrounds
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
        path = self.root / "logo" / f"{abbr}-{variant}.svg"

        async def make():
            raw = await self._get(NHL_LOGO.format(abbr=abbr, variant=variant))
            if b"<svg" not in raw[:2000]:
                raise Missing(abbr)
            _write(path, raw)
        return await self._cached(path, LOGO_TTL, make)

    async def pwhl_logo(self, key: str, tid: int) -> Path | None:
        folder = self.root / "logo"

        async def make():
            raw = await self._get(PWHL_LOGO.format(tid=tid))
            await asyncio.to_thread(_shrink, raw, folder, key, (96,))
        return await self._cached(folder / f"{key}-96.webp", LOGO_TTL, make)


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _shrink(raw: bytes, folder: Path, name: str, sizes=SIZES) -> None:
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
        img.resize((size, size), Image.LANCZOS).save(out, "WEBP", quality=80, method=4)
        _write(folder / f"{name}-{size}.webp", out.getvalue())
