"""
Weather data aggregation and analysis engine.

Converts raw daily weather arrays (RawWeatherData) into a structured WeatherProfile
with monthly aggregates, derived solar metrics, installation timing recommendations,
and a panel cleaning schedule.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timezone

from src.common.schemas import CleaningSchedule, SimpleMetadata, WeatherProfile
from src.services.weather.historical import RawWeatherData

logger = logging.getLogger(__name__)

# Threshold for a "sunny day" (hours of sunshine)
SUNNY_DAY_THRESHOLD_H = 6.0

# Quarter definitions: (start_month, end_month) inclusive, 1-indexed
QUARTERS: list[tuple[int, int]] = [(1, 3), (4, 6), (7, 9), (10, 12)]

# Cleaning schedule thresholds
# Annual precipitation < LOW_PRECIP_MM → more cleaning needed
LOW_PRECIP_MM = 500.0
HIGH_PRECIP_MM = 800.0
# Annual wind speed > HIGH_WIND_MS → more cleaning needed
HIGH_WIND_MS = 5.0
LOW_WIND_MS = 3.0


def _month_index(d: date) -> int:
    """Return 0-based month index (0=January, 11=December)."""
    return d.month - 1


def _quarter_index(month: int) -> int:
    """Return 0-based quarter index for a 1-based month number."""
    return (month - 1) // 3


def _monthly_mean(values: list[float], dates: list[date]) -> list[float]:
    """
    Compute the arithmetic mean of `values` grouped by calendar month.

    Returns a 12-element list (index 0 = January).
    Months with no data default to 0.0.
    """
    sums: list[float] = [0.0] * 12
    counts: list[int] = [0] * 12
    for v, d in zip(values, dates):
        idx = _month_index(d)
        sums[idx] += v
        counts[idx] += 1
    return [sums[i] / counts[i] if counts[i] > 0 else 0.0 for i in range(12)]


def _monthly_sum(values: list[float], dates: list[date]) -> list[float]:
    """
    Compute the sum of `values` grouped by calendar month, then average across years.

    Returns a 12-element list (index 0 = January).
    """
    # Sum per (year, month) then average across years
    year_month_sums: dict[tuple[int, int], float] = defaultdict(float)
    year_month_counts: dict[tuple[int, int], int] = defaultdict(int)
    for v, d in zip(values, dates):
        key = (d.year, d.month)
        year_month_sums[key] += v
        year_month_counts[key] += 1

    # Aggregate across years
    monthly_totals: list[list[float]] = [[] for _ in range(12)]
    for (_, month), total in year_month_sums.items():
        monthly_totals[month - 1].append(total)

    return [
        sum(vals) / len(vals) if vals else 0.0
        for vals in monthly_totals
    ]


def _quarterly_mean(monthly_values: list[float]) -> list[float]:
    """
    Compute quarterly averages from a 12-element monthly list.

    Returns a 4-element list [Q1, Q2, Q3, Q4].
    """
    result: list[float] = []
    for start_m, end_m in QUARTERS:
        months = monthly_values[start_m - 1: end_m]
        result.append(sum(months) / len(months) if months else 0.0)
    return result


def rank_installation_quarters(
    quarterly_precip: list[float],
    quarterly_wind: list[float],
    quarterly_sunshine: list[float],
) -> tuple[int, list[int]]:
    """
    Rank quarters 1–4 from most to least favorable for solar panel installation.

    Scoring: lower precipitation + lower wind + higher sunshine = better.
    Scores are normalized to [0, 1] per metric before combining.

    Args:
        quarterly_precip:   Average monthly precipitation per quarter (mm).
        quarterly_wind:     Average monthly wind speed per quarter (m/s).
        quarterly_sunshine: Average daily sunshine hours per quarter.

    Returns:
        (optimal_quarter, ranked_quarters) where optimal_quarter is 1-indexed
        and ranked_quarters is a list of 4 quarter numbers ordered best→worst.
    """
    def _normalize_invert(vals: list[float]) -> list[float]:
        """Normalize and invert so lower original → higher score."""
        mn, mx = min(vals), max(vals)
        if mx == mn:
            return [0.5] * len(vals)
        return [(mx - v) / (mx - mn) for v in vals]

    def _normalize(vals: list[float]) -> list[float]:
        """Normalize so higher original → higher score."""
        mn, mx = min(vals), max(vals)
        if mx == mn:
            return [0.5] * len(vals)
        return [(v - mn) / (mx - mn) for v in vals]

    precip_score = _normalize_invert(quarterly_precip)
    wind_score = _normalize_invert(quarterly_wind)
    sun_score = _normalize(quarterly_sunshine)

    combined = [
        precip_score[i] + wind_score[i] + sun_score[i]
        for i in range(4)
    ]

    # Sort quarters (1-indexed) by combined score descending
    ranked = sorted(range(1, 5), key=lambda q: combined[q - 1], reverse=True)
    optimal = ranked[0]

    logger.debug(
        "Quarter ranking: scores=%s → ranked=%s, optimal=Q%d",
        [f"{s:.3f}" for s in combined], ranked, optimal,
    )
    return optimal, ranked


def compute_cleaning_schedule(
    monthly_precip: list[float],
    monthly_wind: list[float],
) -> CleaningSchedule:
    """
    Compute a recommended panel cleaning schedule from monthly weather data.

    Frequency logic:
      - Base frequency: 2 times/year
      - Low annual precipitation (< 500 mm) adds +1 cleaning
      - Very low precipitation (< 300 mm) adds another +1
      - High annual wind speed (> 5 m/s) adds +1 cleaning
      - Very high wind speed (> 7 m/s) adds another +1

    Recommended months: the 2–4 months with the lowest precipitation
    (panels are dirtiest when it hasn't rained recently).

    Args:
        monthly_precip: 12-element list of average monthly precipitation (mm).
        monthly_wind:   12-element list of average monthly wind speed (m/s).

    Returns:
        CleaningSchedule with frequency_per_year and recommended_months.
    """
    annual_precip = sum(monthly_precip)
    annual_wind = sum(monthly_wind) / len(monthly_wind) if monthly_wind else 0.0

    frequency = 2
    if annual_precip < LOW_PRECIP_MM:
        frequency += 1
    if annual_precip < 300.0:
        frequency += 1
    if annual_wind > HIGH_WIND_MS:
        frequency += 1
    if annual_wind > 7.0:
        frequency += 1

    frequency = max(1, min(12, frequency))

    # Recommend the `frequency` months with lowest precipitation (1-indexed)
    month_precip_pairs = sorted(
        enumerate(monthly_precip, start=1), key=lambda x: x[1]
    )
    n_months = min(frequency, 12)
    recommended = sorted(m for m, _ in month_precip_pairs[:n_months])

    logger.debug(
        "Cleaning schedule: annual_precip=%.0f mm, annual_wind=%.1f m/s → "
        "frequency=%d/year, months=%s",
        annual_precip, annual_wind, frequency, recommended,
    )
    return CleaningSchedule(
        frequency_per_year=frequency,
        recommended_months=recommended,
    )


def analyze_weather(
    raw: RawWeatherData,
    latitude: float,
    longitude: float,
) -> WeatherProfile:
    """
    Aggregate raw daily weather data into a structured WeatherProfile.

    Steps:
    1. Compute 12-element monthly averages for all weather variables.
    2. Compute annual irradiance from shortwave radiation sum.
    3. Count sunny days (sunshine > 6 h/day).
    4. Compute seasonal (quarterly) sunshine distribution.
    5. Rank installation quarters.
    6. Compute cleaning schedule.

    Args:
        raw:       Normalized daily weather arrays from the Archive API.
        latitude:  Decimal degrees North (used for metadata).
        longitude: Decimal degrees East (used for metadata).

    Returns:
        WeatherProfile ready for Safety Gate 1 validation.
    """
    dates = raw.dates
    if not dates:
        raise ValueError("RawWeatherData contains no dates")

    # 1. Monthly aggregates
    monthly_sunshine = _monthly_mean(raw.sunshine_duration_h, dates)
    monthly_precip = _monthly_sum(raw.precipitation_mm, dates)
    monthly_cloud = _monthly_mean(raw.cloud_cover_pct, dates)
    monthly_wind = _monthly_mean(raw.wind_speed_ms, dates)
    monthly_temp = _monthly_mean(raw.temperature_mean_c, dates)

    # 2. Annual irradiance: sum of daily shortwave radiation / number of years
    n_years = max(1, (dates[-1] - dates[0]).days / 365.25)
    annual_irradiance = sum(raw.shortwave_radiation_kwh_m2) / n_years

    # 3. Sunny days per year
    sunny_days_total = sum(1 for h in raw.sunshine_duration_h if h > SUNNY_DAY_THRESHOLD_H)
    sunny_days_per_year = round(sunny_days_total / n_years)

    # 4. Seasonal sunshine distribution (quarterly averages of monthly means)
    seasonal_sunshine = _quarterly_mean(monthly_sunshine)

    # 5. Installation quarter ranking
    quarterly_precip = _quarterly_mean(monthly_precip)
    quarterly_wind = _quarterly_mean(monthly_wind)
    optimal_quarter, quarter_rankings = rank_installation_quarters(
        quarterly_precip, quarterly_wind, seasonal_sunshine
    )

    # 6. Cleaning schedule
    cleaning_schedule = compute_cleaning_schedule(monthly_precip, monthly_wind)

    profile = WeatherProfile(
        latitude=latitude,
        longitude=longitude,
        data_source="open-meteo-archive",
        date_range_start=dates[0],
        date_range_end=dates[-1],
        monthly_sunshine_hours=monthly_sunshine,
        monthly_precipitation_mm=monthly_precip,
        monthly_cloud_cover_pct=monthly_cloud,
        monthly_wind_speed_ms=monthly_wind,
        monthly_avg_temperature_c=monthly_temp,
        annual_irradiance_kwh_m2=round(annual_irradiance, 1),
        sunny_days_per_year=min(366, max(0, sunny_days_per_year)),
        seasonal_sunshine_hours=seasonal_sunshine,
        optimal_installation_quarter=optimal_quarter,
        quarter_rankings=quarter_rankings,
        cleaning_schedule=cleaning_schedule,
        metadata=SimpleMetadata(timestamp=datetime.now(timezone.utc)),
    )

    logger.info(
        "Weather analysis complete: irradiance=%.0f kWh/m²/yr, sunny_days=%d/yr, "
        "optimal_install=Q%d, cleaning=%d×/yr",
        profile.annual_irradiance_kwh_m2,
        profile.sunny_days_per_year,
        profile.optimal_installation_quarter,
        profile.cleaning_schedule.frequency_per_year,
    )
    return profile
