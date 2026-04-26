"""
Unit tests for backward compatibility of the Weather Intelligence & House Dimensions feature.

Verifies:
- POST /api/v1/assess without location → static climate data, same response format (Req 17.1)
- POST /api/v1/assess with location → weather_profile_available: true (Req 17.2, 17.3)
- WeatherProfile with extra fields → rejected by Pydantic strict mode (Req 9.1)
- WeatherProfile with missing fields → rejected (Req 9.1)

Requirements: 17.1, 17.2, 17.3, 9.1
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.agents.orchestrator.agent import PipelineError, PipelineSuccess
from src.agents.safety.validator import validate_handoff, SCHEMA_REGISTRY
from src.common.schemas import (
    BatteryDesign,
    CleaningSchedule,
    Compliance,
    FinalProposal,
    FinancialSummary,
    HeatPumpDesign,
    HumanSignoff,
    InverterType,
    ProposalMetadata,
    PVDesign,
    SignoffStatus,
    SimpleMetadata,
    SystemDesign,
    WeatherProfile,
)
from src.web.app import app
from src.web.store import proposal_store


# ============================================================================
# Helpers
# ============================================================================

def _make_final_proposal(pipeline_run_id: str | None = None) -> FinalProposal:
    run_id = pipeline_run_id or str(uuid.uuid4())
    return FinalProposal(
        system_design=SystemDesign(
            pv=PVDesign(total_kwp=6.4, panel_count=16, inverter_type=InverterType.HYBRID.value),
            battery=BatteryDesign(included=True, capacity_kwh=10.0),
            heat_pump=HeatPumpDesign(included=True, capacity_kw=10.0),
        ),
        financial_summary=FinancialSummary(
            total_cost_eur=25000.0, annual_savings_eur=2780.0, payback_years=9.0
        ),
        compliance=Compliance(
            electrical_upgrades=[],
            regulatory_notes=["Human installer sign-off required"],
        ),
        human_signoff=HumanSignoff(required=True, status=SignoffStatus.PENDING),
        metadata=ProposalMetadata(
            version="1.0.0",
            generated_at=datetime.now(timezone.utc),
            pipeline_run_id=run_id,
        ),
    )


def _make_valid_weather_profile_dict() -> dict:
    """Return a minimal valid WeatherProfile as a plain dict."""
    monthly_12 = [5.0] * 12
    return {
        "latitude": 52.5,
        "longitude": 13.4,
        "data_source": "open-meteo-archive",
        "date_range_start": "2019-01-01",
        "date_range_end": "2023-12-31",
        "monthly_sunshine_hours": monthly_12,
        "monthly_precipitation_mm": monthly_12,
        "monthly_cloud_cover_pct": monthly_12,
        "monthly_wind_speed_ms": monthly_12,
        "monthly_avg_temperature_c": monthly_12,
        "annual_irradiance_kwh_m2": 1050.0,
        "sunny_days_per_year": 150,
        "seasonal_sunshine_hours": [3.0, 6.0, 8.0, 4.0],
        "optimal_installation_quarter": 2,
        "quarter_rankings": [2, 3, 4, 1],
        "cleaning_schedule": {
            "frequency_per_year": 2,
            "recommended_months": [4, 9],
        },
        "metadata": {"timestamp": "2024-01-01T00:00:00Z"},
    }


def _upload_files(client: TestClient, location: str | None = None):
    """POST /api/v1/assess with minimal fake files and optional location."""
    data = {}
    if location is not None:
        data["location"] = location
    return client.post(
        "/api/v1/assess",
        files={
            "video": ("roof.mp4", b"fake_video", "video/mp4"),
            "photo": ("panel.jpg", b"fake_photo", "image/jpeg"),
            "bill": ("bill.pdf", b"fake_bill", "application/pdf"),
        },
        data=data,
    )


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def clear_store():
    proposal_store.clear()
    yield
    proposal_store.clear()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ============================================================================
# Tests: Backward compatibility — no location field (Req 17.1)
# ============================================================================

class TestNoLocationBackwardCompatibility:
    """POST /api/v1/assess without location must behave identically to the pre-feature API."""

    def test_response_has_pipeline_run_id(self, client):
        """Response must include pipeline_run_id regardless of location presence."""
        success = PipelineSuccess(proposal=_make_final_proposal())
        with patch("src.web.routes.assess.run_pipeline", new=AsyncMock(return_value=success)):
            response = _upload_files(client)

        assert response.status_code == 200
        assert "pipeline_run_id" in response.json()

    def test_response_has_status_completed(self, client):
        """Response status must be 'completed' when no location is provided."""
        success = PipelineSuccess(proposal=_make_final_proposal())
        with patch("src.web.routes.assess.run_pipeline", new=AsyncMock(return_value=success)):
            response = _upload_files(client)

        assert response.json()["status"] == "completed"

    def test_weather_profile_available_is_false_without_location(self, client):
        """weather_profile_available must be False when no location is provided (Req 17.3)."""
        success = PipelineSuccess(proposal=_make_final_proposal(), weather_profile_available=False)
        with patch("src.web.routes.assess.run_pipeline", new=AsyncMock(return_value=success)):
            response = _upload_files(client)

        data = response.json()
        assert data["weather_profile_available"] is False

    def test_run_pipeline_called_without_location(self, client):
        """run_pipeline must be called with location=None when no location field is sent."""
        success = PipelineSuccess(proposal=_make_final_proposal())
        mock = AsyncMock(return_value=success)
        with patch("src.web.routes.assess.run_pipeline", new=mock):
            _upload_files(client, location=None)

        _, kwargs = mock.call_args
        assert kwargs.get("location") is None

    def test_response_format_unchanged(self, client):
        """Response JSON must include all pre-existing fields (Req 17.1)."""
        success = PipelineSuccess(proposal=_make_final_proposal())
        with patch("src.web.routes.assess.run_pipeline", new=AsyncMock(return_value=success)):
            response = _upload_files(client)

        data = response.json()
        # All fields that existed before the feature must still be present
        assert "pipeline_run_id" in data
        assert "status" in data
        # New optional fields must be present but may be null
        assert "weather_profile_available" in data
        assert "mesh_uri" in data
        assert "point_cloud_uri" in data


# ============================================================================
# Tests: With location field (Req 17.2, 17.3)
# ============================================================================

class TestWithLocationField:
    """POST /api/v1/assess with location must produce weather_profile_available: true."""

    def test_weather_profile_available_true_when_location_provided(self, client):
        """weather_profile_available must be True when location is provided and weather succeeds."""
        success = PipelineSuccess(
            proposal=_make_final_proposal(), weather_profile_available=True
        )
        with patch("src.web.routes.assess.run_pipeline", new=AsyncMock(return_value=success)):
            response = _upload_files(client, location="Berlin, Germany")

        assert response.status_code == 200
        assert response.json()["weather_profile_available"] is True

    def test_run_pipeline_called_with_location(self, client):
        """run_pipeline must receive the location string when provided."""
        success = PipelineSuccess(proposal=_make_final_proposal(), weather_profile_available=True)
        mock = AsyncMock(return_value=success)
        with patch("src.web.routes.assess.run_pipeline", new=mock):
            _upload_files(client, location="Hamburg")

        _, kwargs = mock.call_args
        assert kwargs.get("location") == "Hamburg"

    def test_weather_profile_available_false_when_service_fails(self, client):
        """weather_profile_available must be False when weather service fails (soft failure)."""
        success = PipelineSuccess(
            proposal=_make_final_proposal(), weather_profile_available=False
        )
        with patch("src.web.routes.assess.run_pipeline", new=AsyncMock(return_value=success)):
            response = _upload_files(client, location="Unknown Place XYZ")

        assert response.status_code == 200
        assert response.json()["weather_profile_available"] is False

    def test_response_format_same_with_location(self, client):
        """Response format must be identical whether or not location is provided."""
        success = PipelineSuccess(proposal=_make_final_proposal(), weather_profile_available=True)
        with patch("src.web.routes.assess.run_pipeline", new=AsyncMock(return_value=success)):
            response = _upload_files(client, location="Munich")

        data = response.json()
        assert "pipeline_run_id" in data
        assert "status" in data
        assert "weather_profile_available" in data


# ============================================================================
# Tests: WeatherProfile schema strict-mode validation (Req 9.1)
# ============================================================================

class TestWeatherProfileSchemaValidation:
    """WeatherProfile must be registered in SCHEMA_REGISTRY and enforce strict mode."""

    def test_weather_profile_registered_in_schema_registry(self):
        """WeatherProfile must be in SCHEMA_REGISTRY for Safety Gate 1 validation."""
        assert "WeatherProfile" in SCHEMA_REGISTRY
        assert SCHEMA_REGISTRY["WeatherProfile"] is WeatherProfile

    def test_valid_weather_profile_passes_validation(self):
        """A fully valid WeatherProfile dict must pass validate_handoff."""
        data = _make_valid_weather_profile_dict()
        instance, result = validate_handoff(data, "WeatherProfile", "weather_service")
        assert result.valid, f"Expected valid but got errors: {result.errors}"
        assert isinstance(instance, WeatherProfile)

    def test_weather_profile_with_extra_fields_rejected(self):
        """WeatherProfile with extra fields must be rejected (extra='forbid')."""
        data = _make_valid_weather_profile_dict()
        data["unexpected_field"] = "should_be_rejected"

        instance, result = validate_handoff(data, "WeatherProfile", "weather_service")

        assert not result.valid, "Expected validation to fail for extra field"
        error_messages = " ".join(e.message for e in result.errors)
        # Pydantic v2 reports extra fields as "Extra inputs are not permitted"
        assert any(
            "extra" in e.message.lower() or "not permitted" in e.message.lower()
            for e in result.errors
        ), f"Expected extra-field error, got: {error_messages}"

    def test_weather_profile_missing_required_field_rejected(self):
        """WeatherProfile missing a required field must be rejected."""
        data = _make_valid_weather_profile_dict()
        del data["annual_irradiance_kwh_m2"]  # required field

        instance, result = validate_handoff(data, "WeatherProfile", "weather_service")

        assert not result.valid, "Expected validation to fail for missing field"
        assert any(
            "annual_irradiance_kwh_m2" in e.field or "missing" in e.message.lower()
            for e in result.errors
        )

    def test_weather_profile_wrong_type_rejected(self):
        """WeatherProfile with wrong field type must be rejected."""
        data = _make_valid_weather_profile_dict()
        data["latitude"] = "not-a-float"  # must be float

        instance, result = validate_handoff(data, "WeatherProfile", "weather_service")

        assert not result.valid

    def test_weather_profile_lat_outside_germany_rejected(self):
        """WeatherProfile with latitude outside Germany bbox must be rejected by schema."""
        data = _make_valid_weather_profile_dict()
        data["latitude"] = 60.0  # outside 47.0–55.5

        instance, result = validate_handoff(data, "WeatherProfile", "weather_service")

        assert not result.valid

    def test_weather_profile_lon_outside_germany_rejected(self):
        """WeatherProfile with longitude outside Germany bbox must be rejected by schema."""
        data = _make_valid_weather_profile_dict()
        data["longitude"] = 20.0  # outside 5.5–15.5

        instance, result = validate_handoff(data, "WeatherProfile", "weather_service")

        assert not result.valid

    def test_weather_profile_monthly_array_wrong_length_rejected(self):
        """WeatherProfile with monthly array of wrong length must be rejected."""
        data = _make_valid_weather_profile_dict()
        data["monthly_sunshine_hours"] = [5.0] * 11  # must be exactly 12

        instance, result = validate_handoff(data, "WeatherProfile", "weather_service")

        assert not result.valid

    def test_weather_profile_irradiance_out_of_range_rejected_by_guardrails(self):
        """WeatherProfile with irradiance outside Germany range must fail guardrails."""
        data = _make_valid_weather_profile_dict()
        # ge=0 in schema, but guardrail checks 700–1400 range
        data["annual_irradiance_kwh_m2"] = 500.0  # below Germany minimum

        instance, result = validate_handoff(data, "WeatherProfile", "weather_service")

        assert not result.valid
        assert any("irradiance" in e.message.lower() for e in result.errors)

    def test_weather_profile_invalid_quarter_rankings_rejected(self):
        """WeatherProfile with quarter_rankings not a permutation of [1,2,3,4] must fail."""
        data = _make_valid_weather_profile_dict()
        data["quarter_rankings"] = [1, 1, 2, 3]  # duplicate, not a permutation

        instance, result = validate_handoff(data, "WeatherProfile", "weather_service")

        assert not result.valid
        assert any("quarter_rankings" in e.field for e in result.errors)

    def test_weather_profile_optimal_quarter_mismatch_rejected(self):
        """WeatherProfile where quarter_rankings[0] != optimal_installation_quarter must fail."""
        data = _make_valid_weather_profile_dict()
        data["quarter_rankings"] = [2, 3, 4, 1]
        data["optimal_installation_quarter"] = 3  # mismatch: rankings[0]=2 but optimal=3

        instance, result = validate_handoff(data, "WeatherProfile", "weather_service")

        assert not result.valid
        assert any("optimal" in e.message.lower() or "mismatch" in e.message.lower()
                   for e in result.errors)
