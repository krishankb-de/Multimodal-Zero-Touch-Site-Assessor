"""
Tests for orchestrator pre-flight file validation (C2).

Uses a mock ingestion agent so no API key is required.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

from src.agents.orchestrator.agent import run_pipeline, PipelineError


@pytest.fixture
def tmp_files(tmp_path):
    """Create three valid non-empty temp files."""
    video = tmp_path / "roof.mp4"
    photo = tmp_path / "panel.jpg"
    pdf = tmp_path / "bill.pdf"
    video.write_bytes(b"fake-video-data")
    photo.write_bytes(b"fake-photo-data")
    pdf.write_bytes(b"fake-pdf-data")
    return video, photo, pdf


def run(coro):
    return asyncio.run(coro)


class TestOrchestratorPreflight:
    def test_missing_video_returns_error(self, tmp_files):
        video, photo, pdf = tmp_files
        missing = video.parent / "nonexistent.mp4"
        result = run(run_pipeline(missing, photo, pdf))
        assert isinstance(result, PipelineError)
        assert "video_path" in result.message
        assert result.error_type == "validation_failure"

    def test_missing_photo_returns_error(self, tmp_files):
        video, photo, pdf = tmp_files
        missing = photo.parent / "nonexistent.jpg"
        result = run(run_pipeline(video, missing, pdf))
        assert isinstance(result, PipelineError)
        assert "photo_path" in result.message

    def test_missing_pdf_returns_error(self, tmp_files):
        video, photo, pdf = tmp_files
        missing = pdf.parent / "nonexistent.pdf"
        result = run(run_pipeline(video, photo, missing))
        assert isinstance(result, PipelineError)
        assert "pdf_path" in result.message

    def test_empty_video_returns_error(self, tmp_files):
        video, photo, pdf = tmp_files
        video.write_bytes(b"")  # truncate to empty
        result = run(run_pipeline(video, photo, pdf))
        assert isinstance(result, PipelineError)
        assert "empty" in result.message.lower()
        assert "video_path" in result.message

    def test_empty_photo_returns_error(self, tmp_files):
        video, photo, pdf = tmp_files
        photo.write_bytes(b"")
        result = run(run_pipeline(video, photo, pdf))
        assert isinstance(result, PipelineError)
        assert "empty" in result.message.lower()
        assert "photo_path" in result.message

    def test_empty_pdf_returns_error(self, tmp_files):
        video, photo, pdf = tmp_files
        pdf.write_bytes(b"")
        result = run(run_pipeline(video, photo, pdf))
        assert isinstance(result, PipelineError)
        assert "empty" in result.message.lower()
        assert "pdf_path" in result.message
