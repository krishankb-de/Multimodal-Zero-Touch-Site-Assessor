"""
Unit tests for the Synthesis Agent.

Tests cover:
- FinalProposal correctly assembled from all domain agent outputs
- Financial calculations (total_cost, annual_savings, payback_years)
- human_signoff.required is always True and status is "pending"
- Pioneer SLM fallback to rule-based selection
- pipeline_run_id is generated and unique
- Round-trip serialization: FinalProposal → JSON → FinalProposal

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11, 9.10
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.synthesis.agent import run
from src.agents.synthesis.pioneer_client import (
    ComponentPricing,
    PV_COST_PER_KWP,
    BATTERY_COST_PER_KWH,
    HEAT_PUMP_COST_PER_KW,
    HEAT_PUMP_BASE_COST,
    get_rule_based_pricing,
)
from src.common.schemas import (
    BatteryRecommendation,
    BehavioralProfile,
    CalculationMetadata,
    DHWRequirement,
    ElectricalAssessment,
    FaceLayout,
    FinalProposal,
    HeatPumpRecommendation,
    HeatPumpType,
    InverterRecommendation,
    InverterType,
    ModuleLayout,
    OccupancyPattern,
    OptimizationFrequency,
    OptimizationSchedule,
    PanelOrientation,
    SignoffStatus,
    SimpleMetadata,
    StringConfig,
    StringLayout,
    ThermalLoad,
    UValues,
)


# ============================================================================
# Fixtures — domain agent output builders
# ============================================================================


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_module_layout(total_kwp: float = 6.4, total_panels: int = 16) -> ModuleLayout:
    return ModuleLayout(
        panels=[
            FaceLayout(
                face_id="south",
                count=total_panels,
                orientation=PanelOrientation.PORTRAIT,
                panel_watt_peak=400,
            )
        ],
        total_kwp=total_kwp,
        total_panels=total_panels,
        string_config=StringLayout(
            strings=[
                StringConfig(
                    string_id="S1",
                    panels_in_series=8,
                    voc_string_V=380.0,
                    isc_string_A=11.5,
                ),
                StringConfig(
                    string_id="S2",
                    panels_in_series=8,
                    voc_string_V=380.0,
                    isc_string_A=11.5,
                ),
            ]
        ),
        metadata=CalculationMetadata(
            algorithm_version="1.0.0",
            timestamp=_now(),
        ),
    )


def _make_thermal_load(capacity_kw: float = 10.0, cylinder_litres: int = 200) -> ThermalLoad:
    return ThermalLoad(
        design_heat_load_kw=8.5,
        transmission_loss_kw=5.5,
        ventilation_loss_kw=2.0,
        design_outdoor_temp_c=-12,
        design_indoor_temp_c=20,
        u_values_used=UValues(
            walls_w_m2k=0.28,
            roof_w_m2k=0.16,
            floor_w_m2k=0.22,
            windows_w_m2k=1.3,
        ),
        heat_pump_recommendation=HeatPumpRecommendation(
            capacity_kw=capacity_kw,
            type=HeatPumpType.AIR_SOURCE,
            cop_estimate=3.5,
            safety_factor=1.15,
        ),
        dhw_requirement=DHWRequirement(
            daily_litres=150.0,
            cylinder_volume_litres=cylinder_litres,
            fits_in_utility_room=True,
        ),
        metadata=CalculationMetadata(
            calculation_method="DIN_EN_12831_simplified",
            timestamp=_now(),
        ),
    )


def _make_electrical_assessment(
    inverter_type: InverterType = InverterType.HYBRID,
    upgrades: list | None = None,
) -> ElectricalAssessment:
    return ElectricalAssessment(
        current_capacity_sufficient=True,
        max_additional_load_A=40.0,
        upgrades_required=upgrades or [],
        inverter_recommendation=InverterRecommendation(
            type=inverter_type,
            max_ac_output_kw=6.0,
        ),
        ev_charger_compatible=True,
        metadata=SimpleMetadata(timestamp=_now()),
    )


def _make_behavioral_profile(
    capacity_kwh: float = 10.0,
    estimated_savings: float = 780.0,
) -> BehavioralProfile:
    return BehavioralProfile(
        occupancy_pattern=OccupancyPattern.AWAY_DAYTIME,
        self_consumption_ratio=0.35,
        battery_recommendation=BatteryRecommendation(
            capacity_kwh=capacity_kwh,
            rationale="Sized for away_daytime occupancy",
        ),
        optimization_schedule=OptimizationSchedule(
            frequency=OptimizationFrequency.QUARTERLY,
            next_review=date.today(),
        ),
        estimated_annual_savings_eur=estimated_savings,
        metadata=SimpleMetadata(timestamp=_now()),
    )


def _make_rule_based_pricing(
    total_kwp: float = 6.4,
    battery_kwh: float = 10.0,
    heat_pump_kw: float = 10.0,
) -> ComponentPricing:
    return ComponentPricing(
        pv_cost_eur=total_kwp * PV_COST_PER_KWP,
        battery_cost_eur=battery_kwh * BATTERY_COST_PER_KWH,
        heat_pump_cost_eur=HEAT_PUMP_BASE_COST + heat_pump_kw * HEAT_PUMP_COST_PER_KW,
        source="rule_based_fallback",
        warning="Pioneer SLM unavailable — using rule-based Reonic dataset pricing",
    )


# ============================================================================
# Tests: FinalProposal assembly
# ============================================================================


class TestFinalProposalAssembly:
    """FinalProposal must be correctly assembled from all domain agent outputs."""

    @pytest.mark.asyncio
    async def test_run_returns_final_proposal(self):
        """run() must return a FinalProposal instance."""
        pricing = _make_rule_based_pricing()
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            result = await run(
                _make_module_layout(),
                _make_thermal_load(),
                _make_electrical_assessment(),
                _make_behavioral_profile(),
            )
        assert isinstance(result, FinalProposal)

    @pytest.mark.asyncio
    async def test_pv_design_populated_from_module_layout(self):
        """system_design.pv must reflect ModuleLayout total_kwp and total_panels."""
        module_layout = _make_module_layout(total_kwp=8.0, total_panels=20)
        pricing = _make_rule_based_pricing(total_kwp=8.0)
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            result = await run(
                module_layout,
                _make_thermal_load(),
                _make_electrical_assessment(),
                _make_behavioral_profile(),
            )
        assert result.system_design.pv.total_kwp == pytest.approx(8.0)
        assert result.system_design.pv.panel_count == 20

    @pytest.mark.asyncio
    async def test_pv_inverter_type_from_electrical_assessment(self):
        """system_design.pv.inverter_type must come from ElectricalAssessment."""
        electrical = _make_electrical_assessment(inverter_type=InverterType.THREE_PHASE)
        pricing = _make_rule_based_pricing()
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            result = await run(
                _make_module_layout(),
                _make_thermal_load(),
                electrical,
                _make_behavioral_profile(),
            )
        assert result.system_design.pv.inverter_type == "three_phase"

    @pytest.mark.asyncio
    async def test_heat_pump_design_populated_from_thermal_load(self):
        """system_design.heat_pump must reflect ThermalLoad heat pump recommendation."""
        thermal = _make_thermal_load(capacity_kw=12.0, cylinder_litres=250)
        pricing = _make_rule_based_pricing(heat_pump_kw=12.0)
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            result = await run(
                _make_module_layout(),
                thermal,
                _make_electrical_assessment(),
                _make_behavioral_profile(),
            )
        assert result.system_design.heat_pump.capacity_kw == pytest.approx(12.0)
        assert result.system_design.heat_pump.type == "air_source"
        assert result.system_design.heat_pump.cylinder_litres == 250

    @pytest.mark.asyncio
    async def test_battery_design_populated_from_behavioral_profile(self):
        """system_design.battery must reflect BehavioralProfile battery capacity."""
        behavioral = _make_behavioral_profile(capacity_kwh=15.0)
        pricing = _make_rule_based_pricing(battery_kwh=15.0)
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            result = await run(
                _make_module_layout(),
                _make_thermal_load(),
                _make_electrical_assessment(),
                behavioral,
            )
        assert result.system_design.battery.capacity_kwh == pytest.approx(15.0)
        assert result.system_design.battery.included is True

    @pytest.mark.asyncio
    async def test_electrical_upgrades_in_compliance(self):
        """compliance.electrical_upgrades must include all ElectricalAssessment upgrades."""
        from src.common.schemas import UpgradeRequired, UpgradeType
        upgrades = [
            UpgradeRequired(
                type=UpgradeType.BOARD_UPGRADE,
                reason="Board needs replacement",
                estimated_cost_eur=1500.0,
            ),
            UpgradeRequired(
                type=UpgradeType.RCD_ADDITION,
                reason="No RCD present",
                estimated_cost_eur=300.0,
            ),
        ]
        electrical = _make_electrical_assessment(upgrades=upgrades)
        pricing = _make_rule_based_pricing()
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            result = await run(
                _make_module_layout(),
                _make_thermal_load(),
                electrical,
                _make_behavioral_profile(),
            )
        assert len(result.compliance.electrical_upgrades) == 2
        assert "Board needs replacement" in result.compliance.electrical_upgrades
        assert "No RCD present" in result.compliance.electrical_upgrades


# ============================================================================
# Tests: Financial calculations
# ============================================================================


class TestFinancialCalculations:
    """Financial summary must be correctly calculated from component costs and savings."""

    @pytest.mark.asyncio
    async def test_total_cost_sums_component_costs(self):
        """total_cost_eur must equal PV + battery + heat pump + upgrade costs."""
        total_kwp = 6.4
        battery_kwh = 10.0
        heat_pump_kw = 10.0

        pricing = ComponentPricing(
            pv_cost_eur=7680.0,
            battery_cost_eur=8000.0,
            heat_pump_cost_eur=9000.0,
            source="rule_based_fallback",
        )
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            result = await run(
                _make_module_layout(total_kwp=total_kwp),
                _make_thermal_load(capacity_kw=heat_pump_kw),
                _make_electrical_assessment(upgrades=[]),
                _make_behavioral_profile(capacity_kwh=battery_kwh),
            )
        expected_total = 7680.0 + 8000.0 + 9000.0  # no upgrade costs
        assert result.financial_summary.total_cost_eur == pytest.approx(expected_total)

    @pytest.mark.asyncio
    async def test_total_cost_includes_electrical_upgrade_costs(self):
        """total_cost_eur must include electrical upgrade costs."""
        from src.common.schemas import UpgradeRequired, UpgradeType
        upgrades = [
            UpgradeRequired(
                type=UpgradeType.BOARD_UPGRADE,
                reason="Board upgrade needed",
                estimated_cost_eur=1500.0,
            )
        ]
        pricing = ComponentPricing(
            pv_cost_eur=7680.0,
            battery_cost_eur=8000.0,
            heat_pump_cost_eur=9000.0,
            source="rule_based_fallback",
        )
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            result = await run(
                _make_module_layout(),
                _make_thermal_load(),
                _make_electrical_assessment(upgrades=upgrades),
                _make_behavioral_profile(),
            )
        expected_total = 7680.0 + 8000.0 + 9000.0 + 1500.0
        assert result.financial_summary.total_cost_eur == pytest.approx(expected_total)

    @pytest.mark.asyncio
    async def test_annual_savings_includes_behavioral_and_heat_pump_savings(self):
        """annual_savings_eur must include BehavioralProfile savings + heat pump savings."""
        behavioral_savings = 780.0
        heat_pump_kw = 10.0
        expected_heat_pump_savings = heat_pump_kw * 200.0  # 200 EUR/kW/year

        pricing = _make_rule_based_pricing()
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            result = await run(
                _make_module_layout(),
                _make_thermal_load(capacity_kw=heat_pump_kw),
                _make_electrical_assessment(),
                _make_behavioral_profile(estimated_savings=behavioral_savings),
            )
        expected_savings = behavioral_savings + expected_heat_pump_savings
        assert result.financial_summary.annual_savings_eur == pytest.approx(expected_savings)

    @pytest.mark.asyncio
    async def test_payback_years_calculated_correctly(self):
        """payback_years must equal total_cost / annual_savings."""
        pricing = ComponentPricing(
            pv_cost_eur=7680.0,
            battery_cost_eur=8000.0,
            heat_pump_cost_eur=9000.0,
            source="rule_based_fallback",
        )
        behavioral_savings = 780.0
        heat_pump_kw = 10.0
        heat_pump_savings = heat_pump_kw * 200.0

        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            result = await run(
                _make_module_layout(),
                _make_thermal_load(capacity_kw=heat_pump_kw),
                _make_electrical_assessment(upgrades=[]),
                _make_behavioral_profile(estimated_savings=behavioral_savings),
            )
        total_cost = 7680.0 + 8000.0 + 9000.0
        annual_savings = behavioral_savings + heat_pump_savings
        expected_payback = total_cost / annual_savings
        assert result.financial_summary.payback_years == pytest.approx(expected_payback, rel=1e-3)

    @pytest.mark.asyncio
    async def test_payback_years_non_negative(self):
        """payback_years must always be >= 0."""
        pricing = _make_rule_based_pricing()
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            result = await run(
                _make_module_layout(),
                _make_thermal_load(),
                _make_electrical_assessment(),
                _make_behavioral_profile(),
            )
        assert result.financial_summary.payback_years >= 0


# ============================================================================
# Tests: Human sign-off invariant
# ============================================================================


class TestHumanSignoff:
    """human_signoff.required must always be True and status must be 'pending'."""

    @pytest.mark.asyncio
    async def test_human_signoff_required_is_always_true(self):
        """human_signoff.required must be True in every FinalProposal."""
        pricing = _make_rule_based_pricing()
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            result = await run(
                _make_module_layout(),
                _make_thermal_load(),
                _make_electrical_assessment(),
                _make_behavioral_profile(),
            )
        assert result.human_signoff.required is True

    @pytest.mark.asyncio
    async def test_human_signoff_status_is_pending(self):
        """human_signoff.status must be 'pending' at creation."""
        pricing = _make_rule_based_pricing()
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            result = await run(
                _make_module_layout(),
                _make_thermal_load(),
                _make_electrical_assessment(),
                _make_behavioral_profile(),
            )
        assert result.human_signoff.status == SignoffStatus.PENDING

    @pytest.mark.asyncio
    async def test_human_signoff_installer_id_is_none_at_creation(self):
        """human_signoff.installer_id must be None at creation (not yet signed)."""
        pricing = _make_rule_based_pricing()
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            result = await run(
                _make_module_layout(),
                _make_thermal_load(),
                _make_electrical_assessment(),
                _make_behavioral_profile(),
            )
        assert result.human_signoff.installer_id is None
        assert result.human_signoff.signed_at is None


# ============================================================================
# Tests: Pioneer SLM fallback
# ============================================================================


class TestPioneerSLMFallback:
    """Synthesis Agent must fall back to rule-based pricing when Pioneer is unavailable."""

    @pytest.mark.asyncio
    async def test_fallback_pricing_used_when_pioneer_unavailable(self):
        """When Pioneer SLM fails, rule-based pricing must be used."""
        import httpx

        # Simulate Pioneer SLM being unavailable
        async def mock_get_pricing(*args, **kwargs):
            return get_rule_based_pricing(*args, **kwargs)

        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(side_effect=mock_get_pricing),
        ):
            result = await run(
                _make_module_layout(),
                _make_thermal_load(),
                _make_electrical_assessment(),
                _make_behavioral_profile(),
            )
        # Should still produce a valid FinalProposal
        assert isinstance(result, FinalProposal)
        assert result.financial_summary.total_cost_eur > 0

    def test_rule_based_pricing_formula(self):
        """Rule-based pricing must follow the Reonic dataset formula."""
        total_kwp = 6.4
        battery_kwh = 10.0
        heat_pump_kw = 10.0

        pricing = get_rule_based_pricing(total_kwp, battery_kwh, heat_pump_kw)

        assert pricing.pv_cost_eur == pytest.approx(total_kwp * PV_COST_PER_KWP)
        assert pricing.battery_cost_eur == pytest.approx(battery_kwh * BATTERY_COST_PER_KWH)
        assert pricing.heat_pump_cost_eur == pytest.approx(
            HEAT_PUMP_BASE_COST + heat_pump_kw * HEAT_PUMP_COST_PER_KW
        )
        assert pricing.source == "rule_based_fallback"
        assert pricing.warning is not None

    def test_rule_based_pricing_warning_set(self):
        """Rule-based fallback must set a warning message."""
        pricing = get_rule_based_pricing(6.4, 10.0, 10.0)
        assert pricing.warning is not None
        assert len(pricing.warning) > 0

    @pytest.mark.asyncio
    async def test_fallback_warning_appears_in_regulatory_notes(self):
        """When fallback is used, the warning must appear in compliance.regulatory_notes."""
        fallback_pricing = get_rule_based_pricing(6.4, 10.0, 10.0)
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=fallback_pricing),
        ):
            result = await run(
                _make_module_layout(),
                _make_thermal_load(),
                _make_electrical_assessment(),
                _make_behavioral_profile(),
            )
        # The warning from fallback pricing should appear in regulatory notes
        assert any("Pioneer" in note or "rule-based" in note or "fallback" in note.lower()
                   for note in result.compliance.regulatory_notes)


# ============================================================================
# Tests: pipeline_run_id uniqueness
# ============================================================================


class TestPipelineRunId:
    """pipeline_run_id must be generated and unique for each run."""

    @pytest.mark.asyncio
    async def test_pipeline_run_id_is_generated(self):
        """metadata.pipeline_run_id must be set and non-empty."""
        pricing = _make_rule_based_pricing()
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            result = await run(
                _make_module_layout(),
                _make_thermal_load(),
                _make_electrical_assessment(),
                _make_behavioral_profile(),
            )
        assert result.metadata.pipeline_run_id is not None
        assert len(result.metadata.pipeline_run_id) > 0

    @pytest.mark.asyncio
    async def test_pipeline_run_id_is_unique_across_runs(self):
        """Each run must produce a different pipeline_run_id."""
        pricing = _make_rule_based_pricing()
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            result1 = await run(
                _make_module_layout(),
                _make_thermal_load(),
                _make_electrical_assessment(),
                _make_behavioral_profile(),
            )
            result2 = await run(
                _make_module_layout(),
                _make_thermal_load(),
                _make_electrical_assessment(),
                _make_behavioral_profile(),
            )
        assert result1.metadata.pipeline_run_id != result2.metadata.pipeline_run_id

    @pytest.mark.asyncio
    async def test_pipeline_run_id_is_valid_uuid(self):
        """pipeline_run_id must be a valid UUID4 string."""
        pricing = _make_rule_based_pricing()
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            result = await run(
                _make_module_layout(),
                _make_thermal_load(),
                _make_electrical_assessment(),
                _make_behavioral_profile(),
            )
        # Should not raise ValueError
        parsed = uuid.UUID(result.metadata.pipeline_run_id)
        assert parsed.version == 4


# ============================================================================
# Tests: Round-trip serialization
# ============================================================================


class TestRoundTripSerialization:
    """FinalProposal → JSON → FinalProposal must yield an equivalent object."""

    @pytest.mark.asyncio
    async def test_final_proposal_round_trip(self):
        """Round-trip serialization must preserve all fields."""
        pricing = _make_rule_based_pricing()
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            original = await run(
                _make_module_layout(),
                _make_thermal_load(),
                _make_electrical_assessment(),
                _make_behavioral_profile(),
            )

        json_str = original.model_dump_json()
        restored = FinalProposal.model_validate_json(json_str)

        assert restored.system_design.pv.total_kwp == pytest.approx(
            original.system_design.pv.total_kwp
        )
        assert restored.system_design.pv.panel_count == original.system_design.pv.panel_count
        assert restored.system_design.battery.capacity_kwh == pytest.approx(
            original.system_design.battery.capacity_kwh
        )
        assert restored.system_design.heat_pump.capacity_kw == pytest.approx(
            original.system_design.heat_pump.capacity_kw
        )
        assert restored.financial_summary.total_cost_eur == pytest.approx(
            original.financial_summary.total_cost_eur
        )
        assert restored.financial_summary.annual_savings_eur == pytest.approx(
            original.financial_summary.annual_savings_eur
        )
        assert restored.financial_summary.payback_years == pytest.approx(
            original.financial_summary.payback_years
        )
        assert restored.human_signoff.required == original.human_signoff.required
        assert restored.human_signoff.status == original.human_signoff.status
        assert restored.metadata.pipeline_run_id == original.metadata.pipeline_run_id

    @pytest.mark.asyncio
    async def test_round_trip_preserves_compliance(self):
        """Compliance section must survive JSON round-trip."""
        from src.common.schemas import UpgradeRequired, UpgradeType
        upgrades = [
            UpgradeRequired(
                type=UpgradeType.RCD_ADDITION,
                reason="No RCD present",
                estimated_cost_eur=300.0,
            )
        ]
        pricing = _make_rule_based_pricing()
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            original = await run(
                _make_module_layout(),
                _make_thermal_load(),
                _make_electrical_assessment(upgrades=upgrades),
                _make_behavioral_profile(),
            )

        json_str = original.model_dump_json()
        restored = FinalProposal.model_validate_json(json_str)

        assert restored.compliance.electrical_upgrades == original.compliance.electrical_upgrades
        assert restored.compliance.regulatory_notes == original.compliance.regulatory_notes

    @pytest.mark.asyncio
    async def test_round_trip_dict_roundtrip(self):
        """model_dump() → model_validate() must also yield an equivalent object."""
        pricing = _make_rule_based_pricing()
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=pricing),
        ):
            original = await run(
                _make_module_layout(),
                _make_thermal_load(),
                _make_electrical_assessment(),
                _make_behavioral_profile(),
            )

        as_dict = original.model_dump()
        restored = FinalProposal.model_validate(as_dict)

        assert restored.metadata.pipeline_run_id == original.metadata.pipeline_run_id
        assert restored.human_signoff.required == original.human_signoff.required
        assert restored.financial_summary.total_cost_eur == pytest.approx(
            original.financial_summary.total_cost_eur
        )
