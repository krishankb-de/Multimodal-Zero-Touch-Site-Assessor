"""
Geocoding client using the Open-Meteo Geocoding API.

Converts a human-readable location string to (latitude, longitude) coordinates
and validates the result falls within the Germany bounding box.

Open-Meteo Geocoding API docs:
  https://open-meteo.com/en/docs/geocoding-api
  GET https://geocoding-api.open-meteo.com/v1/search?name={query}&count=1&language=en
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

# Germany bounding box (degrees)
GERMANY_LAT_MIN = 47.0
GERMANY_LAT_MAX = 55.5
GERMANY_LON_MIN = 5.5
GERMANY_LON_MAX = 15.5

GEOCODING_API_URL = "https://geocoding-api.open-meteo.com/v1/search"
GEOCODING_TIMEOUT_S = 10.0


class GeocodingError(Exception):
    """Raised when a location string cannot be resolved to valid coordinates."""

    def __init__(self, location: str, reason: str) -> None:
        self.location = location
        self.reason = reason
        super().__init__(f"Geocoding failed for '{location}': {reason}")


def is_within_germany(lat: float, lon: float) -> bool:
    """Return True if (lat, lon) falls within the Germany bounding box."""
    return (
        GERMANY_LAT_MIN <= lat <= GERMANY_LAT_MAX
        and GERMANY_LON_MIN <= lon <= GERMANY_LON_MAX
    )


async def geocode(
    location: str,
    client: httpx.AsyncClient | None = None,
) -> tuple[float, float]:
    """
    Resolve a location string to (latitude, longitude) via Open-Meteo Geocoding API.

    Args:
        location: Human-readable address or place name (e.g. "Hamburg", "Berlin Mitte").
        client:   Optional shared httpx.AsyncClient. A new one is created if not provided.

    Returns:
        (latitude, longitude) tuple in decimal degrees.

    Raises:
        GeocodingError: If the location cannot be resolved, returns no results,
                        or the resolved coordinates fall outside Germany.
        httpx.HTTPError: Propagated on network/HTTP errors (caller handles fallback).
    """
    if not location or not location.strip():
        raise GeocodingError(location, "Location string is empty")

    params = {
        "name": location.strip(),
        "count": 1,
        "language": "en",
        "format": "json",
    }

    own_client = client is None
    _client = client or httpx.AsyncClient(timeout=GEOCODING_TIMEOUT_S)

    try:
        logger.debug("Geocoding location: '%s'", location)
        response = await _client.get(GEOCODING_API_URL, params=params)
        response.raise_for_status()
        data = response.json()
    finally:
        if own_client:
            await _client.aclose()

    results = data.get("results")
    if not results:
        raise GeocodingError(location, "No geocoding results returned")

    top = results[0]
    lat = float(top["latitude"])
    lon = float(top["longitude"])

    logger.debug(
        "Geocoded '%s' → lat=%.4f, lon=%.4f (name=%s, country=%s)",
        location,
        lat,
        lon,
        top.get("name", "?"),
        top.get("country_code", "?"),
    )

    if not is_within_germany(lat, lon):
        raise GeocodingError(
            location,
            f"Resolved coordinates ({lat:.4f}°N, {lon:.4f}°E) are outside Germany "
            f"(bbox: {GERMANY_LAT_MIN}–{GERMANY_LAT_MAX}°N, "
            f"{GERMANY_LON_MIN}–{GERMANY_LON_MAX}°E)",
        )

    return lat, lon
