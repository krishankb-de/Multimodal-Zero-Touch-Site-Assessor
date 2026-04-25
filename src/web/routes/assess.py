"""POST /api/v1/assess — upload media files and trigger the pipeline."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from src.agents.orchestrator.agent import PipelineError, run_pipeline
from src.web.store import proposal_store

router = APIRouter()

MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB

ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm"}
ALLOWED_PHOTO_TYPES = {"image/jpeg", "image/png", "image/heic"}
ALLOWED_PDF_TYPES = {"application/pdf"}


class AssessResponse(BaseModel):
    pipeline_run_id: str
    status: str


@router.post("/assess", response_model=AssessResponse)
async def assess(
    video: UploadFile = File(...),
    photo: UploadFile = File(...),
    bill: UploadFile = File(...),
) -> AssessResponse:
    """
    Accept multipart file uploads, validate them, and trigger the pipeline.

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

        # Run the pipeline
        result = await run_pipeline(video_path, photo_path, pdf_path)

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

    # Store the proposal
    proposal_store[result.metadata.pipeline_run_id] = result

    return AssessResponse(
        pipeline_run_id=result.metadata.pipeline_run_id,
        status="completed",
    )
