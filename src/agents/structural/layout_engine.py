"""
Structural Agent — Module Layout Engine

Pure algorithmic module for solar panel placement on residential roofs.
No LLM dependency — this is deterministic geometry.

Implements:
  - Rectangular bin-packing on roof face polygons
  - Exclusion zone buffers (obstacles, fire code edge setbacks)
  - Orientation optimization (portrait vs landscape)
  - String sizing (series configuration within voltage limits)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Residential DC voltage limit per CLAUDE.md guardrails
MAX_STRING_VOC_V = 1000

# Fire code edge setback (meters from roof edge)
EDGE_SETBACK_M = 0.5

# Standard panel specifications (reference: JA Solar JAM54S30 series)
DEFAULT_PANEL_LENGTH_MM = 1722
DEFAULT_PANEL_WIDTH_MM = 1134
DEFAULT_PANEL_WP = 400
# Voc at STC for a typical 400W mono panel
DEFAULT_VOC_PER_PANEL_V = 37.2


@dataclass
class PanelPlacement:
    """Result of panel placement on a single roof face."""

    face_id: str
    count: int
    orientation: str  # "portrait" or "landscape"
    panel_watt_peak: int
    rows: int
    cols: int


@dataclass
class StringResult:
    """A string of panels wired in series."""

    string_id: str
    panels_in_series: int
    voc_string_V: float
    isc_string_A: float


def calculate_usable_dimensions(
    face_length_m: float,
    face_width_m: float,
    obstacles_area_m2: float,
    setback_m: float = EDGE_SETBACK_M,
) -> tuple[float, float, float]:
    """
    Calculate usable roof dimensions after setbacks and obstacle deductions.

    Returns:
        Tuple of (usable_length_m, usable_width_m, usable_area_m2)
    """
    usable_length = max(0, face_length_m - 2 * setback_m)
    usable_width = max(0, face_width_m - 2 * setback_m)
    usable_area = max(0, usable_length * usable_width - obstacles_area_m2)
    return usable_length, usable_width, usable_area


def _grid_cells_blocked_by_obstacle(
    obs_area_m2: float,
    obs_buffer_m: float,
    cell_along_length_m: float,
    cell_along_width_m: float,
    gap_m: float,
    max_cols: int,
    max_rows: int,
) -> int:
    """
    Rectangle-clip: compute how many panel grid cells are blocked by one obstacle.

    Treats each obstacle as a square of side sqrt(area_m2), expands it by
    buffer_m on all sides, then counts how many panel slots (cols × rows) that
    expanded rectangle covers.
    """
    obs_side = math.sqrt(obs_area_m2)
    blocked = obs_side + 2 * obs_buffer_m
    cols_blocked = math.ceil(blocked / (cell_along_length_m + gap_m))
    rows_blocked = math.ceil(blocked / (cell_along_width_m + gap_m))
    return min(cols_blocked * rows_blocked, max_cols * max_rows)


def fit_panels_on_face(
    face_id: str,
    face_length_m: float,
    face_width_m: float,
    obstacles: list[tuple[float, float]] | None = None,
    panel_length_mm: int = DEFAULT_PANEL_LENGTH_MM,
    panel_width_mm: int = DEFAULT_PANEL_WIDTH_MM,
    panel_wp: int = DEFAULT_PANEL_WP,
    setback_m: float = EDGE_SETBACK_M,
    inter_panel_gap_mm: int = 20,
) -> PanelPlacement:
    """
    Fit as many panels as possible on a roof face using rectangular bin-packing.

    Tries both portrait and landscape orientations and picks the one that
    yields the maximum number of panels.

    Args:
        face_id: Identifier for the roof face.
        face_length_m: Length of the roof face in meters.
        face_width_m: Width of the roof face in meters.
        obstacles: Per-obstacle list of (area_m2, buffer_m) tuples. Each
            obstacle is clipped as a rectangle from the panel grid.
        panel_length_mm: Panel length in millimeters.
        panel_width_mm: Panel width in millimeters.
        panel_wp: Panel watt-peak rating.
        setback_m: Fire code edge setback in meters.
        inter_panel_gap_mm: Gap between panels in mm.

    Returns:
        PanelPlacement with the optimal orientation and count.
    """
    usable_length, usable_width, _ = calculate_usable_dimensions(
        face_length_m, face_width_m, 0.0, setback_m
    )

    # Convert panel dimensions to meters
    p_len_m = panel_length_mm / 1000.0
    p_wid_m = panel_width_mm / 1000.0
    gap_m = inter_panel_gap_mm / 1000.0

    best_placement = PanelPlacement(
        face_id=face_id,
        count=0,
        orientation="portrait",
        panel_watt_peak=panel_wp,
        rows=0,
        cols=0,
    )

    for orientation, dim_along_length, dim_along_width in [
        ("portrait", p_len_m, p_wid_m),
        ("landscape", p_wid_m, p_len_m),
    ]:
        if usable_length <= 0 or usable_width <= 0:
            continue

        cols = int((usable_length + gap_m) / (dim_along_length + gap_m))
        rows = int((usable_width + gap_m) / (dim_along_width + gap_m))
        count = rows * cols

        # Rectangle-clip: subtract grid cells blocked by each obstacle
        if obstacles:
            for obs_area, obs_buffer in obstacles:
                cells_lost = _grid_cells_blocked_by_obstacle(
                    obs_area, obs_buffer,
                    dim_along_length, dim_along_width,
                    gap_m, cols, rows,
                )
                count = max(0, count - cells_lost)

        if count > best_placement.count:
            best_placement = PanelPlacement(
                face_id=face_id,
                count=count,
                orientation=orientation,
                panel_watt_peak=panel_wp,
                rows=rows,
                cols=cols,
            )

    return best_placement


def design_strings(
    total_panels: int,
    voc_per_panel_V: float = DEFAULT_VOC_PER_PANEL_V,
    isc_per_panel_A: float = 11.48,
    max_string_voc_V: float = MAX_STRING_VOC_V,
) -> list[StringResult]:
    """
    Design string configurations that stay within voltage limits.

    Maximizes panels per string while keeping Voc under the residential
    1000V DC limit.

    Args:
        total_panels: Total number of panels to wire.
        voc_per_panel_V: Open-circuit voltage per panel at STC.
        isc_per_panel_A: Short-circuit current per panel at STC.
        max_string_voc_V: Maximum allowed string voltage.

    Returns:
        List of StringResult configurations.
    """
    if total_panels == 0:
        return []

    # Max panels per string, respecting voltage limit
    max_per_string = int(max_string_voc_V / voc_per_panel_V)
    if max_per_string == 0:
        max_per_string = 1

    strings: list[StringResult] = []
    remaining = total_panels
    string_num = 1

    while remaining > 0:
        panels_in_string = min(remaining, max_per_string)
        strings.append(
            StringResult(
                string_id=f"S{string_num}",
                panels_in_series=panels_in_string,
                voc_string_V=round(panels_in_string * voc_per_panel_V, 1),
                isc_string_A=round(isc_per_panel_A, 2),
            )
        )
        remaining -= panels_in_string
        string_num += 1

    return strings


def calculate_total_kwp(placements: list[PanelPlacement]) -> float:
    """Calculate total system kWp from all face placements."""
    return sum(p.count * p.panel_watt_peak / 1000.0 for p in placements)
