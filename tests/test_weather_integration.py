"""
Integration tests for the Weather Intelligence & House Dimensions feature.

Tests the full pipeline with and without location, verifying:
- WeatherProfile flows through all agents when location is provided (Req 1.4, 8.3)
- No weather API calls are made when location is omitted (Req 17.1)
- Safety Gate 1 validates WeatherProfile when present (Req 9.3)
- Pipeline falls back gracefully when weather service fails (Req 2.4)

Requirements: 1.4, 8.3, 9.3, 17.1
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from src.agents.orchestrator.agent import PipelineError, PipelineSuccess, run_pipeline
from src.agents.safety.validator import validate_handoff
from src.agents.synthesis.pioneer_client import ComponentPricing
from src.common.schemas import (
    BoardCondition,
    Breaker,
    BreakerType,
    CalculationMetadata,
    CleaningSchedule,
    ConsumptionData,
    Currency,
    ElectricalData,
    HeatingFuel,
    IngestionMetadata,
    InverterType,
    MainSupply,
    MonthlyConsumption,
    Obstacle,
    ObstacleType,
    RoofData,
    RoofFace,
    RoofTypology,
    SimpleMetadata,
    SourceType,
    SpatialData,
    Tariff,
    UtilityRoom,
    WeatherProfile,
)


# ============================================================================
# Pre-baked fixtures (same as test_pipeline_e2e.py)
# ============================================================================

_NOW = datetime.now(timezone.utc)


def _make_spatial_data() -> SpatialData:
    return SpatialData(
        roof=RoofData(
            typology=RoofTypology.GABLE,
            faces=[
                RoofFace(
                    id="south",
                    orientation_deg=180,
                    tilt_deg=35,
                    area_m2=40.0,
                    length_m=8.0,
                    width_m=5.0,
                )
            ],
            total_usable_area_m2=38.0,
            obstacles=[
                Obstacle(
                    type=ObstacleType.CHIMNEY,
                    face_id="south",
                    area_m2=2.0,
                    buffer_m=0.3,
                )
            ],
        ),
        utility_room=UtilityRoom(
            length_m=3.0,
            width_m=2.5,
            height_m=2.4,
            available_volume_m3=8.0,
            existing_pipework=True,
        ),
        metadata=IngestionMetadata(
            source_type=SourceType.VIDEO,
            confidence_score=0.88,
            timestamp=_NOW,
            gemini_model_version="gemini-2.5-flash",
        ),
    )


def _make_electrical_data() -> ElectricalData:
    from src.common.schemas import BoardCondition, Breaker, BreakerType, MainSupply
    return ElectricalData(
        main_supply=MainSupply(amperage_A=100, phases=3, voltage_V=400),
        breakers=[
            Breaker(label="Heating", rating_A=32, type=BreakerType.MCB),
            Breaker(label="Lights", rating_A=16, type=BreakerType.MCB),
        ],
        board_condition=BoardCondition.GOOD,
        spare_ways=4,
        metadata=IngestionMetadata(
            source_type=SourceType.PHOTO,
            confidence_score=0.91,
            timestamp=_NOW,
        ),
    )


def _make_consumption_data() -> ConsumptionData:
    monthly_kwh = 8500 / 12
    return ConsumptionData(
        annual_kwh=8500.0,
        monthly_breakdown=[
            MonthlyConsumption(month=m, kwh=round(monthly_kwh, 1))
            for m in range(1, 13)
        ],
        tariff=Tariff(
            currency=Currency.EUR,
            rate_per_kwh=0.32,
            feed_in_tariff_per_kwh=0.082,
        ),
        heating_fuel=HeatingFuel.GAS,
        annual_heating_kwh=12000.0,
        has_ev=False,
        metadata=IngestionMetadata(
            source_type=SourceType.PDF,
            confidence_score=0.95,
            timestamp=_NOW,
            bill_period_start=date(2024, 1, 1),
            bill_period_end=date(2024, 12, 31),
        ),
    )


def _make_pricing() -> ComponentPricing:
    return ComponentPricing(
        pv_cost_eur=7680.0,
        battery_cost_eur=8000.0,
        heat_pump_cost_eur=11000.0,
        panel_model="JA Solar JAM54S30-400",
        inverter_model="SolarEdge SE6000H",
        battery_model="BYD HVS 10.2",
        heat_pump_model="Vaillant aroTHERM plus 10",
        source="rule_based_fallback",
    )


def _make_weather_profile() -> WeatherProfile:
    """Build a valid WeatherProfile for Berlin."""
    monthly_12 = [5.0] * 12
    return WeatherProfile(
        latitude=52.52,
        longitude=13.40,
        data_source="open-meteo-archive",
        date_range_start=date(2019, 1, 1),
        date_range_end=date(2023, 12, 31),
        monthly_sunshine_hours=monthly_12,
        monthly_precipitation_mm=monthly_12,
        monthly_cloud_cover_pct=[50.0] * 12,
        monthly_wind_speed_ms=monthly_12,
        monthly_avg_temperature_c=[-2.0, 0.0, 5.0, 10.0, 15.0, 18.0, 20.0, 19.0, 14.0, 9.0, 3.0, -1.0],
        annual_irradiance_kwh_m2=1050.0,
        sunny_days_per_year=150,
        seasonal_sunshine_hours=[3.0, 6.0, 8.0, 4.0],
        optimal_installation_quarter=2,
        quarter_rankings=[2, 3, 4, 1],
        cleaning_schedule=CleaningSchedule(
            frequency_per_year=2,
            recommended_months=[4, 9],
        ),
        metadata=SimpleMetadata(timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc)),
    )


@pytest.fixture
def tmp_media(tmp_path: Path):
    """Three non-empty temp files to pass orchestrator pre-flight check."""
    video = tmp_path / "roof.mp4"
    photo = tmp_path / "panel.jpg"
    pdf = tmp_path / "bill.pdf"
    video.write_bytes(b"fake-video")
    photo.write_bytes(b"fake-photo")
    pdf.write_bytes(b"fake-pdf")
    return video, photo, pdf


# ============================================================================
# Test: Full pipeline WITHOUT location (Req 17.1)
# ============================================================================

class TestPipelineWithoutLocation:
    """Pipeline without location must use static climate data and make no weather API calls."""

    def _run(self, coro):
        return asyncio.run(coro)

    @pytest.fixture(autouse=True)
    def _mock_agents(self):
        with (
            patch("src.agents.ingestion.agent.process_video",
                  new=AsyncMock(return_value=_make_spatial_data())),
            patch("src.agents.ingestion.agent.process_photo",
                  new=AsyncMock(return_value=_make_electrical_data())),
            patch("src.agents.ingestion.agent.process_pdf",
                  new=AsyncMock(return_value=_make_consumption_data())),
            patch("src.agents.synthesis.pioneer_client.get_component_pricing",
                  new=AsyncMock(return_value=_make_pricing())),
        ):
            yield

    def test_pipeline_succeeds_without_location(self, tmp_media):
        """Pipeline must complete successfully when no location is provided."""
        video, photo, pdf = tmp_media
        result = self._run(run_pipeline(video, photo, pdf))
        assert not isinstance(result, PipelineError), f"Pipeline failed: {result}"
        assert isinstance(result, PipelineSuccess)

    def test_weather_profile_available_false_without_location(self, tmp_media):
        """weather_profile_available must be False when no location is provided (Req 17.1)."""
        video, photo, pdf = tmp_media
        result = self._run(run_pipeline(video, photo, pdf))
        assert not isinstance(result, PipelineError)
        assert result.weather_profile_available is False

    def test_no_weather_api_calls_without_location(self, tmp_media):
        """WeatherIntelligenceService must not be called when no location is provided."""
        video, photo, pdf = tmp_media
        with patch(
            "src.agents.orchestrator.agent.WeatherIntelligenceService"
        ) as mock_service_cls:
            self._run(run_pipeline(video, photo, pdf))
        # Service should never be instantiated when location is None
        mock_service_cls.assert_not_called()

    def test_static_climate_note_in_compliance_without_location(self, tmp_media):
        """Compliance notes must reference static regional data when no location is given."""
        video, photo, pdf = tmp_media
        result = self._run(run_pipeline(video, photo, pdf))
        assert not isinstance(result, PipelineError)
        notes_text = " ".join(result.compliance.regulatory_notes)
        # Static path includes "region=" in the note
        assert "region=" in notes_text

    def test_proposal_structure_unchanged_without_location(self, tmp_media):
        """FinalProposal structure must be identical to pre-feature behavior."""
        video, photo, pdf = tmp_media
        result = self._run(run_pipeline(video, photo, pdf))
        assert not isinstance(result, PipelineError)
        proposal = result.proposal
        assert proposal.system_design is not None
        assert proposal.financial_summary is not None
        assert proposal.compliance is not None
        assert proposal.human_signoff.required is True


# ============================================================================
# Test: Full pipeline WITH location (Req 1.4, 8.3)
# ============================================================================

class TestPipelineWithLocation:
    """Pipeline with location must fetch WeatherProfile and pass it through all agents."""

    def _run(self, coro):
        return asyncio.run(coro)

    @pytest.fixture(autouse=True)
    def _mock_agents(self):
        with (
            patch("src.agents.ingestion.agent.process_video",
                  new=AsyncMock(return_value=_make_spatial_data())),
            patch("src.agents.ingestion.agent.process_photo",
                  new=AsyncMock(return_value=_make_electrical_data())),
            patch("src.agents.ingestion.agent.process_pdf",
                  new=AsyncMock(return_value=_make_consumption_data())),
            patch("src.agents.synthesis.pioneer_client.get_component_pricing",
                  new=AsyncMock(return_value=_make_pricing())),
        ):
            yield

    def test_pipeline_succeeds_with_location(self, tmp_media):
        """Pipeline must complete successfully when a valid location is provided."""
        video, photo, pdf = tmp_media
        weather = _make_weather_profile()
        with patch(
            "src.agents.orchestrator.agent.WeatherIntelligenceService"
        ) as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.get_weather_profile.return_value = weather
            mock_cls.return_value = mock_instance

            result = self._run(run_pipeline(video, photo, pdf, location="Berlin"))

        assert not isinstance(result, PipelineError), f"Pipeline failed: {result}"
        assert isinstance(result, PipelineSuccess)

    def test_weather_profile_available_true_with_location(self, tmp_media):
        """weather_profile_available must be True when weather service succeeds (Req 17.3)."""
        video, photo, pdf = tmp_media
        weather = _make_weather_profile()
        with patch(
            "src.agents.orchestrator.agent.WeatherIntelligenceService"
        ) as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.get_weather_profile.return_value = weather
            mock_cls.return_value = mock_instance

            result = self._run(run_pipeline(video, photo, pdf, location="Berlin"))

        assert not isinstance(result, PipelineError)
        assert result.weather_profile_available is True

    def test_weather_service_called_with_location_string(self, tmp_media):
        """WeatherIntelligenceService.get_weather_profile must be called with the location."""
        video, photo, pdf = tmp_media
        weather = _make_weather_profile()
        with patch(
            "src.agents.orchestrator.agent.WeatherIntelligenceService"
        ) as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.get_weather_profile.return_value = weather
            mock_cls.return_value = mock_instance

            self._run(run_pipeline(video, photo, pdf, location="Hamburg"))

        mock_instance.get_weather_profile.assert_called_once_with("Hamburg")

    def test_location_specific_irradiance_in_compliance_note(self, tmp_media):
        """Compliance notes must reference location-specific data when WeatherProfile is used."""
        video, photo, pdf = tmp_media
        weather = _make_weather_profile()
        with patch(
            "src.agents.orchestrator.agent.WeatherIntelligenceService"
        ) as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.get_weather_profile.return_value = weather
            mock_cls.return_value = mock_instance

            result = self._run(run_pipeline(video, photo, pdf, location="Berlin"))

        assert not isinstance(result, PipelineError)
        notes_text = " ".join(result.compliance.regulatory_notes)
        # Location-specific path includes "location-specific" in the note
        assert "location-specific" in notes_text

    def test_annual_yield_uses_location_irradiance(self, tmp_media):
        """PV annual yield must be derived from WeatherProfile irradiance, not static data."""
        video, photo, pdf = tmp_media
        weather = _make_weather_profile()  # irradiance=1050.0, cloud_cover=50%

        with patch(
            "src.agents.orchestrator.agent.WeatherIntelligenceService"
        ) as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.get_weather_profile.return_value = weather
            mock_cls.return_value = mock_instance

            result_with_weather = self._run(run_pipeline(video, photo, pdf, location="Berlin"))

        result_without_weather = self._run(run_pipeline(video, photo, pdf))

        assert not isinstance(result_with_weather, PipelineError)
        assert not isinstance(result_without_weather, PipelineError)

        # Yields should differ because one uses location-specific irradiance + cloud correction
        yield_with = result_with_weather.system_design.pv.annual_yield_kwh
        yield_without = result_without_weather.system_design.pv.annual_yield_kwh
        # Both should be positive
        assert yield_with > 0
        assert yield_without > 0
        # They should differ (different irradiance sources)
        assert yield_with != yield_without


# ============================================================================
# Test: Pipeline fallback when weather service fails (Req 2.4)
# ============================================================================

class TestPipelineWeatherFallback:
    """Pipeline must continue with static data when weather service fails."""

    def _run(self, coro):
        return asyncio.run(coro)

    @pytest.fixture(autouse=True)
    def _mock_agents(self):
        with (
            patch("src.agents.ingestion.agent.process_video",
                  new=AsyncMock(return_value=_make_spatial_data())),
            patch("src.agents.ingestion.agent.process_photo",
                  new=AsyncMock(return_value=_make_electrical_data())),
            patch("src.agents.ingestion.agent.process_pdf",
                  new=AsyncMock(return_value=_make_consumption_data())),
            patch("src.agents.synthesis.pioneer_client.get_component_pricing",
                  new=AsyncMock(return_value=_make_pricing())),
        ):
            yield

    def test_pipeline_continues_when_weather_service_returns_none(self, tmp_media):
        """Pipeline must succeed even when weather service returns None."""
        video, photo, pdf = tmp_media
        with patch(
            "src.agents.orchestrator.agent.WeatherIntelligenceService"
        ) as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.get_weather_profile.return_value = None
            mock_cls.return_value = mock_instance

            result = self._run(run_pipeline(video, photo, pdf, location="Unknown Place"))

        assert not isinstance(result, PipelineError), f"Pipeline failed: {result}"
        assert result.weather_profile_available is False

    def test_pipeline_continues_when_weather_service_raises(self, tmp_media):
        """Pipeline must succeed even when weather service raises an exception."""
        video, photo, pdf = tmp_media
        with patch(
            "src.agents.orchestrator.agent.WeatherIntelligenceService"
        ) as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.get_weather_profile.side_effect = Exception("API timeout")
            mock_cls.return_value = mock_instance

            result = self._run(run_pipeline(video, photo, pdf, location="Berlin"))

        assert not isinstance(result, PipelineError), f"Pipeline failed: {result}"
        assert result.weather_profile_available is False

    def test_static_climate_used_when_weather_fails(self, tmp_media):
        """When weather service fails, compliance note must reference static regional data."""
        video, photo, pdf = tmp_media
        with patch(
            "src.agents.orchestrator.agent.WeatherIntelligenceService"
        ) as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.get_weather_profile.return_value = None
            mock_cls.return_value = mock_instance

            result = self._run(run_pipeline(video, photo, pdf, location="Unknown"))

        assert not isinstance(result, PipelineError)
        notes_text = " ".join(result.compliance.regulatory_notes)
        assert "region=" in notes_text  # static path


# ============================================================================
# Test: Safety Gate 1 validates WeatherProfile (Req 9.3)
# ============================================================================

class TestSafetyGate1WeatherProfile:
    """Safety Gate 1 must validate WeatherProfile when present."""

    def _run(self, coro):
        return asyncio.run(coro)

    @pytest.fixture(autouse=True)
    def _mock_agents(self):
        with (
            patch("src.agents.ingestion.agent.process_video",
                  new=AsyncMock(return_value=_make_spatial_data())),
            patch("src.agents.ingestion.agent.process_photo",
                  new=AsyncMock(return_value=_make_electrical_data())),
            patch("src.agents.ingestion.agent.process_pdf",
                  new=AsyncMock(return_value=_make_consumption_data())),
            patch("src.agents.synthesis.pioneer_client.get_component_pricing",
                  new=AsyncMock(return_value=_make_pricing())),
        ):
            yield

    def test_valid_weather_profile_passes_safety_gate_1(self, tmp_media):
        """A valid WeatherProfile must pass Safety Gate 1 and be used by downstream agents."""
        video, photo, pdf = tmp_media
        weather = _make_weather_profile()
        with patch(
            "src.agents.orchestrator.agent.WeatherIntelligenceService"
        ) as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.get_weather_profile.return_value = weather
            mock_cls.return_value = mock_instance

            result = self._run(run_pipeline(video, photo, pdf, location="Berlin"))

        assert not isinstance(result, PipelineError)
        assert result.weather_profile_available is True

    def test_invalid_weather_profile_falls_back_to_static(self, tmp_media):
        """An invalid WeatherProfile must be discarded at Safety Gate 1 (soft failure)."""
        video, photo, pdf = tmp_media

        # Build a WeatherProfile that will fail guardrail checks
        # (irradiance outside Germany range)
        bad_weather = _make_weather_profile()
        # Bypass Pydantic validation by constructing with model_construct
        bad_weather_dict = bad_weather.model_dump(mode="json")
        bad_weather_dict["annual_irradiance_kwh_m2"] = 200.0  # below 700 minimum

        # Patch validate_handoff to simulate a WeatherProfile that passes schema
        # but fails guardrails — we do this by returning the bad profile from the service
        # and letting the real Safety Gate 1 reject it
        bad_profile = WeatherProfile.model_construct(**{
            **bad_weather.model_dump(),
            "annual_irradiance_kwh_m2": 200.0,
        })

        with patch(
            "src.agents.orchestrator.agent.WeatherIntelligenceService"
        ) as mock_cls:
            mock_instance = AsyncMock()
            mock_instance.get_weather_profile.return_value = bad_profile
            mock_cls.return_value = mock_instance

            result = self._run(run_pipeline(video, photo, pdf, location="Berlin"))

        # Pipeline must still succeed (soft failure — falls back to static data)
        assert not isinstance(result, PipelineError), f"Pipeline failed: {result}"
        # weather_profile_available must be False since the profile was discarded
        assert result.weather_profile_available is False

    def test_weather_profile_validate_handoff_accepts_valid_profile(self):
        """validate_handoff must accept a valid WeatherProfile dict."""
        weather = _make_weather_profile()
        data = weather.model_dump(mode="json")

        instance, result = validate_handoff(data, "WeatherProfile", "weather_service")

        assert result.valid, f"Expected valid WeatherProfile, got errors: {result.errors}"
        assert isinstance(instance, WeatherProfile)

    def test_weather_profile_validate_handoff_rejects_invalid_irradiance(self):
        """validate_handoff must reject WeatherProfile with irradiance outside Germany range."""
        weather = _make_weather_profile()
        data = weather.model_dump(mode="json")
        data["annual_irradiance_kwh_m2"] = 200.0  # below 700 kWh/m²/year minimum

        instance, result = validate_handoff(data, "WeatherProfile", "weather_service")

        assert not result.valid
        assert any("irradiance" in e.message.lower() for e in result.errors)

    def test_weather_profile_validate_handoff_rejects_bad_quarter_rankings(self):
        """validate_handoff must reject WeatherProfile with invalid quarter_rankings."""
        weather = _make_weather_profile()
        data = weather.model_dump(mode="json")
        data["quarter_rankings"] = [1, 2, 3, 3]  # not a permutation of [1,2,3,4]

        instance, result = validate_handoff(data, "WeatherProfile", "weather_service")

        assert not result.valid
        assert any("quarter_rankings" in e.field for e in result.errors)
