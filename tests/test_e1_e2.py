"""
Tests for E1 (GLB-grounded roof validator) and E2 (SLD generator).
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.common.glb_validator import (
    REGION_GLB_MAP,
    validate_spatial_data_against_glb,
)
from src.common.sld_generator import generate_sld, write_sld
from src.common.schemas import (
    BatteryDesign,
    Compliance,
    EVChargerDesign,
    FinalProposal,
    FinancialSummary,
    HeatPumpDesign,
    HumanSignoff,
    ProposalMetadata,
    PVDesign,
    SignoffStatus,
    SystemDesign,
)


_NOW = datetime.now(timezone.utc)

_GLB_DIR = Path(__file__).resolve().parents[1] / "Datasets" / "Exp 3D-Modells"


# ============================================================================
# Helpers
# ============================================================================


def _make_proposal(run_id: str = "test-run-001") -> FinalProposal:
    return FinalProposal(
        system_design=SystemDesign(
            pv=PVDesign(
                total_kwp=6.4,
                panel_count=16,
                panel_model="JA Solar JAM54S30-400",
                inverter_type="hybrid",
                inverter_model="SolarEdge SE6000H",
                annual_yield_kwh=4915.2,
            ),
            battery=BatteryDesign(
                included=True,
                capacity_kwh=10.0,
                model="BYD HVS 10.2",
            ),
            heat_pump=HeatPumpDesign(
                included=True,
                capacity_kw=10.0,
                type="air_source",
                model="Vaillant aroTHERM plus 10",
                cop=3.5,
                cylinder_litres=200,
            ),
            ev_charger=EVChargerDesign(included=False),
        ),
        financial_summary=FinancialSummary(
            total_cost_eur=26680.0,
            annual_savings_eur=3100.0,
            payback_years=8.6,
        ),
        compliance=Compliance(
            electrical_upgrades=[],
            regulatory_notes=["Human installer sign-off required before proposal delivery"],
        ),
        human_signoff=HumanSignoff(required=True, status=SignoffStatus.PENDING),
        metadata=ProposalMetadata(
            pipeline_run_id=run_id,
            version="1.0.0",
            generated_at=_NOW,
        ),
    )


# ============================================================================
# E1: GLB validator
# ============================================================================


class TestGLBValidator:
    def test_known_regions_all_have_glb_entries(self):
        """All climate regions must have a matching GLB mapping."""
        from src.common.climate import known_regions
        for region in known_regions():
            assert region in REGION_GLB_MAP, f"No GLB entry for region '{region}'"

    def test_unknown_region_returns_error(self):
        result = validate_spatial_data_against_glb(
            gemini_face_count=2,
            gemini_total_area_m2=80.0,
            region="NonExistentRegion",
        )
        assert result.valid is False
        assert any(i.code == "UNKNOWN_REGION" for i in result.issues)

    def test_missing_glb_file_returns_error(self, tmp_path):
        result = validate_spatial_data_against_glb(
            gemini_face_count=2,
            gemini_total_area_m2=80.0,
            region="Hamburg",
            glb_dir=tmp_path,  # empty dir — no GLB files
        )
        assert result.valid is False
        assert any(i.code == "GLB_NOT_FOUND" for i in result.issues)

    @pytest.mark.skipif(
        not (_GLB_DIR / "3D_Modell Hamburg.glb").exists(),
        reason="Hamburg GLB not present in Datasets/",
    )
    def test_hamburg_glb_valid_parse(self):
        result = validate_spatial_data_against_glb(
            gemini_face_count=2,
            gemini_total_area_m2=80.0,
            region="Hamburg",
            glb_dir=_GLB_DIR,
        )
        assert result.primitive_count > 0
        assert result.glb_path.endswith(".glb")

    @pytest.mark.skipif(
        not (_GLB_DIR / "3D_Modell Hamburg.glb").exists(),
        reason="Hamburg GLB not present in Datasets/",
    )
    def test_face_count_exceeds_primitives_raises_warning(self):
        result = validate_spatial_data_against_glb(
            gemini_face_count=999,  # intentionally far more than any GLB has
            gemini_total_area_m2=999.0,
            region="Hamburg",
            glb_dir=_GLB_DIR,
        )
        # Should be valid (warning-only) but have the face count warning
        assert any(i.code == "FACE_COUNT_EXCEEDS_MODEL" for i in result.issues)
        assert all(i.severity != "error" for i in result.issues)
        assert result.valid is True

    @pytest.mark.skipif(
        not (_GLB_DIR / "3D_Modell Hamburg.glb").exists(),
        reason="Hamburg GLB not present in Datasets/",
    )
    def test_reasonable_face_count_passes(self):
        result = validate_spatial_data_against_glb(
            gemini_face_count=2,
            gemini_total_area_m2=80.0,
            region="Hamburg",
            glb_dir=_GLB_DIR,
        )
        error_codes = [i.code for i in result.issues if i.severity == "error"]
        assert error_codes == [], f"Unexpected errors: {error_codes}"

    def test_corrupt_glb_returns_error(self, tmp_path):
        bad_glb = tmp_path / "3D_Modell Hamburg.glb"
        bad_glb.write_bytes(b"notglTF" + b"\x00" * 100)
        result = validate_spatial_data_against_glb(
            gemini_face_count=2,
            gemini_total_area_m2=80.0,
            region="Hamburg",
            glb_dir=tmp_path,
        )
        assert result.valid is False
        assert any(i.code == "GLB_PARSE_ERROR" for i in result.issues)


# ============================================================================
# E2: SLD generator
# ============================================================================


class TestSLDGenerator:
    def test_sld_contains_pv_info(self):
        sld = generate_sld(_make_proposal())
        assert "6.4 kWp" in sld
        assert "16 panels" in sld

    def test_sld_contains_battery_info(self):
        sld = generate_sld(_make_proposal())
        assert "10.0 kWh" in sld
        assert "BYD" in sld

    def test_sld_contains_heat_pump_info(self):
        sld = generate_sld(_make_proposal())
        assert "10 kW" in sld
        assert "air_source" in sld

    def test_sld_contains_run_id(self):
        sld = generate_sld(_make_proposal(run_id="abc-123"))
        assert "abc-123" in sld

    def test_sld_contains_signoff_status(self):
        sld = generate_sld(_make_proposal())
        assert "PENDING" in sld

    def test_sld_contains_regulatory_notes(self):
        sld = generate_sld(_make_proposal())
        assert "Human installer sign-off" in sld

    def test_write_sld_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            proposal = _make_proposal(run_id="write-test-xyz")
            out_path = write_sld(proposal, out_dir)
            assert out_path.exists()
            assert out_path.name == "write-test-xyz.sld.txt"
            content = out_path.read_text(encoding="utf-8")
            assert "6.4 kWp" in content

    def test_synthesis_agent_sets_sld_ref(self):
        """Synthesis agent must populate compliance.single_line_diagram_ref."""
        from src.agents.synthesis.agent import run as synthesis_run
        from src.agents.synthesis.pioneer_client import ComponentPricing
        from tests.test_agent_contracts import (
            _behavioral_profile, _electrical_assessment,
            _module_layout, _thermal_load,
        )

        import asyncio

        pricing = ComponentPricing(
            pv_cost_eur=7680.0, battery_cost_eur=5900.0, heat_pump_cost_eur=11000.0,
            source="rule_based_fallback",
        )
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            result = asyncio.run(synthesis_run(
                _module_layout(), _thermal_load(), _electrical_assessment(),
                _behavioral_profile(),
            ))
        assert result.compliance.single_line_diagram_ref is not None
        assert result.compliance.single_line_diagram_ref.endswith(".sld.txt")
        assert Path(result.compliance.single_line_diagram_ref).exists()
