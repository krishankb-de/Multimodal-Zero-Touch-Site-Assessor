"""
House Dimension Estimator.

Extracts approximate building envelope dimensions from roofline video keyframes
using the Gemini multimodal model and a dedicated prompt.

Returns a HouseDimensions schema object on success, or None if dimensions
cannot be determined (pipeline continues without dimension data).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from pydantic import ValidationError

from src.common.schemas import HouseDimensions
from src.agents.ingestion.prompts.dimension_prompt import DIMENSION_ESTIMATION_PROMPT
from src.common.vision_provider import VisionProviderError, analyze_frames_with_fallback

logger = logging.getLogger(__name__)


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences if present."""
    pattern = r"^```(?:json)?\s*\n?(.*?)\n?```\s*$"
    match = re.match(pattern, text.strip(), re.DOTALL)
    return match.group(1).strip() if match else text.strip()


async def estimate_dimensions(frames: list[Path]) -> HouseDimensions | None:
    """
    Estimate building envelope dimensions from video keyframes using Gemini.

    Uses a dedicated prompt that instructs the model to use visual reference
    cues (door heights ~2.1m, window proportions, brick courses) for scale.

    Args:
        frames: List of keyframe image paths extracted from the roofline video.

    Returns:
        HouseDimensions if estimation succeeds with all required fields.
        None if:
          - No frames are provided
          - Gemini returns null or cannot estimate dimensions
          - The response fails HouseDimensions schema validation
          - Any exception occurs during the API call
    """
    if not frames:
        logger.debug("DimensionEstimator: no frames provided, skipping")
        return None

    # Use a subset of frames to keep the prompt focused (max 8 frames)
    selected_frames = frames[:8] if len(frames) > 8 else frames
    logger.debug(
        "DimensionEstimator: estimating dimensions from %d frames", len(selected_frames)
    )

    try:
        raw_result = await analyze_frames_with_fallback(selected_frames, DIMENSION_ESTIMATION_PROMPT)
    except VisionProviderError as exc:
        logger.warning("DimensionEstimator: vision provider failed: %s", exc)
        return None
    except Exception as exc:
        logger.warning("DimensionEstimator: unexpected error during analysis: %s", exc)
        return None

    # Handle null response (model couldn't estimate)
    if raw_result is None:
        logger.info("DimensionEstimator: model returned null — cannot estimate dimensions")
        return None

    # Validate against HouseDimensions schema
    try:
        dimensions = HouseDimensions(**raw_result)
    except (ValidationError, TypeError) as exc:
        logger.warning(
            "DimensionEstimator: response failed schema validation: %s — skipping dimensions",
            exc,
        )
        return None

    # Sanity check: eave must be below ridge
    if dimensions.eave_height_m >= dimensions.ridge_height_m:
        logger.warning(
            "DimensionEstimator: eave_height (%.1f m) >= ridge_height (%.1f m) — "
            "invalid geometry, skipping dimensions",
            dimensions.eave_height_m,
            dimensions.ridge_height_m,
        )
        return None

    logger.info(
        "DimensionEstimator: estimated dimensions — "
        "ridge=%.1f m, eave=%.1f m, width=%.1f m, depth=%.1f m, "
        "wall_area=%.0f m², volume=%.0f m³",
        dimensions.ridge_height_m,
        dimensions.eave_height_m,
        dimensions.footprint_width_m,
        dimensions.footprint_depth_m,
        dimensions.estimated_wall_area_m2,
        dimensions.estimated_volume_m3,
    )
    return dimensions
