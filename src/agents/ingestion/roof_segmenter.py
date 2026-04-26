"""
RANSAC plane fitting on a trimesh mesh to segment roof faces.

Matches each detected plane to a vision-extracted face via azimuth/tilt similarity.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_DEG = math.pi / 180


@dataclass
class RoofFacePolygon3D:
    face_id: str
    vertices: list[list[float]]  # [[x,y,z], ...]
    normal: list[float]           # unit normal [nx, ny, nz]
    azimuth_deg: float
    tilt_deg: float


def _normal_to_azimuth_tilt(normal: np.ndarray) -> tuple[float, float]:
    """Convert a plane unit normal to azimuth (0=N,90=E) and tilt (from horizontal)."""
    nx, ny, nz = float(normal[0]), float(normal[1]), float(normal[2])
    # tilt: angle between normal and vertical
    tilt = math.degrees(math.acos(max(-1.0, min(1.0, abs(nz)))))
    # azimuth: project horizontal component onto N/E axes
    azimuth = math.degrees(math.atan2(nx, ny)) % 360
    return azimuth, tilt


def _ransac_plane(
    points: np.ndarray,
    n_iterations: int = 100,
    threshold: float = 0.05,
) -> tuple[np.ndarray, np.ndarray]:
    """Minimal RANSAC plane fit. Returns (normal, inlier_mask)."""
    best_normal = np.array([0.0, 0.0, 1.0])
    best_mask = np.zeros(len(points), dtype=bool)

    rng = np.random.default_rng(42)
    for _ in range(n_iterations):
        if len(points) < 3:
            break
        idx = rng.choice(len(points), 3, replace=False)
        p0, p1, p2 = points[idx]
        v1 = p1 - p0
        v2 = p2 - p0
        normal = np.cross(v1, v2)
        norm = np.linalg.norm(normal)
        if norm < 1e-9:
            continue
        normal = normal / norm
        d = -np.dot(normal, p0)
        dist = np.abs(points @ normal + d)
        mask = dist < threshold
        if mask.sum() > best_mask.sum():
            best_normal = normal
            best_mask = mask

    return best_normal, best_mask


def segment_roof_faces(
    mesh_path: Path,
    vision_faces: list[dict],
    max_planes: int = 8,
) -> list[RoofFacePolygon3D]:
    """
    Load mesh, fit RANSAC planes, match to vision faces by azimuth/tilt.

    vision_faces: list of dicts with keys id, orientation_deg, tilt_deg
    Returns list of RoofFacePolygon3D matched to vision faces.
    """
    try:
        import trimesh  # type: ignore[import]
    except ImportError:
        logger.warning("trimesh not installed — skipping roof segmentation")
        return []

    try:
        mesh = trimesh.load(str(mesh_path), force="mesh")
    except Exception as exc:
        logger.warning("Failed to load mesh %s: %s", mesh_path, exc)
        return []

    if not hasattr(mesh, "vertices") or len(mesh.vertices) < 4:
        # Point cloud — use points directly
        if hasattr(mesh, "vertices"):
            points = np.array(mesh.vertices)
        else:
            logger.warning("Mesh has no vertices — skipping segmentation")
            return []
    else:
        points = np.array(mesh.vertices)

    planes: list[tuple[np.ndarray, np.ndarray]] = []
    remaining = np.ones(len(points), dtype=bool)

    for _ in range(max_planes):
        active_pts = points[remaining]
        if len(active_pts) < 10:
            break
        normal, inlier_mask_local = _ransac_plane(active_pts)
        if inlier_mask_local.sum() < 4:
            break
        inlier_pts = active_pts[inlier_mask_local]
        planes.append((normal, inlier_pts))
        # Remove inliers from remaining
        active_indices = np.where(remaining)[0]
        remaining[active_indices[inlier_mask_local]] = False

    results: list[RoofFacePolygon3D] = []
    for normal, inlier_pts in planes:
        azimuth, tilt = _normal_to_azimuth_tilt(normal)
        matched_id = _match_vision_face(azimuth, tilt, vision_faces)
        convex_verts = _convex_hull_2d_projected(inlier_pts, normal)
        results.append(
            RoofFacePolygon3D(
                face_id=matched_id or f"plane_{len(results)}",
                vertices=convex_verts,
                normal=normal.tolist(),
                azimuth_deg=azimuth,
                tilt_deg=tilt,
            )
        )

    return results


def _match_vision_face(
    azimuth: float,
    tilt: float,
    vision_faces: list[dict],
    azimuth_tol: float = 45.0,
    tilt_tol: float = 20.0,
) -> Optional[str]:
    best_id: Optional[str] = None
    best_score = float("inf")
    for face in vision_faces:
        az_diff = abs((azimuth - face.get("orientation_deg", 0)) % 360)
        if az_diff > 180:
            az_diff = 360 - az_diff
        tilt_diff = abs(tilt - face.get("tilt_deg", 0))
        if az_diff <= azimuth_tol and tilt_diff <= tilt_tol:
            score = az_diff + tilt_diff
            if score < best_score:
                best_score = score
                best_id = face.get("id")
    return best_id


def _convex_hull_2d_projected(points: np.ndarray, normal: np.ndarray) -> list[list[float]]:
    """Project inlier points onto the plane and return convex hull vertices in 3D."""
    try:
        from scipy.spatial import ConvexHull  # type: ignore[import]

        # Build local 2D axes on the plane
        ref = np.array([1.0, 0.0, 0.0])
        if abs(np.dot(normal, ref)) > 0.9:
            ref = np.array([0.0, 1.0, 0.0])
        u = np.cross(normal, ref)
        u /= np.linalg.norm(u)
        v = np.cross(normal, u)

        coords_2d = np.column_stack([points @ u, points @ v])
        hull = ConvexHull(coords_2d)
        hull_pts = points[hull.vertices]
        return hull_pts.tolist()
    except Exception:
        # Fall back to bounding box corners
        return points[[0, -1]].tolist()
