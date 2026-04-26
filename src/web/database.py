"""SQLAlchemy SQLite persistence layer.

Tables:
  proposals          — pipeline_run_id PK, JSON blob of FinalProposal
  installations      — installation_id PK, baseline JSON blobs
  telemetry          — append-only per-installation EEBus readings
  optimization_history — per-installation OptimizationDelta records

The database file lives at  <project_root>/data/assessor.db  in production.
Tests override this via the DATABASE_URL env var (sqlite:///:memory:).
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine setup — DATABASE_URL env var lets tests inject sqlite:///:memory:
# ---------------------------------------------------------------------------

_default_db_path = Path(__file__).resolve().parents[2] / "data" / "assessor.db"
_default_db_path.parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{_default_db_path}")

_is_memory = DATABASE_URL == "sqlite:///:memory:"
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# StaticPool is required for in-memory SQLite so all sessions share the same
# underlying connection and therefore the same database contents.
engine = create_engine(
    DATABASE_URL,
    connect_args=_connect_args,
    echo=False,
    **({"poolclass": StaticPool} if _is_memory else {}),
)
_SessionFactory = sessionmaker(bind=engine, autocommit=False, autoflush=False)


# ---------------------------------------------------------------------------
# ORM table definitions
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class ProposalRow(Base):
    __tablename__ = "proposals"

    pipeline_run_id = Column(String, primary_key=True)
    data = Column(Text, nullable=False)          # JSON-serialized FinalProposal
    created_at = Column(DateTime, nullable=False)


class InstallationRow(Base):
    __tablename__ = "installations"

    installation_id = Column(String, primary_key=True)
    pipeline_run_id = Column(String, nullable=False)
    baseline_consumption = Column(Text, nullable=False)   # JSON
    baseline_profile = Column(Text, nullable=False)       # JSON
    created_at = Column(DateTime, nullable=False)


class TelemetryRow(Base):
    __tablename__ = "telemetry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    installation_id = Column(String, ForeignKey("installations.installation_id"), nullable=False)
    data = Column(Text, nullable=False)          # JSON-serialized TelemetryPoint
    timestamp = Column(DateTime, nullable=False)


class OptimizationRow(Base):
    __tablename__ = "optimization_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    installation_id = Column(String, ForeignKey("installations.installation_id"), nullable=False)
    data = Column(Text, nullable=False)          # JSON-serialized OptimizationDelta
    optimized_at = Column(DateTime, nullable=False)


# ---------------------------------------------------------------------------
# Session helper
# ---------------------------------------------------------------------------


@contextmanager
def get_session() -> Generator[Session, None, None]:
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Table initialisation — runs once at import so both tests and server work
# ---------------------------------------------------------------------------


def create_tables() -> None:
    Base.metadata.create_all(engine)
    logger.debug("Database tables ensured at %s", DATABASE_URL)


create_tables()
