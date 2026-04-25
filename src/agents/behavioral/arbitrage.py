"""
TOU Arbitrage Module

Provides calculations for Time-of-Use tariff arbitrage:
- Annual savings from shifting load between peak and off-peak windows
- Charge/discharge window determination from a TOU tariff
"""

from __future__ import annotations

from src.common.schemas import TimeOfUse


def calculate_arbitrage_savings(
    shiftable_kwh: float,
    peak_rate: float,
    off_peak_rate: float,
) -> float:
    """
    Calculate annual savings (EUR) from TOU arbitrage.

    Savings come from charging during off-peak hours and discharging (or
    self-consuming) during peak hours, avoiding the higher peak rate.

    Formula: annual_savings = shiftable_kwh × (peak_rate - off_peak_rate) × 365

    Args:
        shiftable_kwh:  Daily kWh that can be shifted from peak to off-peak.
        peak_rate:      Tariff rate during peak hours (EUR/kWh).
        off_peak_rate:  Tariff rate during off-peak hours (EUR/kWh).

    Returns:
        Annual savings in EUR. Returns 0.0 if off_peak_rate >= peak_rate
        (no arbitrage opportunity).
    """
    rate_differential = peak_rate - off_peak_rate
    if rate_differential <= 0:
        return 0.0
    return shiftable_kwh * rate_differential * 365


def determine_charge_discharge_windows(
    tou_tariff: TimeOfUse,
) -> tuple[int, int, int, int]:
    """
    Determine battery charge and discharge windows from a TOU tariff.

    Discharge window = peak hours (peak_hours_start → peak_hours_end).
    Charge window    = 4-hour off-peak window ending just before peak starts.

    Args:
        tou_tariff: TimeOfUse tariff with peak hour boundaries.

    Returns:
        (charge_start, charge_end, discharge_start, discharge_end) as hour integers
        in the range [0, 23].

    Raises:
        ValueError: If the charge and discharge windows overlap.
    """
    # Discharge window = peak hours
    discharge_start = tou_tariff.peak_hours_start
    discharge_end = tou_tariff.peak_hours_end

    # Charge window = 4-hour window ending just before peak starts
    # If peak starts at hour 0, wrap around to hour 23
    charge_end = tou_tariff.peak_hours_start - 1 if tou_tariff.peak_hours_start > 0 else 23
    charge_start = max(0, charge_end - 4)

    # Validate no overlap between charge and discharge windows
    # Build sets of hours covered by each window
    if discharge_start <= discharge_end:
        discharge_hours = set(range(discharge_start, discharge_end + 1))
    else:
        # Wraps midnight
        discharge_hours = set(range(discharge_start, 24)) | set(range(0, discharge_end + 1))

    if charge_start <= charge_end:
        charge_hours = set(range(charge_start, charge_end + 1))
    else:
        # Wraps midnight
        charge_hours = set(range(charge_start, 24)) | set(range(0, charge_end + 1))

    overlap = charge_hours & discharge_hours
    if overlap:
        raise ValueError(
            f"Charge window ({charge_start}–{charge_end}h) and discharge window "
            f"({discharge_start}–{discharge_end}h) overlap at hours: "
            f"{sorted(overlap)}"
        )

    return charge_start, charge_end, discharge_start, discharge_end
