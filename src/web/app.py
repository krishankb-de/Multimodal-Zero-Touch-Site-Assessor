"""FastAPI application for the Zero-Touch Agent Pipeline web layer."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.common.schemas import FinalProposal
from src.web.store import proposal_store  # noqa: F401 — re-exported for convenience

app = FastAPI(
    title="Zero-Touch Site Assessor API",
    description="Multimodal AI pipeline for solar + heat pump proposals",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and include routers after app is created to avoid circular imports
from src.web.routes import assess, proposals  # noqa: E402

app.include_router(assess.router, prefix="/api/v1")
app.include_router(proposals.router, prefix="/api/v1")
