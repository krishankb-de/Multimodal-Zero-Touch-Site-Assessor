"""
Unit tests for the Ingestion Agent.

Tests cover:
- File format validation (valid and invalid formats)
- Gemini API calls with mocked responses for each media type
- confidence_score and gemini_model_version set in metadata
- Retry logic with exponential backoff on API errors
- Structured error response on Gemini failure/timeout
- Round-trip serialization for SpatialData, ElectricalData, ConsumptionData

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 11.1
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.ingestion.agent import IngestionError, process_pdf, process_photo, process_video
from src.agents.ingestion.media_handler import UnsupportedFormatError
from src.common.schemas import ConsumptionData, ElectricalData, SpatialData


# ============================================================================
# Helpers — minimal valid payloads that Gemini would return
# ============================================================================


def _valid_spatial_payload() -> dict:
    """Minimal valid SpatialData payload as Gemini would return it."""
    return {
        "confidence_score": 0.88,
        "roof": {
            "typology": "gable",
            "faces": [
                {
                    "id": "south",
                    "orientation_deg": 180,
                    "tilt_deg": 35,
                    "area_m2": 40,
                    "length_m": 8,
                    "width_m": 5,
                }
            ],
            "total_usable_area_m2": 38,
            "obstacles": [],
        },
        "utility_room": {
            "length_m": 3,
            "width_m": 2.5,
            "height_m": 2.4,
            "available_volume_m3": 12,
            "existing_pipework": True,
            "spatial_constraints": [],
        },
    }


def _valid_electrical_payload() -> dict:
    """Minimal valid ElectricalData payload as Gemini would return it."""
    return {
        "confidence_score": 0.92,
        "main_supply": {"amperage_A": 100, "phases": 1, "voltage_V": 230},
        "breakers": [
            {"label": "Lighting", "rating_A": 6, "type": "MCB"},
            {"label": "Ring Main", "rating_A": 32, "type": "RCBO"},
        ],
        "board_condition": "good",
        "spare_ways": 4,
    }


def _valid_consumption_payload() -> dict:
    """Minimal valid ConsumptionData payload as Gemini would return it."""
    monthly = [{"month": m, "kwh": 350.0} for m in range(1, 13)]
    return {
        "confidence_score": 0.95,
        "bill_period_start": "2024-01-01",
        "bill_period_end": "2024-12-31",
        "annual_kwh": 4200.0,
        "monthly_breakdown": monthly,
        "tariff": {
            "currency": "EUR",
            "rate_per_kwh": 0.32,
            "feed_in_tariff_per_kwh": 0.08,
        },
        "heating_fuel": "gas",
        "annual_heating_kwh": 12000.0,
        "has_ev": False,
    }


def _make_temp_file(tmp_path: Path, name: str) -> Path:
    """Create a zero-byte temp file with the given name."""
    p = tmp_path / name
    p.write_bytes(b"")
    return p


# ============================================================================
# Mock helpers — target the new google-genai SDK
#
# The agent uses _upload_and_generate(file_path, prompt) -> dict internally.
# We mock that coroutine directly to avoid needing a real Gemini connection.
# ============================================================================

UPLOAD_AND_GENERATE = "src.agents.ingestion.agent._upload_and_generate"


# ============================================================================
# Tests: File format validation
# ============================================================================


class TestFileFormatValidation:
    """File format validation must accept valid formats and reject invalid ones."""

    # --- Video ---

    @pytest.mark.parametrize("ext", [".mp4", ".mov", ".webm"])
    def test_valid_video_formats_accepted(self, tmp_path, ext):
        """Valid video extensions must not raise UnsupportedFormatError."""
        f = _make_temp_file(tmp_path, f"video{ext}")
        from src.agents.ingestion.media_handler import validate_video_format
        validate_video_format(f)  # no exception

    @pytest.mark.parametrize("ext", [".avi", ".mkv", ".flv", ".wmv", ".pdf", ".jpg"])
    def test_invalid_video_formats_rejected(self, tmp_path, ext):
        """Invalid video extensions must raise UnsupportedFormatError."""
        f = _make_temp_file(tmp_path, f"video{ext}")
        from src.agents.ingestion.media_handler import validate_video_format
        with pytest.raises(UnsupportedFormatError):
            validate_video_format(f)

    # --- Photo ---

    @pytest.mark.parametrize("ext", [".jpeg", ".jpg", ".png", ".heic"])
    def test_valid_photo_formats_accepted(self, tmp_path, ext):
        """Valid photo extensions must not raise UnsupportedFormatError."""
        f = _make_temp_file(tmp_path, f"photo{ext}")
        from src.agents.ingestion.media_handler import validate_photo_format
        validate_photo_format(f)  # no exception

    @pytest.mark.parametrize("ext", [".bmp", ".gif", ".tiff", ".mp4", ".pdf"])
    def test_invalid_photo_formats_rejected(self, tmp_path, ext):
        """Invalid photo extensions must raise UnsupportedFormatError."""
        f = _make_temp_file(tmp_path, f"photo{ext}")
        from src.agents.ingestion.media_handler import validate_photo_format
        with pytest.raises(UnsupportedFormatError):
            validate_photo_format(f)

    # --- PDF ---

    def test_valid_pdf_format_accepted(self, tmp_path):
        """PDF extension must not raise UnsupportedFormatError."""
        f = _make_temp_file(tmp_path, "bill.pdf")
        from src.agents.ingestion.media_handler import validate_pdf_format
        validate_pdf_format(f)  # no exception

    @pytest.mark.parametrize("ext", [".doc", ".docx", ".txt", ".jpg", ".mp4"])
    def test_invalid_pdf_formats_rejected(self, tmp_path, ext):
        """Non-PDF extensions must raise UnsupportedFormatError."""
        f = _make_temp_file(tmp_path, f"bill{ext}")
        from src.agents.ingestion.media_handler import validate_pdf_format
        with pytest.raises(UnsupportedFormatError):
            validate_pdf_format(f)

    def test_unsupported_format_error_message_is_descriptive(self, tmp_path):
        """UnsupportedFormatError message must mention the rejected format."""
        f = _make_temp_file(tmp_path, "video.avi")
        from src.agents.ingestion.media_handler import validate_video_format
        with pytest.raises(UnsupportedFormatError, match=r"\.avi"):
            validate_video_format(f)

    @pytest.mark.asyncio
    async def test_invalid_format_rejected_before_gemini_call(self, tmp_path):
        """Invalid format must raise before any Gemini API call is made."""
        f = _make_temp_file(tmp_path, "video.avi")
        with patch(UPLOAD_AND_GENERATE, new=AsyncMock()) as mock_upload:
            with pytest.raises(UnsupportedFormatError):
                await process_video(f)
            mock_upload.assert_not_called()


# ============================================================================
# Tests: Gemini API calls with mocked responses
# ============================================================================


class TestGeminiAPICallsMocked:
    """Gemini API calls must produce correctly typed Pydantic models."""

    @pytest.mark.asyncio
    async def test_process_video_returns_spatial_data(self, tmp_path):
        """process_video must return a SpatialData instance."""
        f = _make_temp_file(tmp_path, "roof.mp4")
        with patch(UPLOAD_AND_GENERATE, new=AsyncMock(return_value=_valid_spatial_payload())):
            result = await process_video(f)

        assert isinstance(result, SpatialData)
        assert result.roof.typology.value == "gable"
        assert len(result.roof.faces) == 1

    @pytest.mark.asyncio
    async def test_process_photo_returns_electrical_data(self, tmp_path):
        """process_photo must return an ElectricalData instance."""
        f = _make_temp_file(tmp_path, "panel.jpg")
        with patch(UPLOAD_AND_GENERATE, new=AsyncMock(return_value=_valid_electrical_payload())):
            result = await process_photo(f)

        assert isinstance(result, ElectricalData)
        assert result.main_supply.amperage_A == 100
        assert len(result.breakers) == 2

    @pytest.mark.asyncio
    async def test_process_photo_sanitizes_missing_breaker_ratings(self, tmp_path):
        """process_photo should normalize malformed breaker rows instead of failing validation."""
        f = _make_temp_file(tmp_path, "panel.jpg")
        payload = {
            "confidence_score": 0.85,
            "main_supply": {"amperage_A": 80, "phases": 1, "voltage_V": 230},
            "breakers": [
                {"label": "Sockets 16A", "rating_A": None, "type": "MCB"},
                {"label": "Lighting", "rating_A": None, "type": "unknown"},
            ],
            "board_condition": "fair",
            "spare_ways": 2,
        }
        with patch(UPLOAD_AND_GENERATE, new=AsyncMock(return_value=payload)):
            result = await process_photo(f)

        assert isinstance(result, ElectricalData)
        assert len(result.breakers) >= 1
        assert all(isinstance(b.rating_A, int) for b in result.breakers)

    @pytest.mark.asyncio
    async def test_process_pdf_returns_consumption_data(self, tmp_path):
        """process_pdf must return a ConsumptionData instance."""
        f = _make_temp_file(tmp_path, "bill.pdf")
        with patch(UPLOAD_AND_GENERATE, new=AsyncMock(return_value=_valid_consumption_payload())):
            result = await process_pdf(f)

        assert isinstance(result, ConsumptionData)
        assert result.annual_kwh == 4200.0
        assert len(result.monthly_breakdown) == 12


# ============================================================================
# Tests: Metadata fields (confidence_score, gemini_model_version)
# ============================================================================


class TestMetadataFields:
    """confidence_score and gemini_model_version must be set in metadata."""

    @pytest.mark.asyncio
    async def test_confidence_score_set_from_gemini_response(self, tmp_path):
        """confidence_score in metadata must match the value from Gemini response."""
        f = _make_temp_file(tmp_path, "roof.mp4")
        payload = _valid_spatial_payload()
        payload["confidence_score"] = 0.77
        with patch(UPLOAD_AND_GENERATE, new=AsyncMock(return_value=payload)):
            result = await process_video(f)

        assert result.metadata.confidence_score == pytest.approx(0.77)

    @pytest.mark.asyncio
    async def test_gemini_model_version_set_in_metadata(self, tmp_path):
        """gemini_model_version must be set to the configured model name."""
        f = _make_temp_file(tmp_path, "panel.jpg")
        with patch(UPLOAD_AND_GENERATE, new=AsyncMock(return_value=_valid_electrical_payload())):
            result = await process_photo(f)

        assert result.metadata.gemini_model_version is not None
        assert "gemini" in result.metadata.gemini_model_version.lower()

    @pytest.mark.asyncio
    async def test_bill_period_dates_extracted_from_pdf(self, tmp_path):
        """bill_period_start and bill_period_end must be set from PDF response."""
        f = _make_temp_file(tmp_path, "bill.pdf")
        with patch(UPLOAD_AND_GENERATE, new=AsyncMock(return_value=_valid_consumption_payload())):
            result = await process_pdf(f)

        assert result.metadata.bill_period_start is not None
        assert result.metadata.bill_period_end is not None
        assert str(result.metadata.bill_period_start) == "2024-01-01"
        assert str(result.metadata.bill_period_end) == "2024-12-31"

    @pytest.mark.asyncio
    async def test_source_type_set_correctly_for_video(self, tmp_path):
        """source_type must be 'video' for process_video output."""
        f = _make_temp_file(tmp_path, "roof.mp4")
        with patch(UPLOAD_AND_GENERATE, new=AsyncMock(return_value=_valid_spatial_payload())):
            result = await process_video(f)

        assert result.metadata.source_type.value == "video"

    @pytest.mark.asyncio
    async def test_source_type_set_correctly_for_photo(self, tmp_path):
        """source_type must be 'photo' for process_photo output."""
        f = _make_temp_file(tmp_path, "panel.jpg")
        with patch(UPLOAD_AND_GENERATE, new=AsyncMock(return_value=_valid_electrical_payload())):
            result = await process_photo(f)

        assert result.metadata.source_type.value == "photo"

    @pytest.mark.asyncio
    async def test_source_type_set_correctly_for_pdf(self, tmp_path):
        """source_type must be 'pdf' for process_pdf output."""
        f = _make_temp_file(tmp_path, "bill.pdf")
        with patch(UPLOAD_AND_GENERATE, new=AsyncMock(return_value=_valid_consumption_payload())):
            result = await process_pdf(f)

        assert result.metadata.source_type.value == "pdf"


# ============================================================================
# Tests: Retry logic with exponential backoff
# ============================================================================


class TestRetryLogic:
    """Ingestion Agent must retry up to 3 times on API errors."""

    @pytest.mark.asyncio
    async def test_retries_on_api_error_and_succeeds(self, tmp_path):
        """Agent must succeed on the 3rd attempt after 2 failures."""
        f = _make_temp_file(tmp_path, "roof.mp4")
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("Simulated API error")
            return _valid_spatial_payload()

        with patch("src.agents.ingestion.agent.asyncio.sleep"):  # skip actual sleep
            with patch(UPLOAD_AND_GENERATE, side_effect=side_effect):
                result = await process_video(f)

        assert isinstance(result, SpatialData)
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_ingestion_error_after_all_retries_exhausted(self, tmp_path):
        """Agent must raise IngestionError after 3 failed attempts."""
        f = _make_temp_file(tmp_path, "roof.mp4")

        with patch("src.agents.ingestion.agent.asyncio.sleep"):
            with patch(UPLOAD_AND_GENERATE, new=AsyncMock(side_effect=RuntimeError("API down"))):
                with pytest.raises(IngestionError) as exc_info:
                    await process_video(f)

        assert "video" in str(exc_info.value).lower() or "VIDEO" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_ingestion_error_contains_source_type(self, tmp_path):
        """IngestionError must carry the source_type attribute."""
        f = _make_temp_file(tmp_path, "panel.jpg")

        with patch("src.agents.ingestion.agent.asyncio.sleep"):
            with patch(UPLOAD_AND_GENERATE, new=AsyncMock(side_effect=RuntimeError("Timeout"))):
                with pytest.raises(IngestionError) as exc_info:
                    await process_photo(f)

        assert exc_info.value.source_type is not None

    @pytest.mark.asyncio
    async def test_pdf_raises_ingestion_error_after_retries(self, tmp_path):
        """process_pdf must raise IngestionError after all retries fail."""
        f = _make_temp_file(tmp_path, "bill.pdf")

        with patch("src.agents.ingestion.agent.asyncio.sleep"):
            with patch(UPLOAD_AND_GENERATE, new=AsyncMock(side_effect=ConnectionError("Network error"))):
                with pytest.raises(IngestionError):
                    await process_pdf(f)

    @pytest.mark.asyncio
    async def test_unsupported_format_not_retried(self, tmp_path):
        """UnsupportedFormatError must propagate immediately without retrying."""
        f = _make_temp_file(tmp_path, "video.avi")
        with patch(UPLOAD_AND_GENERATE, new=AsyncMock()) as mock_fn:
            with pytest.raises(UnsupportedFormatError):
                await process_video(f)
        # Gemini should never be called for an unsupported format
        mock_fn.assert_not_called()


# ============================================================================
# Tests: Round-trip serialization
# ============================================================================


class TestRoundTripSerialization:
    """Serializing and deserializing each schema must yield an equivalent object."""

    @pytest.mark.asyncio
    async def test_spatial_data_round_trip(self, tmp_path):
        """SpatialData → JSON → SpatialData must yield an equivalent object."""
        f = _make_temp_file(tmp_path, "roof.mp4")
        with patch(UPLOAD_AND_GENERATE, new=AsyncMock(return_value=_valid_spatial_payload())):
            original = await process_video(f)

        json_str = original.model_dump_json()
        restored = SpatialData.model_validate_json(json_str)

        assert restored.roof.typology == original.roof.typology
        assert restored.roof.total_usable_area_m2 == original.roof.total_usable_area_m2
        assert len(restored.roof.faces) == len(original.roof.faces)
        assert restored.metadata.confidence_score == pytest.approx(
            original.metadata.confidence_score
        )

    @pytest.mark.asyncio
    async def test_electrical_data_round_trip(self, tmp_path):
        """ElectricalData → JSON → ElectricalData must yield an equivalent object."""
        f = _make_temp_file(tmp_path, "panel.jpg")
        with patch(UPLOAD_AND_GENERATE, new=AsyncMock(return_value=_valid_electrical_payload())):
            original = await process_photo(f)

        json_str = original.model_dump_json()
        restored = ElectricalData.model_validate_json(json_str)

        assert restored.main_supply.amperage_A == original.main_supply.amperage_A
        assert restored.main_supply.phases == original.main_supply.phases
        assert len(restored.breakers) == len(original.breakers)
        assert restored.metadata.confidence_score == pytest.approx(
            original.metadata.confidence_score
        )

    @pytest.mark.asyncio
    async def test_consumption_data_round_trip(self, tmp_path):
        """ConsumptionData → JSON → ConsumptionData must yield an equivalent object."""
        f = _make_temp_file(tmp_path, "bill.pdf")
        with patch(UPLOAD_AND_GENERATE, new=AsyncMock(return_value=_valid_consumption_payload())):
            original = await process_pdf(f)

        json_str = original.model_dump_json()
        restored = ConsumptionData.model_validate_json(json_str)

        assert restored.annual_kwh == pytest.approx(original.annual_kwh)
        assert len(restored.monthly_breakdown) == len(original.monthly_breakdown)
        assert restored.tariff.rate_per_kwh == pytest.approx(original.tariff.rate_per_kwh)
        assert restored.metadata.bill_period_start == original.metadata.bill_period_start
        assert restored.metadata.bill_period_end == original.metadata.bill_period_end

    @pytest.mark.asyncio
    async def test_round_trip_preserves_metadata_timestamp(self, tmp_path):
        """Metadata timestamp must survive JSON round-trip."""
        f = _make_temp_file(tmp_path, "roof.mp4")
        with patch(UPLOAD_AND_GENERATE, new=AsyncMock(return_value=_valid_spatial_payload())):
            original = await process_video(f)

        json_str = original.model_dump_json()
        restored = SpatialData.model_validate_json(json_str)

        assert restored.metadata.timestamp == original.metadata.timestamp
