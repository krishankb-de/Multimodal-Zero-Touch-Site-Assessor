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
from src.agents.ingestion.prompts.pdf_prompt import PDF_EXTRACTION_PROMPT
from src.agents.ingestion.prompts.photo_prompt import PHOTO_EXTRACTION_PROMPT
from src.agents.ingestion.prompts.video_prompt import VIDEO_EXTRACTION_PROMPT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gemini client — native async via client.aio
# ---------------------------------------------------------------------------

_client = genai.Client(api_key=config.gemini.api_key)

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------

_RETRY_DELAYS = [1, 2, 4]  # seconds — exponential backoff for 3 retries


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


async def process_video(file_path: Path) -> SpatialData:
    """
    Process a roofline video and return structured SpatialData.

    Raises:
        UnsupportedFormatError: immediately if the file extension is invalid.
        IngestionError: after 3 failed retries on Gemini API errors.
    """
    validate_video_format(file_path)

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
            data = await _upload_and_generate(file_path, VIDEO_EXTRACTION_PROMPT)
            confidence_score = float(data.pop("confidence_score", 0.0))
            metadata = IngestionMetadata(
                source_type=SourceType.VIDEO,
                confidence_score=confidence_score,
                timestamp=_now_utc(),
                gemini_model_version=config.gemini.model_name,
            )
            return SpatialData(**data, metadata=metadata)
        except UnsupportedFormatError:
            raise
        except Exception as exc:
            last_exc = exc
            logger.debug("process_video error on attempt %d: %s", attempt + 1, exc)

    raise IngestionError(
        source_type=SourceType.VIDEO,
        message=f"Failed after {len(_RETRY_DELAYS)} retries: {last_exc}",
    )


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
