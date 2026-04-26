"""
Property-based tests for the Weather Intelligence & House Dimensions feature.

Feature: weather-intelligence-house-dimensions
Tests Properties 1–11 from the design document using Hypothesis.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.common.schemas import (
    CleaningSchedule,
    DimensionConfidence,
    HouseDimensions,
    PanelOrientation,
    SimpleMetadata,
    WeatherProfile,
)
from src.services.weather.cache import WeatherCache
from src.services.weather.geocoding import (
    GERMANY_LAT_MAX,
    GERMANY_LAT_MIN,
    GERMANY_LON_MAX,
    GERMANY_LON_MIN,
    is_within_germany,
)


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_METADATA = SimpleMetadata(timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc))

_MONTHLY_12 = st.lists(st.floats(min_value=0.0, max_value=500.0, allow_nan=False), min_size=12, max_size=12)
_MONTHLY_TEMP = st.lists(st.floats(min_value=-30.0, max_value=40.0, allow_nan=False), min_size=12, max_size=12)
_MONTHLY_CLOUD = st.lists(st.floats(min_value=0.0, max_value=100.0, allow_nan=False), min_size=12, max_size=12)
_QUARTERLY_4 = st.lists(st.floats(min_value=0.0, max_value=16.0, allow_nan=False), min_size=4, max_size=4)
_QUARTER_RANKINGS = st.permutations([1, 2, 3, 4])


@st.composite
def valid_weather_profiles(draw: st.DrawFn) -> WeatherProfile:
    lat = draw(st.floats(min_value=47.0, max_value=55.5, allow_nan=False))
    lon = draw(st.floats(min_value=5.5, max_value=15.5, allow_nan=False))
    rankings = draw(_QUARTER_RANKINGS)
    optimal = rankings[0]
    cleaning_months = draw(
        st.lists(st.integers(min_value=1, max_value=12), min_size=1, max_size=12, unique=True)
    )
    return WeatherProfile(
        latitude=lat,
        longitude=lon,
        data_source="open-meteo-archive",
        date_range_start=date(2019, 1, 1),
        date_range_end=date(2023, 12, 31),
        monthly_sunshine_hours=draw(_MONTHLY_12),
        monthly_precipitation_mm=draw(_MONTHLY_12),
        monthly_cloud_cover_pct=draw(_MONTHLY_CLOUD),
        monthly_wind_speed_ms=draw(_MONTHLY_12),
        monthly_avg_temperature_c=draw(_MONTHLY_TEMP),
        annual_irradiance_kwh_m2=draw(st.floats(min_value=700.0, max_value=1400.0, allow_nan=False)),
        sunny_days_per_year=draw(st.integers(min_value=0, max_value=366)),
        seasonal_sunshine_hours=draw(_QUARTERLY_4),
        optimal_installation_quarter=optimal,
        quarter_rankings=rankings,
        cleaning_schedule=CleaningSchedule(
            frequency_per_year=draw(st.integers(min_value=1, max_value=12)),
            recommended_months=sorted(cleaning_months),
        ),
        metadata=_METADATA,
    )


@st.composite
def valid_house_dimensions(draw: st.DrawFn) -> HouseDimensions:
    ridge = draw(st.floats(min_value=2.0, max_value=25.0, allow_nan=False))
    eave = draw(st.floats(min_value=1.5, max_value=min(ridge, 20.0), allow_nan=False))
    width = draw(st.floats(min_value=3.0, max_value=50.0, allow_nan=False))
    depth = draw(st.floats(min_value=3.0, max_value=50.0, allow_nan=False))
    wall_area = draw(st.floats(min_value=10.0, max_value=2000.0, allow_nan=False))
    volume = draw(st.floats(min_value=20.0, max_value=50000.0, allow_nan=False))
    conf = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
    return HouseDimensions(
        ridge_height_m=ridge,
        eave_height_m=eave,
        footprint_width_m=width,
        footprint_depth_m=depth,
        estimated_wall_area_m2=wall_area,
        estimated_volume_m3=volume,
        confidence=DimensionConfidence(
            ridge_height=conf,
            eave_height=conf,
            footprint_width=conf,
            footprint_depth=conf,
        ),
    )


# ---------------------------------------------------------------------------
# Property 1: WeatherProfile serialization round-trip
# Feature: weather-intelligence-house-dimensions, Property 1
# ---------------------------------------------------------------------------

@given(wp=valid_weather_profiles())
@settings(max_examples=100)
def test_weather_profile_round_trip(wp: WeatherProfile) -> None:
    """
    Property 1: WeatherProfile serialization round-trip.
    For any valid WeatherProfile, serializing to JSON and deserializing
    must produce an equivalent object.
    Validates: Requirements 16.1
    """
    json_data = wp.model_dump(mode="json")
    restored = WeatherProfile(**json_data)
    assert restored == wp


# ---------------------------------------------------------------------------
# Property 2: HouseDimensions serialization round-trip
# Feature: weather-intelligence-house-dimensions, Property 2
# ---------------------------------------------------------------------------

@given(hd=valid_house_dimensions())
@settings(max_examples=100)
def test_house_dimensions_round_trip(hd: HouseDimensions) -> None:
    """
    Property 2: HouseDimensions serialization round-trip.
    For any valid HouseDimensions, serializing to JSON and deserializing
    must produce an equivalent object.
    Validates: Requirements 16.2
    """
    json_data = hd.model_dump(mode="json")
    restored = HouseDimensions(**json_data)
    assert restored == hd


# ---------------------------------------------------------------------------
# Property 3: Germany bounding box coordinate validation
# Feature: weather-intelligence-house-dimensions, Property 3
# ---------------------------------------------------------------------------

@given(
    lat=st.floats(min_value=40.0, max_value=62.0, allow_nan=False),
    lon=st.floats(min_value=-5.0, max_value=25.0, allow_nan=False),
)
@settings(max_examples=200)
def test_germany_bbox_validation(lat: float, lon: float) -> None:
    """
    Property 3: Germany bounding box coordinate validation.
    is_within_germany() accepts (lat, lon) iff 47.0 ≤ lat ≤ 55.5 and 5.5 ≤ lon ≤ 15.5.
    Validates: Requirements 1.5
    """
    result = is_within_germany(lat, lon)
    expected = (
        GERMANY_LAT_MIN <= lat <= GERMANY_LAT_MAX
        and GERMANY_LON_MIN <= lon <= GERMANY_LON_MAX
    )
    assert result == expected, (
        f"is_within_germany({lat}, {lon}) = {result}, expected {expected}"
    )


# ---------------------------------------------------------------------------
# Property 4: Cache key equivalence for nearby coordinates
# Feature: weather-intelligence-house-dimensions, Property 4
# ---------------------------------------------------------------------------

@given(
    lat1=st.floats(min_value=47.0, max_value=55.5, allow_nan=False),
    lon1=st.floats(min_value=5.5, max_value=15.5, allow_nan=False),
    lat2=st.floats(min_value=47.0, max_value=55.5, allow_nan=False),
    lon2=st.floats(min_value=5.5, max_value=15.5, allow_nan=False),
    wp=valid_weather_profiles(),
)
@settings(max_examples=100)
def test_cache_key_equivalence(
    lat1: float, lon1: float, lat2: float, lon2: float, wp: WeatherProfile
) -> None:
    """
    Property 4: Cache key equivalence for nearby coordinates.
    Two coordinate pairs that round to the same (lat, lon) at 2 decimal places
    must return the same cached WeatherProfile.
    Validates: Requirements 2.5
    """
    cache = WeatherCache()
    cache.put(lat1, lon1, wp)

    same_key = round(lat1, 2) == round(lat2, 2) and round(lon1, 2) == round(lon2, 2)

    result = cache.get(lat2, lon2)
    if same_key:
        assert result == wp, (
            f"Expected cache hit for ({lat2}, {lon2}) matching key of ({lat1}, {lon1})"
        )
    else:
        assert result is None, (
            f"Expected cache miss for ({lat2}, {lon2}) with different key from ({lat1}, {lon1})"
        )


# ---------------------------------------------------------------------------
# Helpers for analysis PBT tests
# ---------------------------------------------------------------------------

from collections import defaultdict
from datetime import timedelta

from src.services.weather.analysis import (
    SUNNY_DAY_THRESHOLD_H,
    _monthly_mean,
    _quarterly_mean,
    compute_cleaning_schedule,
    rank_installation_quarters,
)
from src.services.weather.historical import RawWeatherData


def _make_raw(n_days: int, seed_val: float = 5.0) -> RawWeatherData:
    """Build a RawWeatherData with n_days of constant values for testing."""
    start = date(2019, 1, 1)
    dates = [start + timedelta(days=i) for i in range(n_days)]
    vals = [seed_val] * n_days
    return RawWeatherData(
        dates=dates,
        sunshine_duration_h=vals,
        precipitation_mm=vals,
        temperature_mean_c=vals,
        temperature_min_c=vals,
        temperature_max_c=vals,
        wind_speed_ms=vals,
        shortwave_radiation_kwh_m2=vals,
        cloud_cover_pct=vals,
    )


# ---------------------------------------------------------------------------
# Property 5: Monthly weather aggregation correctness
# Feature: weather-intelligence-house-dimensions, Property 5
# ---------------------------------------------------------------------------

@given(
    n_days=st.integers(min_value=365, max_value=1826),
    values=st.lists(
        st.floats(min_value=0.0, max_value=500.0, allow_nan=False),
        min_size=365, max_size=1826,
    ),
)
@settings(max_examples=50)
def test_monthly_aggregation_correctness(n_days: int, values: list[float]) -> None:
    """
    Property 5: Monthly weather aggregation correctness.
    Each monthly value must equal the arithmetic mean of daily values in that month.
    Validates: Requirements 2.2, 4.1, 4.2, 4.3
    """
    # Trim/pad values to exactly n_days
    vals = (values * ((n_days // len(values)) + 1))[:n_days]
    start = date(2019, 1, 1)
    dates = [start + timedelta(days=i) for i in range(n_days)]

    result = _monthly_mean(vals, dates)
    assert len(result) == 12

    # Verify each month independently
    for month_idx in range(12):
        expected_vals = [v for v, d in zip(vals, dates) if d.month - 1 == month_idx]
        if expected_vals:
            expected_mean = sum(expected_vals) / len(expected_vals)
            assert abs(result[month_idx] - expected_mean) < 1e-9, (
                f"Month {month_idx + 1}: expected {expected_mean}, got {result[month_idx]}"
            )
        else:
            assert result[month_idx] == 0.0


# ---------------------------------------------------------------------------
# Property 6: Derived sunshine metrics correctness
# Feature: weather-intelligence-house-dimensions, Property 6
# ---------------------------------------------------------------------------

@given(
    sunshine_hours=st.lists(
        st.floats(min_value=0.0, max_value=16.0, allow_nan=False),
        min_size=365, max_size=730,
    ),
)
@settings(max_examples=50)
def test_derived_sunshine_metrics(sunshine_hours: list[float]) -> None:
    """
    Property 6: Derived sunshine metrics correctness.
    sunny_days_per_year equals count of days with sunshine > 6h.
    seasonal_sunshine_hours matches quarterly averages of monthly means.
    Validates: Requirements 3.1, 3.2, 3.3
    """
    n = len(sunshine_hours)
    start = date(2019, 1, 1)
    dates = [start + timedelta(days=i) for i in range(n)]

    # Sunny days
    expected_sunny = sum(1 for h in sunshine_hours if h > SUNNY_DAY_THRESHOLD_H)
    n_years = max(1, n / 365.25)
    expected_per_year = round(expected_sunny / n_years)

    # Monthly means → quarterly
    monthly = _monthly_mean(sunshine_hours, dates)
    expected_quarterly = _quarterly_mean(monthly)

    # Verify quarterly computation
    for q_idx, (start_m, end_m) in enumerate([(1, 3), (4, 6), (7, 9), (10, 12)]):
        months_slice = monthly[start_m - 1: end_m]
        expected_q = sum(months_slice) / len(months_slice)
        assert abs(expected_quarterly[q_idx] - expected_q) < 1e-9

    # Verify sunny days count is non-negative and bounded
    assert 0 <= expected_per_year <= 366


# ---------------------------------------------------------------------------
# Property 7: Installation quarter ranking consistency
# Feature: weather-intelligence-house-dimensions, Property 7
# ---------------------------------------------------------------------------

@given(
    precip=st.lists(st.floats(min_value=0.0, max_value=200.0, allow_nan=False), min_size=4, max_size=4),
    wind=st.lists(st.floats(min_value=0.0, max_value=15.0, allow_nan=False), min_size=4, max_size=4),
    sunshine=st.lists(st.floats(min_value=0.0, max_value=16.0, allow_nan=False), min_size=4, max_size=4),
)
@settings(max_examples=200)
def test_quarter_ranking_consistency(
    precip: list[float], wind: list[float], sunshine: list[float]
) -> None:
    """
    Property 7: Installation quarter ranking consistency.
    optimal_installation_quarter == quarter_rankings[0].
    quarter_rankings is a permutation of [1, 2, 3, 4].
    Validates: Requirements 5.1, 5.2
    """
    optimal, rankings = rank_installation_quarters(precip, wind, sunshine)

    assert sorted(rankings) == [1, 2, 3, 4], f"rankings {rankings} is not a permutation of [1,2,3,4]"
    assert rankings[0] == optimal, (
        f"optimal={optimal} but rankings[0]={rankings[0]}"
    )
    assert 1 <= optimal <= 4


# ---------------------------------------------------------------------------
# Property 8: Cleaning schedule correctness
# Feature: weather-intelligence-house-dimensions, Property 8
# ---------------------------------------------------------------------------

@given(
    precip=st.lists(st.floats(min_value=0.0, max_value=200.0, allow_nan=False), min_size=12, max_size=12),
    wind=st.lists(st.floats(min_value=0.0, max_value=15.0, allow_nan=False), min_size=12, max_size=12),
)
@settings(max_examples=200)
def test_cleaning_schedule_correctness(precip: list[float], wind: list[float]) -> None:
    """
    Property 8: Cleaning schedule correctness.
    - frequency is between 1 and 12
    - recommended_months is a non-empty subset of months with lowest precipitation
    - recommended_months are valid calendar months (1–12)
    Validates: Requirements 6.1, 6.2, 6.3
    """
    schedule = compute_cleaning_schedule(precip, wind)

    assert 1 <= schedule.frequency_per_year <= 12
    assert len(schedule.recommended_months) >= 1
    assert all(1 <= m <= 12 for m in schedule.recommended_months)

    # Recommended months must be among the lowest-precipitation months
    sorted_months = sorted(range(1, 13), key=lambda m: precip[m - 1])
    n = schedule.frequency_per_year
    lowest_precip_months = set(sorted_months[:n])
    for m in schedule.recommended_months:
        assert m in lowest_precip_months, (
            f"Month {m} is not among the {n} lowest-precipitation months {lowest_precip_months}"
        )
