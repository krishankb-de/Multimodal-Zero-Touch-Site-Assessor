"""
DIN EN 12831 Simplified Heat Load Calculation

Implements the simplified method for residential buildings using
standardized flat U-values. This is the legally recognized method
for AI-based sizing when exact component data is missing.

Reference: DIN EN 12831-1:2017, Annex B (simplified method)

Calculation:
    Φ_HL = Φ_T + Φ_V

Where:
    Φ_T = Transmission heat loss = Σ(U_i × A_i) × (θ_int - θ_ext)
    Φ_V = Ventilation heat loss  = 0.34 × n × V × (θ_int - θ_ext)
    n   = Air change rate (typ. 0.5 h⁻¹ for residential)
    V   = Heated volume (m³)
"""

from __future__ import annotations

from dataclasses import dataclass

# Standard air change rate for residential buildings (h⁻¹)
DEFAULT_AIR_CHANGE_RATE = 0.5

# Specific heat capacity of air (Wh / (m³·K))
AIR_HEAT_CAPACITY = 0.34

# Standardized U-values for German residential buildings by construction era
# Units: W/(m²·K)
STANDARD_U_VALUES = {
    "pre_1978": {
        "walls": 1.4,
        "roof": 0.9,
        "floor": 0.8,
        "windows": 2.8,
    },
    "1978_1994": {
        "walls": 0.6,
        "roof": 0.4,
        "floor": 0.5,
        "windows": 2.0,
    },
    "post_1994": {
        "walls": 0.35,
        "roof": 0.25,
        "floor": 0.35,
        "windows": 1.4,
    },
    "post_2009": {
        "walls": 0.28,
        "roof": 0.16,
        "floor": 0.22,
        "windows": 1.3,
    },
    "default": {
        "walls": 0.45,
        "roof": 0.30,
        "floor": 0.40,
        "windows": 1.6,
    },
}

# Typical building geometry ratios for residential properties
# (used when exact dimensions are unavailable)
WALL_AREA_RATIO = 1.3        # wall area / floor area
ROOF_AREA_RATIO = 1.0        # roof area ≈ floor area for single story
WINDOW_TO_WALL_RATIO = 0.15  # 15% of wall area is windows
FLOOR_TO_CEILING_HEIGHT = 2.5  # meters

# DHW sizing: litres per person per day (DIN 4708 / EN 15316-3-1, 60°C supply)
DHW_LITRES_PER_PERSON = 50

# Occupancy estimate: persons per house_size_sqm
OCCUPANCY_PER_SQM = 0.02  # e.g., 120m² → ~2.4 → 3 persons


@dataclass
class HeatLoadResult:
    """Result of DIN EN 12831 simplified calculation."""

    transmission_loss_kw: float
    ventilation_loss_kw: float
    design_heat_load_kw: float
    u_values: dict[str, float]
    design_outdoor_temp_c: float
    design_indoor_temp_c: float


def get_u_values(building_year: int | None = None) -> dict[str, float]:
    """
    Select appropriate standardized U-values based on building construction year.

    Args:
        building_year: Year the building was constructed. None uses defaults.

    Returns:
        Dict with keys: walls, roof, floor, windows — values in W/(m²·K).
    """
    if building_year is None:
        return STANDARD_U_VALUES["default"].copy()
    elif building_year < 1978:
        return STANDARD_U_VALUES["pre_1978"].copy()
    elif building_year < 1994:
        return STANDARD_U_VALUES["1978_1994"].copy()
    elif building_year < 2009:
        return STANDARD_U_VALUES["post_1994"].copy()
    else:
        return STANDARD_U_VALUES["post_2009"].copy()


def calculate_transmission_loss(
    house_size_sqm: float,
    u_values: dict[str, float],
    delta_temp: float,
    num_stories: int = 2,
) -> float:
    """
    Calculate transmission heat loss Φ_T through the building envelope.

    Uses standardized geometry ratios when exact dimensions aren't available.

    Args:
        house_size_sqm: Total heated floor area in m².
        u_values: U-values for walls, roof, floor, windows.
        delta_temp: Temperature difference (θ_int - θ_ext) in K.
        num_stories: Number of building stories.

    Returns:
        Transmission heat loss in kW.
    """
    floor_area_per_story = house_size_sqm / num_stories

    # Estimate component areas
    wall_area = house_size_sqm * WALL_AREA_RATIO
    window_area = wall_area * WINDOW_TO_WALL_RATIO
    net_wall_area = wall_area - window_area
    roof_area = floor_area_per_story * ROOF_AREA_RATIO
    floor_area = floor_area_per_story  # Ground floor only

    # Φ_T = Σ(U_i × A_i) × ΔT
    transmission_loss_w = delta_temp * (
        u_values["walls"] * net_wall_area
        + u_values["windows"] * window_area
        + u_values["roof"] * roof_area
        + u_values["floor"] * floor_area
    )

    return transmission_loss_w / 1000.0  # Convert to kW


def calculate_ventilation_loss(
    house_size_sqm: float,
    delta_temp: float,
    air_change_rate: float = DEFAULT_AIR_CHANGE_RATE,
) -> float:
    """
    Calculate ventilation heat loss Φ_V.

    Φ_V = 0.34 × n × V × ΔT

    Args:
        house_size_sqm: Total heated floor area in m².
        delta_temp: Temperature difference in K.
        air_change_rate: Air changes per hour.

    Returns:
        Ventilation heat loss in kW.
    """
    volume = house_size_sqm * FLOOR_TO_CEILING_HEIGHT
    ventilation_loss_w = AIR_HEAT_CAPACITY * air_change_rate * volume * delta_temp
    return ventilation_loss_w / 1000.0


def calculate_design_heat_load(
    house_size_sqm: float,
    design_outdoor_temp_c: float = -12.0,
    design_indoor_temp_c: float = 20.0,
    building_year: int | None = None,
    safety_factor: float = 1.15,
) -> HeatLoadResult:
    """
    Execute the full DIN EN 12831 simplified heat load calculation.

    Args:
        house_size_sqm: Total heated floor area in m².
        design_outdoor_temp_c: Local winter design temperature in °C.
        design_indoor_temp_c: Target indoor temperature in °C.
        building_year: Year of construction (for U-value selection).
        safety_factor: Safety margin multiplier (typically 1.10–1.15).

    Returns:
        HeatLoadResult with all components and the total design heat load.
    """
    delta_temp = design_indoor_temp_c - design_outdoor_temp_c
    u_values = get_u_values(building_year)

    transmission = calculate_transmission_loss(house_size_sqm, u_values, delta_temp)
    ventilation = calculate_ventilation_loss(house_size_sqm, delta_temp)

    raw_heat_load = transmission + ventilation
    design_heat_load = raw_heat_load * safety_factor

    return HeatLoadResult(
        transmission_loss_kw=round(transmission, 2),
        ventilation_loss_kw=round(ventilation, 2),
        design_heat_load_kw=round(design_heat_load, 2),
        u_values=u_values,
        design_outdoor_temp_c=design_outdoor_temp_c,
        design_indoor_temp_c=design_indoor_temp_c,
    )


def estimate_dhw_requirement(
    house_size_sqm: float,
    num_inhabitants: int | None = None,
) -> tuple[float, int]:
    """
    Estimate domestic hot water (DHW) requirements.

    Args:
        house_size_sqm: Floor area for occupancy estimation.
        num_inhabitants: Number of occupants (estimated if None).

    Returns:
        Tuple of (daily_litres, recommended_cylinder_volume_litres).
    """
    if num_inhabitants is None:
        num_inhabitants = max(1, round(house_size_sqm * OCCUPANCY_PER_SQM))

    daily_litres = num_inhabitants * DHW_LITRES_PER_PERSON

    # Select standard cylinder size
    standard_sizes = [150, 170, 200, 210, 250, 300]
    # Cylinder should hold ~1.5x daily requirement for recovery time
    target = daily_litres * 1.5
    cylinder = min((s for s in standard_sizes if s >= target), default=300)

    return daily_litres, cylinder


def recommend_heat_pump_capacity(
    design_heat_load_kw: float,
) -> float:
    """
    Recommend heat pump capacity based on design heat load.

    For residential, the heat pump should cover 100% of the design
    heat load (monovalent operation is standard for new installs).
    We round up to the nearest standard capacity.

    Returns:
        Recommended heat pump capacity in kW.
    """
    # Standard residential heat pump sizes
    standard_sizes = [4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 25, 30]
    return min((s for s in standard_sizes if s >= design_heat_load_kw), default=30)


def calculate_transmission_loss_from_dimensions(
    wall_area_m2: float,
    u_values: dict[str, float],
    delta_temp: float,
    roof_area_m2: float | None = None,
    floor_area_m2: float | None = None,
) -> float:
    """
    Calculate transmission heat loss using actual building dimensions.

    Used when HouseDimensions are available from the Dimension Estimator.
    Provides more accurate results than the roof-area proxy method.

    Args:
        wall_area_m2:  Estimated total external wall area (m²).
        u_values:      U-values for walls, roof, floor, windows.
        delta_temp:    Temperature difference (θ_int - θ_ext) in K.
        roof_area_m2:  Roof area (m²). Estimated from wall_area if None.
        floor_area_m2: Floor area (m²). Estimated from wall_area if None.

    Returns:
        Transmission heat loss in kW.
    """
    window_area = wall_area_m2 * WINDOW_TO_WALL_RATIO
    net_wall_area = wall_area_m2 - window_area

    # Estimate roof and floor from wall area if not provided
    if roof_area_m2 is None:
        roof_area_m2 = wall_area_m2 * 0.4  # rough ratio for typical house
    if floor_area_m2 is None:
        floor_area_m2 = wall_area_m2 * 0.4

    transmission_loss_w = delta_temp * (
        u_values["walls"] * net_wall_area
        + u_values["windows"] * window_area
        + u_values["roof"] * roof_area_m2
        + u_values["floor"] * floor_area_m2
    )
    return transmission_loss_w / 1000.0


def calculate_ventilation_loss_from_volume(
    volume_m3: float,
    delta_temp: float,
    air_change_rate: float = DEFAULT_AIR_CHANGE_RATE,
) -> float:
    """
    Calculate ventilation heat loss using actual building volume.

    Used when HouseDimensions are available from the Dimension Estimator.

    Args:
        volume_m3:       Estimated building volume (m³).
        delta_temp:      Temperature difference in K.
        air_change_rate: Air changes per hour.

    Returns:
        Ventilation heat loss in kW.
    """
    ventilation_loss_w = AIR_HEAT_CAPACITY * air_change_rate * volume_m3 * delta_temp
    return ventilation_loss_w / 1000.0
