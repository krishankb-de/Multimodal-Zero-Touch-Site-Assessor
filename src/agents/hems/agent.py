"""
HEMS Quarterly Adaptive Optimizer

Implements EEBus-compatible post-install optimization:
1. Ingest smart-meter telemetry (EEBus SMGW / EMC readings).
2. Detect occupancy drift by comparing new consumption patterns to the
   baseline ConsumptionData from the original site assessment.
3. Re-run the Behavioral Agent with a patched ConsumptionData that
   reflects telemetry-observed months.
4. Return an OptimizationDelta describing what changed and why.

Drift detection heuristics:
  - Export fraction = total_exported / (total_imported + total_exported)
    * > 0.40 → AWAY_DAYTIME   (high solar export, nobody home consuming it)
    * < 0.15 → HOME_ALL_DAY   (most solar self-consumed on site)
    * else   → MIXED
  - Winter/summer ratio from telemetry-derived monthly kWh (same logic
    as the Behavioral Agent) when ≥ 6 months of readings are available.
  - Drift is declared when inferred pattern ≠ baseline pattern.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean

from src.agents.behavioral import agent as behavioral_agent
from src.common.schemas import (
    BehavioralProfile,
    ConsumptionData,
    MonthlyConsumption,
    OccupancyPattern,
    OptimizationDelta,
    TelemetryPoint,
)

logger = logging.getLogger(__name__)

# Thresholds for export-fraction-based occupancy inference
EXPORT_AWAY_THRESHOLD = 0.40   # > this → away_daytime
EXPORT_HOME_THRESHOLD = 0.15   # < this → home_all_day

# Reuse seasonal windows from Behavioral Agent
WINTER_MONTHS = {11, 12, 1, 2}
SUMMER_MONTHS = {5, 6, 7, 8}
RATIO_HOME_ALL_DAY = 1.5
RATIO_AWAY_DAYTIME = 1.2


def _infer_occupancy_from_telemetry(readings: list[TelemetryPoint]) -> tuple[OccupancyPattern, str]:
    """
    Infer occupancy from telemetry, returning (pattern, reason).

    Prefers winter/summer ratio when ≥ 6 months of data available;
    falls back to export-fraction heuristic.
    """
    if not readings:
        return OccupancyPattern.UNKNOWN, "no telemetry readings"

    total_imported = sum(r.kwh_imported for r in readings)
    total_exported = sum(r.kwh_exported for r in readings)
    total_energy = total_imported + total_exported

    # Monthly buckets: month number → list of kWh imported
    monthly: dict[int, list[float]] = defaultdict(list)
    for r in readings:
        monthly[r.timestamp.month].append(r.kwh_imported)

    months_covered = len(monthly)

    # Seasonal ratio path (≥ 6 months of data)
    if months_covered >= 6:
        winter_vals = [mean(monthly[m]) for m in WINTER_MONTHS if m in monthly]
        summer_vals = [mean(monthly[m]) for m in SUMMER_MONTHS if m in monthly]
        if winter_vals and summer_vals:
            w_avg = mean(winter_vals)
            s_avg = mean(summer_vals)
            ratio = w_avg / s_avg if s_avg > 0 else 1.5
            if ratio > RATIO_HOME_ALL_DAY:
                return OccupancyPattern.HOME_ALL_DAY, f"seasonal ratio={ratio:.2f} > {RATIO_HOME_ALL_DAY}"
            elif ratio < RATIO_AWAY_DAYTIME:
                return OccupancyPattern.AWAY_DAYTIME, f"seasonal ratio={ratio:.2f} < {RATIO_AWAY_DAYTIME}"
            else:
                return OccupancyPattern.MIXED, f"seasonal ratio={ratio:.2f} in mixed range"

    # Export-fraction fallback
    if total_energy == 0:
        return OccupancyPattern.UNKNOWN, "zero energy in readings"

    export_fraction = total_exported / total_energy
    if export_fraction > EXPORT_AWAY_THRESHOLD:
        return (
            OccupancyPattern.AWAY_DAYTIME,
            f"export fraction={export_fraction:.2f} > {EXPORT_AWAY_THRESHOLD} (high solar export → away daytime)",
        )
    elif export_fraction < EXPORT_HOME_THRESHOLD:
        return (
            OccupancyPattern.HOME_ALL_DAY,
            f"export fraction={export_fraction:.2f} < {EXPORT_HOME_THRESHOLD} (low export → home all day)",
        )
    else:
        return OccupancyPattern.MIXED, f"export fraction={export_fraction:.2f} in mixed range"


def _patch_consumption_data(
    baseline: ConsumptionData,
    readings: list[TelemetryPoint],
) -> ConsumptionData:
    """
    Build updated ConsumptionData by replacing telemetry-covered months
    with observed kWh totals, keeping all other baseline months intact.
    """
    # Aggregate telemetry monthly kWh imported
    monthly_totals: dict[int, float] = defaultdict(float)
    for r in readings:
        monthly_totals[r.timestamp.month] += r.kwh_imported

    # Patch matching months in the baseline breakdown
    patched_months: list[MonthlyConsumption] = []
    for m in baseline.monthly_breakdown:
        if m.month in monthly_totals:
            patched_months.append(MonthlyConsumption(month=m.month, kwh=monthly_totals[m.month]))
        else:
            patched_months.append(m)

    new_annual = sum(m.kwh for m in patched_months)
    return baseline.model_copy(
        update={
            "annual_kwh": max(500.0, min(100000.0, new_annual)),
            "monthly_breakdown": patched_months,
        }
    )


def run(
    installation_id: str,
    baseline_consumption: ConsumptionData,
    baseline_profile: BehavioralProfile,
    readings: list[TelemetryPoint],
) -> OptimizationDelta:
    """
    Execute a HEMS quarterly reoptimization pass.

    1. Infer occupancy pattern from telemetry.
    2. Declare drift if inferred pattern differs from baseline.
    3. Patch ConsumptionData with telemetry-observed monthly kWh.
    4. Re-run Behavioral Agent on patched data.
    5. Return OptimizationDelta.
    """
    logger.info("HEMS Agent: reoptimizing installation %s (%d readings)", installation_id, len(readings))

    new_occupancy, drift_reason = _infer_occupancy_from_telemetry(readings)
    old_occupancy = baseline_profile.occupancy_pattern
    drift_detected = new_occupancy != old_occupancy and new_occupancy != OccupancyPattern.UNKNOWN

    logger.info(
        "  Occupancy: baseline=%s, inferred=%s, drift=%s (%s)",
        old_occupancy.value,
        new_occupancy.value,
        drift_detected,
        drift_reason,
    )

    patched_consumption = _patch_consumption_data(baseline_consumption, readings)
    new_profile: BehavioralProfile = behavioral_agent.run(patched_consumption)

    old_battery = baseline_profile.battery_recommendation.capacity_kwh
    new_battery = new_profile.battery_recommendation.capacity_kwh
    old_savings = baseline_profile.estimated_annual_savings_eur
    new_savings = new_profile.estimated_annual_savings_eur

    logger.info(
        "HEMS Agent: battery %+.2f kWh, savings %+.2f EUR/year",
        new_battery - old_battery,
        (new_savings or 0.0) - (old_savings or 0.0),
    )

    return OptimizationDelta(
        installation_id=installation_id,
        drift_detected=drift_detected,
        drift_reason=drift_reason,
        old_occupancy=old_occupancy,
        new_occupancy=new_occupancy,
        old_battery_kwh=old_battery,
        new_battery_kwh=new_battery,
        battery_delta_kwh=round(new_battery - old_battery, 3),
        old_savings_eur=old_savings,
        new_savings_eur=new_savings,
        savings_delta_eur=round((new_savings or 0.0) - (old_savings or 0.0), 2)
        if new_savings is not None or old_savings is not None
        else None,
        new_profile=new_profile,
        optimized_at=datetime.now(timezone.utc),
    )
