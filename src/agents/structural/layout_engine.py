"""
Structural Agent — Module Layout Engine

Pure algorithmic module for solar panel placement on residential roofs.
No LLM dependency — this is deterministic geometry.

Implements:
  - Rectangular bin-packing on roof face polygons (2D path)
  - Polygon-clipped panel placement via Sutherland-Hodgman (3D path)
  - Exclusion zone buffers (obstacles, fire code edge setbacks)
  - Orientation optimization (portrait vs landscape)
  - String sizing (series configuration within voltage limits)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

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


# ---------------------------------------------------------------------------
# Polygon-clipped placement (3D path — Sutherland-Hodgman)
# ---------------------------------------------------------------------------

def _sutherland_hodgman(
    subject: list[tuple[float, float]],
    clip: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Clip a convex polygon (subject) against another convex polygon (clip)."""

    def _inside(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> bool:
        return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0

    def _intersect(
        p1: tuple[float, float], p2: tuple[float, float],
        p3: tuple[float, float], p4: tuple[float, float],
    ) -> tuple[float, float]:
        x1, y1 = p1; x2, y2 = p2; x3, y3 = p3; x4, y4 = p4
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) < 1e-12:
            return p2
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))

    output = list(subject)
    if not output:
        return output

    for i in range(len(clip)):
        if not output:
            break
        inp = output
        output = []
        a = clip[i]
        b = clip[(i + 1) % len(clip)]
        for j in range(len(inp)):
            curr = inp[j]
            prev = inp[j - 1]
            if _inside(curr, a, b):
                if not _inside(prev, a, b):
                    output.append(_intersect(prev, curr, a, b))
                output.append(curr)
            elif _inside(prev, a, b):
                output.append(_intersect(prev, curr, a, b))
    return output


def _polygon_area_2d(pts: list[tuple[float, float]]) -> float:
    """Shoelace formula."""
    n = len(pts)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _project_vertices_to_2d(
    vertices_3d: list[list[float]],
) -> list[tuple[float, float]]:
    """Project 3D face polygon vertices to 2D (X-Y plane of the face)."""
    import numpy as np  # type: ignore[import]

    if len(vertices_3d) < 3:
        return []

    pts = [np.array(v[:3], dtype=float) for v in vertices_3d]
    origin = pts[0]
    # Build local axes from first two edges
    u = pts[1] - origin
    u_len = float(np.linalg.norm(u))
    if u_len < 1e-9:
        return []
    u = u / u_len

    # Normal from cross product
    for p in pts[2:]:
        n_candidate = np.cross(u, p - origin)
        if float(np.linalg.norm(n_candidate)) > 1e-9:
            n = n_candidate / float(np.linalg.norm(n_candidate))
            break
    else:
        return []

    v = np.cross(n, u)
    v = v / (float(np.linalg.norm(v)) + 1e-12)

    return [(float(np.dot(p - origin, u)), float(np.dot(p - origin, v))) for p in pts]


def fit_panels_on_face_polygon(
    face_id: str,
    polygon_vertices_3d: list[list[float]],
    panel_length_mm: int = DEFAULT_PANEL_LENGTH_MM,
    panel_width_mm: int = DEFAULT_PANEL_WIDTH_MM,
    panel_wp: int = DEFAULT_PANEL_WP,
    setback_m: float = EDGE_SETBACK_M,
    inter_panel_gap_mm: int = 20,
) -> Optional[PanelPlacement]:
    """
    Fit panels onto a face defined by 3D polygon vertices using Sutherland-Hodgman clipping.

    Projects the face polygon to 2D, shrinks it by setback, then tiles panels in a grid
    and clips each panel cell against the face boundary. Returns None if projection fails;
    caller should fall back to fit_panels_on_face.
    """
    try:
        poly_2d = _project_vertices_to_2d(polygon_vertices_3d)
    except Exception:
        return None

    if len(poly_2d) < 3:
        return None

    # Shrink polygon by setback using centroid-based scaling
    cx = sum(p[0] for p in poly_2d) / len(poly_2d)
    cy = sum(p[1] for p in poly_2d) / len(poly_2d)
    # Compute approx inset by scaling toward centroid
    face_area = _polygon_area_2d(poly_2d)
    if face_area < 0.5:
        return None

    # Estimate scale factor for setback (simple approximation)
    perimeter = sum(
        math.hypot(poly_2d[(i + 1) % len(poly_2d)][0] - poly_2d[i][0],
                   poly_2d[(i + 1) % len(poly_2d)][1] - poly_2d[i][1])
        for i in range(len(poly_2d))
    )
    inset_ratio = max(0.0, 1.0 - setback_m * perimeter / (2 * face_area + 1e-9))
    clipped_poly = [(cx + (p[0] - cx) * inset_ratio, cy + (p[1] - cy) * inset_ratio)
                    for p in poly_2d]
    clipped_area = _polygon_area_2d(clipped_poly)

    p_len_m = panel_length_mm / 1000.0
    p_wid_m = panel_width_mm / 1000.0
    gap_m = inter_panel_gap_mm / 1000.0

    best_count = 0
    best_orientation = "portrait"

    for orientation, dim_l, dim_w in [
        ("portrait", p_len_m, p_wid_m),
        ("landscape", p_wid_m, p_len_m),
    ]:
        cell_area = (dim_l + gap_m) * (dim_w + gap_m)
        if cell_area <= 0:
            continue

        # Bounding box of the clipped polygon
        xs = [p[0] for p in clipped_poly]
        ys = [p[1] for p in clipped_poly]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        count = 0
        y = min_y
        while y + dim_w <= max_y + 1e-6:
            x = min_x
            while x + dim_l <= max_x + 1e-6:
                # Panel cell as polygon
                panel_poly = [
                    (x, y), (x + dim_l, y),
                    (x + dim_l, y + dim_w), (x, y + dim_w),
                ]
                intersected = _sutherland_hodgman(panel_poly, clipped_poly)
                if _polygon_area_2d(intersected) >= 0.8 * dim_l * dim_w:
                    count += 1
                x += dim_l + gap_m
            y += dim_w + gap_m

        if count > best_count:
            best_count = count
            best_orientation = orientation

    # Compute rows/cols for the best orientation
    p_len_m_best = p_len_m if best_orientation == "portrait" else p_wid_m
    p_wid_m_best = p_wid_m if best_orientation == "portrait" else p_len_m
    xs = [p[0] for p in clipped_poly]
    ys = [p[1] for p in clipped_poly]
    cols = max(1, int((max(xs) - min(xs) + gap_m) / (p_len_m_best + gap_m)))
    rows = max(1, int((max(ys) - min(ys) + gap_m) / (p_wid_m_best + gap_m)))

    return PanelPlacement(
        face_id=face_id,
        count=best_count,
        orientation=best_orientation,
        panel_watt_peak=panel_wp,
        rows=rows,
        cols=cols,
    )
