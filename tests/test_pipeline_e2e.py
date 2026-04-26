"""
Offline end-to-end pipeline test (D1).

Runs the full orchestrator DAG — Ingestion → Safety Gates → Domain Agents →
Synthesis → FinalProposal — with:
  - Gemini calls replaced by pre-baked SpatialData / ElectricalData / ConsumptionData
  - Pioneer SLM replaced by a stub ComponentPricing
  - Temp files created to pass the orchestrator pre-flight check

No API key required. Tests correctness of the pipeline wiring, safety gate
progression, and FinalProposal structure.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.orchestrator.agent import PipelineError, run_pipeline
from src.agents.synthesis.pioneer_client import ComponentPricing
from src.common.schemas import (
    BoardCondition,
    Breaker,
    BreakerType,
    CalculationMetadata,
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
    SourceType,
    SpatialData,
    Tariff,
    UtilityRoom,
)


# ============================================================================
# Pre-baked ingestion outputs (replace Gemini calls)
# ============================================================================

_NOW = datetime.now(timezone.utc)
_TODAY = date.today()


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
    return ElectricalData(
        main_supply=MainSupply(amperage_A=100, phases=3, voltage_V=400),
        breakers=[
            Breaker(label="Heating", rating_A=32, type=BreakerType.MCB),
            Breaker(label="Lights", rating_A=16, type=BreakerType.MCB),
            Breaker(label="Sockets", rating_A=20, type=BreakerType.RCBO),
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
# Tests
# ============================================================================


class TestPipelineE2E:
    """Full offline pipeline from file paths to FinalProposal."""

    def _run(self, coro):
        return asyncio.run(coro)

    @pytest.fixture(autouse=True)
    def _mock_ingestion_and_pioneer(self):
        """Replace all external calls with pre-baked fixtures."""
        with (
            patch(
                "src.agents.ingestion.agent.process_video",
                new=AsyncMock(return_value=_make_spatial_data()),
            ),
            patch(
                "src.agents.ingestion.agent.process_photo",
                new=AsyncMock(return_value=_make_electrical_data()),
            ),
            patch(
                "src.agents.ingestion.agent.process_pdf",
                new=AsyncMock(return_value=_make_consumption_data()),
            ),
            patch(
                "src.agents.synthesis.pioneer_client.get_component_pricing",
                new=AsyncMock(return_value=_make_pricing()),
            ),
        ):
            yield

    def test_pipeline_returns_final_proposal(self, tmp_media):
        video, photo, pdf = tmp_media
        result = self._run(run_pipeline(video, photo, pdf))
        assert not isinstance(result, PipelineError), f"Pipeline failed: {result}"

    def test_human_signoff_always_required(self, tmp_media):
        video, photo, pdf = tmp_media
        result = self._run(run_pipeline(video, photo, pdf))
        assert not isinstance(result, PipelineError)
        assert result.human_signoff.required is True
        assert result.human_signoff.status.value == "pending"

    def test_pv_design_populated(self, tmp_media):
        video, photo, pdf = tmp_media
        result = self._run(run_pipeline(video, photo, pdf))
        assert not isinstance(result, PipelineError)
        pv = result.system_design.pv
        assert pv.total_kwp > 0
        assert pv.panel_count > 0
        assert pv.annual_yield_kwh is not None and pv.annual_yield_kwh > 0

    def test_financial_summary_positive(self, tmp_media):
        video, photo, pdf = tmp_media
        result = self._run(run_pipeline(video, photo, pdf))
        assert not isinstance(result, PipelineError)
        fin = result.financial_summary
        assert fin.total_cost_eur > 0
        assert fin.annual_savings_eur > 0
        assert fin.payback_years > 0

    def test_metadata_run_id_present(self, tmp_media):
        video, photo, pdf = tmp_media
        result = self._run(run_pipeline(video, photo, pdf))
        assert not isinstance(result, PipelineError)
        assert result.metadata.pipeline_run_id is not None

    def test_two_runs_have_different_run_ids(self, tmp_media):
        video, photo, pdf = tmp_media
        r1 = self._run(run_pipeline(video, photo, pdf))
        r2 = self._run(run_pipeline(video, photo, pdf))
        assert not isinstance(r1, PipelineError)
        assert not isinstance(r2, PipelineError)
        assert r1.metadata.pipeline_run_id != r2.metadata.pipeline_run_id

    def test_climate_note_in_compliance(self, tmp_media):
        video, photo, pdf = tmp_media
        result = self._run(run_pipeline(video, photo, pdf))
        assert not isinstance(result, PipelineError)
        notes_text = " ".join(result.compliance.regulatory_notes)
        assert "region=" in notes_text
        assert "irradiance=" in notes_text

    def test_proposal_round_trip_json(self, tmp_media):
        """FinalProposal must survive a JSON round-trip (schema compliance)."""
        video, photo, pdf = tmp_media
        result = self._run(run_pipeline(video, photo, pdf))
        assert not isinstance(result, PipelineError)
        from src.common.schemas import FinalProposal
        dumped = result.proposal.model_dump(mode="json")
        reloaded = FinalProposal.model_validate(dumped)
        assert reloaded.human_signoff.required is True
