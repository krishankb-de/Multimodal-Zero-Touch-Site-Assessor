"""
Regional climate data for German residential solar + heat pump projects.

Regions match the 3D model filenames in Datasets/Exp 3D-Modells/:
  Brandenburg, Hamburg, North Germany, Ruhr

Sources:
  - Design outdoor temps: DIN EN 12831-1 Annex A (German climate zones)
  - Annual irradiance: DWD / PVGIS long-term averages (kWh/m²/year, optimal tilt)
"""

from __future__ import annotations

# Typical PV system efficiency (inverter + wiring + soiling losses)
SYSTEM_EFFICIENCY = 0.80

_CLIMATE_TABLE: dict[str, dict[str, float]] = {
    "Brandenburg": {
        "design_outdoor_temp_c": -14.0,
        "annual_irradiance_kwh_m2": 1050.0,
    },
    "Hamburg": {
        "design_outdoor_temp_c": -12.0,
        "annual_irradiance_kwh_m2": 960.0,
    },
    "North Germany": {
        "design_outdoor_temp_c": -10.0,
        "annual_irradiance_kwh_m2": 940.0,
    },
    "Ruhr": {
        "design_outdoor_temp_c": -10.0,
        "annual_irradiance_kwh_m2": 970.0,
    },
}

DEFAULT_REGION = "Hamburg"


def _lookup(region: str) -> dict[str, float]:
    return _CLIMATE_TABLE.get(region, _CLIMATE_TABLE[DEFAULT_REGION])


def design_outdoor_temp_c(region: str) -> float:
    """Return DIN EN 12831 design outdoor temperature for the region (°C)."""
    return _lookup(region)["design_outdoor_temp_c"]


def annual_irradiance_kwh_m2(region: str) -> float:
    """Return long-term annual PV irradiance for the region (kWh/m²/year)."""
    return _lookup(region)["annual_irradiance_kwh_m2"]


def annual_pv_yield_kwh(total_kwp: float, region: str) -> float:
    """
    Estimate annual PV energy yield (kWh/year).

    Formula: total_kwp × irradiance_kwh_m2 × system_efficiency
    (irradiance here is per kWp, so units are already kWh/kWp/year from PVGIS)
    """
    return total_kwp * annual_irradiance_kwh_m2(region) * SYSTEM_EFFICIENCY


def known_regions() -> list[str]:
    return list(_CLIMATE_TABLE.keys())
