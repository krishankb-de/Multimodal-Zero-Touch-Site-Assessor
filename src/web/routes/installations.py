"""
POST /api/v1/installations                   — register an installation
POST /api/v1/installations/{id}/telemetry    — ingest EEBus telemetry batch
POST /api/v1/installations/{id}/reoptimize   — quarterly HEMS reoptimization pass
GET  /api/v1/installations/{id}              — fetch installation record
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.agents.hems import agent as hems_agent
from src.common.schemas import (
    BehavioralProfile,
    ConsumptionData,
    InstallationRecord,
    OptimizationDelta,
    TelemetryPoint,
)

router = APIRouter()

# In-memory stores (per ISSUES.md B4 spec: "in-memory store OK")
_installations: dict[str, InstallationRecord] = {}
_optimization_history: dict[str, list[OptimizationDelta]] = {}


# ---------------------------------------------------------------------------
# Request/response bodies
# ---------------------------------------------------------------------------


class RegisterInstallationRequest(BaseModel):
    pipeline_run_id: str
    baseline_consumption: ConsumptionData
    baseline_profile: BehavioralProfile


class RegisterInstallationResponse(BaseModel):
    installation_id: str
    pipeline_run_id: str
    created_at: datetime


class TelemetryBatch(BaseModel):
    readings: Annotated[list[TelemetryPoint], Field(min_length=1)]


class TelemetryResponse(BaseModel):
    installation_id: str
    readings_accepted: int
    total_readings: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/installations", response_model=RegisterInstallationResponse, status_code=201)
async def register_installation(body: RegisterInstallationRequest) -> RegisterInstallationResponse:
    """Register a commissioned installation for post-install HEMS tracking."""
    installation_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    record = InstallationRecord(
        installation_id=installation_id,
        pipeline_run_id=body.pipeline_run_id,
        baseline_consumption=body.baseline_consumption,
        baseline_profile=body.baseline_profile,
        telemetry=[],
        created_at=now,
    )
    _installations[installation_id] = record
    _optimization_history[installation_id] = []

    return RegisterInstallationResponse(
        installation_id=installation_id,
        pipeline_run_id=body.pipeline_run_id,
        created_at=now,
    )


@router.get("/installations/{installation_id}", response_model=InstallationRecord)
async def get_installation(installation_id: str) -> InstallationRecord:
    record = _installations.get(installation_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Installation '{installation_id}' not found")
    return record


@router.post("/installations/{installation_id}/telemetry", response_model=TelemetryResponse)
async def ingest_telemetry(installation_id: str, body: TelemetryBatch) -> TelemetryResponse:
    """
    Ingest a batch of EEBus-compatible smart-meter readings.

    Readings are appended to the installation's telemetry log.
    Call /reoptimize to trigger the HEMS optimizer after ingestion.
    """
    record = _installations.get(installation_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Installation '{installation_id}' not found")

    updated_telemetry = record.telemetry + body.readings
    _installations[installation_id] = record.model_copy(update={"telemetry": updated_telemetry})

    return TelemetryResponse(
        installation_id=installation_id,
        readings_accepted=len(body.readings),
        total_readings=len(updated_telemetry),
    )


@router.post("/installations/{installation_id}/reoptimize", response_model=OptimizationDelta)
async def reoptimize(installation_id: str) -> OptimizationDelta:
    """
    Run the HEMS quarterly optimization pass.

    Detects occupancy drift from accumulated telemetry, re-runs the
    Behavioral Agent with patched monthly consumption, and returns an
    OptimizationDelta describing changes to battery sizing and savings.
    Requires at least one telemetry reading.
    """
    record = _installations.get(installation_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Installation '{installation_id}' not found")
    if not record.telemetry:
        raise HTTPException(
            status_code=422,
            detail="No telemetry available — POST readings to /telemetry first",
        )

    delta = hems_agent.run(
        installation_id=installation_id,
        baseline_consumption=record.baseline_consumption,
        baseline_profile=record.baseline_profile,
        readings=record.telemetry,
    )
    _optimization_history[installation_id].append(delta)
    return delta


@router.get("/installations/{installation_id}/optimizations", response_model=list[OptimizationDelta])
async def get_optimization_history(installation_id: str) -> list[OptimizationDelta]:
    if installation_id not in _installations:
        raise HTTPException(status_code=404, detail=f"Installation '{installation_id}' not found")
    return _optimization_history.get(installation_id, [])
