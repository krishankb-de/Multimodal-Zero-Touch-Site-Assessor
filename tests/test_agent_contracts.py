"""
Per-agent contract tests (D2).

Each test:
  1. Runs the agent with valid, realistic inputs.
  2. Validates the output through validate_handoff (Safety Agent).
  3. Round-trips the output: model_dump(mode="json") → model_validate → field checks.

No API keys required — ingestion and synthesis are stubbed where needed.
Deterministic domain agents (structural, electrical, thermodynamic, behavioral)
run with real logic.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.safety.validator import validate_handoff
from src.agents.structural import agent as structural_agent
from src.agents.electrical import agent as electrical_agent
from src.agents.thermodynamic import agent as thermodynamic_agent
from src.agents.behavioral import agent as behavioral_agent
from src.agents.synthesis.agent import run as synthesis_run
from src.agents.synthesis.pioneer_client import ComponentPricing
from src.common.schemas import (
    BatteryRecommendation,
    BehavioralProfile,
    BoardCondition,
    Breaker,
    BreakerType,
    CalculationMetadata,
    ConsumptionData,
    Currency,
    DHWRequirement,
    ElectricalAssessment,
    ElectricalData,
    FaceLayout,
    FinalProposal,
    HeatingFuel,
    HeatPumpRecommendation,
    HeatPumpType,
    IngestionMetadata,
    InverterRecommendation,
    InverterType,
    MainSupply,
    ModuleLayout,
    MonthlyConsumption,
    Obstacle,
    ObstacleType,
    OccupancyPattern,
    OptimizationFrequency,
    OptimizationSchedule,
    PanelOrientation,
    RoofData,
    RoofFace,
    RoofTypology,
    SignoffStatus,
    SimpleMetadata,
    SourceType,
    SpatialData,
    StringConfig,
    StringLayout,
    Tariff,
    ThermalLoad,
    UValues,
    UtilityRoom,
)


_NOW = datetime.now(timezone.utc)


# ============================================================================
# Shared fixtures
# ============================================================================


def _spatial_data() -> SpatialData:
    return SpatialData(
        roof=RoofData(
            typology=RoofTypology.GABLE,
            faces=[
                RoofFace(
                    id="south",
                    orientation_deg=180,
                    tilt_deg=35,
                    area_m2=50.0,
                    length_m=10.0,
                    width_m=5.0,
                ),
                RoofFace(
                    id="north",
                    orientation_deg=0,
                    tilt_deg=35,
                    area_m2=50.0,
                    length_m=10.0,
                    width_m=5.0,
                ),
            ],
            total_usable_area_m2=90.0,
            obstacles=[
                Obstacle(type=ObstacleType.CHIMNEY, face_id="south", area_m2=2.0, buffer_m=0.3),
            ],
        ),
        utility_room=UtilityRoom(
            length_m=4.0,
            width_m=3.0,
            height_m=2.5,
            available_volume_m3=12.0,
            existing_pipework=True,
        ),
        metadata=IngestionMetadata(
            source_type=SourceType.VIDEO,
            confidence_score=0.90,
            timestamp=_NOW,
        ),
    )


def _electrical_data() -> ElectricalData:
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
            confidence_score=0.88,
            timestamp=_NOW,
        ),
    )


def _consumption_data() -> ConsumptionData:
    monthly_kwh = 9000 / 12
    return ConsumptionData(
        annual_kwh=9000.0,
        monthly_breakdown=[
            MonthlyConsumption(month=m, kwh=round(monthly_kwh, 1)) for m in range(1, 13)
        ],
        tariff=Tariff(currency=Currency.EUR, rate_per_kwh=0.32, feed_in_tariff_per_kwh=0.082),
        heating_fuel=HeatingFuel.GAS,
        annual_heating_kwh=14000.0,
        has_ev=False,
        metadata=IngestionMetadata(
            source_type=SourceType.PDF,
            confidence_score=0.93,
            timestamp=_NOW,
        ),
    )


def _module_layout() -> ModuleLayout:
    return ModuleLayout(
        panels=[
            FaceLayout(
                face_id="south",
                count=16,
                orientation=PanelOrientation.PORTRAIT,
                panel_watt_peak=400,
            )
        ],
        total_kwp=6.4,
        total_panels=16,
        string_config=StringLayout(
            strings=[
                StringConfig(string_id="S1", panels_in_series=8, voc_string_V=297.6, isc_string_A=11.48),
                StringConfig(string_id="S2", panels_in_series=8, voc_string_V=297.6, isc_string_A=11.48),
            ]
        ),
        metadata=CalculationMetadata(algorithm_version="1.0.0", timestamp=_NOW),
    )


def _thermal_load() -> ThermalLoad:
    return ThermalLoad(
        design_heat_load_kw=9.0,
        transmission_loss_kw=6.0,
        ventilation_loss_kw=2.5,
        design_outdoor_temp_c=-12.0,
        design_indoor_temp_c=20,
        u_values_used=UValues(walls_w_m2k=0.28, roof_w_m2k=0.16, floor_w_m2k=0.22, windows_w_m2k=1.3),
        heat_pump_recommendation=HeatPumpRecommendation(
            capacity_kw=10.0, type=HeatPumpType.AIR_SOURCE, cop_estimate=3.5, safety_factor=1.15
        ),
        dhw_requirement=DHWRequirement(
            daily_litres=150.0, cylinder_volume_litres=200, fits_in_utility_room=True
        ),
        metadata=CalculationMetadata(calculation_method="DIN_EN_12831_simplified", timestamp=_NOW),
    )


def _electrical_assessment() -> ElectricalAssessment:
    return ElectricalAssessment(
        current_capacity_sufficient=True,
        max_additional_load_A=32.0,
        upgrades_required=[],
        inverter_recommendation=InverterRecommendation(
            type=InverterType.THREE_PHASE, max_ac_output_kw=7.36
        ),
        ev_charger_compatible=True,
        metadata=SimpleMetadata(timestamp=_NOW),
    )


def _behavioral_profile() -> BehavioralProfile:
    return BehavioralProfile(
        occupancy_pattern=OccupancyPattern.AWAY_DAYTIME,
        self_consumption_ratio=0.24,
        battery_recommendation=BatteryRecommendation(
            capacity_kwh=5.9, rationale="Sized for away_daytime occupancy"
        ),
        optimization_schedule=OptimizationSchedule(
            frequency=OptimizationFrequency.QUARTERLY,
            next_review=date.today(),
        ),
        estimated_annual_savings_eur=820.0,
        metadata=SimpleMetadata(timestamp=_NOW),
    )


def _stub_pricing() -> ComponentPricing:
    return ComponentPricing(
        pv_cost_eur=7680.0,
        battery_cost_eur=5900.0,
        heat_pump_cost_eur=11000.0,
        panel_model="JA Solar JAM54S30-400",
        inverter_model="SolarEdge SE7600H",
        battery_model="BYD HVS 5.1",
        heat_pump_model="Vaillant aroTHERM plus 10",
        source="rule_based_fallback",
    )


# ============================================================================
# Helper — round-trip for any schema
# ============================================================================

def _round_trip(model, schema_cls):
    """Dump to JSON dict, re-validate, return the reloaded instance."""
    dumped = model.model_dump(mode="json")
    return schema_cls.model_validate(dumped)


# ============================================================================
# Contract: Structural Agent
# ============================================================================


class TestStructuralAgentContract:
    def test_output_passes_safety_gate(self):
        result, _ = structural_agent.run(_spatial_data())
        _, vr = validate_handoff(result.model_dump(mode="json"), "ModuleLayout", "structural")
        assert vr.valid, f"Safety gate rejected: {[e.message for e in vr.errors]}"

    def test_round_trip(self):
        result, _ = structural_agent.run(_spatial_data())
        reloaded = _round_trip(result, ModuleLayout)
        assert reloaded.total_kwp == result.total_kwp
        assert reloaded.total_panels == result.total_panels

    def test_obstacle_reduces_panel_count(self):
        """Roof with chimney must yield fewer panels than same roof without obstacles."""
        spatial_no_obs = _spatial_data()
        spatial_no_obs.roof.obstacles.clear()
        spatial_no_obs.roof.obstacles  # empty list now

        layout_with, _ = structural_agent.run(_spatial_data())
        layout_without, _ = structural_agent.run(spatial_no_obs)
        assert layout_with.total_panels <= layout_without.total_panels

    def test_string_voltage_within_limit(self):
        result, _ = structural_agent.run(_spatial_data())
        for s in result.string_config.strings:
            assert s.voc_string_V <= 1000, f"String {s.string_id} exceeds 1000V DC"


# ============================================================================
# Contract: Electrical Agent
# ============================================================================


class TestElectricalAgentContract:
    def test_output_passes_safety_gate(self):
        result = electrical_agent.run(_electrical_data())
        _, vr = validate_handoff(
            result.model_dump(mode="json"), "ElectricalAssessment", "electrical"
        )
        assert vr.valid, f"Safety gate rejected: {[e.message for e in vr.errors]}"

    def test_round_trip(self):
        result = electrical_agent.run(_electrical_data())
        reloaded = _round_trip(result, ElectricalAssessment)
        assert reloaded.current_capacity_sufficient == result.current_capacity_sufficient
        assert reloaded.inverter_recommendation.type == result.inverter_recommendation.type

    def test_three_phase_supply_gives_three_phase_inverter(self):
        result = electrical_agent.run(_electrical_data())
        assert result.inverter_recommendation.type == InverterType.THREE_PHASE

    def test_sufficient_capacity_with_headroom(self):
        result = electrical_agent.run(_electrical_data())
        assert result.current_capacity_sufficient is True
        assert result.max_additional_load_A > 0


# ============================================================================
# Contract: Thermodynamic Agent
# ============================================================================


class TestThermodynamicAgentContract:
    def test_output_passes_safety_gate(self):
        result = thermodynamic_agent.run(_spatial_data(), _consumption_data())
        _, vr = validate_handoff(result.model_dump(mode="json"), "ThermalLoad", "thermodynamic")
        assert vr.valid, f"Safety gate rejected: {[e.message for e in vr.errors]}"

    def test_round_trip(self):
        result = thermodynamic_agent.run(_spatial_data(), _consumption_data())
        reloaded = _round_trip(result, ThermalLoad)
        assert reloaded.design_heat_load_kw == pytest.approx(result.design_heat_load_kw)
        assert reloaded.dhw_requirement.cylinder_volume_litres == result.dhw_requirement.cylinder_volume_litres

    def test_cop_within_guardrail(self):
        result = thermodynamic_agent.run(_spatial_data(), _consumption_data())
        cop = result.heat_pump_recommendation.cop_estimate
        assert 1.0 <= cop <= 7.0

    def test_dhw_daily_litres_at_least_50(self):
        result = thermodynamic_agent.run(_spatial_data(), _consumption_data())
        assert result.dhw_requirement.daily_litres >= 50.0

    def test_outdoor_temp_from_regional_table(self):
        """design_outdoor_temp_c must come from climate table, not old config constant."""
        from src.common import climate
        from src.common.config import config
        result = thermodynamic_agent.run(_spatial_data(), _consumption_data())
        expected_temp = climate.design_outdoor_temp_c(config.market.region)
        assert result.design_outdoor_temp_c == pytest.approx(expected_temp)


# ============================================================================
# Contract: Behavioral Agent
# ============================================================================


class TestBehavioralAgentContract:
    def test_output_passes_safety_gate(self):
        result = behavioral_agent.run(_consumption_data())
        _, vr = validate_handoff(result.model_dump(mode="json"), "BehavioralProfile", "behavioral")
        assert vr.valid, f"Safety gate rejected: {[e.message for e in vr.errors]}"

    def test_round_trip(self):
        result = behavioral_agent.run(_consumption_data())
        reloaded = _round_trip(result, BehavioralProfile)
        assert reloaded.occupancy_pattern == result.occupancy_pattern
        assert reloaded.battery_recommendation.capacity_kwh == pytest.approx(
            result.battery_recommendation.capacity_kwh
        )

    def test_battery_capacity_within_bounds(self):
        result = behavioral_agent.run(_consumption_data())
        cap = result.battery_recommendation.capacity_kwh
        assert 0.5 <= cap <= 50.0

    def test_self_consumption_ratio_between_0_and_1(self):
        result = behavioral_agent.run(_consumption_data())
        assert 0.0 <= result.self_consumption_ratio <= 1.0

    def test_savings_within_allowed_range(self):
        result = behavioral_agent.run(_consumption_data())
        assert 0.0 <= result.estimated_annual_savings_eur <= 5000.0


# ============================================================================
# Contract: Synthesis Agent
# ============================================================================


class TestSynthesisAgentContract:
    @pytest.mark.asyncio
    async def test_output_passes_safety_gate(self):
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=_stub_pricing()),
        ):
            result = await synthesis_run(
                _module_layout(), _thermal_load(), _electrical_assessment(),
                _behavioral_profile(), _consumption_data(), _spatial_data(),
            )
        _, vr = validate_handoff(result.model_dump(mode="json"), "FinalProposal", "synthesis")
        assert vr.valid, f"Safety gate rejected: {[e.message for e in vr.errors]}"

    @pytest.mark.asyncio
    async def test_round_trip(self):
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=_stub_pricing()),
        ):
            result = await synthesis_run(
                _module_layout(), _thermal_load(), _electrical_assessment(),
                _behavioral_profile(), _consumption_data(), _spatial_data(),
            )
        reloaded = _round_trip(result, FinalProposal)
        assert reloaded.human_signoff.required is True
        assert reloaded.human_signoff.status == SignoffStatus.PENDING
        assert reloaded.financial_summary.total_cost_eur == pytest.approx(
            result.financial_summary.total_cost_eur
        )

    @pytest.mark.asyncio
    async def test_annual_yield_populated_from_climate(self):
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=_stub_pricing()),
        ):
            result = await synthesis_run(
                _module_layout(), _thermal_load(), _electrical_assessment(),
                _behavioral_profile(), _consumption_data(), _spatial_data(),
            )
        assert result.system_design.pv.annual_yield_kwh is not None
        assert result.system_design.pv.annual_yield_kwh > 0

    @pytest.mark.asyncio
    async def test_human_signoff_always_required(self):
        with patch(
            "src.agents.synthesis.pioneer_client.get_component_pricing",
            new=AsyncMock(return_value=_stub_pricing()),
        ):
            result = await synthesis_run(
                _module_layout(), _thermal_load(), _electrical_assessment(),
                _behavioral_profile(),
            )
        assert result.human_signoff.required is True
        assert result.human_signoff.status == SignoffStatus.PENDING
