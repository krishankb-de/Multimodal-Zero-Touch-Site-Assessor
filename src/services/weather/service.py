"""
Weather Intelligence Service — main orchestrator.

Ties together geocoding → cache lookup → historical data fetch → analysis → cache store.
Returns a WeatherProfile on success, or None on any API failure (caller falls back
to static regional climate data).
"""

from __future__ import annotations

import logging

import httpx

from src.common.schemas import WeatherProfile
from src.services.weather.analysis import analyze_weather
from src.services.weather.cache import WeatherCache
from src.services.weather.geocoding import GeocodingError, geocode
from src.services.weather.historical import WeatherFetchError, fetch_historical_weather

logger = logging.getLogger(__name__)


class WeatherIntelligenceService:
    """
    Orchestrates the full weather intelligence pipeline:
      geocode → cache check → fetch historical data → analyze → cache store → return.

    Usage:
        service = WeatherIntelligenceService()
        profile = await service.get_weather_profile("Hamburg")
        # profile is WeatherProfile or None (on API failure)
    """

    def __init__(self) -> None:
        self._cache = WeatherCache()
        # Shared async client — reused across calls for connection pooling
        self._client = httpx.AsyncClient(timeout=30.0)

    async def get_weather_profile(self, location: str) -> WeatherProfile | None:
        """
        Retrieve a WeatherProfile for the given location string.

        Pipeline:
        1. Geocode location → (lat, lon)
        2. Check in-memory cache
        3. Fetch 5 years of historical data from Open-Meteo Archive API
        4. Analyze raw data → WeatherProfile
        5. Store in cache
        6. Return WeatherProfile

        Returns:
            WeatherProfile on success.
            None if any API call fails (caller uses static climate data as fallback).

        Raises:
            GeocodingError: If the location cannot be resolved or is outside Germany.
                            This is re-raised so the caller can return a 422 to the user.
        """
        if not location or not location.strip():
            logger.warning("WeatherIntelligenceService: empty location string, skipping")
            return None

        # Step 1: Geocode — GeocodingError is intentionally propagated
        try:
            lat, lon = await geocode(location, client=self._client)
        except GeocodingError:
            raise  # Let the orchestrator/route handle this as a user-facing error
        except httpx.HTTPError as exc:
            logger.warning(
                "WeatherIntelligenceService: geocoding HTTP error for '%s': %s — "
                "falling back to static climate data",
                location, exc,
            )
            return None

        # Step 2: Cache check
        cached = self._cache.get(lat, lon)
        if cached is not None:
            logger.info(
                "WeatherIntelligenceService: cache hit for '%s' (%.4f, %.4f)",
                location, lat, lon,
            )
            return cached

        # Step 3: Fetch historical data
        try:
            raw = await fetch_historical_weather(lat, lon, years=5, client=self._client)
        except (WeatherFetchError, httpx.HTTPError) as exc:
            logger.warning(
                "WeatherIntelligenceService: historical data fetch failed for "
                "'%s' (%.4f, %.4f): %s — falling back to static climate data",
                location, lat, lon, exc,
            )
            return None

        # Step 4: Analyze
        try:
            profile = analyze_weather(raw, lat, lon)
        except Exception as exc:
            logger.warning(
                "WeatherIntelligenceService: analysis failed for '%s': %s — "
                "falling back to static climate data",
                location, exc,
            )
            return None

        # Step 5: Cache
        self._cache.put(lat, lon, profile)

        logger.info(
            "WeatherIntelligenceService: profile ready for '%s' "
            "(%.4f, %.4f) — irradiance=%.0f kWh/m²/yr, sunny_days=%d/yr",
            location, lat, lon,
            profile.annual_irradiance_kwh_m2,
            profile.sunny_days_per_year,
        )
        return profile

    async def close(self) -> None:
        """Close the shared HTTP client."""
        await self._client.aclose()
