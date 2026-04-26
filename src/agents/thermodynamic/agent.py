"""
Thermodynamic Agent

Takes SpatialData and ConsumptionData from the Ingestion Agent and produces
a ThermalLoad using the DIN EN 12831 simplified calculation engine.

No LLM dependency — this is a deterministic, standards-based calculation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from src.common.config import config
from src.common import climate
from src.common.schemas import (
    CalculationMetadata,
    ConsumptionData,
    DHWRequirement,
    HeatPumpRecommendation,
    HeatPumpType,
    SpatialData,
    ThermalLoad,
    UValues,
    WeatherProfile,
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


def run(
    spatial_data: SpatialData,
    consumption_data: ConsumptionData,
    weather_profile: Optional[WeatherProfile] = None,
) -> ThermalLoad:
    """
    Execute the Thermodynamic Agent pipeline.

    1. Determine design outdoor temperature (from WeatherProfile if available, else static)
    2. Determine house size / building geometry (from HouseDimensions if available, else roof proxy)
    3. Calculate design heat load via DIN EN 12831
    4. Estimate DHW requirement and cylinder sizing
    5. Recommend heat pump capacity
    6. Evaluate whether cylinder fits in utility room
    7. Produce a validated ThermalLoad

    Args:
        spatial_data:    Validated SpatialData from the Ingestion Agent.
        consumption_data: Validated ConsumptionData from the Ingestion Agent.
        weather_profile: Optional WeatherProfile — when present, uses location-specific
                         minimum temperature as design outdoor temperature (Req 8.2).

    Returns:
        ThermalLoad ready for validation by the Safety Agent.
    """
    logger.info("Thermodynamic Agent: starting DIN EN 12831 heat load calculation")

    # Step 1: Determine design outdoor temperature
    region = config.market.region
    if weather_profile is not None:
        # Use location-specific minimum monthly temperature (Req 8.2)
        design_outdoor_temp_c = min(weather_profile.monthly_avg_temperature_c)
        logger.info(
            "Thermodynamic Agent: using location-specific design outdoor temp = %.1f °C "
            "(min of monthly averages from WeatherProfile)",
            design_outdoor_temp_c,
        )
    else:
        design_outdoor_temp_c = climate.design_outdoor_temp_c(region)
        logger.info(
            "Thermodynamic Agent: design outdoor temp = %.1f °C (region=%s, static)",
            design_outdoor_temp_c,
            region,
        )

    # Step 2: Determine building geometry
    # Use HouseDimensions when available (Req 12.1, 12.2), else roof-area proxy (Req 12.3)
    house_dimensions = spatial_data.house_dimensions
    use_dimensions = house_dimensions is not None

    if use_dimensions and house_dimensions is not None:
        wall_area_m2 = house_dimensions.estimated_wall_area_m2
        volume_m3 = house_dimensions.estimated_volume_m3
        # Estimate floor area from footprint
        floor_area_m2 = house_dimensions.footprint_width_m * house_dimensions.footprint_depth_m
        house_size_sqm = floor_area_m2  # used for DHW estimation
        logger.info(
            "Thermodynamic Agent: using HouseDimensions — "
            "wall_area=%.0f m², volume=%.0f m³, floor_area=%.0f m²",
            wall_area_m2, volume_m3, floor_area_m2,
        )
    else:
        # Existing roof-area proxy
        house_size_sqm = spatial_data.roof.total_usable_area_m2
        wall_area_m2 = None
        volume_m3 = None
        floor_area_m2 = None
        logger.info(
            "Thermodynamic Agent: using roof-area proxy — house_size=%.1f m²",
            house_size_sqm,
        )

    # building_year is not available in the current schemas — use default U-values
    building_year: int | None = None
    u_values_dict = din_en_12831.get_u_values(building_year)

    # Step 3: Calculate design heat load
    delta_temp = 20.0 - design_outdoor_temp_c  # design_indoor_temp_c = 20°C

    if use_dimensions and wall_area_m2 is not None and volume_m3 is not None:
        # Dimension-aware calculation (Req 12.1, 12.2)
        transmission = din_en_12831.calculate_transmission_loss_from_dimensions(
            wall_area_m2=wall_area_m2,
            u_values=u_values_dict,
            delta_temp=delta_temp,
            floor_area_m2=floor_area_m2,
        )
        ventilation = din_en_12831.calculate_ventilation_loss_from_volume(
            volume_m3=volume_m3,
            delta_temp=delta_temp,
        )
        raw_heat_load = transmission + ventilation
        design_heat_load_kw = round(raw_heat_load * DEFAULT_SAFETY_FACTOR, 2)
        heat_load_result = din_en_12831.HeatLoadResult(
            transmission_loss_kw=round(transmission, 2),
            ventilation_loss_kw=round(ventilation, 2),
            design_heat_load_kw=design_heat_load_kw,
            u_values=u_values_dict,
            design_outdoor_temp_c=design_outdoor_temp_c,
            design_indoor_temp_c=20.0,
        )
        logger.info(
            "Thermodynamic Agent: dimension-aware heat load = %.2f kW "
            "(transmission=%.2f kW, ventilation=%.2f kW)",
            heat_load_result.design_heat_load_kw,
            heat_load_result.transmission_loss_kw,
            heat_load_result.ventilation_loss_kw,
        )
    else:
        # Existing roof-area proxy calculation (Req 12.3)
        heat_load_result = din_en_12831.calculate_design_heat_load(
            house_size_sqm=house_size_sqm,
            design_outdoor_temp_c=design_outdoor_temp_c,
            building_year=building_year,
            safety_factor=DEFAULT_SAFETY_FACTOR,
        )
        logger.info(
            "Thermodynamic Agent: proxy heat load = %.2f kW "
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
