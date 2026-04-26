"""
Unit tests for the Weather Intelligence Service.

Tests fallback behavior, geocoding errors, and successful profile retrieval
using mocked HTTP responses (no real API calls).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.services.weather.geocoding import GeocodingError
from src.services.weather.service import WeatherIntelligenceService


# ---------------------------------------------------------------------------
# Helpers — build minimal valid API responses
# ---------------------------------------------------------------------------

def _geocoding_response(lat: float = 53.55, lon: float = 9.99) -> dict:
    return {
        "results": [
            {
                "name": "Hamburg",
                "latitude": lat,
                "longitude": lon,
                "country_code": "DE",
                "elevation": 6.0,
                "timezone": "Europe/Berlin",
            }
        ]
    }


def _archive_response(n_days: int = 1100) -> dict:
    """Build a minimal Open-Meteo Archive API response with n_days of data."""
    start = date(2019, 1, 1)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(n_days)]
    daily_vals = [5.0] * n_days
    hourly_times = []
    hourly_cloud = []
    for d in dates:
        for h in range(24):
            hourly_times.append(f"{d}T{h:02d}:00")
            hourly_cloud.append(50.0)
    return {
        "daily": {
            "time": dates,
            "sunshine_duration": [18000.0] * n_days,   # 5 hours in seconds
            "precipitation_sum": daily_vals,
            "temperature_2m_mean": daily_vals,
            "temperature_2m_min": [0.0] * n_days,
            "temperature_2m_max": [10.0] * n_days,
            "wind_speed_10m_max": [18.0] * n_days,     # 18 km/h = 5 m/s
            "shortwave_radiation_sum": [10.8] * n_days, # 10.8 MJ/m² = 3 kWh/m²
        },
        "hourly": {
            "time": hourly_times,
            "cloud_cover": hourly_cloud,
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_service_returns_none_on_http_500_from_geocoding() -> None:
    """
    When the geocoding API returns HTTP 500, the service returns None
    (falls back to static climate data) rather than raising.
    Requirements: 2.4
    """
    service = WeatherIntelligenceService()

    with patch.object(service._client, "get") as mock_get:
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
        mock_get.return_value = mock_response

        result = await service.get_weather_profile("Hamburg")

    assert result is None


@pytest.mark.asyncio
async def test_service_raises_geocoding_error_for_unknown_location() -> None:
    """
    When geocoding returns no results, GeocodingError is raised
    (so the caller can return a 422 to the user).
    Requirements: 1.3
    """
    service = WeatherIntelligenceService()

    with patch.object(service._client, "get") as mock_get:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"results": []}  # no results
        mock_get.return_value = mock_response

        with pytest.raises(GeocodingError) as exc_info:
            await service.get_weather_profile("XYZ_NONEXISTENT_PLACE_12345")

    assert "No geocoding results" in str(exc_info.value)


@pytest.mark.asyncio
async def test_service_returns_none_on_http_500_from_archive() -> None:
    """
    When the archive API returns HTTP 500, the service returns None
    (falls back to static climate data).
    Requirements: 2.4
    """
    service = WeatherIntelligenceService()
    call_count = 0

    def _side_effect(url: str, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        mock_response = MagicMock()
        if "geocoding" in url:
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = _geocoding_response()
        else:
            # Archive API fails
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "500 Server Error",
                request=MagicMock(),
                response=MagicMock(status_code=500),
            )
        return mock_response

    with patch.object(service._client, "get", side_effect=_side_effect):
        result = await service.get_weather_profile("Hamburg")

    assert result is None


@pytest.mark.asyncio
async def test_service_returns_weather_profile_for_valid_location() -> None:
    """
    When both geocoding and archive APIs succeed, the service returns a WeatherProfile.
    Requirements: 2.1, 2.3
    """
    service = WeatherIntelligenceService()

    def _side_effect(url: str, **kwargs: object) -> MagicMock:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        if "geocoding" in url:
            mock_response.json.return_value = _geocoding_response(lat=53.55, lon=9.99)
        else:
            mock_response.json.return_value = _archive_response(n_days=1100)
        return mock_response

    with patch.object(service._client, "get", side_effect=_side_effect):
        result = await service.get_weather_profile("Hamburg")

    assert result is not None
    assert result.latitude == pytest.approx(53.55)
    assert result.longitude == pytest.approx(9.99)
    assert result.data_source == "open-meteo-archive"
    assert len(result.monthly_sunshine_hours) == 12
    assert result.annual_irradiance_kwh_m2 > 0


@pytest.mark.asyncio
async def test_service_caches_result_and_avoids_second_api_call() -> None:
    """
    A second call with the same location should return the cached profile
    without making additional API calls.
    Requirements: 2.5
    """
    service = WeatherIntelligenceService()
    call_count = 0

    def _side_effect(url: str, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        if "geocoding" in url:
            mock_response.json.return_value = _geocoding_response(lat=53.55, lon=9.99)
        else:
            mock_response.json.return_value = _archive_response(n_days=1100)
        return mock_response

    with patch.object(service._client, "get", side_effect=_side_effect):
        result1 = await service.get_weather_profile("Hamburg")
        first_call_count = call_count
        result2 = await service.get_weather_profile("Hamburg")

    # Second call should only geocode (1 call), not fetch archive again
    assert result1 == result2
    assert call_count == first_call_count + 1  # only geocoding on second call


@pytest.mark.asyncio
async def test_service_raises_geocoding_error_for_location_outside_germany() -> None:
    """
    When geocoding resolves to coordinates outside Germany, GeocodingError is raised.
    Requirements: 1.5
    """
    service = WeatherIntelligenceService()

    with patch.object(service._client, "get") as mock_get:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        # Paris coordinates — outside Germany bbox
        mock_response.json.return_value = _geocoding_response(lat=48.85, lon=2.35)
        mock_get.return_value = mock_response

        with pytest.raises(GeocodingError) as exc_info:
            await service.get_weather_profile("Paris")

    assert "outside Germany" in str(exc_info.value)
