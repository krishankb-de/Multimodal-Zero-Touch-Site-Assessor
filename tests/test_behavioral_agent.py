"""
Unit tests for the Behavioral Agent.

Tests cover:
- Occupancy pattern detection from seasonal consumption ratios
- Battery sizing formula: daily_avg × self_consumption_factor × occupancy_multiplier, clamped
- TOU arbitrage savings calculation with known tariff differentials
- Charge/discharge window non-overlap invariant
- Optimization schedule frequency and next_review date
- Annual savings estimation
- Round-trip serialization: BehavioralProfile → JSON → BehavioralProfile
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.agents.behavioral.agent import (
    BATTERY_MAX_KWH,
    BATTERY_MIN_KWH,
    OCCUPANCY_MULTIPLIERS,
    REVIEW_PERIOD_DAYS,
    SELF_CONSUMPTION_FACTORS,
    _detect_occupancy,
    run,
)
from src.agents.behavioral.arbitrage import (
    calculate_arbitrage_savings,
    determine_charge_discharge_windows,
)
from src.common.schemas import (
    BehavioralProfile,
    ConsumptionData,
    Currency,
    IngestionMetadata,
    MonthlyConsumption,
    OccupancyPattern,
    OptimizationFrequency,
    SourceType,
    Tariff,
    TimeOfUse,
)


# ============================================================================
# Fixtures — ConsumptionData builders
# ============================================================================


def _metadata() -> IngestionMetadata:
    return IngestionMetadata(
        source_type=SourceType.PDF,
        confidence_score=0.95,
        timestamp=datetime.now(timezone.utc),
    )


def _make_consumption(
    monthly_kwh: dict[int, float],
    rate_per_kwh: float = 0.30,
    feed_in_tariff: float | None = 0.08,
    tou: TimeOfUse | None = None,
) -> ConsumptionData:
    """Build a ConsumptionData from a month→kWh mapping."""
    monthly_breakdown = [
        MonthlyConsumption(month=m, kwh=monthly_kwh[m]) for m in range(1, 13)
    ]
    annual_kwh = sum(monthly_kwh.values())
    tariff = Tariff(
        currency=Currency.EUR,
        rate_per_kwh=rate_per_kwh,
        feed_in_tariff_per_kwh=feed_in_tariff,
        time_of_use=tou,
    )
    return ConsumptionData(
        annual_kwh=annual_kwh,
        monthly_breakdown=monthly_breakdown,
        tariff=tariff,
        metadata=_metadata(),
    )


def _home_all_day_monthly() -> dict[int, float]:
    """
    Winter months (Nov=11, Dec=12, Jan=1, Feb=2) avg >> summer months (May-Aug) avg.
    Ratio = winter_avg / summer_avg > 1.5 → HOME_ALL_DAY.
    """
    return {
        1: 600,   # Jan  (winter)
        2: 580,   # Feb  (winter)
        3: 400,
        4: 350,
        5: 300,   # May  (summer)
        6: 280,   # Jun  (summer)
        7: 270,   # Jul  (summer)
        8: 290,   # Aug  (summer)
        9: 350,
        10: 420,
        11: 560,  # Nov  (winter)
        12: 590,  # Dec  (winter)
    }


def _away_daytime_monthly() -> dict[int, float]:
    """
    Winter/summer ratio < 1.2 → AWAY_DAYTIME.
    Winter avg ≈ 360, summer avg ≈ 340 → ratio ≈ 1.06.
    """
    return {
        1: 370,
        2: 360,
        3: 350,
        4: 345,
        5: 340,
        6: 335,
        7: 330,
        8: 345,
        9: 350,
        10: 355,
        11: 355,
        12: 365,
    }


def _mixed_monthly() -> dict[int, float]:
    """
    Winter/summer ratio between 1.2 and 1.5 → MIXED.
    Winter avg ≈ 480, summer avg ≈ 360 → ratio ≈ 1.33.
    """
    return {
        1: 490,
        2: 480,
        3: 420,
        4: 380,
        5: 360,
        6: 350,
        7: 355,
        8: 375,
        9: 390,
        10: 430,
        11: 470,
        12: 485,
    }


# ============================================================================
# Tests: Occupancy detection
# ============================================================================


class TestOccupancyDetection:
    """Occupancy pattern is derived from the winter/summer consumption ratio."""

    def test_home_all_day_ratio_above_1_5(self):
        """Winter/summer ratio > 1.5 → HOME_ALL_DAY."""
        data = _make_consumption(_home_all_day_monthly())
        pattern = _detect_occupancy(data)
        assert pattern == OccupancyPattern.HOME_ALL_DAY

    def test_away_daytime_ratio_below_1_2(self):
        """Winter/summer ratio < 1.2 → AWAY_DAYTIME."""
        data = _make_consumption(_away_daytime_monthly())
        pattern = _detect_occupancy(data)
        assert pattern == OccupancyPattern.AWAY_DAYTIME

    def test_mixed_ratio_between_1_2_and_1_5(self):
        """Winter/summer ratio in [1.2, 1.5] → MIXED."""
        data = _make_consumption(_mixed_monthly())
        pattern = _detect_occupancy(data)
        assert pattern == OccupancyPattern.MIXED

    def test_home_all_day_boundary_exactly_above_1_5(self):
        """Ratio just above 1.5 is still HOME_ALL_DAY."""
        # winter_avg = 151, summer_avg = 100 → ratio = 1.51
        monthly = {m: 100 for m in range(1, 13)}
        monthly[1] = 151
        monthly[2] = 151
        monthly[11] = 151
        monthly[12] = 151
        data = _make_consumption(monthly)
        pattern = _detect_occupancy(data)
        assert pattern == OccupancyPattern.HOME_ALL_DAY

    def test_away_daytime_boundary_exactly_below_1_2(self):
        """Ratio just below 1.2 is AWAY_DAYTIME."""
        # winter_avg = 119, summer_avg = 100 → ratio = 1.19
        monthly = {m: 100 for m in range(1, 13)}
        monthly[1] = 119
        monthly[2] = 119
        monthly[11] = 119
        monthly[12] = 119
        data = _make_consumption(monthly)
        pattern = _detect_occupancy(data)
        assert pattern == OccupancyPattern.AWAY_DAYTIME

    def test_run_returns_correct_occupancy_pattern(self):
        """Full agent run returns the expected occupancy pattern."""
        data = _make_consumption(_home_all_day_monthly())
        profile = run(data)
        assert profile.occupancy_pattern == OccupancyPattern.HOME_ALL_DAY


# ============================================================================
# Tests: Battery sizing
# ============================================================================


class TestBatterySizing:
    """Battery capacity = daily_avg × self_consumption_factor × occupancy_multiplier, clamped."""

    def test_battery_sizing_home_all_day(self):
        """Verify formula for HOME_ALL_DAY occupancy."""
        data = _make_consumption(_home_all_day_monthly())
        profile = run(data)

        annual_kwh = sum(_home_all_day_monthly().values())
        daily_avg = annual_kwh / 365
        factor = SELF_CONSUMPTION_FACTORS[OccupancyPattern.HOME_ALL_DAY]
        multiplier = OCCUPANCY_MULTIPLIERS[OccupancyPattern.HOME_ALL_DAY]
        expected_raw = daily_avg * factor * multiplier
        expected = max(BATTERY_MIN_KWH, min(BATTERY_MAX_KWH, expected_raw))

        assert profile.battery_recommendation.capacity_kwh == pytest.approx(expected, rel=1e-3)

    def test_battery_sizing_away_daytime(self):
        """Verify formula for AWAY_DAYTIME occupancy."""
        data = _make_consumption(_away_daytime_monthly())
        profile = run(data)

        annual_kwh = sum(_away_daytime_monthly().values())
        daily_avg = annual_kwh / 365
        factor = SELF_CONSUMPTION_FACTORS[OccupancyPattern.AWAY_DAYTIME]
        multiplier = OCCUPANCY_MULTIPLIERS[OccupancyPattern.AWAY_DAYTIME]
        expected_raw = daily_avg * factor * multiplier
        expected = max(BATTERY_MIN_KWH, min(BATTERY_MAX_KWH, expected_raw))

        assert profile.battery_recommendation.capacity_kwh == pytest.approx(expected, rel=1e-3)

    def test_battery_sizing_mixed(self):
        """Verify formula for MIXED occupancy."""
        data = _make_consumption(_mixed_monthly())
        profile = run(data)

        annual_kwh = sum(_mixed_monthly().values())
        daily_avg = annual_kwh / 365
        factor = SELF_CONSUMPTION_FACTORS[OccupancyPattern.MIXED]
        multiplier = OCCUPANCY_MULTIPLIERS[OccupancyPattern.MIXED]
        expected_raw = daily_avg * factor * multiplier
        expected = max(BATTERY_MIN_KWH, min(BATTERY_MAX_KWH, expected_raw))

        assert profile.battery_recommendation.capacity_kwh == pytest.approx(expected, rel=1e-3)

    def test_battery_clamped_to_minimum(self):
        """Very low consumption → raw capacity below 0.5 kWh → clamped to BATTERY_MIN_KWH."""
        # annual_kwh = 500 (minimum allowed), daily_avg ≈ 1.37 kWh
        # raw = 1.37 × 0.3 × 0.8 ≈ 0.33 kWh → clamped to 0.5
        monthly = {m: round(500 / 12, 1) for m in range(1, 13)}
        # Adjust to hit exactly 500 kWh
        total = sum(monthly.values())
        monthly[12] = round(monthly[12] + (500 - total), 1)
        data = _make_consumption(monthly)
        profile = run(data)
        assert profile.battery_recommendation.capacity_kwh >= BATTERY_MIN_KWH

    def test_battery_clamped_to_maximum(self):
        """Very high consumption → raw capacity above 50 kWh → clamped to BATTERY_MAX_KWH."""
        # annual_kwh = 100000 (maximum allowed), daily_avg ≈ 273.97 kWh
        # raw = 273.97 × 0.5 × 1.0 ≈ 137 kWh → clamped to 50
        monthly = {m: round(100000 / 12, 1) for m in range(1, 13)}
        total = sum(monthly.values())
        monthly[12] = round(monthly[12] + (100000 - total), 1)
        data = _make_consumption(monthly)
        profile = run(data)
        assert profile.battery_recommendation.capacity_kwh <= BATTERY_MAX_KWH

    def test_battery_capacity_within_schema_bounds(self):
        """Battery capacity must always satisfy schema constraints [0.5, 50]."""
        for monthly_fn in [_home_all_day_monthly, _away_daytime_monthly, _mixed_monthly]:
            data = _make_consumption(monthly_fn())
            profile = run(data)
            assert 0.5 <= profile.battery_recommendation.capacity_kwh <= 50.0


# ============================================================================
# Tests: TOU arbitrage savings
# ============================================================================


class TestTOUArbitrageSavings:
    """Arbitrage savings = shiftable_kwh × (peak_rate - off_peak_rate) × 365."""

    def test_arbitrage_savings_known_values(self):
        """Verify savings formula with explicit known inputs."""
        # shiftable_kwh = daily_avg × 0.3
        # annual_kwh = 3650 → daily_avg = 10 kWh → shiftable = 3 kWh/day
        # peak_rate = 0.40, off_peak_rate = 0.15 → differential = 0.25
        # expected = 3 × 0.25 × 365 = 273.75 EUR/year
        savings = calculate_arbitrage_savings(
            shiftable_kwh=3.0,
            peak_rate=0.40,
            off_peak_rate=0.15,
        )
        assert savings == pytest.approx(273.75, rel=1e-6)

    def test_arbitrage_savings_zero_when_no_differential(self):
        """No savings when peak_rate == off_peak_rate."""
        savings = calculate_arbitrage_savings(
            shiftable_kwh=5.0,
            peak_rate=0.30,
            off_peak_rate=0.30,
        )
        assert savings == 0.0

    def test_arbitrage_savings_zero_when_off_peak_higher(self):
        """No savings (returns 0.0) when off_peak_rate > peak_rate."""
        savings = calculate_arbitrage_savings(
            shiftable_kwh=5.0,
            peak_rate=0.20,
            off_peak_rate=0.35,
        )
        assert savings == 0.0

    def test_arbitrage_savings_in_profile_with_tou_tariff(self):
        """Agent sets arbitrage_savings_eur_annual when TOU tariff is present."""
        tou = TimeOfUse(
            peak_rate=0.40,
            off_peak_rate=0.15,
            peak_hours_start=17,
            peak_hours_end=21,
        )
        data = _make_consumption(_away_daytime_monthly(), tou=tou)
        profile = run(data)
        assert profile.battery_recommendation.arbitrage_savings_eur_annual is not None
        assert profile.battery_recommendation.arbitrage_savings_eur_annual > 0

    def test_no_arbitrage_savings_without_tou_tariff(self):
        """Agent leaves arbitrage_savings_eur_annual as None when no TOU tariff."""
        data = _make_consumption(_away_daytime_monthly(), tou=None)
        profile = run(data)
        assert profile.battery_recommendation.arbitrage_savings_eur_annual is None

    def test_arbitrage_savings_matches_formula(self):
        """Verify the agent's arbitrage savings match the formula exactly."""
        tou = TimeOfUse(
            peak_rate=0.40,
            off_peak_rate=0.15,
            peak_hours_start=17,
            peak_hours_end=21,
        )
        monthly = _away_daytime_monthly()
        annual_kwh = sum(monthly.values())
        data = _make_consumption(monthly, tou=tou)
        profile = run(data)

        daily_avg = annual_kwh / 365
        shiftable_kwh = daily_avg * 0.3  # SHIFTABLE_FRACTION = 0.3
        expected_savings = shiftable_kwh * (0.40 - 0.15) * 365

        assert profile.battery_recommendation.arbitrage_savings_eur_annual == pytest.approx(
            expected_savings, rel=1e-3
        )


# ============================================================================
# Tests: Charge/discharge window non-overlap invariant
# ============================================================================


class TestChargeDischargeWindows:
    """Charge and discharge windows must never overlap."""

    def test_windows_do_not_overlap_standard_peak(self):
        """Standard evening peak: charge 12–16h, discharge 17–21h — no overlap."""
        tou = TimeOfUse(
            peak_rate=0.40,
            off_peak_rate=0.15,
            peak_hours_start=17,
            peak_hours_end=21,
        )
        charge_start, charge_end, discharge_start, discharge_end = (
            determine_charge_discharge_windows(tou)
        )
        charge_hours = set(range(charge_start, charge_end + 1))
        discharge_hours = set(range(discharge_start, discharge_end + 1))
        assert charge_hours.isdisjoint(discharge_hours)

    def test_windows_do_not_overlap_morning_peak(self):
        """Morning peak: charge window ends before peak starts — no overlap."""
        tou = TimeOfUse(
            peak_rate=0.35,
            off_peak_rate=0.10,
            peak_hours_start=8,
            peak_hours_end=12,
        )
        charge_start, charge_end, discharge_start, discharge_end = (
            determine_charge_discharge_windows(tou)
        )
        charge_hours = set(range(charge_start, charge_end + 1))
        discharge_hours = set(range(discharge_start, discharge_end + 1))
        assert charge_hours.isdisjoint(discharge_hours)

    def test_discharge_window_equals_peak_hours(self):
        """Discharge window must match the peak hours from the tariff."""
        tou = TimeOfUse(
            peak_rate=0.40,
            off_peak_rate=0.15,
            peak_hours_start=17,
            peak_hours_end=21,
        )
        _, _, discharge_start, discharge_end = determine_charge_discharge_windows(tou)
        assert discharge_start == 17
        assert discharge_end == 21

    def test_charge_window_ends_before_peak_starts(self):
        """Charge window must end at peak_hours_start - 1."""
        tou = TimeOfUse(
            peak_rate=0.40,
            off_peak_rate=0.15,
            peak_hours_start=17,
            peak_hours_end=21,
        )
        _, charge_end, _, _ = determine_charge_discharge_windows(tou)
        assert charge_end == 16  # peak_hours_start - 1

    def test_overlap_raises_value_error(self):
        """Overlapping windows must raise ValueError."""
        # Construct a scenario where the computed charge window would overlap
        # with the discharge window. Peak starts at hour 1 → charge_end = 0,
        # charge_start = max(0, -4) = 0 → charge covers {0}, discharge covers {1..X}.
        # Actually the implementation prevents overlap by design; we test the
        # ValueError path by calling with a tariff where peak_hours_start = 0,
        # which wraps charge_end to 23 and charge_start to 19.
        # To force an overlap we need to craft a case where the algorithm
        # produces overlapping windows. The only way is if peak spans the
        # entire night, so let's verify the ValueError is raised when we
        # manually call with overlapping windows by testing the guard directly.
        # We test this by checking that a very wide peak window (0–23) causes
        # the function to raise ValueError.
        tou = TimeOfUse(
            peak_rate=0.40,
            off_peak_rate=0.15,
            peak_hours_start=0,
            peak_hours_end=23,
        )
        with pytest.raises(ValueError, match="overlap"):
            determine_charge_discharge_windows(tou)

    def test_agent_skips_arbitrage_on_overlap_error(self):
        """Agent gracefully skips arbitrage when windows overlap (no crash)."""
        tou = TimeOfUse(
            peak_rate=0.40,
            off_peak_rate=0.15,
            peak_hours_start=0,
            peak_hours_end=23,
        )
        data = _make_consumption(_away_daytime_monthly(), tou=tou)
        # Should not raise — agent catches ValueError and skips arbitrage
        profile = run(data)
        assert profile.battery_recommendation.arbitrage_savings_eur_annual is None
        assert profile.battery_recommendation.charge_window_start is None


# ============================================================================
# Tests: Optimization schedule
# ============================================================================


class TestOptimizationSchedule:
    """Optimization schedule must be quarterly with next_review ~90 days out."""

    def test_optimization_frequency_is_quarterly(self):
        """optimization_schedule.frequency must be QUARTERLY."""
        data = _make_consumption(_mixed_monthly())
        profile = run(data)
        assert profile.optimization_schedule.frequency == OptimizationFrequency.QUARTERLY

    def test_next_review_is_approximately_90_days(self):
        """next_review must be today + 90 days (within ±1 day tolerance)."""
        data = _make_consumption(_mixed_monthly())
        profile = run(data)
        expected = date.today() + timedelta(days=REVIEW_PERIOD_DAYS)
        delta = abs((profile.optimization_schedule.next_review - expected).days)
        assert delta <= 1

    def test_next_review_is_in_the_future(self):
        """next_review must always be after today."""
        data = _make_consumption(_mixed_monthly())
        profile = run(data)
        assert profile.optimization_schedule.next_review > date.today()


# ============================================================================
# Tests: Annual savings estimation
# ============================================================================


class TestAnnualSavings:
    """Annual savings = self_consumption + feed_in + arbitrage, clamped to [0, 5000]."""

    def test_annual_savings_positive_with_feed_in(self):
        """Annual savings must be positive when feed-in tariff is set."""
        data = _make_consumption(_mixed_monthly(), feed_in_tariff=0.08)
        profile = run(data)
        assert profile.estimated_annual_savings_eur is not None
        assert profile.estimated_annual_savings_eur > 0

    def test_annual_savings_increases_with_tou(self):
        """Adding a TOU tariff should increase annual savings."""
        data_no_tou = _make_consumption(_away_daytime_monthly(), tou=None)
        tou = TimeOfUse(
            peak_rate=0.40,
            off_peak_rate=0.15,
            peak_hours_start=17,
            peak_hours_end=21,
        )
        data_with_tou = _make_consumption(_away_daytime_monthly(), tou=tou)

        profile_no_tou = run(data_no_tou)
        profile_with_tou = run(data_with_tou)

        assert (
            profile_with_tou.estimated_annual_savings_eur
            > profile_no_tou.estimated_annual_savings_eur
        )

    def test_annual_savings_within_schema_bounds(self):
        """Annual savings must satisfy schema constraint [0, 5000]."""
        for monthly_fn in [_home_all_day_monthly, _away_daytime_monthly, _mixed_monthly]:
            data = _make_consumption(monthly_fn())
            profile = run(data)
            assert profile.estimated_annual_savings_eur is not None
            assert 0 <= profile.estimated_annual_savings_eur <= 5000

    def test_annual_savings_formula_no_tou(self):
        """Verify savings formula without TOU: self_consumption + feed_in."""
        monthly = _mixed_monthly()
        annual_kwh = sum(monthly.values())
        rate = 0.30
        feed_in = 0.08
        data = _make_consumption(monthly, rate_per_kwh=rate, feed_in_tariff=feed_in, tou=None)
        profile = run(data)

        daily_avg = annual_kwh / 365
        occupancy = profile.occupancy_pattern
        factor = SELF_CONSUMPTION_FACTORS[occupancy]
        self_consumption_savings = daily_avg * factor * rate * 365
        feed_in_revenue = daily_avg * 0.2 * feed_in * 365  # FEED_IN_EXPORT_FRACTION = 0.2
        expected = max(0.0, min(5000.0, self_consumption_savings + feed_in_revenue))

        assert profile.estimated_annual_savings_eur == pytest.approx(expected, rel=1e-3)


# ============================================================================
# Tests: Round-trip serialization
# ============================================================================


class TestRoundTripSerialization:
    """BehavioralProfile → JSON → BehavioralProfile must yield an equivalent object."""

    def test_round_trip_no_tou(self):
        """Round-trip without TOU tariff."""
        data = _make_consumption(_mixed_monthly(), tou=None)
        original = run(data)

        json_str = original.model_dump_json()
        restored = BehavioralProfile.model_validate_json(json_str)

        assert restored.occupancy_pattern == original.occupancy_pattern
        assert restored.battery_recommendation.capacity_kwh == pytest.approx(
            original.battery_recommendation.capacity_kwh, rel=1e-6
        )
        assert restored.optimization_schedule.frequency == original.optimization_schedule.frequency
        assert restored.optimization_schedule.next_review == original.optimization_schedule.next_review
        assert restored.estimated_annual_savings_eur == pytest.approx(
            original.estimated_annual_savings_eur, rel=1e-6
        )
        assert restored.self_consumption_ratio == pytest.approx(
            original.self_consumption_ratio, rel=1e-6
        )

    def test_round_trip_with_tou(self):
        """Round-trip with TOU tariff and arbitrage windows set."""
        tou = TimeOfUse(
            peak_rate=0.40,
            off_peak_rate=0.15,
            peak_hours_start=17,
            peak_hours_end=21,
        )
        data = _make_consumption(_away_daytime_monthly(), tou=tou)
        original = run(data)

        json_str = original.model_dump_json()
        restored = BehavioralProfile.model_validate_json(json_str)

        assert restored.occupancy_pattern == original.occupancy_pattern
        assert restored.battery_recommendation.charge_window_start == original.battery_recommendation.charge_window_start
        assert restored.battery_recommendation.charge_window_end == original.battery_recommendation.charge_window_end
        assert restored.battery_recommendation.discharge_window_start == original.battery_recommendation.discharge_window_start
        assert restored.battery_recommendation.discharge_window_end == original.battery_recommendation.discharge_window_end
        assert restored.battery_recommendation.arbitrage_savings_eur_annual == pytest.approx(
            original.battery_recommendation.arbitrage_savings_eur_annual, rel=1e-6
        )

    def test_round_trip_dict_roundtrip(self):
        """model_dump() → model_validate() also yields equivalent object."""
        data = _make_consumption(_home_all_day_monthly())
        original = run(data)

        as_dict = original.model_dump()
        restored = BehavioralProfile.model_validate(as_dict)

        assert restored.occupancy_pattern == original.occupancy_pattern
        assert restored.battery_recommendation.capacity_kwh == pytest.approx(
            original.battery_recommendation.capacity_kwh, rel=1e-6
        )
        assert restored.optimization_schedule.next_review == original.optimization_schedule.next_review

    def test_round_trip_preserves_metadata_timestamp(self):
        """Metadata timestamp survives JSON round-trip."""
        data = _make_consumption(_mixed_monthly())
        original = run(data)

        json_str = original.model_dump_json()
        restored = BehavioralProfile.model_validate_json(json_str)

        assert restored.metadata.timestamp == original.metadata.timestamp
