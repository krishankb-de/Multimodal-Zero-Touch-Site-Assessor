"""
Pipeline DAG definition for the Zero-Touch Agent Pipeline.

Defines execution order, data routing, and timeout constants.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PipelineStage(str, Enum):
    INGESTION = "ingestion"
    DOMAIN_PARALLEL = "domain_parallel"
    SYNTHESIS = "synthesis"


# Timeout constants
AGENT_TIMEOUT_SECONDS = 120    # Per-agent timeout
PIPELINE_TIMEOUT_SECONDS = 300  # Full pipeline timeout

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
