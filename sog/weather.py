"""Weather at puck drop for outdoor games (Winter Classic, Heritage Classic), from Open-Meteo (free, no key).

The game's city (venueLocation) is looked up once with Open-Meteo's geocoder; the forecast is the hour nearest puck drop,
and only within FORECAST_DAYS of the game (Open-Meteo forecasts 16 days, but a week out is the useful range). Pages
never wait on this: Feed.weather_peek() returns the saved copy and refreshes it in the background.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from curl_cffi.requests import AsyncSession

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
FORECAST_DAYS = 7
TTL = timedelta(hours=1)
GEO_TTL = timedelta(days=30)

# WMO weather codes (Open-Meteo's weather_code) -> a few words.
WORDS = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
         51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
         61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
         71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "rain showers", 81: "rain showers",
         82: "heavy showers", 85: "snow showers", 86: "heavy snow showers", 95: "thunderstorms", 96: "thunderstorms",
         99: "thunderstorms"}

_session: AsyncSession | None = None


async def _get(url: str, params: dict) -> dict:
    global _session
    if _session is None:
        _session = AsyncSession(timeout=15)
    r = await _session.get(url, params=params)
    r.raise_for_status()
    return r.json()


def wanted(g: dict, now: datetime | None = None) -> bool:
    """An outdoor game that hasn't finished, with puck drop within the forecast range."""
    ev = g.get("event") or {}
    if ev.get("kind") != "outdoor" or not ev.get("city") or not g.get("start") or g.get("state") in ("final", "postponed"):
        return False
    start = datetime.fromisoformat(g["start"].replace("Z", "+00:00"))
    now = now or datetime.now(timezone.utc)
    return start - now < timedelta(days=FORECAST_DAYS) and now - start < timedelta(hours=4)


async def geocode(city: str) -> dict | None:
    data = await _get(GEOCODE, {"name": city, "count": 1, "language": "en", "format": "json"})
    hit = (data.get("results") or [None])[0]
    return {"lat": hit["latitude"], "lon": hit["longitude"]} if hit else None


async def forecast(lat: float, lon: float, start: str) -> dict | None:
    """The hour nearest puck drop: {"c": -3.2, "code": 71, "text": "light snow", "wind": 14 (km/h)}."""
    data = await _get(FORECAST, {"latitude": lat, "longitude": lon, "timezone": "UTC", "forecast_days": FORECAST_DAYS + 1,
                                 "hourly": "temperature_2m,weather_code,wind_speed_10m"})
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return None
    t0 = datetime.fromisoformat(start.replace("Z", "+00:00")).replace(minute=0, second=0, microsecond=0)
    want = t0.strftime("%Y-%m-%dT%H:%M")
    i = times.index(want) if want in times else None
    if i is None:
        return None
    code = (hourly.get("weather_code") or [None] * len(times))[i]
    return {"c": (hourly.get("temperature_2m") or [None] * len(times))[i], "code": code,
            "text": WORDS.get(code, ""), "wind": (hourly.get("wind_speed_10m") or [None] * len(times))[i]}
