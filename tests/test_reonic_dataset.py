"""
Tests for the Reonic dataset loader and kNN retrieval.

Acceptance criteria for issue B2:
- Loads ≥1 historical project from Datasets/Project Data/
- Retrieves ≥3 nearest neighbors for a synthetic German residential profile
- summarize_neighbors returns non-zero medians + at least one brand
- Synthesis agent populates panel/inverter/heat-pump model fields from retrieval
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.synthesis import pioneer_client
from src.agents.synthesis.reonic_dataset import (
    CustomerProfile,
    find_similar,
    load_dataset,
    retrieve_for_profile,
    summarize_neighbors,
)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def test_load_dataset_non_empty():
    """Reonic CSVs under Datasets/Project Data/ produce ≥1 historical project."""
    projects = load_dataset()
    assert len(projects) >= 10, f"Expected ≥10 projects, got {len(projects)}"


def test_load_dataset_has_pv_projects():
    """At least some loaded projects must have non-zero PV capacity."""
    projects = load_dataset()
    pv_projects = [p for p in projects if p.pv_kwp > 0]
    assert len(pv_projects) >= 5


def test_load_dataset_cached():
    """Repeat calls return the same list instance (LRU-cached)."""
    a = load_dataset()
    b = load_dataset()
    assert a is b


# ---------------------------------------------------------------------------
# kNN retrieval
# ---------------------------------------------------------------------------


def _german_profile() -> CustomerProfile:
    return CustomerProfile(
        energy_demand_wh=5_000_000.0,
        energy_price_per_wh=0.00035,
        has_ev=False,
        heating_existing_type="gas",
        house_size_sqm=140.0,
    )


def test_find_similar_returns_at_least_three():
    """B2 acceptance: ≥3 matches for a synthetic profile."""
    neighbors = find_similar(_german_profile(), k=5)
    assert len(neighbors) >= 3


def test_find_similar_respects_k():
    """k=1 returns at most 1 result."""
    assert len(find_similar(_german_profile(), k=1)) <= 1


def test_summarize_neighbors_yields_brand_and_capacity():
    """Aggregation produces non-zero PV median and at least one brand."""
    summary = retrieve_for_profile(_german_profile(), k=5)
    assert summary is not None
    assert summary.n_neighbors >= 3
    assert summary.median_pv_kwp > 0
    # At least one of these brands should be populated from the dataset
    assert any([summary.top_panel_brand, summary.top_inverter_brand, summary.top_heatpump_brand])


def test_summarize_empty_returns_none():
    assert summarize_neighbors([]) is None


# ---------------------------------------------------------------------------
# End-to-end: synthesis pulls Reonic-grounded models
# ---------------------------------------------------------------------------


def test_rule_based_pricing_with_profile_pulls_brand():
    """get_rule_based_pricing(customer_profile=...) attaches Reonic brand suggestions."""
    pricing = pioneer_client.get_rule_based_pricing(
        total_kwp=8.0,
        battery_kwh=10.0,
        heat_pump_kw=10.0,
        customer_profile=_german_profile(),
    )
    assert pricing.source == "rule_based_fallback"
    assert pricing.reonic_neighbor_ids is not None
    assert len(pricing.reonic_neighbor_ids) >= 3
    # At least one model field should be populated by Reonic retrieval
    assert any([
        pricing.panel_model,
        pricing.inverter_model,
        pricing.heat_pump_model,
    ])


@pytest.mark.asyncio
async def test_synthesis_populates_models_from_reonic():
    """FinalProposal.system_design must carry Reonic-derived model strings when consumption is provided."""
    from src.agents.synthesis.agent import run
    from src.common.schemas import (
        BatteryRecommendation,
        BehavioralProfile,
        CalculationMetadata,
        ConsumptionData,
        IngestionMetadata,
        Currency,
        DHWRequirement,
        ElectricalAssessment,
        FaceLayout,
        HeatingFuel,
        HeatPumpRecommendation,
        HeatPumpType,
        InverterRecommendation,
        InverterType,
        ModuleLayout,
        MonthlyConsumption,
        OccupancyPattern,
        OptimizationFrequency,
        OptimizationSchedule,
        PanelOrientation,
        SimpleMetadata,
        SourceType,
        StringConfig,
        StringLayout,
        Tariff,
        ThermalLoad,
        UValues,
    )

    now = datetime.now(timezone.utc)
    consumption = ConsumptionData(
        annual_kwh=5000.0,
        monthly_breakdown=[MonthlyConsumption(month=m, kwh=400.0 + m * 5) for m in range(1, 13)],
        tariff=Tariff(currency=Currency.EUR, rate_per_kwh=0.35),
        heating_fuel=HeatingFuel.GAS,
        annual_heating_kwh=12000.0,
        has_ev=False,
        metadata=IngestionMetadata(
            source_type=SourceType.PDF,
            confidence_score=0.9,
            timestamp=now,
        ),
    )

    module_layout = ModuleLayout(
        panels=[FaceLayout(face_id="south", count=20, orientation=PanelOrientation.PORTRAIT, panel_watt_peak=400)],
        total_kwp=8.0,
        total_panels=20,
        string_config=StringLayout(strings=[
            StringConfig(string_id="S1", panels_in_series=10, voc_string_V=420.0, isc_string_A=11.5),
            StringConfig(string_id="S2", panels_in_series=10, voc_string_V=420.0, isc_string_A=11.5),
        ]),
        metadata=CalculationMetadata(algorithm_version="1.0.0", timestamp=now),
    )
    thermal = ThermalLoad(
        design_heat_load_kw=8.5,
        transmission_loss_kw=5.5,
        ventilation_loss_kw=2.0,
        design_outdoor_temp_c=-12,
        design_indoor_temp_c=20,
        u_values_used=UValues(walls_w_m2k=0.28, roof_w_m2k=0.16, floor_w_m2k=0.22, windows_w_m2k=1.3),
        heat_pump_recommendation=HeatPumpRecommendation(
            capacity_kw=10.0, type=HeatPumpType.AIR_SOURCE, cop_estimate=3.5, safety_factor=1.15,
        ),
        dhw_requirement=DHWRequirement(daily_litres=150.0, cylinder_volume_litres=200, fits_in_utility_room=True),
        metadata=CalculationMetadata(calculation_method="DIN_EN_12831_simplified", timestamp=now),
    )
    electrical = ElectricalAssessment(
        current_capacity_sufficient=True,
        max_additional_load_A=40.0,
        upgrades_required=[],
        inverter_recommendation=InverterRecommendation(type=InverterType.HYBRID, max_ac_output_kw=8.0),
        ev_charger_compatible=True,
        metadata=SimpleMetadata(timestamp=now),
    )
    behavioral = BehavioralProfile(
        occupancy_pattern=OccupancyPattern.AWAY_DAYTIME,
        self_consumption_ratio=0.35,
        battery_recommendation=BatteryRecommendation(capacity_kwh=10.0, rationale="Sized for away_daytime"),
        optimization_schedule=OptimizationSchedule(frequency=OptimizationFrequency.QUARTERLY, next_review=date.today()),
        estimated_annual_savings_eur=780.0,
        metadata=SimpleMetadata(timestamp=now),
    )

    # Force rule-based path by clearing api key
    with patch("src.agents.synthesis.pioneer_client.config") as mock_config:
        mock_config.pioneer.api_key = ""
        result = await run(
            module_layout=module_layout,
            thermal_load=thermal,
            electrical_assessment=electrical,
            behavioral_profile=behavioral,
            consumption_data=consumption,
        )

    # Reonic retrieval must have populated at least one model string
    assert any([
        result.system_design.pv.panel_model,
        result.system_design.pv.inverter_model,
        result.system_design.heat_pump.model,
    ]), "Synthesis should attach Reonic-grounded models when consumption is provided"

    # Regulatory note must reference Reonic provenance
    assert any("Reonic" in n for n in result.compliance.regulatory_notes)
