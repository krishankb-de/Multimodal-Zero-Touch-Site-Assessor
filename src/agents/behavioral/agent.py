"""
Behavioral Agent

Analyzes household consumption patterns to produce a BehavioralProfile:
- Occupancy pattern detection from seasonal consumption ratios
- Battery capacity sizing based on occupancy and daily consumption
- TOU arbitrage windows and savings when a time-of-use tariff is present
- Optimization schedule (quarterly review)
- Annual savings estimate (self-consumption + feed-in + arbitrage)

No LLM calls — fully deterministic.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from statistics import mean

from src.agents.behavioral.arbitrage import (
    calculate_arbitrage_savings,
    determine_charge_discharge_windows,
)
from src.common.schemas import (
    BatteryRecommendation,
    BehavioralProfile,
    ConsumptionData,
    OccupancyPattern,
    OptimizationFrequency,
    OptimizationSchedule,
    SimpleMetadata,
)

logger = logging.getLogger(__name__)

# Winter months: November, December, January, February
WINTER_MONTHS = {11, 12, 1, 2}

# Summer months: May, June, July, August
SUMMER_MONTHS = {5, 6, 7, 8}

# Occupancy ratio thresholds (winter_avg / summer_avg)
RATIO_HOME_ALL_DAY = 1.5   # > this → home_all_day
RATIO_AWAY_DAYTIME = 1.2   # < this → away_daytime

# Self-consumption factors by occupancy pattern
SELF_CONSUMPTION_FACTORS: dict[OccupancyPattern, float] = {
    OccupancyPattern.AWAY_DAYTIME: 0.3,
    OccupancyPattern.HOME_ALL_DAY: 0.5,
    OccupancyPattern.MIXED: 0.4,
    OccupancyPattern.SHIFT_WORKER: 0.4,
    OccupancyPattern.UNKNOWN: 0.4,
}

# Occupancy multipliers for battery sizing
OCCUPANCY_MULTIPLIERS: dict[OccupancyPattern, float] = {
    OccupancyPattern.HOME_ALL_DAY: 1.0,
    OccupancyPattern.AWAY_DAYTIME: 0.8,
    OccupancyPattern.MIXED: 0.9,
    OccupancyPattern.SHIFT_WORKER: 0.9,
    OccupancyPattern.UNKNOWN: 0.9,
}

# Battery capacity clamp bounds (kWh)
BATTERY_MIN_KWH = 0.5
BATTERY_MAX_KWH = 50.0

# Annual savings clamp bounds (EUR)
SAVINGS_MIN_EUR = 0.0
SAVINGS_MAX_EUR = 5000.0

# Fraction of daily consumption that is shiftable for TOU arbitrage
SHIFTABLE_FRACTION = 0.3

# Fraction of daily consumption exported as feed-in
FEED_IN_EXPORT_FRACTION = 0.2

# Optimization review period (days)
REVIEW_PERIOD_DAYS = 90


def _detect_occupancy(consumption_data: ConsumptionData) -> OccupancyPattern:
    """
    Detect occupancy pattern from the winter/summer consumption ratio.

    Winter months: Nov (11), Dec (12), Jan (1), Feb (2)
    Summer months: May (5), Jun (6), Jul (7), Aug (8)

    Ratio = winter_avg / summer_avg:
      > 1.5  → HOME_ALL_DAY
      < 1.2  → AWAY_DAYTIME
      else   → MIXED
    """
    monthly_map = {m.month: m.kwh for m in consumption_data.monthly_breakdown}

    winter_values = [monthly_map[m] for m in WINTER_MONTHS if m in monthly_map]
    summer_values = [monthly_map[m] for m in SUMMER_MONTHS if m in monthly_map]

    if not winter_values or not summer_values:
        logger.warning("Behavioral Agent: incomplete seasonal data, defaulting to MIXED")
        return OccupancyPattern.MIXED

    winter_avg = mean(winter_values)
    summer_avg = mean(summer_values)

    if summer_avg == 0:
        ratio = 1.5  # Default to home_all_day when no summer consumption
    else:
        ratio = winter_avg / summer_avg

    logger.info(
        "  Occupancy detection: winter_avg=%.2f kWh, summer_avg=%.2f kWh, ratio=%.3f",
        winter_avg,
        summer_avg,
        ratio,
    )

    if ratio > RATIO_HOME_ALL_DAY:
        return OccupancyPattern.HOME_ALL_DAY
    elif ratio < RATIO_AWAY_DAYTIME:
        return OccupancyPattern.AWAY_DAYTIME
    else:
        return OccupancyPattern.MIXED


def run(consumption_data: ConsumptionData) -> BehavioralProfile:
    """
    Execute the Behavioral Agent analysis.

    1. Detect occupancy pattern from seasonal consumption ratio
    2. Size battery capacity based on occupancy and daily average
    3. Calculate TOU arbitrage windows and savings (if TOU tariff present)
    4. Build optimization schedule (quarterly, next review in 90 days)
    5. Estimate annual savings (self-consumption + feed-in + arbitrage)

    Args:
        consumption_data: Validated ConsumptionData from the Ingestion Agent.

    Returns:
        BehavioralProfile ready for validation by the Safety Agent.
    """
    logger.info(
        "Behavioral Agent: analysing %.0f kWh/year consumption",
        consumption_data.annual_kwh,
    )

    # -------------------------------------------------------------------------
    # 1. Occupancy detection
    # -------------------------------------------------------------------------
    occupancy_pattern = _detect_occupancy(consumption_data)
    logger.info("  Occupancy pattern: %s", occupancy_pattern.value)

    # -------------------------------------------------------------------------
    # 2. Battery sizing
    # -------------------------------------------------------------------------
    daily_avg_kwh = consumption_data.annual_kwh / 365

    self_consumption_factor = SELF_CONSUMPTION_FACTORS.get(occupancy_pattern, 0.4)
    occupancy_multiplier = OCCUPANCY_MULTIPLIERS.get(occupancy_pattern, 0.9)

    raw_capacity_kwh = daily_avg_kwh * self_consumption_factor * occupancy_multiplier
    capacity_kwh = max(BATTERY_MIN_KWH, min(BATTERY_MAX_KWH, raw_capacity_kwh))

    logger.info(
        "  Battery sizing: daily_avg=%.2f kWh, factor=%.1f, multiplier=%.1f → %.2f kWh (clamped: %.2f kWh)",
        daily_avg_kwh,
        self_consumption_factor,
        occupancy_multiplier,
        raw_capacity_kwh,
        capacity_kwh,
    )

    # -------------------------------------------------------------------------
    # 3. TOU arbitrage (optional)
    # -------------------------------------------------------------------------
    charge_start: int | None = None
    charge_end: int | None = None
    discharge_start: int | None = None
    discharge_end: int | None = None
    arbitrage_savings: float | None = None

    tou_tariff = consumption_data.tariff.time_of_use
    if tou_tariff is not None:
        try:
            charge_start, charge_end, discharge_start, discharge_end = (
                determine_charge_discharge_windows(tou_tariff)
            )
            shiftable_kwh = daily_avg_kwh * SHIFTABLE_FRACTION
            arbitrage_savings = calculate_arbitrage_savings(
                shiftable_kwh,
                tou_tariff.peak_rate,
                tou_tariff.off_peak_rate,
            )
            logger.info(
                "  TOU arbitrage: charge %d–%dh, discharge %d–%dh, savings=%.2f EUR/year",
                charge_start,
                charge_end,
                discharge_start,
                discharge_end,
                arbitrage_savings,
            )
        except ValueError as exc:
            logger.warning("  TOU arbitrage window error: %s — skipping arbitrage", exc)

    # -------------------------------------------------------------------------
    # 4. Battery recommendation
    # -------------------------------------------------------------------------
    rationale = (
        f"Sized for {occupancy_pattern.value} occupancy: {capacity_kwh:.1f} kWh"
    )

    battery_recommendation = BatteryRecommendation(
        capacity_kwh=round(capacity_kwh, 2),
        rationale=rationale,
        charge_window_start=charge_start,
        charge_window_end=charge_end,
        discharge_window_start=discharge_start,
        discharge_window_end=discharge_end,
        arbitrage_savings_eur_annual=round(arbitrage_savings, 2) if arbitrage_savings is not None else None,
    )

    # -------------------------------------------------------------------------
    # 5. Optimization schedule
    # -------------------------------------------------------------------------
    optimization_schedule = OptimizationSchedule(
        frequency=OptimizationFrequency.QUARTERLY,
        next_review=date.today() + timedelta(days=REVIEW_PERIOD_DAYS),
    )

    # -------------------------------------------------------------------------
    # 6. Annual savings estimate
    # -------------------------------------------------------------------------
    tariff = consumption_data.tariff
    feed_in_rate = tariff.feed_in_tariff_per_kwh or 0.0

    self_consumption_savings = (
        daily_avg_kwh * self_consumption_factor * tariff.rate_per_kwh * 365
    )
    feed_in_revenue = daily_avg_kwh * FEED_IN_EXPORT_FRACTION * feed_in_rate * 365
    total_savings_raw = (
        self_consumption_savings + feed_in_revenue + (arbitrage_savings or 0.0)
    )
    estimated_annual_savings_eur = max(
        SAVINGS_MIN_EUR, min(SAVINGS_MAX_EUR, total_savings_raw)
    )

    logger.info(
        "  Annual savings: self_consumption=%.2f EUR, feed_in=%.2f EUR, arbitrage=%.2f EUR → total=%.2f EUR",
        self_consumption_savings,
        feed_in_revenue,
        arbitrage_savings or 0.0,
        estimated_annual_savings_eur,
    )

    # -------------------------------------------------------------------------
    # 7. Self-consumption ratio
    # -------------------------------------------------------------------------
    raw_ratio = self_consumption_factor * occupancy_multiplier
    self_consumption_ratio = max(0.0, min(1.0, raw_ratio))

    logger.info(
        "Behavioral Agent: complete — occupancy=%s, battery=%.2f kWh, savings=%.2f EUR/year",
        occupancy_pattern.value,
        capacity_kwh,
        estimated_annual_savings_eur,
    )

    return BehavioralProfile(
        occupancy_pattern=occupancy_pattern,
        self_consumption_ratio=round(self_consumption_ratio, 4),
        battery_recommendation=battery_recommendation,
        optimization_schedule=optimization_schedule,
        estimated_annual_savings_eur=round(estimated_annual_savings_eur, 2),
        metadata=SimpleMetadata(timestamp=datetime.now(timezone.utc)),
    )
