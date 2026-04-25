"""
Design Synthesis Agent.

Combines all domain agent outputs into a FinalProposal, calling the Pioneer SLM
for component pricing (with rule-based fallback) and assembling the full proposal
ready for human installer sign-off.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.agents.synthesis import pioneer_client
from src.agents.synthesis.reonic_dataset import CustomerProfile
from src.common.schemas import (
    BatteryDesign,
    BehavioralProfile,
    Compliance,
    ConsumptionData,
    ElectricalAssessment,
    FinalProposal,
    FinancialSummary,
    HeatPumpDesign,
    HumanSignoff,
    ModuleLayout,
    ProposalMetadata,
    PVDesign,
    SignoffStatus,
    SpatialData,
    SystemDesign,
    ThermalLoad,
)


def _build_customer_profile(
    consumption_data: ConsumptionData | None,
    spatial_data: SpatialData | None,
) -> CustomerProfile | None:
    """Build a Reonic-retrieval feature vector from ingestion outputs."""
    if consumption_data is None:
        return None
    house_size_sqm: float | None = None
    if spatial_data is not None:
        ur = spatial_data.utility_room
        house_size_sqm = ur.length_m * ur.width_m * 8  # rough proxy: utility footprint × floors
    return CustomerProfile(
        energy_demand_wh=float(consumption_data.annual_kwh) * 1000.0,
        energy_price_per_wh=float(consumption_data.tariff.rate_per_kwh) / 1000.0,
        has_ev=bool(consumption_data.has_ev),
        heating_existing_type=(consumption_data.heating_fuel.value
                               if consumption_data.heating_fuel else "none"),
        house_size_sqm=house_size_sqm,
    )


async def run(
    module_layout: ModuleLayout,
    thermal_load: ThermalLoad,
    electrical_assessment: ElectricalAssessment,
    behavioral_profile: BehavioralProfile,
    consumption_data: ConsumptionData | None = None,
    spatial_data: SpatialData | None = None,
) -> FinalProposal:
    """
    Assemble a FinalProposal from all domain agent outputs.

    Steps:
    1. Fetch component pricing from Pioneer SLM (or rule-based fallback).
    2. Build system_design from domain agent outputs.
    3. Calculate financial summary.
    4. Build compliance section.
    5. Set human_signoff to required/pending.
    6. Generate proposal metadata.
    """

    # ------------------------------------------------------------------
    # 1. Component pricing + Reonic-grounded recommendations
    # ------------------------------------------------------------------
    customer_profile = _build_customer_profile(consumption_data, spatial_data)
    pricing = await pioneer_client.get_component_pricing(
        total_kwp=module_layout.total_kwp,
        battery_kwh=behavioral_profile.battery_recommendation.capacity_kwh,
        heat_pump_kw=thermal_load.heat_pump_recommendation.capacity_kw,
        customer_profile=customer_profile,
    )

    # ------------------------------------------------------------------
    # 2. System design
    # ------------------------------------------------------------------
    pv = PVDesign(
        total_kwp=module_layout.total_kwp,
        panel_count=module_layout.total_panels,
        panel_model=pricing.panel_model,
        inverter_type=electrical_assessment.inverter_recommendation.type.value,
        inverter_model=pricing.inverter_model,
    )

    battery = BatteryDesign(
        included=True,
        capacity_kwh=behavioral_profile.battery_recommendation.capacity_kwh,
        model=pricing.battery_model,
    )

    heat_pump = HeatPumpDesign(
        included=True,
        capacity_kw=thermal_load.heat_pump_recommendation.capacity_kw,
        type=thermal_load.heat_pump_recommendation.type.value,
        model=pricing.heat_pump_model,
        cop=thermal_load.heat_pump_recommendation.cop_estimate,
        cylinder_litres=thermal_load.dhw_requirement.cylinder_volume_litres,
    )

    system_design = SystemDesign(pv=pv, battery=battery, heat_pump=heat_pump)

    # ------------------------------------------------------------------
    # 3. Financial summary
    # ------------------------------------------------------------------
    electrical_upgrade_cost = sum(
        u.estimated_cost_eur for u in electrical_assessment.upgrades_required
    )

    total_cost_eur = (
        pricing.pv_cost_eur
        + pricing.battery_cost_eur
        + pricing.heat_pump_cost_eur
        + electrical_upgrade_cost
    )

    # 200 EUR/kW/year operational savings vs gas boiler
    heat_pump_savings = thermal_load.heat_pump_recommendation.capacity_kw * 200.0

    annual_savings_eur = (
        behavioral_profile.estimated_annual_savings_eur or 0.0
    ) + heat_pump_savings

    payback_years = (
        total_cost_eur / annual_savings_eur if annual_savings_eur > 0 else 0.0
    )

    financial_summary = FinancialSummary(
        total_cost_eur=total_cost_eur,
        annual_savings_eur=annual_savings_eur,
        payback_years=payback_years,
    )

    # ------------------------------------------------------------------
    # 4. Compliance
    # ------------------------------------------------------------------
    electrical_upgrades = [u.reason for u in electrical_assessment.upgrades_required]

    regulatory_notes: list[str] = [
        "Human installer sign-off required before proposal delivery"
    ]
    if pricing.warning:
        regulatory_notes.append(pricing.warning)
    if pricing.reonic_neighbor_ids:
        regulatory_notes.append(
            f"Design grounded in {len(pricing.reonic_neighbor_ids)} Reonic historical projects "
            f"(source={pricing.source})"
        )

    compliance = Compliance(
        electrical_upgrades=electrical_upgrades,
        regulatory_notes=regulatory_notes,
    )

    # ------------------------------------------------------------------
    # 5. Human sign-off (always required, always pending at creation)
    # ------------------------------------------------------------------
    human_signoff = HumanSignoff(
        required=True,
        status=SignoffStatus.PENDING,
    )

    # ------------------------------------------------------------------
    # 6. Metadata
    # ------------------------------------------------------------------
    metadata = ProposalMetadata(
        pipeline_run_id=str(uuid.uuid4()),
        version="1.0.0",
        generated_at=datetime.now(timezone.utc),
        all_validations_passed=None,  # Set by orchestrator after Safety Agent validation
    )

    return FinalProposal(
        system_design=system_design,
        financial_summary=financial_summary,
        compliance=compliance,
        human_signoff=human_signoff,
        metadata=metadata,
    )
