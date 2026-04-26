"""
Property-based tests for dimension-aware heat load calculation.

Feature: weather-intelligence-house-dimensions
Property 9: Dimension-aware heat load calculation

Verifies that when HouseDimensions are available, the thermodynamic agent's
heat load calculation uses estimated_wall_area_m2 for transmission loss and
estimated_volume_m3 for ventilation loss — not the roof-area proxy.

Validates: Requirements 12.1, 12.2
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.agents.thermodynamic import din_en_12831
from src.agents.thermodynamic.din_en_12831 import (
    AIR_HEAT_CAPACITY,
    DEFAULT_AIR_CHANGE_RATE,
    WINDOW_TO_WALL_RATIO,
    calculate_transmission_loss_from_dimensions,
    calculate_ventilation_loss_from_volume,
    get_u_values,
)
from src.common.schemas import DimensionConfidence, HouseDimensions


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------


@st.composite
def valid_house_dimensions(draw: st.DrawFn) -> HouseDimensions:
    """Generate random valid HouseDimensions within schema constraints."""
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


@st.composite
def design_temperatures(draw: st.DrawFn) -> tuple[float, float]:
    """Generate (outdoor_temp, indoor_temp) pairs where indoor > outdoor."""
    outdoor = draw(st.floats(min_value=-25.0, max_value=10.0, allow_nan=False))
    indoor = draw(st.floats(min_value=15.0, max_value=25.0, allow_nan=False))
    return outdoor, indoor


# ---------------------------------------------------------------------------
# Property 9: Dimension-aware heat load calculation
# Feature: weather-intelligence-house-dimensions, Property 9
# ---------------------------------------------------------------------------


@given(dims=valid_house_dimensions(), temps=design_temperatures())
@settings(max_examples=200)
def test_transmission_loss_uses_wall_area(
    dims: HouseDimensions, temps: tuple[float, float]
) -> None:
    """
    Property 9a: Transmission loss is computed from estimated_wall_area_m2.

    calculate_transmission_loss_from_dimensions() must produce a result
    that is a deterministic function of wall_area_m2 and delta_temp —
    not of any roof-area proxy derived from house_size_sqm.

    Validates: Requirements 12.1
    """
    outdoor_temp, indoor_temp = temps
    delta_temp = indoor_temp - outdoor_temp
    u_values = get_u_values(building_year=None)

    result = calculate_transmission_loss_from_dimensions(
        wall_area_m2=dims.estimated_wall_area_m2,
        u_values=u_values,
        delta_temp=delta_temp,
    )

    # Manually reproduce the expected formula:
    # window_area = wall_area * WINDOW_TO_WALL_RATIO
    # net_wall_area = wall_area - window_area
    # roof_area_m2 = wall_area * 0.4  (default estimate)
    # floor_area_m2 = wall_area * 0.4  (default estimate)
    # Φ_T = delta_temp * (U_walls * net_wall + U_windows * window + U_roof * roof + U_floor * floor)
    wall_area = dims.estimated_wall_area_m2
    window_area = wall_area * WINDOW_TO_WALL_RATIO
    net_wall_area = wall_area - window_area
    roof_area = wall_area * 0.4
    floor_area = wall_area * 0.4

    expected_w = delta_temp * (
        u_values["walls"] * net_wall_area
        + u_values["windows"] * window_area
        + u_values["roof"] * roof_area
        + u_values["floor"] * floor_area
    )
    expected_kw = expected_w / 1000.0

    assert abs(result - expected_kw) < 1e-9, (
        f"Transmission loss mismatch: got {result:.6f} kW, expected {expected_kw:.6f} kW "
        f"(wall_area={wall_area}, delta_temp={delta_temp})"
    )


@given(dims=valid_house_dimensions(), temps=design_temperatures())
@settings(max_examples=200)
def test_ventilation_loss_uses_volume(
    dims: HouseDimensions, temps: tuple[float, float]
) -> None:
    """
    Property 9b: Ventilation loss is computed from estimated_volume_m3.

    calculate_ventilation_loss_from_volume() must produce a result that is
    a deterministic function of volume_m3 and delta_temp — not of any
    floor-area-derived volume proxy.

    Validates: Requirements 12.2
    """
    outdoor_temp, indoor_temp = temps
    delta_temp = indoor_temp - outdoor_temp

    result = calculate_ventilation_loss_from_volume(
        volume_m3=dims.estimated_volume_m3,
        delta_temp=delta_temp,
    )

    # Manually reproduce the expected formula:
    # Φ_V = AIR_HEAT_CAPACITY * air_change_rate * volume_m3 * delta_temp
    expected_w = AIR_HEAT_CAPACITY * DEFAULT_AIR_CHANGE_RATE * dims.estimated_volume_m3 * delta_temp
    expected_kw = expected_w / 1000.0

    assert abs(result - expected_kw) < 1e-9, (
        f"Ventilation loss mismatch: got {result:.6f} kW, expected {expected_kw:.6f} kW "
        f"(volume={dims.estimated_volume_m3}, delta_temp={delta_temp})"
    )


@given(dims=valid_house_dimensions(), temps=design_temperatures())
@settings(max_examples=200)
def test_dimension_aware_differs_from_proxy(
    dims: HouseDimensions, temps: tuple[float, float]
) -> None:
    """
    Property 9c: Dimension-aware ventilation loss differs from the roof-area proxy.

    When HouseDimensions are available, the ventilation loss must use
    estimated_volume_m3 directly. The proxy method derives volume from
    house_size_sqm * FLOOR_TO_CEILING_HEIGHT. These two paths must produce
    different results whenever the actual volume differs from the proxy volume,
    confirming the dimension-aware path is not silently falling back to the proxy.

    Validates: Requirements 12.1, 12.2
    """
    outdoor_temp, indoor_temp = temps
    delta_temp = indoor_temp - outdoor_temp

    # Dimension-aware path: uses actual volume
    ventilation_dims = calculate_ventilation_loss_from_volume(
        volume_m3=dims.estimated_volume_m3,
        delta_temp=delta_temp,
    )

    # Proxy path: derives volume from floor area * ceiling height
    proxy_floor_area = dims.footprint_width_m * dims.footprint_depth_m
    proxy_volume = proxy_floor_area * din_en_12831.FLOOR_TO_CEILING_HEIGHT
    ventilation_proxy = din_en_12831.calculate_ventilation_loss(
        house_size_sqm=proxy_floor_area,
        delta_temp=delta_temp,
    )

    # When volumes differ, losses must differ proportionally
    if abs(dims.estimated_volume_m3 - proxy_volume) > 1e-6:
        assert abs(ventilation_dims - ventilation_proxy) > 1e-9, (
            f"Expected different ventilation losses when actual volume "
            f"({dims.estimated_volume_m3:.2f} m³) differs from proxy volume "
            f"({proxy_volume:.2f} m³), but both gave {ventilation_dims:.6f} kW"
        )
    else:
        # Volumes are effectively equal — losses should match
        assert abs(ventilation_dims - ventilation_proxy) < 1e-6


@given(dims=valid_house_dimensions(), temps=design_temperatures())
@settings(max_examples=200)
def test_heat_load_scales_with_wall_area(
    dims: HouseDimensions, temps: tuple[float, float]
) -> None:
    """
    Property 9d: Transmission loss scales linearly with wall area.

    Doubling estimated_wall_area_m2 must double the transmission loss,
    confirming the calculation is driven by the actual wall area and not
    a fixed proxy.

    Validates: Requirements 12.1
    """
    outdoor_temp, indoor_temp = temps
    delta_temp = indoor_temp - outdoor_temp
    u_values = get_u_values(building_year=None)

    loss_base = calculate_transmission_loss_from_dimensions(
        wall_area_m2=dims.estimated_wall_area_m2,
        u_values=u_values,
        delta_temp=delta_temp,
    )

    # Double the wall area — loss must also double (linear relationship)
    loss_doubled = calculate_transmission_loss_from_dimensions(
        wall_area_m2=dims.estimated_wall_area_m2 * 2.0,
        u_values=u_values,
        delta_temp=delta_temp,
    )

    assert abs(loss_doubled - loss_base * 2.0) < 1e-9, (
        f"Transmission loss is not linear in wall_area: "
        f"base={loss_base:.6f} kW, doubled={loss_doubled:.6f} kW "
        f"(expected {loss_base * 2.0:.6f} kW)"
    )


@given(dims=valid_house_dimensions(), temps=design_temperatures())
@settings(max_examples=200)
def test_heat_load_scales_with_volume(
    dims: HouseDimensions, temps: tuple[float, float]
) -> None:
    """
    Property 9e: Ventilation loss scales linearly with building volume.

    Doubling estimated_volume_m3 must double the ventilation loss,
    confirming the calculation is driven by the actual volume and not
    a fixed proxy.

    Validates: Requirements 12.2
    """
    outdoor_temp, indoor_temp = temps
    delta_temp = indoor_temp - outdoor_temp

    loss_base = calculate_ventilation_loss_from_volume(
        volume_m3=dims.estimated_volume_m3,
        delta_temp=delta_temp,
    )

    loss_doubled = calculate_ventilation_loss_from_volume(
        volume_m3=dims.estimated_volume_m3 * 2.0,
        delta_temp=delta_temp,
    )

    assert abs(loss_doubled - loss_base * 2.0) < 1e-9, (
        f"Ventilation loss is not linear in volume: "
        f"base={loss_base:.6f} kW, doubled={loss_doubled:.6f} kW "
        f"(expected {loss_base * 2.0:.6f} kW)"
    )
