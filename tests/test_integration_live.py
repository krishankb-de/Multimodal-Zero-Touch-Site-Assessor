"""
Live integration test — runs the full pipeline against real Gemini and Pioneer APIs.

This test is skipped automatically when GEMINI_API_KEY is not set.
Run manually with:
    python -m pytest tests/test_integration_live.py -v -s

Uses the real house video from Datasets/Videos/ and creates synthetic photo/PDF files.
Drives the complete pipeline:
  Ingestion (Gemini 2.5 Flash) → Domain agents → Synthesis (Pioneer DeepSeek-V3.1) → Safety validation
"""

from __future__ import annotations

import asyncio
import struct
from pathlib import Path

import pytest

from src.common.config import config

# Skip the entire module if no real API key is configured
pytestmark = pytest.mark.skipif(
    not config.gemini.api_key,
    reason="GEMINI_API_KEY not set — skipping live integration tests",
)

# Real house video path
HOUSE_VIDEO = Path("Datasets/Videos/videoplayback.mp4")


# ============================================================================
# Minimal synthetic media file builders
# ============================================================================


def _make_minimal_jpeg(path: Path) -> None:
    """Write a 1×1 white JPEG to path."""
    # Minimal valid JPEG (1×1 white pixel)
    jpeg_bytes = bytes([
        0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
        0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
        0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
        0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
        0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
        0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
        0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
        0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
        0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
        0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
        0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
        0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D,
        0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
        0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
        0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
        0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
        0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
        0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
        0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75,
        0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
        0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3,
        0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6,
        0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9,
        0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
        0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3, 0xF4,
        0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01,
        0x00, 0x00, 0x3F, 0x00, 0xFB, 0xD2, 0x8A, 0x28, 0x03, 0xFF, 0xD9,
    ])
    path.write_bytes(jpeg_bytes)


def _make_minimal_mp4(path: Path) -> None:
    """Write a minimal valid MP4 container (ftyp + mdat boxes) to path."""
    # ftyp box: file type
    ftyp = b"ftyp" + b"isom" + b"\x00\x00\x02\x00" + b"isom" + b"iso2" + b"mp41"
    ftyp_size = struct.pack(">I", 4 + len(ftyp))
    ftyp_box = ftyp_size + ftyp

    # mdat box: empty media data
    mdat_box = struct.pack(">I", 8) + b"mdat"

    path.write_bytes(ftyp_box + mdat_box)


def _make_minimal_pdf(path: Path) -> None:
    """Write a minimal valid PDF with a text page describing a utility bill."""
    content = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj

2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj

3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]
   /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj

4 0 obj
<< /Length 300 >>
stream
BT
/F1 12 Tf
50 750 Td
(Electricity Bill - January 2024 to December 2024) Tj
0 -20 Td
(Annual consumption: 4200 kWh) Tj
0 -20 Td
(Monthly breakdown: Jan 350, Feb 350, Mar 350, Apr 350, May 350, Jun 350,) Tj
0 -20 Td
(Jul 350, Aug 350, Sep 350, Oct 350, Nov 350, Dec 350 kWh) Tj
0 -20 Td
(Unit rate: 0.32 EUR/kWh) Tj
0 -20 Td
(Feed-in tariff: 0.08 EUR/kWh) Tj
0 -20 Td
(Heating fuel: gas) Tj
ET
endstream
endobj

5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj

xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000274 00000 n
0000000626 00000 n

trailer
<< /Size 6 /Root 1 0 R >>
startxref
715
%%EOF
"""
    path.write_bytes(content)


# ============================================================================
# Live integration tests
# ============================================================================


class TestLivePipeline:
    """End-to-end pipeline tests using real Gemini and Pioneer API calls."""

    @pytest.mark.asyncio
    async def test_process_pdf_live(self, tmp_path):
        """process_pdf must extract ConsumptionData from a real PDF via Gemini."""
        from src.agents.ingestion.agent import process_pdf
        from src.common.schemas import ConsumptionData

        pdf_path = tmp_path / "bill.pdf"
        _make_minimal_pdf(pdf_path)

        result = await process_pdf(pdf_path)

        assert isinstance(result, ConsumptionData)
        assert result.annual_kwh > 0
        assert len(result.monthly_breakdown) == 12
        assert result.metadata.confidence_score >= 0.0
        assert result.metadata.gemini_model_version is not None
        print(f"\n✓ process_pdf: annual_kwh={result.annual_kwh}, "
              f"confidence={result.metadata.confidence_score:.2f}, "
              f"model={result.metadata.gemini_model_version}")

    @pytest.mark.asyncio
    async def test_process_photo_live(self, tmp_path):
        """process_photo must extract ElectricalData from a real JPEG via Gemini."""
        from src.agents.ingestion.agent import process_photo
        from src.common.schemas import ElectricalData

        photo_path = tmp_path / "panel.jpg"
        _make_minimal_jpeg(photo_path)

        result = await process_photo(photo_path)

        assert isinstance(result, ElectricalData)
        assert result.main_supply.amperage_A > 0
        assert result.metadata.confidence_score >= 0.0
        print(f"\n✓ process_photo: amperage={result.main_supply.amperage_A}A, "
              f"phases={result.main_supply.phases}, "
              f"breakers={len(result.breakers)}, "
              f"confidence={result.metadata.confidence_score:.2f}")

    @pytest.mark.asyncio
    async def test_process_video_live(self):
        """process_video must extract SpatialData from the real house video via Gemini."""
        from src.agents.ingestion.agent import process_video
        from src.common.schemas import SpatialData

        assert HOUSE_VIDEO.exists(), f"House video not found: {HOUSE_VIDEO}"

        result = await process_video(HOUSE_VIDEO)

        assert isinstance(result, SpatialData)
        assert result.roof.total_usable_area_m2 > 0
        assert len(result.roof.faces) >= 1
        assert result.metadata.confidence_score >= 0.0
        print(f"\n✓ process_video (real house): roof_area={result.roof.total_usable_area_m2}m², "
              f"faces={len(result.roof.faces)}, "
              f"typology={result.roof.typology.value}, "
              f"confidence={result.metadata.confidence_score:.2f}")

    @pytest.mark.asyncio
    async def test_pioneer_pricing_live(self):
        """Pioneer SLM must return real component pricing via DeepSeek-V3.1."""
        from src.agents.synthesis.pioneer_client import get_component_pricing

        pricing = await get_component_pricing(
            total_kwp=6.4,
            battery_kwh=10.0,
            heat_pump_kw=10.0,
        )

        assert pricing.source == "pioneer_slm", f"Expected pioneer_slm, got: {pricing.source}"
        assert pricing.pv_cost_eur > 0
        assert pricing.battery_cost_eur > 0
        assert pricing.heat_pump_cost_eur > 0
        print(f"\n✓ Pioneer pricing (DeepSeek-V3.1):")
        print(f"  PV ({6.4}kWp): €{pricing.pv_cost_eur:,.0f}")
        print(f"  Battery ({10.0}kWh): €{pricing.battery_cost_eur:,.0f}")
        print(f"  Heat pump ({10.0}kW): €{pricing.heat_pump_cost_eur:,.0f}")
        print(f"  Total: €{pricing.pv_cost_eur + pricing.battery_cost_eur + pricing.heat_pump_cost_eur:,.0f}")

    @pytest.mark.asyncio
    async def test_full_pipeline_with_real_video(self, tmp_path):
        """
        Full end-to-end pipeline using the real house video + synthetic photo/PDF.
        Ingestion via Gemini 2.5 Flash → domain agents → Synthesis via Pioneer DeepSeek-V3.1.
        """
        from src.agents.ingestion.agent import process_pdf, process_photo, process_video
        from src.agents.structural.agent import run as structural_run
        from src.agents.electrical.agent import run as electrical_run
        from src.agents.thermodynamic.agent import run as thermodynamic_run
        from src.agents.behavioral.agent import run as behavioral_run
        from src.agents.synthesis.agent import run as synthesis_run
        from src.agents.safety.validator import validate_handoff
        from src.common.schemas import FinalProposal

        assert HOUSE_VIDEO.exists(), f"House video not found: {HOUSE_VIDEO}"

        # Create synthetic photo and PDF (real video is used for spatial data)
        photo_path = tmp_path / "panel.jpg"
        pdf_path = tmp_path / "bill.pdf"
        _make_minimal_jpeg(photo_path)
        _make_minimal_pdf(pdf_path)

        print(f"\n{'='*60}")
        print(f"FULL PIPELINE TEST — Gemini {config.gemini.model_name} + Pioneer {config.pioneer.model_name}")
        print(f"{'='*60}")

        # ----------------------------------------------------------------
        # Stage 1: Ingestion — run all three concurrently
        # ----------------------------------------------------------------
        print("\n--- Stage 1: Ingestion (Gemini) ---")
        spatial_data, electrical_data, consumption_data = await asyncio.gather(
            process_video(HOUSE_VIDEO),
            process_photo(photo_path),
            process_pdf(pdf_path),
        )
        print(f"  ✓ SpatialData: roof_area={spatial_data.roof.total_usable_area_m2}m², "
              f"typology={spatial_data.roof.typology.value}, "
              f"faces={len(spatial_data.roof.faces)}, "
              f"confidence={spatial_data.metadata.confidence_score:.2f}")
        print(f"  ✓ ElectricalData: {electrical_data.main_supply.amperage_A}A "
              f"{electrical_data.main_supply.phases}ph, "
              f"breakers={len(electrical_data.breakers)}, "
              f"confidence={electrical_data.metadata.confidence_score:.2f}")
        print(f"  ✓ ConsumptionData: {consumption_data.annual_kwh:.0f}kWh/yr, "
              f"confidence={consumption_data.metadata.confidence_score:.2f}")

        # ----------------------------------------------------------------
        # Safety Gate 1
        # ----------------------------------------------------------------
        print("\n--- Safety Gate 1 ---")
        all_valid = True
        for obj, schema, src in [
            (spatial_data, "SpatialData", "ingestion"),
            (electrical_data, "ElectricalData", "ingestion"),
            (consumption_data, "ConsumptionData", "ingestion"),
        ]:
            _, result = validate_handoff(obj.model_dump(mode="json"), schema, src)
            status = "✓ PASS" if result.valid else f"✗ FAIL ({len(result.errors)} errors)"
            print(f"  {schema}: {status}")
            for w in result.warnings:
                print(f"    ⚠ {w}")
            if not result.valid:
                all_valid = False
                for e in result.errors:
                    print(f"    ✗ [{e.code}] {e.message}")

        # ----------------------------------------------------------------
        # Stage 2: Domain agents (deterministic, no API calls)
        # ----------------------------------------------------------------
        print("\n--- Stage 2: Domain agents ---")
        module_layout = structural_run(spatial_data)
        electrical_assessment = electrical_run(electrical_data)
        thermal_load = thermodynamic_run(spatial_data, consumption_data)
        behavioral_profile = behavioral_run(consumption_data)

        print(f"  ✓ ModuleLayout: {module_layout.total_kwp:.1f}kWp, "
              f"{module_layout.total_panels} panels, "
              f"{len(module_layout.string_config.strings)} strings")
        print(f"  ✓ ElectricalAssessment: sufficient={electrical_assessment.current_capacity_sufficient}, "
              f"upgrades={len(electrical_assessment.upgrades_required)}, "
              f"inverter={electrical_assessment.inverter_recommendation.type.value}")
        print(f"  ✓ ThermalLoad: design={thermal_load.design_heat_load_kw:.1f}kW, "
              f"HP={thermal_load.heat_pump_recommendation.capacity_kw:.0f}kW, "
              f"cylinder={thermal_load.dhw_requirement.cylinder_volume_litres}L")
        print(f"  ✓ BehavioralProfile: {behavioral_profile.occupancy_pattern.value}, "
              f"battery={behavioral_profile.battery_recommendation.capacity_kwh:.1f}kWh, "
              f"savings=€{behavioral_profile.estimated_annual_savings_eur:.0f}/yr")

        # ----------------------------------------------------------------
        # Safety Gate 2
        # ----------------------------------------------------------------
        print("\n--- Safety Gate 2 ---")
        for obj, schema, src in [
            (module_layout, "ModuleLayout", "structural"),
            (electrical_assessment, "ElectricalAssessment", "electrical"),
            (thermal_load, "ThermalLoad", "thermodynamic"),
            (behavioral_profile, "BehavioralProfile", "behavioral"),
        ]:
            _, result = validate_handoff(obj.model_dump(mode="json"), schema, src)
            status = "✓ PASS" if result.valid else f"✗ FAIL ({len(result.errors)} errors)"
            print(f"  {schema}: {status}")
            for w in result.warnings:
                print(f"    ⚠ {w}")
            if not result.valid:
                all_valid = False

        # ----------------------------------------------------------------
        # Stage 3: Synthesis (Pioneer SLM)
        # ----------------------------------------------------------------
        print("\n--- Stage 3: Synthesis (Pioneer DeepSeek-V3.1) ---")
        final_proposal = await synthesis_run(
            module_layout=module_layout,
            thermal_load=thermal_load,
            electrical_assessment=electrical_assessment,
            behavioral_profile=behavioral_profile,
        )
        print(f"  ✓ FinalProposal: run_id={final_proposal.metadata.pipeline_run_id}")
        print(f"  ✓ System: {final_proposal.system_design.pv.total_kwp}kWp PV + "
              f"{final_proposal.system_design.battery.capacity_kwh}kWh battery + "
              f"{final_proposal.system_design.heat_pump.capacity_kw}kW HP")
        print(f"  ✓ Financials: cost=€{final_proposal.financial_summary.total_cost_eur:,.0f}, "
              f"savings=€{final_proposal.financial_summary.annual_savings_eur:,.0f}/yr, "
              f"payback={final_proposal.financial_summary.payback_years:.1f}yr")
        print(f"  ✓ Signoff: required={final_proposal.human_signoff.required}, "
              f"status={final_proposal.human_signoff.status.value}")
        if final_proposal.compliance.electrical_upgrades:
            print(f"  ⚠ Electrical upgrades: {len(final_proposal.compliance.electrical_upgrades)}")
        for note in final_proposal.compliance.regulatory_notes:
            print(f"    • {note}")

        # ----------------------------------------------------------------
        # Safety Gate 3
        # ----------------------------------------------------------------
        print("\n--- Safety Gate 3 ---")
        _, result = validate_handoff(
            final_proposal.model_dump(mode="json"), "FinalProposal", "synthesis"
        )
        status = "✓ PASS" if result.valid else f"✗ FAIL ({len(result.errors)} errors)"
        print(f"  FinalProposal: {status}")
        for w in result.warnings:
            print(f"    ⚠ {w}")
        if not result.valid:
            for e in result.errors:
                print(f"    ✗ [{e.code}] {e.message}")

        print(f"\n{'='*60}")
        print("✓ FULL PIPELINE COMPLETED SUCCESSFULLY")
        print(f"{'='*60}")

        # Final assertions
        assert isinstance(final_proposal, FinalProposal)
        assert final_proposal.human_signoff.required is True
        assert final_proposal.human_signoff.status.value == "pending"
        assert final_proposal.financial_summary.total_cost_eur > 0
        assert final_proposal.financial_summary.payback_years >= 0
        assert result.valid, f"FinalProposal failed Safety Gate 3: {[e.message for e in result.errors]}"
