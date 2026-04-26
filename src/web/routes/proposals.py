"""GET /api/v1/proposals/{pipeline_run_id} and POST /api/v1/proposals/{pipeline_run_id}/signoff"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.common.schemas import FinalProposal, SignoffStatus, WeatherProfile
from src.web.auth import require_installer_auth
from src.web.store import proposal_store, weather_store

router = APIRouter()


@router.get("/proposals/{pipeline_run_id}/weather", response_model=WeatherProfile)
async def get_weather(pipeline_run_id: str) -> WeatherProfile:
    """Return the WeatherProfile computed during the pipeline run, if available."""
    profile = weather_store.get(pipeline_run_id)
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail=f"Weather profile for run '{pipeline_run_id}' not available",
        )
    return profile


@router.get("/proposals/{pipeline_run_id}", response_model=FinalProposal)
async def get_proposal(pipeline_run_id: str) -> FinalProposal:
    """Return the FinalProposal for a completed pipeline run."""
    proposal = proposal_store.get(pipeline_run_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"Proposal '{pipeline_run_id}' not found")
    return proposal


class SignoffRequest(BaseModel):
    action: Literal["approve", "reject"]
    notes: str | None = None
    installer_id: str | None = None


@router.post("/proposals/{pipeline_run_id}/signoff")
async def signoff_proposal(
    pipeline_run_id: str,
    request: SignoffRequest,
    api_key: str = Depends(require_installer_auth),
) -> FinalProposal:
    """
    Installer approve or reject a proposal.

    Requires a valid installer API key (Authorization: Bearer <key>).
    Rejection requires a notes field.
    """
    proposal = proposal_store.get(pipeline_run_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"Proposal '{pipeline_run_id}' not found")

    if request.action == "reject" and not request.notes:
        raise HTTPException(
            status_code=422,
            detail="Rejection requires a 'notes' field explaining the reason",
        )

    new_status = SignoffStatus.APPROVED if request.action == "approve" else SignoffStatus.REJECTED

    updated_signoff = proposal.human_signoff.model_copy(
        update={
            "status": new_status,
            "installer_id": request.installer_id or api_key,
            "signed_at": datetime.now(timezone.utc),
            "notes": request.notes,
        }
    )

    updated_proposal = proposal.model_copy(update={"human_signoff": updated_signoff})
    proposal_store[pipeline_run_id] = updated_proposal

    return updated_proposal
