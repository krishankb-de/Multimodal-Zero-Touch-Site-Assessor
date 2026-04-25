"""
Safety / Validation Agent — Core Validator

This is the most critical component of the system. It validates every inter-agent
handoff against the schemas defined in CLAUDE.md and enforces domain-specific
safety constraints for residential renewable energy systems.

Every agent output MUST pass through `validate_handoff()` before being forwarded
to the next agent in the pipeline.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Union

from pydantic import ValidationError as PydanticValidationError

from src.common.schemas import (
    BehavioralProfile,
    ConsumptionData,
    ElectricalAssessment,
    ElectricalData,
    ErrorSeverity,
    FinalProposal,
    ModuleLayout,
    SpatialData,
    ThermalLoad,
    ValidationError,
    ValidationResult,
)
from src.agents.safety.guardrails import run_guardrail_checks

logger = logging.getLogger(__name__)

# Maps schema name strings to Pydantic model classes
SCHEMA_REGISTRY: dict[str, type] = {
    "SpatialData": SpatialData,
    "ElectricalData": ElectricalData,
    "ConsumptionData": ConsumptionData,
    "ModuleLayout": ModuleLayout,
    "ThermalLoad": ThermalLoad,
    "ElectricalAssessment": ElectricalAssessment,
    "BehavioralProfile": BehavioralProfile,
    "FinalProposal": FinalProposal,
}

# Type alias for all valid handoff payloads
HandoffPayload = Union[
    SpatialData,
    ElectricalData,
    ConsumptionData,
    ModuleLayout,
    ThermalLoad,
    ElectricalAssessment,
    BehavioralProfile,
    FinalProposal,
]


def validate_schema(
    data: dict[str, Any],
    schema_name: str,
    agent_source: str,
) -> tuple[HandoffPayload | None, list[ValidationError]]:
    """
    Validate raw dict data against the named schema.

    Returns:
        Tuple of (parsed model instance or None, list of validation errors).
    """
    model_class = SCHEMA_REGISTRY.get(schema_name)
    if model_class is None:
        return None, [
            ValidationError(
                code="UNKNOWN_SCHEMA",
                message=f"Schema '{schema_name}' is not registered",
                field="$root",
                severity=ErrorSeverity.CRITICAL,
            )
        ]

    try:
        instance = model_class.model_validate(data, strict=False)
        return instance, []
    except PydanticValidationError as exc:
        errors: list[ValidationError] = []
        for err in exc.errors():
            field_path = ".".join(str(loc) for loc in err["loc"])
            errors.append(
                ValidationError(
                    code="SCHEMA_VALIDATION_FAILED",
                    message=err["msg"],
                    field=field_path,
                    severity=ErrorSeverity.ERROR,
                )
            )
        return None, errors


def validate_handoff(
    data: dict[str, Any],
    schema_name: str,
    agent_source: str,
) -> tuple[HandoffPayload | None, ValidationResult]:
    """
    Full validation pipeline for an inter-agent handoff.

    1. Schema validation (Pydantic strict mode)
    2. Domain-specific guardrail checks
    3. Produces a ValidationResult with pass/fail verdict

    Args:
        data: Raw JSON dict from the source agent.
        schema_name: Name of the target schema (must match SCHEMA_REGISTRY).
        agent_source: Name of the agent producing this data.

    Returns:
        Tuple of (validated model instance or None, ValidationResult).
    """
    logger.debug(
        "Validating handoff: agent=%s schema=%s",
        agent_source,
        schema_name,
    )

    # Step 1: Schema validation
    instance, schema_errors = validate_schema(data, schema_name, agent_source)

    # Step 2: Domain guardrail checks (only if schema passes)
    guardrail_errors: list[ValidationError] = []
    warnings: list[str] = []
    if instance is not None:
        guardrail_errors, warnings = run_guardrail_checks(instance, schema_name)

    # Combine all errors
    all_errors = schema_errors + guardrail_errors
    is_valid = len(all_errors) == 0

    result = ValidationResult(
        valid=is_valid,
        agent_source=agent_source,
        schema_name=schema_name,
        errors=all_errors,
        warnings=warnings,
        timestamp=datetime.now(timezone.utc),
    )

    if not is_valid:
        logger.warning(
            "Handoff REJECTED: agent=%s schema=%s errors=%d",
            agent_source,
            schema_name,
            len(all_errors),
        )
        for err in all_errors:
            logger.warning("  [%s] %s: %s (field: %s)", err.severity, err.code, err.message, err.field)
    else:
        logger.info(
            "Handoff ACCEPTED: agent=%s schema=%s warnings=%d",
            agent_source,
            schema_name,
            len(warnings),
        )

    return instance if is_valid else None, result
