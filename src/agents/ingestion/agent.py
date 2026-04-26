"""
Ingestion Agent — processes video, photo, and PDF inputs via Gemini.

Uses the google-genai SDK (v1+) with its native async client.

Each process_* function:
  1. Validates the file format
  2. Uploads the file to Gemini Files API
  3. Calls the Gemini model with the appropriate prompt
  4. Parses the JSON response into a typed Pydantic schema
  5. Retries up to 3 times with exponential backoff on transient errors
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import google.genai as genai
from google.genai import types as genai_types

from src.common.config import config
from src.common.schemas import (
    ConsumptionData,
    ElectricalData,
    IngestionMetadata,
    SourceType,
    SpatialData,
)
from src.agents.ingestion.media_handler import (
    UnsupportedFormatError,
    validate_pdf_format,
    validate_photo_format,
    validate_video_format,
)
from src.agents.ingestion.frame_extractor import extract_keyframes
from src.agents.ingestion.prompts.pdf_prompt import PDF_EXTRACTION_PROMPT
from src.agents.ingestion.prompts.photo_prompt import PHOTO_EXTRACTION_PROMPT
from src.agents.ingestion.prompts.video_prompt import MULTI_FRAME_VIDEO_PROMPT, VIDEO_EXTRACTION_PROMPT
from src.agents.ingestion.dimension_estimator import estimate_dimensions
from src.agents.ingestion.reconstruction import reconstruct_mesh
from src.common.vision_provider import VisionProviderError, analyze_frames_with_fallback

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gemini client — native async via client.aio
# ---------------------------------------------------------------------------

_client = genai.Client(api_key=config.gemini.api_key)

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------

_RETRY_DELAYS = [1, 2, 4]  # seconds — exponential backoff for 3 retries
_VALID_BREAKER_RATINGS = frozenset({6, 10, 13, 16, 20, 25, 32, 40, 50, 63, 80, 100, 125})
_BREAKER_RATING_RE = re.compile(r"\b(6|10|13|16|20|25|32|40|50|63|80|100|125)\s*A?\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class IngestionError(Exception):
    """Raised when ingestion fails after all retries are exhausted."""

    def __init__(self, source_type: str, message: str) -> None:
        self.source_type = source_type
        super().__init__(f"[{source_type}] {message}")


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ```) if present."""
    pattern = r"^```(?:json)?\s*\n?(.*?)\n?```\s*$"
    match = re.match(pattern, text.strip(), re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _parse_response(response: genai_types.GenerateContentResponse) -> dict:
    """Extract and parse JSON from a Gemini response object."""
    raw_text = response.text
    cleaned = _strip_code_fences(raw_text)
    return json.loads(cleaned)


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


async def _upload_and_generate(file_path: Path, prompt: str) -> dict:
    """
    Upload a file to Gemini Files API and generate content with the given prompt.
    Returns the parsed JSON dict from the model response.
    """
    # Upload file using the async client
    uploaded_file = await _client.aio.files.upload(file=file_path)
    logger.debug("Uploaded file: %s (uri=%s)", file_path.name, uploaded_file.uri)

    # Generate content: pass the prompt text and the uploaded file reference
    response = await _client.aio.models.generate_content(
        model=config.gemini.model_name,
        contents=[prompt, uploaded_file],
    )
    return _parse_response(response)


# ---------------------------------------------------------------------------
# Public async processing functions
# ---------------------------------------------------------------------------


async def process_video(file_path: Path, run_id: str | None = None) -> SpatialData:
    """
    Process a roofline video and return structured SpatialData.

    Extracts keyframes first, then uses the multi-frame vision provider chain
    (Pioneer → Gemini). Falls back to single-blob Gemini if frame-based analysis fails.

    Raises:
        UnsupportedFormatError: immediately if the file extension is invalid.
        IngestionError: after 3 failed retries.
    """
    validate_video_format(file_path)

    import uuid as _uuid
    effective_run_id = run_id or _uuid.uuid4().hex

    # Extract keyframes — fall back to single-blob path if extraction fails
    frames: list[Path] = []
    try:
        frames = extract_keyframes(file_path, effective_run_id)
        logger.debug("process_video: extracted %d keyframes for run %s", len(frames), effective_run_id)
    except Exception as exc:
        logger.warning("process_video: frame extraction failed (%s) — using single-blob path", exc)

    last_exc: Exception | None = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            logger.warning(
                "process_video: attempt %d failed, retrying in %ds — %s",
                attempt,
                delay,
                last_exc,
            )
            await asyncio.sleep(delay)
        try:
            if frames:
                prompt = MULTI_FRAME_VIDEO_PROMPT.format(n_frames=len(frames))
                data = await analyze_frames_with_fallback(frames, prompt)
            else:
                data = await _upload_and_generate(file_path, VIDEO_EXTRACTION_PROMPT)

            # Strip per-face polygon_vertices_image — stored on faces but not yet in schema
            _strip_extra_face_fields(data)

            confidence_score = float(data.pop("confidence_score", 0.0))
            metadata = IngestionMetadata(
                source_type=SourceType.VIDEO,
                confidence_score=confidence_score,
                timestamp=_now_utc(),
                gemini_model_version=config.gemini.model_name,
            )

            # Estimate house dimensions from keyframes (optional — None on failure)
            house_dimensions = None
            if frames:
                try:
                    house_dimensions = await estimate_dimensions(frames)
                except Exception as dim_exc:
                    logger.warning(
                        "process_video: dimension estimation failed: %s — continuing without dimensions",
                        dim_exc,
                    )

            spatial_data = SpatialData(**data, metadata=metadata, house_dimensions=house_dimensions)

            # Attempt 3D mesh reconstruction from keyframes (Tier 1–3, silent Tier 4 fallback)
            if frames:
                try:
                    recon = await reconstruct_mesh(
                        frames,
                        effective_run_id,
                        spatial_data.model_dump(mode="json"),
                    )
                    if recon is not None:
                        spatial_data = spatial_data.model_copy(update={
                            "mesh_uri": recon.mesh_uri if recon.mesh_uri else None,
                            "point_cloud_uri": recon.point_cloud_uri,
                            "reconstruction_confidence": recon.confidence,
                        })
                        logger.info(
                            "process_video: 3D reconstruction complete (tier=%d, confidence=%.2f)",
                            recon.tier,
                            recon.confidence,
                        )
                except Exception as recon_exc:
                    logger.warning(
                        "process_video: 3D reconstruction failed: %s — continuing in 2D-only mode",
                        recon_exc,
                    )

            return spatial_data
        except UnsupportedFormatError:
            raise
        except (VisionProviderError, Exception) as exc:
            last_exc = exc
            logger.debug("process_video error on attempt %d: %s", attempt + 1, exc)

    raise IngestionError(
        source_type=SourceType.VIDEO,
        message=f"Failed after {len(_RETRY_DELAYS)} retries: {last_exc}",
    )


def _strip_extra_face_fields(data: dict) -> None:
    """Remove fields not yet in the Pydantic schema (phase-4 additions)."""
    for face in data.get("roof", {}).get("faces", []):
        face.pop("confidence_score", None)
        face.pop("polygon_vertices_image", None)


def _coerce_breaker_rating(*candidates: object) -> int | None:
    """Extract a valid standard breaker rating from mixed model output."""
    for value in candidates:
        if isinstance(value, int) and value in _VALID_BREAKER_RATINGS:
            return value
        if isinstance(value, float):
            as_int = int(value)
            if float(as_int) == value and as_int in _VALID_BREAKER_RATINGS:
                return as_int
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
            if value.isdigit():
                as_int = int(value)
                if as_int in _VALID_BREAKER_RATINGS:
                    return as_int
            match = _BREAKER_RATING_RE.search(value)
            if match:
                return int(match.group(1))
    return None


def _sanitize_electrical_payload(data: dict) -> None:
    """Normalize flaky LLM breaker rows so ElectricalData validation remains robust."""
    raw_breakers = data.get("breakers")
    if not isinstance(raw_breakers, list):
        return

    sanitized: list[dict] = []
    for idx, raw in enumerate(raw_breakers):
        if not isinstance(raw, dict):
            continue

        rating = _coerce_breaker_rating(
            raw.get("rating_A"),
            raw.get("label"),
            raw.get("circuit_description"),
        )
        if rating is None:
            logger.warning("process_photo: dropped breaker %d due to missing/invalid rating", idx)
            continue

        breaker_type_raw = raw.get("type")
        if isinstance(breaker_type_raw, str):
            t = breaker_type_raw.strip()
            upper = t.upper()
            if upper in {"MCB", "RCBO", "RCD", "MCCB"}:
                breaker_type = upper
            elif t.lower() == "isolator":
                breaker_type = "isolator"
            else:
                breaker_type = "unknown"
        else:
            breaker_type = "unknown"

        sanitized.append(
            {
                "label": str(raw.get("label") or f"Circuit {idx + 1}"),
                "rating_A": rating,
                "type": breaker_type,
                "circuit_description": raw.get("circuit_description"),
            }
        )

    if not sanitized:
        logger.warning("process_photo: no valid breakers parsed — using a conservative fallback row")
        sanitized = [
            {
                "label": "Unknown circuit",
                "rating_A": 16,
                "type": "unknown",
                "circuit_description": "Auto-generated fallback after parsing failures",
            }
        ]

    data["breakers"] = sanitized


async def process_photo(file_path: Path) -> ElectricalData:
    """
    Process an electrical panel photo and return structured ElectricalData.

    Raises:
        UnsupportedFormatError: immediately if the file extension is invalid.
        IngestionError: after 3 failed retries on Gemini API errors.
    """
    validate_photo_format(file_path)

    last_exc: Exception | None = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            logger.warning(
                "process_photo: attempt %d failed, retrying in %ds — %s",
                attempt,
                delay,
                last_exc,
            )
            await asyncio.sleep(delay)
        try:
            data = await _upload_and_generate(file_path, PHOTO_EXTRACTION_PROMPT)
            _sanitize_electrical_payload(data)
            confidence_score = float(data.pop("confidence_score", 0.0))
            metadata = IngestionMetadata(
                source_type=SourceType.PHOTO,
                confidence_score=confidence_score,
                timestamp=_now_utc(),
                gemini_model_version=config.gemini.model_name,
            )
            return ElectricalData(**data, metadata=metadata)
        except UnsupportedFormatError:
            raise
        except Exception as exc:
            last_exc = exc
            logger.debug("process_photo error on attempt %d: %s", attempt + 1, exc)

    raise IngestionError(
        source_type=SourceType.PHOTO,
        message=f"Failed after {len(_RETRY_DELAYS)} retries: {last_exc}",
    )


async def process_pdf(file_path: Path) -> ConsumptionData:
    """
    Process a utility bill PDF and return structured ConsumptionData.

    Raises:
        UnsupportedFormatError: immediately if the file extension is invalid.
        IngestionError: after 3 failed retries on Gemini API errors.
    """
    validate_pdf_format(file_path)

    last_exc: Exception | None = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            logger.warning(
                "process_pdf: attempt %d failed, retrying in %ds — %s",
                attempt,
                delay,
                last_exc,
            )
            await asyncio.sleep(delay)
        try:
            data = await _upload_and_generate(file_path, PDF_EXTRACTION_PROMPT)
            confidence_score = float(data.pop("confidence_score", 0.0))
            bill_period_start = data.pop("bill_period_start", None)
            bill_period_end = data.pop("bill_period_end", None)

            # Synthesize monthly breakdown if Gemini couldn't extract it
            monthly = data.get("monthly_breakdown") or []
            if len(monthly) < 12:
                annual = float(data.get("annual_kwh") or 3600)
                per_month = round(annual / 12, 1)
                data["monthly_breakdown"] = [{"month": m, "kwh": per_month} for m in range(1, 13)]
                logger.warning(
                    "process_pdf: monthly_breakdown incomplete (%d months) — synthesised uniform distribution from annual_kwh=%.0f",
                    len(monthly),
                    annual,
                )

            metadata = IngestionMetadata(
                source_type=SourceType.PDF,
                confidence_score=confidence_score,
                timestamp=_now_utc(),
                gemini_model_version=config.gemini.model_name,
                bill_period_start=bill_period_start,
                bill_period_end=bill_period_end,
            )
            return ConsumptionData(**data, metadata=metadata)
        except UnsupportedFormatError:
            raise
        except Exception as exc:
            last_exc = exc
            logger.debug("process_pdf error on attempt %d: %s", attempt + 1, exc)

    raise IngestionError(
        source_type=SourceType.PDF,
        message=f"Failed after {len(_RETRY_DELAYS)} retries: {last_exc}",
    )
