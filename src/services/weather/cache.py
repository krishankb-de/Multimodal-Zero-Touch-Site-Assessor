"""
In-memory coordinate-keyed cache for WeatherProfile objects.

Cache keys are (round(lat, 2), round(lon, 2)) tuples, giving ~1.1 km precision
at German latitudes. This avoids redundant Open-Meteo API calls for nearby locations.
"""

from __future__ import annotations

import logging

from src.common.schemas import WeatherProfile

logger = logging.getLogger(__name__)

# Decimal places for coordinate rounding (~1.1 km precision at 52°N)
_COORD_PRECISION = 2


def _key(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat, _COORD_PRECISION), round(lon, _COORD_PRECISION))


class WeatherCache:
    """
    Thread-safe in-memory cache for WeatherProfile objects keyed by rounded coordinates.

    Suitable for the single-process FastAPI deployment. For multi-process deployments
    this should be replaced with a shared cache (Redis, etc.).
    """

    def __init__(self) -> None:
        self._store: dict[tuple[float, float], WeatherProfile] = {}

    def get(self, lat: float, lon: float) -> WeatherProfile | None:
        """
        Return the cached WeatherProfile for the given coordinates, or None on miss.

        Coordinates are rounded to 2 decimal places before lookup.
        """
        k = _key(lat, lon)
        profile = self._store.get(k)
        if profile is not None:
            logger.debug("WeatherCache HIT for key %s", k)
        else:
            logger.debug("WeatherCache MISS for key %s", k)
        return profile

    def put(self, lat: float, lon: float, profile: WeatherProfile) -> None:
        """
        Store a WeatherProfile under the rounded coordinate key.
        """
        k = _key(lat, lon)
        self._store[k] = profile
        logger.debug("WeatherCache PUT for key %s", k)

    def clear(self) -> None:
        """Remove all cached entries."""
        self._store.clear()
        logger.debug("WeatherCache cleared")

    def __len__(self) -> int:
        return len(self._store)
