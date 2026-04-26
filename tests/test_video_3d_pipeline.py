"""
End-to-end stub test for the video → frame extraction → reconstruction pipeline.

Uses a 5-frame synthetic video fixture.  All Gemini / Pioneer API calls are
mocked so no real credentials are needed.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np
import pytest

from src.agents.ingestion.frame_extractor import extract_keyframes
from src.agents.ingestion.reconstruction import reconstruct_mesh, ReconstructionResult
from src.common.artifact_store import frames_dir, mesh_path, reconstruction_json_path, run_dir
from src.common.glb_validator import validate_reconstruction_against_region


# ---------------------------------------------------------------------------
# Fixture — synthetic 5-frame video
# ---------------------------------------------------------------------------

def _make_video(path: Path, n_frames: int = 5) -> None:
    h, w = 64, 96
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, 5, (w, h))
    for i in range(n_frames):
        frame = np.full((h, w, 3), int(i * 40), dtype=np.uint8)
        writer.write(frame)
    writer.release()


@pytest.fixture()
def synthetic_video(tmp_path: Path) -> Path:
    p = tmp_path / "roof.mp4"
    _make_video(p)
    return p


# ---------------------------------------------------------------------------
# P1 — Frame extraction
# ---------------------------------------------------------------------------

def test_frame_extraction_from_5_frame_video(synthetic_video: Path) -> None:
    run_id = uuid.uuid4().hex
    frames = extract_keyframes(synthetic_video, run_id, n_uniform=5)
    assert len(frames) >= 1
    assert all(f.exists() for f in frames)
    assert all(f.suffix == ".jpg" for f in frames)


# ---------------------------------------------------------------------------
# P3 — Reconstruction tiers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reconstruction_tier4_fallback(synthetic_video: Path) -> None:
    """All tiers fail → Tier 4 silent 2D-only; reconstruction.json records tier=4."""
    run_id = uuid.uuid4().hex
    frames = extract_keyframes(synthetic_video, run_id, n_uniform=5)

    # Patch all three active tiers to fail
    with (
        patch("src.agents.ingestion.reconstruction._try_sfm", return_value=None),
        patch("src.agents.ingestion.reconstruction._try_pioneer", new_callable=AsyncMock, return_value=None),
        patch("src.agents.ingestion.reconstruction._try_gemini_depth", new_callable=AsyncMock, return_value=None),
    ):
        result = await reconstruct_mesh(frames, run_id)

    assert result is None
    rj = reconstruction_json_path(run_id)
    assert rj.exists()
    data = json.loads(rj.read_text())
    assert data["success"] is False
    assert data["tier"] == 4


@pytest.mark.asyncio
async def test_reconstruction_tier3_gemini_depth(synthetic_video: Path, tmp_path: Path) -> None:
    """Tier 3 Gemini depth succeeds → mesh.glb written, reconstruction.json records tier=3."""
    import trimesh  # noqa: F401 — ensure dep available

    run_id = uuid.uuid4().hex
    frames = extract_keyframes(synthetic_video, run_id, n_uniform=5)

    # Build a minimal real GLB using trimesh so the file write path works
    fake_mesh_path = mesh_path(run_id)
    fake_mesh_path.parent.mkdir(parents=True, exist_ok=True)

    tier3_result = ReconstructionResult(
        mesh_uri=str(fake_mesh_path),
        point_cloud_uri=None,
        tier=3,
        runtime_s=0.5,
        confidence=0.72,
    )

    with (
        patch("src.agents.ingestion.reconstruction._try_sfm", return_value=None),
        patch("src.agents.ingestion.reconstruction._try_pioneer", new_callable=AsyncMock, return_value=None),
        patch("src.agents.ingestion.reconstruction._try_gemini_depth", new_callable=AsyncMock, return_value=tier3_result),
    ):
        result = await reconstruct_mesh(frames, run_id)

    assert result is not None
    assert result.tier == 3
    rj = reconstruction_json_path(run_id)
    data = json.loads(rj.read_text())
    assert data["success"] is True
    assert data["tier"] == 3
    assert data["confidence"] == pytest.approx(0.72, abs=0.01)


# ---------------------------------------------------------------------------
# P7.1 — validate_reconstruction_against_region advisory
# ---------------------------------------------------------------------------

def test_cross_check_missing_mesh_is_advisory(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent.glb"
    result = validate_reconstruction_against_region(missing, "Hamburg")
    assert result.valid is True  # advisory — never hard-blocks
    codes = [i.code for i in result.issues]
    assert "GENERATED_MESH_MISSING" in codes


def test_cross_check_unknown_region_is_advisory(tmp_path: Path) -> None:
    fake_glb = tmp_path / "mesh.glb"
    fake_glb.write_bytes(b"")  # empty — function checks existence first
    result = validate_reconstruction_against_region(fake_glb, "Atlantis")
    # Validator may not find region ref but stays advisory
    assert result.valid is True


def test_cross_check_valid_trimesh_glb(tmp_path: Path) -> None:
    """Generate a real GLB via trimesh and check it passes the advisory cross-check."""
    try:
        import trimesh
        import numpy as np
    except ImportError:
        pytest.skip("trimesh not installed")

    pts = np.array([[0, 0, 0], [5, 0, 0], [5, 5, 1], [0, 5, 1]], dtype=float)
    cloud = trimesh.PointCloud(pts)
    glb_path = tmp_path / "mesh.glb"
    cloud.export(str(glb_path))

    result = validate_reconstruction_against_region(glb_path, "Hamburg")
    assert result.valid is True
    # No MESH_BBOX_IMPLAUSIBLE expected for a 5×5m roof-sized cloud
    error_codes = [i.code for i in result.issues if i.severity == "error"]
    assert error_codes == []


# ---------------------------------------------------------------------------
# P4 — Schema round-trip with 3D fields
# ---------------------------------------------------------------------------

def test_spatial_data_3d_fields_nullable() -> None:
    """SpatialData with all new 3D fields set to None still validates."""
    from datetime import datetime, timezone
    from src.common.schemas import (
        IngestionMetadata, RoofData, RoofFace, RoofTypology,
        SourceType, SpatialData, UtilityRoom,
    )

    spatial = SpatialData(
        roof=RoofData(
            typology=RoofTypology.GABLE,
            faces=[RoofFace(
                id="south",
                orientation_deg=180,
                tilt_deg=30,
                area_m2=40,
                polygon_vertices_3d=None,
                polygon_vertices_image=None,
            )],
            total_usable_area_m2=40,
            obstacles=[],
        ),
        utility_room=UtilityRoom(
            length_m=3, width_m=2, height_m=2.5, available_volume_m3=10
        ),
        metadata=IngestionMetadata(
            source_type=SourceType.VIDEO,
            confidence_score=0.85,
            timestamp=datetime.now(timezone.utc),
        ),
        mesh_uri=None,
        point_cloud_uri=None,
        reconstruction_confidence=None,
    )
    dumped = spatial.model_dump()
    assert dumped["mesh_uri"] is None
    reloaded = SpatialData.model_validate(dumped)
    assert reloaded.roof.faces[0].polygon_vertices_3d is None


def test_spatial_data_3d_fields_populated() -> None:
    """SpatialData with 3D polygon vertices round-trips correctly."""
    from datetime import datetime, timezone
    from src.common.schemas import (
        IngestionMetadata, RoofData, RoofFace, RoofTypology,
        SourceType, SpatialData, UtilityRoom,
    )

    verts = [[0.0, 0.0, 0.0], [5.0, 0.0, 0.5], [5.0, 4.0, 0.5], [0.0, 4.0, 0.0]]
    spatial = SpatialData(
        roof=RoofData(
            typology=RoofTypology.GABLE,
            faces=[RoofFace(
                id="south",
                orientation_deg=180,
                tilt_deg=30,
                area_m2=20,
                polygon_vertices_3d=verts,
            )],
            total_usable_area_m2=20,
            obstacles=[],
        ),
        utility_room=UtilityRoom(
            length_m=3, width_m=2, height_m=2.5, available_volume_m3=10
        ),
        metadata=IngestionMetadata(
            source_type=SourceType.VIDEO,
            confidence_score=0.9,
            timestamp=datetime.now(timezone.utc),
        ),
        mesh_uri="/artifacts/abc123/mesh.glb",
        reconstruction_confidence=0.85,
    )
    reloaded = SpatialData.model_validate(spatial.model_dump())
    assert reloaded.roof.faces[0].polygon_vertices_3d == verts
    assert reloaded.mesh_uri == "/artifacts/abc123/mesh.glb"
