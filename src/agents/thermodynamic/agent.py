"""
Thermodynamic Agent

Takes SpatialData and ConsumptionData from the Ingestion Agent and produces
a ThermalLoad using the DIN EN 12831 simplified calculation engine.

No LLM dependency — this is a deterministic, standards-based calculation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.common.config import config
from src.common.schemas import (
    CalculationMetadata,
    ConsumptionData,
    DHWRequirement,
    HeatPumpRecommendation,
    HeatPumpType,
    SpatialData,
    ThermalLoad,
    UValues,
)
from src.agents.thermodynamic import din_en_12831

logger = logging.getLogger(__name__)

AGENT_VERSION = "1.0.0"

# Physical volume overhead factor for cylinder insulation jacket
# A 200L cylinder ≈ 0.2 m³ physical volume (20% overhead for insulation)
CYLINDER_VOLUME_OVERHEAD_FACTOR = 1.2

# Default COP estimate for air-source heat pump
DEFAULT_AIR_SOURCE_COP = 3.5

# Default safety factor for heat pump sizing
DEFAULT_SAFETY_FACTOR = 1.15


def _estimate_cylinder_volume_m3(cylinder_litres: int) -> float:
    """
    Estimate the physical volume (m³) occupied by a DHW cylinder including
    its insulation jacket.

    Formula: cylinder_volume_m3 = cylinder_litres / 1000 * 1.2
    (20% overhead for insulation jacket)

    Args:
        cylinder_litres: Cylinder capacity in litres.

    Returns:
        Physical volume in m³ including insulation jacket.
    """
    return (cylinder_litres / 1000) * CYLINDER_VOLUME_OVERHEAD_FACTOR


def run(spatial_data: SpatialData, consumption_data: ConsumptionData) -> ThermalLoad:
    """
    Execute the Thermodynamic Agent pipeline.

    1. Estimate house size from roof area
    2. Calculate design heat load via DIN EN 12831
    3. Estimate DHW requirement and cylinder sizing
    4. Recommend heat pump capacity
    5. Evaluate whether cylinder fits in utility room
    6. Produce a validated ThermalLoad

    Args:
        spatial_data: Validated SpatialData from the Ingestion Agent.
        consumption_data: Validated ConsumptionData from the Ingestion Agent.

    Returns:
        ThermalLoad ready for validation by the Safety Agent.
    """
    logger.info("Thermodynamic Agent: starting DIN EN 12831 heat load calculation")

    # Step 1: Estimate house size from roof area
    # Roof total usable area ≈ floor area for typical residential buildings
    house_size_sqm = spatial_data.roof.total_usable_area_m2
    logger.info("Thermodynamic Agent: estimated house size = %.1f m²", house_size_sqm)

    # Step 2: Determine design outdoor temperature from config
    design_outdoor_temp_c = config.market.design_outdoor_temp_c
    logger.info(
        "Thermodynamic Agent: design outdoor temp = %.1f °C (from config)",
        design_outdoor_temp_c,
    )

    # building_year is not available in the current schemas — use default U-values
    # (DIN EN 12831 engine will select "default" U-values when building_year is None)
    building_year: int | None = None

    # Step 3: Calculate design heat load via DIN EN 12831 simplified method
    heat_load_result = din_en_12831.calculate_design_heat_load(
        house_size_sqm=house_size_sqm,
        design_outdoor_temp_c=design_outdoor_temp_c,
        building_year=building_year,
        safety_factor=DEFAULT_SAFETY_FACTOR,
    )
    logger.info(
        "Thermodynamic Agent: design heat load = %.2f kW "
        "(transmission=%.2f kW, ventilation=%.2f kW)",
        heat_load_result.design_heat_load_kw,
        heat_load_result.transmission_loss_kw,
        heat_load_result.ventilation_loss_kw,
    )

    # Step 4: Estimate DHW requirement and cylinder sizing
    daily_litres, cylinder_volume_litres = din_en_12831.estimate_dhw_requirement(
        house_size_sqm=house_size_sqm,
    )
    logger.info(
        "Thermodynamic Agent: DHW = %.0f L/day, cylinder = %d L",
        daily_litres,
        cylinder_volume_litres,
    )

    # Step 5: Evaluate whether the cylinder fits in the utility room
    cylinder_physical_volume_m3 = _estimate_cylinder_volume_m3(cylinder_volume_litres)
    available_volume_m3 = spatial_data.utility_room.available_volume_m3
    fits_in_utility_room: bool | None = None
    if available_volume_m3 > 0:
        fits_in_utility_room = cylinder_physical_volume_m3 <= available_volume_m3
        logger.info(
            "Thermodynamic Agent: cylinder physical volume = %.3f m³, "
            "available = %.3f m³, fits = %s",
            cylinder_physical_volume_m3,
            available_volume_m3,
            fits_in_utility_room,
        )
    else:
        logger.info(
            "Thermodynamic Agent: utility room available_volume_m3 = 0, "
            "skipping fits_in_utility_room evaluation"
        )

    # Step 6: Recommend heat pump capacity
    recommended_capacity_kw = din_en_12831.recommend_heat_pump_capacity(
        design_heat_load_kw=heat_load_result.design_heat_load_kw,
    )
    logger.info(
        "Thermodynamic Agent: recommended heat pump capacity = %.0f kW",
        recommended_capacity_kw,
    )

    # Step 7: Build the UValues sub-model from the engine's selected U-values
    u_values_dict = heat_load_result.u_values
    u_values = UValues(
        walls_w_m2k=u_values_dict.get("walls"),
        roof_w_m2k=u_values_dict.get("roof"),
        floor_w_m2k=u_values_dict.get("floor"),
        windows_w_m2k=u_values_dict.get("windows"),
    )

    # Step 8: Assemble the ThermalLoad output
    thermal_load = ThermalLoad(
        design_heat_load_kw=heat_load_result.design_heat_load_kw,
        transmission_loss_kw=heat_load_result.transmission_loss_kw,
        ventilation_loss_kw=heat_load_result.ventilation_loss_kw,
        design_outdoor_temp_c=heat_load_result.design_outdoor_temp_c,
        design_indoor_temp_c=heat_load_result.design_indoor_temp_c,
        u_values_used=u_values,
        heat_pump_recommendation=HeatPumpRecommendation(
            capacity_kw=float(recommended_capacity_kw),
            type=HeatPumpType.AIR_SOURCE,
            cop_estimate=DEFAULT_AIR_SOURCE_COP,
            safety_factor=DEFAULT_SAFETY_FACTOR,
        ),
        dhw_requirement=DHWRequirement(
            daily_litres=float(daily_litres),
            cylinder_volume_litres=cylinder_volume_litres,
            fits_in_utility_room=fits_in_utility_room,
        ),
        metadata=CalculationMetadata(
            algorithm_version=AGENT_VERSION,
            calculation_method="DIN_EN_12831_simplified",
            timestamp=datetime.now(timezone.utc),
        ),
    )

    logger.info(
        "Thermodynamic Agent: complete — heat load=%.2f kW, "
        "heat pump=%d kW, cylinder=%d L",
        thermal_load.design_heat_load_kw,
        recommended_capacity_kw,
        cylinder_volume_litres,
    )

    return thermal_load
