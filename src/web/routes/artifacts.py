"""GET /api/v1/artifacts/{run_id}/{filename} — stream reconstruction artifacts."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from src.common.artifact_store import run_dir

router = APIRouter()

_ALLOWED_FILENAMES = frozenset(
    ["mesh.glb", "point_cloud.ply", "reconstruction.json", "cameras.json"]
)


@router.get("/artifacts/{run_id}/{filename}")
async def get_artifact(run_id: str, filename: str) -> FileResponse:
    """
    Stream a reconstruction artifact file.

    Only whitelisted filenames are served (mesh.glb, point_cloud.ply,
    reconstruction.json, cameras.json).
    """
    if filename not in _ALLOWED_FILENAMES:
        raise HTTPException(status_code=404, detail=f"Artifact '{filename}' not available")

    artifact_path = run_dir(run_id) / filename
    if not artifact_path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {run_id}/{filename}")

    media_type, _ = mimetypes.guess_type(filename)
    if media_type is None:
        # glb and ply are not always in the mimetypes db
        media_type = {
            ".glb": "model/gltf-binary",
            ".ply": "application/octet-stream",
            ".json": "application/json",
        }.get(Path(filename).suffix, "application/octet-stream")

    return FileResponse(
        path=str(artifact_path),
        media_type=media_type,
        filename=filename,
    )
