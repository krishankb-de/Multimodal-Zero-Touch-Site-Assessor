"""
Tiered 3D roof mesh reconstruction.

Tier 1: Structure-from-Motion via pycolmap (optional dep)
Tier 2: Pioneer SLM geometric inference (stub until confirmed)
Tier 3: Gemini multi-frame depth + geometry
Tier 4: Silent 2D-only fallback — returns None
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.common.artifact_store import (
    mesh_path,
    point_cloud_path,
    reconstruction_json_path,
    run_dir,
)
from src.common.config import config

logger = logging.getLogger(__name__)


@dataclass
class ReconstructionResult:
    mesh_uri: str
    point_cloud_uri: Optional[str]
    tier: int
    runtime_s: float
    confidence: float
    cameras_json_uri: Optional[str] = None


# ---------------------------------------------------------------------------
# Tier 1 — pycolmap SfM
# ---------------------------------------------------------------------------

def _try_sfm(frames_dir: Path, run_id: str, budget_s: int) -> Optional[ReconstructionResult]:
    try:
        import pycolmap  # type: ignore[import]
    except ImportError:
        logger.debug("pycolmap not installed — skipping Tier 1")
        return None

    import tempfile
    import threading

    result_holder: list[Optional[ReconstructionResult]] = [None]
    exc_holder: list[Optional[Exception]] = [None]

    def _run() -> None:
        try:
            t0 = time.monotonic()
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                db_path = tmp / "colmap.db"
                sparse_path = tmp / "sparse"
                sparse_path.mkdir()

                pycolmap.extract_features(
                    database_path=db_path,
                    image_path=frames_dir,
                )
                pycolmap.match_exhaustive(database_path=db_path)
                maps = pycolmap.incremental_mapping(
                    database_path=db_path,
                    image_path=frames_dir,
                    output_path=sparse_path,
                )

                if not maps:
                    exc_holder[0] = RuntimeError("SfM produced no reconstruction")
                    return

                reconstruction = maps[0]

                # Export point cloud as PLY
                ply_out = point_cloud_path(run_id)
                reconstruction.export_PLY(str(ply_out))

                # Build a minimal GLB from the sparse points using trimesh
                try:
                    import numpy as np
                    import trimesh  # type: ignore[import]

                    pts = np.array([[p.xyz[0], p.xyz[1], p.xyz[2]] for p in reconstruction.points3D.values()])
                    cloud = trimesh.PointCloud(pts)
                    glb_out = mesh_path(run_id)
                    cloud.export(str(glb_out))
                except Exception as te:
                    logger.warning("Tier 1: trimesh export failed (%s) — no GLB", te)
                    glb_out = None

                runtime = time.monotonic() - t0
                result_holder[0] = ReconstructionResult(
                    mesh_uri=str(glb_out) if glb_out and glb_out.exists() else "",
                    point_cloud_uri=str(ply_out) if ply_out.exists() else None,
                    tier=1,
                    runtime_s=runtime,
                    confidence=0.85,
                )
        except Exception as exc:
            exc_holder[0] = exc

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=budget_s)

    if t.is_alive():
        logger.warning("Tier 1 SfM exceeded budget (%ds) — aborting", budget_s)
        return None
    if exc_holder[0]:
        logger.warning("Tier 1 SfM failed: %s", exc_holder[0])
        return None
    return result_holder[0]


# ---------------------------------------------------------------------------
# Tier 2 — Pioneer geometric inference (stub)
# ---------------------------------------------------------------------------

async def _try_pioneer(frames: list[Path], spatial_data_dict: dict) -> Optional[ReconstructionResult]:
    from src.common.vision_provider import NotSupported, PioneerVisionAdapter
    try:
        adapter = PioneerVisionAdapter()
        prompt = (
            "Given these roofline keyframes and the 2D spatial data below, "
            "estimate per-face 3D polygon vertices (metric coords, origin at centroid). "
            "Return JSON with key 'faces_3d': [{face_id, vertices_3d: [[x,y,z],...]}].\n"
            f"SpatialData: {json.dumps(spatial_data_dict)}"
        )
        await adapter.analyze_frames(frames, prompt)
        # Pioneer is a stub — NotSupported is always raised
    except NotSupported:
        logger.debug("Tier 2: Pioneer not supported — skipping")
    except Exception as exc:
        logger.warning("Tier 2: Pioneer failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Tier 3 — Gemini multi-frame depth
# ---------------------------------------------------------------------------

async def _try_gemini_depth(frames: list[Path], run_id: str) -> Optional[ReconstructionResult]:
    try:
        from src.common.vision_provider import GeminiVisionAdapter
        import numpy as np
        import trimesh  # type: ignore[import]

        prompt = (
            "Analyse these roofline keyframes. For each visible roof face, estimate "
            "approximate 3D polygon vertices in metric coordinates (origin = centroid, "
            "Z = height above base). Return JSON: "
            "{\"faces_3d\": [{\"face_id\": str, \"vertices_3d\": [[x,y,z],...], "
            "\"confidence\": float}], \"overall_confidence\": float}"
        )
        adapter = GeminiVisionAdapter()
        data = await adapter.analyze_frames(frames, prompt)

        overall_confidence = float(data.get("overall_confidence", 0.5))
        faces_3d = data.get("faces_3d", [])
        if not faces_3d:
            return None

        # Build a coarse mesh from face vertex clouds
        all_verts: list[list[float]] = []
        for face in faces_3d:
            all_verts.extend(face.get("vertices_3d", []))

        if len(all_verts) < 4:
            return None

        pts = np.array(all_verts, dtype=float)
        cloud = trimesh.PointCloud(pts)
        glb_out = mesh_path(run_id)
        cloud.export(str(glb_out))

        return ReconstructionResult(
            mesh_uri=str(glb_out),
            point_cloud_uri=None,
            tier=3,
            runtime_s=0.0,
            confidence=overall_confidence,
        )
    except Exception as exc:
        logger.warning("Tier 3: Gemini depth failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def reconstruct_mesh(
    frames: list[Path],
    run_id: str,
    spatial_data_dict: dict | None = None,
) -> Optional[ReconstructionResult]:
    """
    Attempt 3D reconstruction in tier order. Returns None on total failure (Tier 4).
    Emits reconstruction.json regardless of outcome.
    """
    budget_s = max(1, int(config.reconstruction.budget_s))
    frames_dir = frames[0].parent if frames else run_dir(run_id) / "frames"
    t0 = time.monotonic()
    deadline = t0 + float(budget_s)

    result: Optional[ReconstructionResult] = None

    # Tier 1
    if frames_dir.is_dir() and frames:
        remaining = max(1, int(deadline - time.monotonic()))
        result = await asyncio.get_event_loop().run_in_executor(
            None, _try_sfm, frames_dir, run_id, remaining
        )

    # Tier 2
    if result is None and frames:
        remaining = deadline - time.monotonic()
        if remaining > 0:
            try:
                result = await asyncio.wait_for(
                    _try_pioneer(frames, spatial_data_dict or {}),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                logger.warning("Tier 2: budget exceeded before completion")

    # Tier 3
    if result is None and frames:
        remaining = deadline - time.monotonic()
        if remaining > 0:
            try:
                result = await asyncio.wait_for(
                    _try_gemini_depth(frames, run_id),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                logger.warning("Tier 3: budget exceeded before completion")

    # Tier 4 — silent 2D fallback
    if result is None:
        logger.warning("reconstruct_mesh: all tiers failed for run %s — 2D-only mode", run_id)

    # Persist reconstruction.json
    _write_reconstruction_json(run_id, result, time.monotonic() - t0)
    return result


def _write_reconstruction_json(
    run_id: str,
    result: Optional[ReconstructionResult],
    total_runtime: float,
) -> None:
    payload: dict = {
        "run_id": run_id,
        "success": result is not None,
        "total_runtime_s": round(total_runtime, 2),
    }
    if result:
        payload.update(
            {
                "tier": result.tier,
                "tier_runtime_s": round(result.runtime_s, 2),
                "confidence": result.confidence,
                "mesh_uri": result.mesh_uri,
                "point_cloud_uri": result.point_cloud_uri,
            }
        )
    else:
        payload["tier"] = 4

    out = reconstruction_json_path(run_id)
    out.write_text(json.dumps(payload, indent=2))
    logger.debug("Wrote %s", out)
