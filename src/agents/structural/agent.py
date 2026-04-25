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
)

logger = logging.getLogger(__name__)

AGENT_VERSION = "1.0.0"


def run(spatial_data: SpatialData) -> ModuleLayout:
    """
    Execute the Structural Agent pipeline.

    1. For each roof face, calculate panel placement
    2. Apply obstacle exclusion zones
    3. Design string configurations within voltage limits
    4. Produce a validated ModuleLayout

    Args:
        spatial_data: Validated SpatialData from the Ingestion Agent.

    Returns:
        ModuleLayout ready for validation by the Safety Agent.
    """
    logger.info("Structural Agent: starting module layout for %d roof faces", len(spatial_data.roof.faces))

    placements = []
    exclusion_zones: list[str] = []

    for face in spatial_data.roof.faces:
        # Calculate obstacle area for this face
        face_obstacles_area = sum(
            obs.area_m2 + (obs.buffer_m * 2 * (obs.area_m2 ** 0.5))  # Buffer approximation
            for obs in spatial_data.roof.obstacles
            if obs.face_id == face.id
        )

        # Track which exclusion zones were applied
        for obs in spatial_data.roof.obstacles:
            if obs.face_id == face.id:
                exclusion_zones.append(f"{obs.type.value}_on_{face.id}")

        # Use face dimensions if available, otherwise estimate from area
        face_length = face.length_m if face.length_m else (face.area_m2 ** 0.5) * 1.5
        face_width = face.width_m if face.width_m else (face.area_m2 ** 0.5) / 1.5

        placement = fit_panels_on_face(
            face_id=face.id,
            face_length_m=face_length,
            face_width_m=face_width,
            obstacles_area_m2=face_obstacles_area,
        )

        placements.append(placement)
        logger.info(
            "  Face '%s': %d panels (%s), %.1f kWp",
            face.id,
            placement.count,
            placement.orientation,
            placement.count * placement.panel_watt_peak / 1000,
        )

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

    logger.info(
        "Structural Agent: complete — %d panels, %.1f kWp, %d strings",
        total_panels,
        total_kwp,
        len(strings),
    )

    return layout
