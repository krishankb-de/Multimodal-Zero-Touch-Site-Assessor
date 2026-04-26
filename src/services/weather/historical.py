"""
Open-Meteo Historical Weather API client.

Fetches daily historical weather data for a given location over 3–5 years.

Open-Meteo Archive API docs:
  https://open-meteo.com/en/docs/historical-weather-api
  GET https://archive-api.open-meteo.com/v1/archive
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import httpx

logger = logging.getLogger(__name__)

ARCHIVE_API_URL = "https://archive-api.open-meteo.com/v1/archive"
ARCHIVE_TIMEOUT_S = 30.0

# Daily variables to request from the API
DAILY_VARIABLES = [
    "sunshine_duration",        # seconds/day → converted to hours
    "precipitation_sum",        # mm/day
    "temperature_2m_mean",      # °C
    "temperature_2m_min",       # °C
    "temperature_2m_max",       # °C
    "wind_speed_10m_max",       # km/h → converted to m/s
    "shortwave_radiation_sum",  # MJ/m² → converted to kWh/m²
]

# Hourly variable for cloud cover (aggregated to daily mean client-side)
HOURLY_VARIABLES = ["cloud_cover"]

# Minimum years of data required for a valid profile
MIN_YEARS = 3


class WeatherFetchError(Exception):
    """Raised when historical weather data cannot be retrieved or is insufficient."""

    def __init__(self, lat: float, lon: float, reason: str) -> None:
        self.lat = lat
        self.lon = lon
        self.reason = reason
        super().__init__(f"Weather fetch failed for ({lat}, {lon}): {reason}")


@dataclass
class RawWeatherData:
    """
    Date-indexed daily weather arrays returned by the Open-Meteo Archive API.

    All arrays are parallel — index i corresponds to dates[i].
    Units are normalized on ingestion:
      - sunshine_duration_h: hours/day (converted from seconds)
      - precipitation_mm: mm/day
      - temperature_mean_c: °C
      - temperature_min_c: °C
      - temperature_max_c: °C
      - wind_speed_ms: m/s (converted from km/h)
      - shortwave_radiation_kwh_m2: kWh/m²/day (converted from MJ/m²)
      - cloud_cover_pct: % (0–100), daily mean from hourly data
    """

    dates: list[date] = field(default_factory=list)
    sunshine_duration_h: list[float] = field(default_factory=list)
    precipitation_mm: list[float] = field(default_factory=list)
    temperature_mean_c: list[float] = field(default_factory=list)
    temperature_min_c: list[float] = field(default_factory=list)
    temperature_max_c: list[float] = field(default_factory=list)
    wind_speed_ms: list[float] = field(default_factory=list)
    shortwave_radiation_kwh_m2: list[float] = field(default_factory=list)
    cloud_cover_pct: list[float] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.dates)


def _safe_float(value: object, default: float = 0.0) -> float:
    """Return float(value) or default if value is None/NaN."""
    if value is None:
        return default
    try:
        f = float(value)  # type: ignore[arg-type]
        return f if f == f else default  # NaN check
    except (TypeError, ValueError):
        return default


def _aggregate_hourly_cloud_cover(
    hourly_times: list[str],
    hourly_cloud: list[float | None],
    daily_dates: list[str],
) -> list[float]:
    """
    Aggregate hourly cloud cover values to daily means.

    Args:
        hourly_times: ISO datetime strings (e.g. "2023-01-01T00:00")
        hourly_cloud: Cloud cover percentage per hour (0–100), may contain None
        daily_dates:  Date strings (e.g. "2023-01-01") for each daily record

    Returns:
        List of daily mean cloud cover percentages, one per daily_dates entry.
    """
    # Build date → list of hourly values
    daily_map: dict[str, list[float]] = {d: [] for d in daily_dates}
    for t, v in zip(hourly_times, hourly_cloud):
        day_str = t[:10]  # "YYYY-MM-DD"
        if day_str in daily_map and v is not None:
            daily_map[day_str].append(float(v))

    result: list[float] = []
    for d in daily_dates:
        vals = daily_map[d]
        result.append(sum(vals) / len(vals) if vals else 0.0)
    return result


async def fetch_historical_weather(
    latitude: float,
    longitude: float,
    years: int = 5,
    client: httpx.AsyncClient | None = None,
) -> RawWeatherData:
    """
    Fetch daily historical weather data from the Open-Meteo Archive API.

    Retrieves the most recent `years` years of data (capped at 5, minimum 3).
    Validates that the response contains at least MIN_YEARS × 365 days.

    Args:
        latitude:  Decimal degrees North.
        longitude: Decimal degrees East.
        years:     Number of years to retrieve (3–5).
        client:    Optional shared httpx.AsyncClient.

    Returns:
        RawWeatherData with normalized daily arrays.

    Raises:
        WeatherFetchError: If the API returns insufficient data or an error.
        httpx.HTTPError:   Propagated on network/HTTP errors.
    """
    years = max(MIN_YEARS, min(5, years))
    end_date = date.today() - timedelta(days=5)  # API has ~5-day lag
    start_date = date(end_date.year - years, end_date.month, end_date.day)

    params: dict[str, object] = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": ",".join(DAILY_VARIABLES),
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": "Europe/Berlin",
        "format": "json",
    }

    own_client = client is None
    _client = client or httpx.AsyncClient(timeout=ARCHIVE_TIMEOUT_S)

    try:
        logger.debug(
            "Fetching historical weather for (%.4f, %.4f) from %s to %s",
            latitude, longitude, start_date, end_date,
        )
        response = await _client.get(ARCHIVE_API_URL, params=params)
        response.raise_for_status()
        data = response.json()
    finally:
        if own_client:
            await _client.aclose()

    daily = data.get("daily", {})
    daily_dates: list[str] = daily.get("time", [])

    if len(daily_dates) < MIN_YEARS * 365:
        raise WeatherFetchError(
            latitude, longitude,
            f"Insufficient data: got {len(daily_dates)} days, need at least {MIN_YEARS * 365}",
        )

    # Normalize units
    sunshine_raw = daily.get("sunshine_duration", [])
    wind_raw = daily.get("wind_speed_10m_max", [])
    radiation_raw = daily.get("shortwave_radiation_sum", [])

    sunshine_h = [_safe_float(v) / 3600.0 for v in sunshine_raw]   # seconds → hours
    wind_ms = [_safe_float(v) / 3.6 for v in wind_raw]              # km/h → m/s
    radiation_kwh = [_safe_float(v) / 3.6 for v in radiation_raw]   # MJ/m² → kWh/m²

    # Aggregate hourly cloud cover to daily means
    hourly = data.get("hourly", {})
    hourly_times: list[str] = hourly.get("time", [])
    hourly_cloud: list[float | None] = hourly.get("cloud_cover", [])
    cloud_daily = _aggregate_hourly_cloud_cover(hourly_times, hourly_cloud, daily_dates)

    raw = RawWeatherData(
        dates=[date.fromisoformat(d) for d in daily_dates],
        sunshine_duration_h=sunshine_h,
        precipitation_mm=[_safe_float(v) for v in daily.get("precipitation_sum", [])],
        temperature_mean_c=[_safe_float(v) for v in daily.get("temperature_2m_mean", [])],
        temperature_min_c=[_safe_float(v) for v in daily.get("temperature_2m_min", [])],
        temperature_max_c=[_safe_float(v) for v in daily.get("temperature_2m_max", [])],
        wind_speed_ms=wind_ms,
        shortwave_radiation_kwh_m2=radiation_kwh,
        cloud_cover_pct=cloud_daily,
    )

    logger.debug(
        "Fetched %d days of weather data for (%.4f, %.4f)",
        len(raw), latitude, longitude,
    )
    return raw
