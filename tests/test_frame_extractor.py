"""Tests for frame_extractor — uses a synthetic in-memory mp4."""

from __future__ import annotations

import uuid
from pathlib import Path

import cv2
import numpy as np
import pytest

from src.agents.ingestion.frame_extractor import extract_keyframes


def _make_synthetic_video(path: Path, n_frames: int = 60, fps: int = 10) -> None:
    """Write a small synthetic mp4 with solid-color frames."""
    h, w = 120, 160
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (w, h))
    for i in range(n_frames):
        color = int(i * 255 / n_frames)
        frame = np.full((h, w, 3), color, dtype=np.uint8)
        writer.write(frame)
    writer.release()


@pytest.fixture()
def synthetic_video(tmp_path: Path) -> Path:
    p = tmp_path / "test.mp4"
    _make_synthetic_video(p, n_frames=60)
    return p


def test_extract_returns_paths(synthetic_video: Path, tmp_path: Path) -> None:
    run_id = uuid.uuid4().hex
    frames = extract_keyframes(synthetic_video, run_id, n_uniform=12)
    assert len(frames) >= 1
    for f in frames:
        assert f.exists()
        assert f.suffix == ".jpg"


def test_extract_uniform_count(synthetic_video: Path) -> None:
    run_id = uuid.uuid4().hex
    frames = extract_keyframes(synthetic_video, run_id, n_uniform=6, scene_threshold=99.0)
    # With scene_threshold=99.0 only uniform positions fire; expect ~6 frames
    assert 4 <= len(frames) <= 12


def test_extract_scene_change(synthetic_video: Path) -> None:
    run_id = uuid.uuid4().hex
    # Very low threshold — almost every frame is a "scene change"
    frames_low = extract_keyframes(synthetic_video, run_id, n_uniform=1, scene_threshold=0.0)
    run_id2 = uuid.uuid4().hex
    frames_high = extract_keyframes(synthetic_video, run_id2, n_uniform=1, scene_threshold=99.0)
    assert len(frames_low) > len(frames_high)


def test_invalid_video_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(ValueError, match="no frames|Cannot open"):
        extract_keyframes(bad, uuid.uuid4().hex)
