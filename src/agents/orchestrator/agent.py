"""
Orchestrator Agent — runs the full Zero-Touch Agent Pipeline.

Execution order:
  Stage 1 (Ingestion):        process_video + process_photo + process_pdf  [concurrent]
  Safety Gate 1:              validate SpatialData, ElectricalData, ConsumptionData
  Stage 2 (Domain parallel):  structural + electrical + thermodynamic + behavioral  [concurrent]
  Safety Gate 2:              validate ModuleLayout, ElectricalAssessment, ThermalLoad, BehavioralProfile
  Stage 3 (Synthesis):        synthesis_agent.run(...)
  Safety Gate 3:              validate FinalProposal

All stages are wrapped in per-agent and full-pipeline timeouts.
Every log message is prefixed with the pipeline_run_id for traceability.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.agents.orchestrator.dag import AGENT_TIMEOUT_SECONDS, PIPELINE_TIMEOUT_SECONDS, PipelineStage
from src.agents.ingestion import agent as ingestion_agent
from src.agents.structural import agent as structural_agent
from src.agents.electrical import agent as electrical_agent
from src.agents.thermodynamic import agent as thermodynamic_agent
from src.agents.behavioral import agent as behavioral_agent
from src.agents.synthesis import agent as synthesis_agent
from src.agents.safety.validator import validate_handoff
from src.common.schemas import FinalProposal, ValidationResult

logger = logging.getLogger(__name__)


@dataclass
class PipelineError:
    """Structured error returned when the pipeline cannot complete successfully."""

    pipeline_run_id: str
    stage: str
    agent_name: str
    error_type: str  # "validation_failure", "agent_exception", "timeout"
    message: str
    validation_errors: list | None = None  # ValidationResult errors if validation_failure


async def run_pipeline(
    video_path: Path,
    photo_path: Path,
    pdf_path: Path,
) -> FinalProposal | PipelineError:
    """
    Execute the full Zero-Touch Agent Pipeline.

    Args:
        video_path: Path to the roofline video file.
        photo_path: Path to the electrical panel photo file.
        pdf_path:   Path to the utility bill PDF file.

    Returns:
        FinalProposal on success, or PipelineError on any failure.
    """
    pipeline_run_id = str(uuid.uuid4())
    pipeline_start = datetime.now(timezone.utc)

    logger.info("[%s] Pipeline starting — video=%s photo=%s pdf=%s",
                pipeline_run_id, video_path, photo_path, pdf_path)

    try:
        result = await asyncio.wait_for(
            _execute_pipeline(pipeline_run_id, video_path, photo_path, pdf_path),
            timeout=PIPELINE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        duration = (datetime.now(timezone.utc) - pipeline_start).total_seconds()
        logger.error("[%s] Pipeline timed out after %.1fs (limit=%ds)",
                     pipeline_run_id, duration, PIPELINE_TIMEOUT_SECONDS)
        return PipelineError(
            pipeline_run_id=pipeline_run_id,
            stage="pipeline",
            agent_name="orchestrator",
            error_type="timeout",
            message=f"Full pipeline exceeded {PIPELINE_TIMEOUT_SECONDS}s timeout",
        )
    except Exception as exc:
        duration = (datetime.now(timezone.utc) - pipeline_start).total_seconds()
        logger.exception("[%s] Unhandled pipeline exception after %.1fs: %s",
                         pipeline_run_id, duration, exc)
        return PipelineError(
            pipeline_run_id=pipeline_run_id,
            stage="pipeline",
            agent_name="orchestrator",
            error_type="agent_exception",
            message=str(exc),
        )

    duration = (datetime.now(timezone.utc) - pipeline_start).total_seconds()
    logger.info("[%s] Pipeline complete in %.1fs", pipeline_run_id, duration)
    return result


async def _execute_pipeline(
    pipeline_run_id: str,
    video_path: Path,
    photo_path: Path,
    pdf_path: Path,
) -> FinalProposal | PipelineError:
    """Inner pipeline logic (wrapped by the outer timeout in run_pipeline)."""

    # ------------------------------------------------------------------
    # Pre-flight — verify all input files exist and are non-empty
    # ------------------------------------------------------------------
    file_checks = [
        (video_path, "video_path"),
        (photo_path, "photo_path"),
        (pdf_path, "pdf_path"),
    ]
    for path, field in file_checks:
        if not path.exists():
            return PipelineError(
                pipeline_run_id=pipeline_run_id,
                stage=PipelineStage.INGESTION.value,
                agent_name="orchestrator",
                error_type="validation_failure",
                message=f"File not found: {field}={path}",
            )
        if path.stat().st_size == 0:
            return PipelineError(
                pipeline_run_id=pipeline_run_id,
                stage=PipelineStage.INGESTION.value,
                agent_name="orchestrator",
                error_type="validation_failure",
                message=f"File is empty: {field}={path}",
            )

    # ------------------------------------------------------------------
    # Stage 1 — Ingestion (three concurrent calls)
    # ------------------------------------------------------------------
    logger.info("[%s] Stage 1 — Ingestion starting", pipeline_run_id)
    stage1_start = datetime.now(timezone.utc)

    try:
        spatial_data, electrical_data, consumption_data = await asyncio.gather(
            asyncio.wait_for(ingestion_agent.process_video(video_path), AGENT_TIMEOUT_SECONDS),
            asyncio.wait_for(ingestion_agent.process_photo(photo_path), AGENT_TIMEOUT_SECONDS),
            asyncio.wait_for(ingestion_agent.process_pdf(pdf_path), AGENT_TIMEOUT_SECONDS),
        )
    except asyncio.TimeoutError as exc:
        duration = (datetime.now(timezone.utc) - stage1_start).total_seconds()
        logger.error("[%s] Ingestion timed out after %.1fs", pipeline_run_id, duration)
        return PipelineError(
            pipeline_run_id=pipeline_run_id,
            stage=PipelineStage.INGESTION.value,
            agent_name="ingestion",
            error_type="timeout",
            message=f"Ingestion agent timed out after {AGENT_TIMEOUT_SECONDS}s",
        )
    except Exception as exc:
        duration = (datetime.now(timezone.utc) - stage1_start).total_seconds()
        logger.exception("[%s] Ingestion failed after %.1fs: %s", pipeline_run_id, duration, exc)
        return PipelineError(
            pipeline_run_id=pipeline_run_id,
            stage=PipelineStage.INGESTION.value,
            agent_name="ingestion",
            error_type="agent_exception",
            message=str(exc),
        )

    stage1_duration = (datetime.now(timezone.utc) - stage1_start).total_seconds()
    logger.info("[%s] Stage 1 — Ingestion complete in %.1fs", pipeline_run_id, stage1_duration)

    # ------------------------------------------------------------------
    # Safety Gate 1 — validate ingestion outputs
    # ------------------------------------------------------------------
    logger.info("[%s] Safety Gate 1 — validating ingestion outputs", pipeline_run_id)

    for data_obj, schema_name, agent_name in [
        (spatial_data, "SpatialData", "ingestion"),
        (electrical_data, "ElectricalData", "ingestion"),
        (consumption_data, "ConsumptionData", "ingestion"),
    ]:
        _, result = validate_handoff(data_obj.model_dump(), schema_name, agent_name)
        if not result.valid:
            logger.warning("[%s] Safety Gate 1 rejected %s: %d errors",
                           pipeline_run_id, schema_name, len(result.errors))
            return PipelineError(
                pipeline_run_id=pipeline_run_id,
                stage=PipelineStage.INGESTION.value,
                agent_name=agent_name,
                error_type="validation_failure",
                message=f"{schema_name} failed Safety Gate 1 validation",
                validation_errors=result.errors,
            )

    logger.info("[%s] Safety Gate 1 — all ingestion outputs valid", pipeline_run_id)

    # ------------------------------------------------------------------
    # Stage 2 — Domain agents (four concurrent calls)
    # ------------------------------------------------------------------
    logger.info("[%s] Stage 2 — Domain agents starting", pipeline_run_id)
    stage2_start = datetime.now(timezone.utc)

    domain_tasks = [
        asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, structural_agent.run, spatial_data),
            AGENT_TIMEOUT_SECONDS,
        ),
        asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, electrical_agent.run, electrical_data),
            AGENT_TIMEOUT_SECONDS,
        ),
        asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None, thermodynamic_agent.run, spatial_data, consumption_data
            ),
            AGENT_TIMEOUT_SECONDS,
        ),
        asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, behavioral_agent.run, consumption_data),
            AGENT_TIMEOUT_SECONDS,
        ),
    ]

    domain_results = await asyncio.gather(*domain_tasks, return_exceptions=True)

    stage2_duration = (datetime.now(timezone.utc) - stage2_start).total_seconds()
    logger.info("[%s] Stage 2 — Domain agents finished in %.1fs", pipeline_run_id, stage2_duration)

    # Check for exceptions in domain results
    domain_agent_names = ["structural", "electrical", "thermodynamic", "behavioral"]
    for agent_name, res in zip(domain_agent_names, domain_results):
        if isinstance(res, BaseException):
            error_type = "timeout" if isinstance(res, asyncio.TimeoutError) else "agent_exception"
            logger.error("[%s] Domain agent '%s' failed: %s", pipeline_run_id, agent_name, res)
            return PipelineError(
                pipeline_run_id=pipeline_run_id,
                stage=PipelineStage.DOMAIN_PARALLEL.value,
                agent_name=agent_name,
                error_type=error_type,
                message=str(res),
            )

    module_layout, electrical_assessment, thermal_load, behavioral_profile = domain_results

    logger.info("[%s] Stage 2 — structural=%.1f kWp, electrical=%s, thermal=%.1f kW, behavioral=%s",
                pipeline_run_id,
                module_layout.total_kwp,
                electrical_assessment.current_capacity_sufficient,
                thermal_load.design_heat_load_kw,
                behavioral_profile.occupancy_pattern.value)

    # ------------------------------------------------------------------
    # Safety Gate 2 — validate domain agent outputs
    # ------------------------------------------------------------------
    logger.info("[%s] Safety Gate 2 — validating domain agent outputs", pipeline_run_id)

    for data_obj, schema_name, agent_name in [
        (module_layout, "ModuleLayout", "structural"),
        (electrical_assessment, "ElectricalAssessment", "electrical"),
        (thermal_load, "ThermalLoad", "thermodynamic"),
        (behavioral_profile, "BehavioralProfile", "behavioral"),
    ]:
        _, result = validate_handoff(data_obj.model_dump(), schema_name, agent_name)
        if not result.valid:
            logger.warning("[%s] Safety Gate 2 rejected %s: %d errors",
                           pipeline_run_id, schema_name, len(result.errors))
            return PipelineError(
                pipeline_run_id=pipeline_run_id,
                stage=PipelineStage.DOMAIN_PARALLEL.value,
                agent_name=agent_name,
                error_type="validation_failure",
                message=f"{schema_name} failed Safety Gate 2 validation",
                validation_errors=result.errors,
            )

    logger.info("[%s] Safety Gate 2 — all domain outputs valid", pipeline_run_id)

    # ------------------------------------------------------------------
    # Stage 3 — Synthesis
    # ------------------------------------------------------------------
    logger.info("[%s] Stage 3 — Synthesis starting", pipeline_run_id)
    stage3_start = datetime.now(timezone.utc)

    try:
        final_proposal = await asyncio.wait_for(
            synthesis_agent.run(
                module_layout=module_layout,
                thermal_load=thermal_load,
                electrical_assessment=electrical_assessment,
                behavioral_profile=behavioral_profile,
                consumption_data=consumption_data,
                spatial_data=spatial_data,
            ),
            AGENT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        duration = (datetime.now(timezone.utc) - stage3_start).total_seconds()
        logger.error("[%s] Synthesis timed out after %.1fs", pipeline_run_id, duration)
        return PipelineError(
            pipeline_run_id=pipeline_run_id,
            stage=PipelineStage.SYNTHESIS.value,
            agent_name="synthesis",
            error_type="timeout",
            message=f"Synthesis agent timed out after {AGENT_TIMEOUT_SECONDS}s",
        )
    except Exception as exc:
        duration = (datetime.now(timezone.utc) - stage3_start).total_seconds()
        logger.exception("[%s] Synthesis failed after %.1fs: %s", pipeline_run_id, duration, exc)
        return PipelineError(
            pipeline_run_id=pipeline_run_id,
            stage=PipelineStage.SYNTHESIS.value,
            agent_name="synthesis",
            error_type="agent_exception",
            message=str(exc),
        )

    stage3_duration = (datetime.now(timezone.utc) - stage3_start).total_seconds()
    logger.info("[%s] Stage 3 — Synthesis complete in %.1fs", pipeline_run_id, stage3_duration)

    # ------------------------------------------------------------------
    # Safety Gate 3 — validate FinalProposal
    # ------------------------------------------------------------------
    logger.info("[%s] Safety Gate 3 — validating FinalProposal", pipeline_run_id)

    _, result = validate_handoff(final_proposal.model_dump(mode="json"), "FinalProposal", "synthesis")
    if not result.valid:
        logger.warning("[%s] Safety Gate 3 rejected FinalProposal: %d errors",
                       pipeline_run_id, len(result.errors))
        return PipelineError(
            pipeline_run_id=pipeline_run_id,
            stage=PipelineStage.SYNTHESIS.value,
            agent_name="synthesis",
            error_type="validation_failure",
            message="FinalProposal failed Safety Gate 3 validation",
            validation_errors=result.errors,
        )

    logger.info("[%s] Safety Gate 3 — FinalProposal valid", pipeline_run_id)

    return final_proposal
