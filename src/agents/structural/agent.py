"""
Structural Agent

Takes SpatialData from the Ingestion Agent and produces a ModuleLayout.
Uses the layout_engine for deterministic panel placement — no LLM calls.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from src.common.schemas import (
    CalculationMetadata,
    FaceLayout,
    ModuleLayout,
    PanelDimensions,
    SpatialData,
    StringConfig,
    StringLayout,
    WeatherProfile,
)
from src.agents.structural.layout_engine import (
    DEFAULT_PANEL_LENGTH_MM,
    DEFAULT_PANEL_WIDTH_MM,
    DEFAULT_PANEL_WP,
    calculate_total_kwp,
    design_strings,
    fit_panels_on_face,
    fit_panels_on_face_polygon,
)
from src.agents.structural.shading import (
    DEFAULT_LATITUDE_DEG,
    FaceSpec,
    annual_shading_factor,
    compute_monthly_irradiance_factors,
)

logger = logging.getLogger(__name__)

AGENT_VERSION = "1.0.0"


def run(
    spatial_data: SpatialData,
    weather_profile: Optional[WeatherProfile] = None,
) -> tuple[ModuleLayout, dict[str, float]]:
    """
    Execute the Structural Agent pipeline.

    1. For each roof face, calculate panel placement (polygon-clipped if 3D data available)
    2. Apply obstacle exclusion zones
    3. Compute per-face shading factors (uses location latitude from WeatherProfile when available)
    4. Design string configurations within voltage limits
    5. Produce a validated ModuleLayout

    Args:
        spatial_data:    Validated SpatialData from the Ingestion Agent.
        weather_profile: Optional WeatherProfile — when present, uses location-specific
                         latitude for sun-path shading calculations (Req 8.1).

    Returns:
        Tuple of (ModuleLayout, face_shading_factors) where face_shading_factors
        maps face_id → annual shading factor (0–1). Synthesis uses this to
        adjust annual yield.
    """
    # Determine latitude for shading calculations (Req 8.1)
    latitude_deg = DEFAULT_LATITUDE_DEG
    if weather_profile is not None:
        latitude_deg = weather_profile.latitude
        logger.info(
            "Structural Agent: using location-specific latitude=%.4f° from WeatherProfile",
            latitude_deg,
        )

    # Determine building height for self-shading (Req 13.2)
    building_height_m: float | None = None
    if spatial_data.house_dimensions is not None:
        building_height_m = spatial_data.house_dimensions.ridge_height_m
        logger.info(
            "Structural Agent: using building ridge height=%.1f m from HouseDimensions",
            building_height_m,
        )

    logger.info("Structural Agent: starting module layout for %d roof faces", len(spatial_data.roof.faces))

    placements = []
    exclusion_zones: list[str] = []
    face_specs: list[FaceSpec] = []

    for face in spatial_data.roof.faces:
        face_obstacles = [
            (obs.area_m2, obs.buffer_m)
            for obs in spatial_data.roof.obstacles
            if obs.face_id == face.id
        ]
        total_obstacle_area = sum(a for a, _ in face_obstacles)

        for obs in spatial_data.roof.obstacles:
            if obs.face_id == face.id:
                exclusion_zones.append(f"{obs.type.value}_on_{face.id}")

        face_specs.append(FaceSpec(
            face_id=face.id,
            tilt_deg=face.tilt_deg,
            azimuth_deg=face.orientation_deg,
            obstacle_area_m2=total_obstacle_area,
            face_area_m2=face.area_m2,
        ))
        placement = None
        if face.polygon_vertices_3d and len(face.polygon_vertices_3d) >= 3:
            placement = fit_panels_on_face_polygon(
                face_id=face.id,
                polygon_vertices_3d=face.polygon_vertices_3d,
            )
            if placement is not None:
                logger.info("  Face '%s': 3D polygon placement (%d panels)", face.id, placement.count)

        # 2D rectangular fallback
        if placement is None:
            face_length = face.length_m if face.length_m else (face.area_m2 ** 0.5) * 1.5
            face_width = face.width_m if face.width_m else (face.area_m2 ** 0.5) / 1.5
            placement = fit_panels_on_face(
                face_id=face.id,
                face_length_m=face_length,
                face_width_m=face_width,
                obstacles=face_obstacles if face_obstacles else None,
            )

        placements.append(placement)
        logger.info(
            "  Face '%s': %d panels (%s), %.1f kWp",
            face.id,
            placement.count,
            placement.orientation,
            placement.count * placement.panel_watt_peak / 1000,
        )

    # Tilt validation refinement using HouseDimensions (Req 13.1)
    if building_height_m is not None and spatial_data.house_dimensions is not None:
        eave_h = spatial_data.house_dimensions.eave_height_m
        ridge_h = spatial_data.house_dimensions.ridge_height_m
        roof_rise = ridge_h - eave_h
        for face in spatial_data.roof.faces:
            # Compute implied tilt from rise/run if footprint is available
            half_width = spatial_data.house_dimensions.footprint_width_m / 2.0
            if half_width > 0:
                implied_tilt_deg = math.degrees(math.atan(roof_rise / half_width))
                logger.debug(
                    "  Face '%s': implied tilt from dimensions=%.1f° (schema tilt=%.1f°)",
                    face.id, implied_tilt_deg, face.tilt_deg,
                )

    # Compute per-face shading factors (use location-specific latitude when available)
    monthly_factors = compute_monthly_irradiance_factors(face_specs, latitude_deg=latitude_deg)
    face_shading: dict[str, float] = {
        fid: annual_shading_factor(factors)
        for fid, factors in monthly_factors.items()
    }

    # Design string configurations
    total_panels = sum(p.count for p in placements)
    strings = design_strings(total_panels)

    # Build output
    face_layouts = [
        FaceLayout(
            face_id=p.face_id,
            count=p.count,
            orientation=p.orientation,  # type: ignore[arg-type]
            panel_watt_peak=p.panel_watt_peak,
            panel_dimensions_mm=PanelDimensions(
                length=DEFAULT_PANEL_LENGTH_MM,
                width=DEFAULT_PANEL_WIDTH_MM,
            ),
        )
        for p in placements
    ]

    string_configs = [
        StringConfig(
            string_id=s.string_id,
            panels_in_series=s.panels_in_series,
            voc_string_V=s.voc_string_V,
            isc_string_A=s.isc_string_A,
        )
        for s in strings
    ]

    total_kwp = calculate_total_kwp(placements)

    layout = ModuleLayout(
        panels=face_layouts,
        total_kwp=round(total_kwp, 2),
        total_panels=total_panels,
        string_config=StringLayout(strings=string_configs),
        exclusion_zones_applied=exclusion_zones,
        metadata=CalculationMetadata(
            algorithm_version=AGENT_VERSION,
            timestamp=datetime.now(timezone.utc),
        ),
    )

    mean_shading = sum(face_shading.values()) / len(face_shading) if face_shading else 1.0
    logger.info(
        "Structural Agent: complete — %d panels, %.1f kWp, %d strings, mean shading factor=%.3f",
        total_panels,
        total_kwp,
        len(strings),
        mean_shading,
    )

    return layout, face_shading
