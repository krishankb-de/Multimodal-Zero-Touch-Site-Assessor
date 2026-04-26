"""
Design Synthesis Agent.

Combines all domain agent outputs into a FinalProposal, calling the Pioneer SLM
for component pricing (with rule-based fallback) and assembling the full proposal
ready for human installer sign-off.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.common import climate as climate_data
from src.common.config import config
from src.common import sld_generator
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
    InstallationPlan,
    ModuleLayout,
    PanelOrientation,
    PanelPosition,
    ProposalMetadata,
    PVDesign,
    SignoffStatus,
    SpatialData,
    SystemDesign,
    ThermalLoad,
    WeatherProfile,
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


def _compute_shading_multiplier(
    module_layout: ModuleLayout,
    face_shading_factors: dict[str, float] | None,
) -> float:
    """Weighted-average shading factor across all faces (by panel count)."""
    if not face_shading_factors:
        return 1.0
    total_panels = sum(f.count for f in module_layout.panels)
    if total_panels == 0:
        return 1.0
    weighted = sum(
        face_shading_factors.get(f.face_id, 1.0) * f.count
        for f in module_layout.panels
    )
    return weighted / total_panels


def _compute_annual_yield_kwh(
    module_layout: ModuleLayout,
    shading_multiplier: float,
    weather_profile: Optional[WeatherProfile],
    region: str,
) -> tuple[float, str]:
    """
    Compute annual PV yield and return (yield_kwh, data_source_note).

    When a WeatherProfile is available, uses location-specific irradiance
    with a cloud cover correction factor (Req 7.1, 7.2).
    Falls back to static regional data otherwise (Req 7.3).
    """
    if weather_profile is not None:
        # Location-specific irradiance from historical data (Req 7.1)
        irradiance = weather_profile.annual_irradiance_kwh_m2

        # Cloud cover correction factor: each 1% of cloud cover reduces yield
        # by 0.5% relative to clear-sky baseline (empirical approximation).
        # avg_cloud_cover_pct of 0 → factor 1.0; 100% → factor 0.5 (Req 7.2)
        avg_cloud_cover_pct = sum(weather_profile.monthly_cloud_cover_pct) / 12.0
        cloud_correction = 1.0 - (avg_cloud_cover_pct / 100.0) * 0.5

        annual_yield_kwh = (
            module_layout.total_kwp
            * irradiance
            * climate_data.SYSTEM_EFFICIENCY
            * cloud_correction
            * shading_multiplier
        )
        data_source_note = (
            f"Climate data: location-specific (lat={weather_profile.latitude:.4f}, "
            f"lon={weather_profile.longitude:.4f}), "
            f"irradiance={irradiance:.0f} kWh/m²/year, "
            f"avg_cloud_cover={avg_cloud_cover_pct:.1f}%, "
            f"cloud_correction_factor={cloud_correction:.3f}"
        )
    else:
        # Static regional fallback (Req 7.3)
        annual_yield_kwh = (
            climate_data.annual_pv_yield_kwh(module_layout.total_kwp, region)
            * shading_multiplier
        )
        data_source_note = (
            f"Climate data: static regional (region={region}), "
            f"irradiance={climate_data.annual_irradiance_kwh_m2(region):.0f} kWh/m²/year, "
            f"design_outdoor_temp={climate_data.design_outdoor_temp_c(region):.1f}°C"
        )

    return annual_yield_kwh, data_source_note


def _generate_installation_plan(
    spatial_data: SpatialData,
    module_layout: ModuleLayout,
) -> Optional[InstallationPlan]:
    """
    Generate an InstallationPlan when HouseDimensions are available (Req 14.1–14.3).

    Lays out panels on each roof face using a simple row-by-column grid starting
    from the top-left corner of each face. Panel dimensions default to 1.0 m × 1.7 m
    (portrait) or 1.7 m × 1.0 m (landscape) when not specified in the FaceLayout.

    Returns None when HouseDimensions are not available (Req 14.3).
    """
    if spatial_data is None or spatial_data.house_dimensions is None:
        return None

    dims = spatial_data.house_dimensions

    # Default panel physical dimensions (metres)
    DEFAULT_PANEL_W_PORTRAIT = 1.0
    DEFAULT_PANEL_H_PORTRAIT = 1.7

    panel_positions: list[PanelPosition] = []
    panels_per_face: dict[str, int] = {}

    for face in module_layout.panels:
        if face.count == 0:
            continue

        # Resolve physical panel size
        if face.panel_dimensions_mm is not None:
            pw_m = face.panel_dimensions_mm.width / 1000.0
            ph_m = face.panel_dimensions_mm.length / 1000.0
        else:
            pw_m = DEFAULT_PANEL_W_PORTRAIT
            ph_m = DEFAULT_PANEL_H_PORTRAIT

        # Swap for landscape orientation
        if face.orientation == PanelOrientation.LANDSCAPE:
            pw_m, ph_m = ph_m, pw_m

        # Simple grid layout: fill columns left-to-right, rows top-to-bottom
        # Use building width as the available face width
        face_width_m = dims.footprint_width_m
        cols = max(1, int(face_width_m / pw_m))

        placed = 0
        row = 0
        while placed < face.count:
            col = placed % cols
            if placed > 0 and col == 0:
                row += 1
            panel_positions.append(
                PanelPosition(
                    face_id=face.face_id,
                    x_offset_m=round(col * pw_m, 3),
                    y_offset_m=round(row * ph_m, 3),
                    width_m=round(pw_m, 3),
                    height_m=round(ph_m, 3),
                    orientation=face.orientation,
                )
            )
            placed += 1

        panels_per_face[face.face_id] = face.count

    return InstallationPlan(
        building_width_m=dims.footprint_width_m,
        building_depth_m=dims.footprint_depth_m,
        building_ridge_height_m=dims.ridge_height_m,
        building_eave_height_m=dims.eave_height_m,
        panel_positions=panel_positions,
        panels_per_face=panels_per_face,
        total_kwp=module_layout.total_kwp,
    )


async def run(
    module_layout: ModuleLayout,
    thermal_load: ThermalLoad,
    electrical_assessment: ElectricalAssessment,
    behavioral_profile: BehavioralProfile,
    consumption_data: ConsumptionData | None = None,
    spatial_data: SpatialData | None = None,
    face_shading_factors: dict[str, float] | None = None,
    weather_profile: Optional[WeatherProfile] = None,
    pipeline_run_id: Optional[str] = None,
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
    7. Generate SLD and attach reference.
    8. Generate InstallationPlan when HouseDimensions are available.

    Args:
        weather_profile: Optional WeatherProfile — when present, uses location-specific
                         irradiance with cloud cover correction (Req 7.1, 7.2, 7.3).
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
    region = config.market.region
    # Apply per-face shading correction when available (weighted by panel count per face)
    shading_multiplier = _compute_shading_multiplier(module_layout, face_shading_factors)

    # Use location-specific irradiance when WeatherProfile is available (Req 7.1, 7.2)
    annual_yield_kwh, data_source_note = _compute_annual_yield_kwh(
        module_layout, shading_multiplier, weather_profile, region
    )

    pv = PVDesign(
        total_kwp=module_layout.total_kwp,
        panel_count=module_layout.total_panels,
        panel_model=pricing.panel_model,
        inverter_type=electrical_assessment.inverter_recommendation.type.value,
        inverter_model=pricing.inverter_model,
        annual_yield_kwh=annual_yield_kwh,
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

    # PV export savings: yield exported at feed-in tariff (assume 30% self-consumed)
    feed_in_rate = consumption_data.tariff.feed_in_tariff_per_kwh if (
        consumption_data and consumption_data.tariff.feed_in_tariff_per_kwh
    ) else 0.082
    pv_export_savings = annual_yield_kwh * 0.70 * feed_in_rate

    # 200 EUR/kW/year operational savings vs gas boiler
    heat_pump_savings = thermal_load.heat_pump_recommendation.capacity_kw * 200.0

    annual_savings_eur = (
        behavioral_profile.estimated_annual_savings_eur or 0.0
    ) + heat_pump_savings + pv_export_savings

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
        "Human installer sign-off required before proposal delivery",
        data_source_note,  # Req 7.3: data source note (location-specific or static)
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
    run_id = pipeline_run_id or str(uuid.uuid4())
    metadata = ProposalMetadata(
        pipeline_run_id=run_id,
        version="1.0.0",
        generated_at=datetime.now(timezone.utc),
        all_validations_passed=None,  # Set by orchestrator after Safety Agent validation
    )

    # ------------------------------------------------------------------
    # 7. Generate InstallationPlan when HouseDimensions are available (Req 14.1–14.3)
    # ------------------------------------------------------------------
    installation_plan = _generate_installation_plan(spatial_data, module_layout) if spatial_data else None

    proposal = FinalProposal(
        system_design=system_design,
        financial_summary=financial_summary,
        compliance=compliance,
        human_signoff=human_signoff,
        metadata=metadata,
        installation_plan=installation_plan,
    )

    # ------------------------------------------------------------------
    # 8. Generate SLD and attach reference
    # ------------------------------------------------------------------
    sld_dir = Path(__file__).resolve().parents[3] / "sld_output"
    sld_path = sld_generator.write_sld(proposal, sld_dir)
    proposal.compliance.single_line_diagram_ref = str(sld_path)

    return proposal
