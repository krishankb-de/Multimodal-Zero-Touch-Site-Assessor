"""In-memory proposal store shared across the web layer.

Kept in a separate module to avoid circular imports between app.py and routes.
"""

from __future__ import annotations

from src.common.schemas import FinalProposal

# In-memory proposal store: pipeline_run_id → FinalProposal
proposal_store: dict[str, FinalProposal] = {}
