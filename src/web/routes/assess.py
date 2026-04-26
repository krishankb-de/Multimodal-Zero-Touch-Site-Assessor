"""POST /api/v1/assess — upload media files and trigger the pipeline."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from src.agents.orchestrator.agent import PipelineError, PipelineSuccess, run_pipeline
from src.common.artifact_store import mesh_path, point_cloud_path, run_dir
from src.web.store import proposal_store, weather_store

router = APIRouter()

MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB

ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm"}
ALLOWED_PHOTO_TYPES = {"image/jpeg", "image/png", "image/heic"}
ALLOWED_PDF_TYPES = {"application/pdf"}


class AssessResponse(BaseModel):
    pipeline_run_id: str
    status: str
    mesh_uri: Optional[str] = None
    point_cloud_uri: Optional[str] = None
    reconstruction_confidence: Optional[float] = None
    weather_profile_available: Optional[bool] = None


@router.post("/assess", response_model=AssessResponse)
async def assess(
    video: UploadFile = File(...),
    photo: UploadFile = File(...),
    bill: UploadFile = File(...),
    location: Optional[str] = Form(default=None),
) -> AssessResponse:
    """
    Accept multipart file uploads, validate them, and trigger the pipeline.

    Args:
        video:    Roofline video file.
        photo:    Electrical panel photo file.
        bill:     Utility bill PDF file.
        location: Optional address or place name for location-specific weather data (Req 17.2).

    Returns pipeline_run_id and status on success.
    Returns HTTP 413 if any file exceeds 100 MB.
    Returns HTTP 422 if the pipeline fails validation.
    """
    # Read all files into memory to check sizes
    video_bytes = await video.read()
    photo_bytes = await photo.read()
    bill_bytes = await bill.read()

    # Check file sizes
    for name, content in [("video", video_bytes), ("photo", photo_bytes), ("bill", bill_bytes)]:
        if len(content) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File '{name}' exceeds the 100 MB size limit ({len(content)} bytes)",
            )

    # Save to temp files
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Determine file extensions from filenames
        video_ext = Path(video.filename or "video.mp4").suffix or ".mp4"
        photo_ext = Path(photo.filename or "photo.jpg").suffix or ".jpg"
        bill_ext = Path(bill.filename or "bill.pdf").suffix or ".pdf"

        video_path = tmp / f"video{video_ext}"
        photo_path = tmp / f"photo{photo_ext}"
        pdf_path = tmp / f"bill{bill_ext}"

        video_path.write_bytes(video_bytes)
        photo_path.write_bytes(photo_bytes)
        pdf_path.write_bytes(bill_bytes)

        # Run the pipeline — pass optional location for weather intelligence (Req 17.1)
        result = await run_pipeline(video_path, photo_path, pdf_path, location=location)

    if isinstance(result, PipelineError):
        if result.error_type == "validation_failure":
            raise HTTPException(
                status_code=422,
                detail={
                    "message": result.message,
                    "stage": result.stage,
                    "agent": result.agent_name,
                    "errors": [
                        {"code": e.code, "message": e.message, "field": e.field}
                        for e in (result.validation_errors or [])
                    ],
                },
            )
        else:
            raise HTTPException(
                status_code=500,
                detail={
                    "message": result.message,
                    "stage": result.stage,
                    "agent": result.agent_name,
                },
            )

    # Store the proposal and weather profile (if available)
    proposal_store[result.proposal.metadata.pipeline_run_id] = result.proposal
    if result.weather_profile is not None:
        weather_store[result.proposal.metadata.pipeline_run_id] = result.weather_profile

    # Resolve 3D artifact URIs if available from the pipeline result
    run_id = result.proposal.metadata.pipeline_run_id
    mp = mesh_path(run_id)
    pcp = point_cloud_path(run_id)

    return AssessResponse(
        pipeline_run_id=run_id,
        status="completed",
        mesh_uri=f"/api/v1/artifacts/{run_id}/mesh.glb" if mp.exists() else None,
        point_cloud_uri=f"/api/v1/artifacts/{run_id}/point_cloud.ply" if pcp.exists() else None,
        weather_profile_available=result.weather_profile_available,  # Req 17.3
    )
