"""Deterministic keyframe extraction from roofline videos."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from src.common.artifact_store import frames_dir

logger = logging.getLogger(__name__)


def extract_keyframes(
    video_path: Path,
    run_id: str,
    n_uniform: int = 24,
    scene_threshold: float = 0.4,
) -> list[Path]:
    """
    Extract keyframes from a video using uniform sampling + scene-change detection.

    Returns list of saved JPEG paths under artifacts/{run_id}/frames/.
    """
    out_dir = frames_dir(run_id)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        raise ValueError(f"Video has no frames: {video_path}")

    # Uniform sampling positions
    step = max(1, total_frames // n_uniform)
    uniform_positions = set(range(0, total_frames, step))

    saved: list[Path] = []
    prev_hist: np.ndarray | None = None
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Scene-change detection via histogram delta
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [64], [0, 256]).flatten()
        hist = hist / (hist.sum() + 1e-9)

        is_scene_change = False
        if prev_hist is not None:
            delta = float(np.sum(np.abs(hist - prev_hist)))
            is_scene_change = delta > scene_threshold
        prev_hist = hist

        if frame_idx in uniform_positions or is_scene_change:
            out_path = out_dir / f"frame_{frame_idx:06d}.jpg"
            cv2.imwrite(str(out_path), frame)
            saved.append(out_path)

        frame_idx += 1

    cap.release()
    logger.debug("Extracted %d keyframes from %s → %s", len(saved), video_path.name, out_dir)
    return saved
