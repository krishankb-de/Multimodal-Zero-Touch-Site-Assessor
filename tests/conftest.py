"""Pytest configuration — must be imported before any src modules.

Sets DATABASE_URL to an in-memory SQLite instance so tests never touch
the production database file and tables are recreated fresh each run.
"""

from __future__ import annotations

import os

# Set before any src.web.database import so the engine is created in-memory.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
