"""
POST /api/v1/installations                   — register an installation
POST /api/v1/installations/{id}/telemetry    — ingest EEBus telemetry batch
POST /api/v1/installations/{id}/reoptimize   — quarterly HEMS reoptimization pass
GET  /api/v1/installations/{id}              — fetch installation record
GET  /api/v1/installations/{id}/optimizations — list optimization history
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from src.agents.hems import agent as hems_agent
from src.common.schemas import (
    BehavioralProfile,
    ConsumptionData,
    InstallationRecord,
    OptimizationDelta,
    TelemetryPoint,
)
from src.web.database import InstallationRow, OptimizationRow, TelemetryRow, get_session

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response bodies
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
# DB helpers
# ---------------------------------------------------------------------------


def _load_installation(installation_id: str) -> InstallationRecord | None:
    with get_session() as session:
        row = session.get(InstallationRow, installation_id)
        if row is None:
            return None
        # Read all column values inside the session before it closes
        inst_id = row.installation_id
        run_id = row.pipeline_run_id
        baseline_cons_json = row.baseline_consumption
        baseline_prof_json = row.baseline_profile
        created_at = row.created_at
        telemetry_rows = session.execute(
            select(TelemetryRow)
            .where(TelemetryRow.installation_id == installation_id)
            .order_by(TelemetryRow.id)
        ).scalars().all()
        telemetry_json = [r.data for r in telemetry_rows]

    return InstallationRecord(
        installation_id=inst_id,
        pipeline_run_id=run_id,
        baseline_consumption=ConsumptionData.model_validate_json(baseline_cons_json),
        baseline_profile=BehavioralProfile.model_validate_json(baseline_prof_json),
        telemetry=[TelemetryPoint.model_validate_json(d) for d in telemetry_json],
        created_at=created_at,
    )


def _installation_exists(installation_id: str) -> bool:
    with get_session() as session:
        return session.get(InstallationRow, installation_id) is not None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/installations", response_model=RegisterInstallationResponse, status_code=201)
async def register_installation(body: RegisterInstallationRequest) -> RegisterInstallationResponse:
    """Register a commissioned installation for post-install HEMS tracking."""
    installation_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    with get_session() as session:
        session.add(InstallationRow(
            installation_id=installation_id,
            pipeline_run_id=body.pipeline_run_id,
            baseline_consumption=body.baseline_consumption.model_dump_json(),
            baseline_profile=body.baseline_profile.model_dump_json(),
            created_at=now,
        ))

    return RegisterInstallationResponse(
        installation_id=installation_id,
        pipeline_run_id=body.pipeline_run_id,
        created_at=now,
    )


@router.get("/installations/{installation_id}", response_model=InstallationRecord)
async def get_installation(installation_id: str) -> InstallationRecord:
    record = _load_installation(installation_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Installation '{installation_id}' not found")
    return record


@router.post("/installations/{installation_id}/telemetry", response_model=TelemetryResponse)
async def ingest_telemetry(installation_id: str, body: TelemetryBatch) -> TelemetryResponse:
    """Append a batch of EEBus-compatible smart-meter readings."""
    if not _installation_exists(installation_id):
        raise HTTPException(status_code=404, detail=f"Installation '{installation_id}' not found")

    with get_session() as session:
        for reading in body.readings:
            session.add(TelemetryRow(
                installation_id=installation_id,
                data=reading.model_dump_json(),
                timestamp=reading.timestamp,
            ))
        session.flush()  # make new rows visible within this session
        total = session.execute(
            select(TelemetryRow)
            .where(TelemetryRow.installation_id == installation_id)
        ).scalars().all().__len__()

    return TelemetryResponse(
        installation_id=installation_id,
        readings_accepted=len(body.readings),
        total_readings=total,
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
    record = _load_installation(installation_id)
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

    with get_session() as session:
        session.add(OptimizationRow(
            installation_id=installation_id,
            data=delta.model_dump_json(),
            optimized_at=delta.optimized_at,
        ))

    return delta


@router.get("/installations/{installation_id}/optimizations", response_model=list[OptimizationDelta])
async def get_optimization_history(installation_id: str) -> list[OptimizationDelta]:
    if not _installation_exists(installation_id):
        raise HTTPException(status_code=404, detail=f"Installation '{installation_id}' not found")

    with get_session() as session:
        json_list = [
            r.data for r in session.execute(
                select(OptimizationRow)
                .where(OptimizationRow.installation_id == installation_id)
                .order_by(OptimizationRow.id)
            ).scalars().all()
        ]

    return [OptimizationDelta.model_validate_json(d) for d in json_list]
