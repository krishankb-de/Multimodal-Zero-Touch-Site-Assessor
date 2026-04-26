"""
Pipeline DAG definition for the Zero-Touch Agent Pipeline.

Defines execution order, data routing, and timeout constants.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class PipelineStage(str, Enum):
    INGESTION = "ingestion"
    DOMAIN_PARALLEL = "domain_parallel"
    SYNTHESIS = "synthesis"


# Timeout constants
def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


AGENT_TIMEOUT_SECONDS = _env_int("AGENT_TIMEOUT_SECONDS", 240)  # Per-agent timeout
PIPELINE_TIMEOUT_SECONDS = _env_int("PIPELINE_TIMEOUT_SECONDS", 600)  # Full pipeline timeout

# DAG stage definitions (for documentation/logging)
DAG_STAGES = [
    {
        "stage": PipelineStage.INGESTION,
        "agents": ["ingestion"],
        "description": "Extract SpatialData, ElectricalData, ConsumptionData from media",
    },
    {
        "stage": PipelineStage.DOMAIN_PARALLEL,
        "agents": ["structural", "electrical", "thermodynamic", "behavioral"],
        "description": "Run four domain agents concurrently",
    },
    {
        "stage": PipelineStage.SYNTHESIS,
        "agents": ["synthesis"],
        "description": "Combine domain outputs into FinalProposal",
    },
]

# Data routing: which schemas go to which agents
DATA_ROUTING = {
    "SpatialData": ["structural", "thermodynamic"],
    "ElectricalData": ["electrical"],
    "ConsumptionData": ["thermodynamic", "behavioral"],
}
