"""DB-backed proposal store with a dict-like interface.

Replaces the previous in-memory dict.  Existing call-sites that use
  proposal_store[run_id] = proposal
  proposal_store.get(run_id)
  run_id in proposal_store
  proposal_store.clear()
continue to work unchanged.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select

from src.common.schemas import FinalProposal, WeatherProfile
from src.web.database import ProposalRow, get_session

logger = logging.getLogger(__name__)


class ProposalStore:
    """Persistent proposal store backed by SQLite via SQLAlchemy."""

    def __setitem__(self, pipeline_run_id: str, proposal: FinalProposal) -> None:
        data = proposal.model_dump_json()
        now = datetime.now(timezone.utc)
        with get_session() as session:
            existing = session.get(ProposalRow, pipeline_run_id)
            if existing is not None:
                existing.data = data
            else:
                session.add(ProposalRow(
                    pipeline_run_id=pipeline_run_id,
                    data=data,
                    created_at=now,
                ))

    def __getitem__(self, pipeline_run_id: str) -> FinalProposal:
        with get_session() as session:
            row = session.get(ProposalRow, pipeline_run_id)
            if row is None:
                raise KeyError(pipeline_run_id)
            data = row.data  # read inside session before it closes
        return FinalProposal.model_validate_json(data)

    def get(self, pipeline_run_id: str) -> FinalProposal | None:
        with get_session() as session:
            row = session.get(ProposalRow, pipeline_run_id)
            if row is None:
                return None
            data = row.data  # read inside session before it closes
        return FinalProposal.model_validate_json(data)

    def __contains__(self, pipeline_run_id: object) -> bool:
        with get_session() as session:
            return session.get(ProposalRow, pipeline_run_id) is not None

    def clear(self) -> None:
        """Delete all proposals — used by tests to reset state between cases."""
        with get_session() as session:
            session.execute(delete(ProposalRow))


proposal_store = ProposalStore()

# Simple in-memory store for weather profiles keyed by pipeline_run_id.
# Not persisted — acceptable since weather data is re-fetchable if needed.
weather_store: dict[str, WeatherProfile] = {}
