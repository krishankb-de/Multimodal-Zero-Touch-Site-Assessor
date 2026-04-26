"""
Structural Agent

Takes SpatialData from the Ingestion Agent and produces a ModuleLayout.
Uses the layout_engine for deterministic panel placement — no LLM calls.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.common.schemas import (
    CalculationMetadata,
    FaceLayout,
    ModuleLayout,
    PanelDimensions,
    SpatialData,
    StringConfig,
    StringLayout,
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
    FaceSpec,
    annual_shading_factor,
    compute_monthly_irradiance_factors,
)

logger = logging.getLogger(__name__)

AGENT_VERSION = "1.0.0"


def run(spatial_data: SpatialData) -> tuple[ModuleLayout, dict[str, float]]:
    """
    Execute the Structural Agent pipeline.

    1. For each roof face, calculate panel placement (polygon-clipped if 3D data available)
    2. Apply obstacle exclusion zones
    3. Compute per-face shading factors
    4. Design string configurations within voltage limits
    5. Produce a validated ModuleLayout

    Args:
        spatial_data: Validated SpatialData from the Ingestion Agent.

    Returns:
        Tuple of (ModuleLayout, face_shading_factors) where face_shading_factors
        maps face_id → annual shading factor (0–1). Synthesis uses this to
        adjust annual yield.
    """
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

        # 3D polygon path — use Sutherland-Hodgman clipping when vertices available
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

    # Compute per-face shading factors
    monthly_factors = compute_monthly_irradiance_factors(face_specs)
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
