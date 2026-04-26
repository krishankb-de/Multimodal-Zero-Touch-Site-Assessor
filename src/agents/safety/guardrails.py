"""
Safety Guardrails — Domain-Specific Validation Rules

These rules enforce physical, electrical, and regulatory constraints for
residential renewable energy systems. They go beyond schema validation to
catch semantically invalid but syntactically correct data.

All rules from the CLAUDE.md guardrails table are implemented here.
"""

from __future__ import annotations

from src.common.schemas import (
    BehavioralProfile,
    ConsumptionData,
    ElectricalAssessment,
    ElectricalData,
    ErrorSeverity,
    FinalProposal,
    ModuleLayout,
    SpatialData,
    ThermalLoad,
    ValidationError,
    WeatherProfile,
    VALID_BREAKER_RATINGS,
    VALID_CYLINDER_SIZES,
)

# Maximum kWp per m² — typical high-efficiency panel is ~0.22 kWp/m²
MAX_KWP_PER_M2 = 0.22

# Residential voltage limits
MAX_DC_VOLTAGE = 1000  # Volts
MAX_AC_VOLTAGE = 400   # Volts

# Confidence floor for Gemini outputs
MIN_CONFIDENCE_SCORE = 0.6

# Germany bounding box (must match geocoding.py constants)
GERMANY_LAT_MIN = 47.0
GERMANY_LAT_MAX = 55.5
GERMANY_LON_MIN = 5.5
GERMANY_LON_MAX = 15.5

# Plausible annual irradiance range for Germany (kWh/m²/year)
GERMANY_IRRADIANCE_MIN = 700.0
GERMANY_IRRADIANCE_MAX = 1400.0


def run_guardrail_checks(
    instance: object,
    schema_name: str,
) -> tuple[list[ValidationError], list[str]]:
    """
    Run domain-specific guardrail checks on a validated model instance.

    Returns:
        Tuple of (hard errors, soft warnings).
    """
    errors: list[ValidationError] = []
    warnings: list[str] = []

    # Dispatch to schema-specific checks
    match schema_name:
        case "SpatialData":
            assert isinstance(instance, SpatialData)
            _check_spatial_data(instance, errors, warnings)
        case "ElectricalData":
            assert isinstance(instance, ElectricalData)
            _check_electrical_data(instance, errors, warnings)
        case "ConsumptionData":
            assert isinstance(instance, ConsumptionData)
            _check_consumption_data(instance, errors, warnings)
        case "ModuleLayout":
            assert isinstance(instance, ModuleLayout)
            _check_module_layout(instance, errors, warnings)
        case "ThermalLoad":
            assert isinstance(instance, ThermalLoad)
            _check_thermal_load(instance, errors, warnings)
        case "ElectricalAssessment":
            assert isinstance(instance, ElectricalAssessment)
            _check_electrical_assessment(instance, errors, warnings)
        case "BehavioralProfile":
            assert isinstance(instance, BehavioralProfile)
            _check_behavioral_profile(instance, errors, warnings)
        case "FinalProposal":
            assert isinstance(instance, FinalProposal)
            _check_final_proposal(instance, errors, warnings)
        case "WeatherProfile":
            assert isinstance(instance, WeatherProfile)
            _check_weather_profile(instance, errors, warnings)

    return errors, warnings


# ============================================================================
# SpatialData checks
# ============================================================================


def _check_spatial_data(
    data: SpatialData,
    errors: list[ValidationError],
    warnings: list[str],
) -> None:
    # Confidence floor — global
    if data.metadata.confidence_score < MIN_CONFIDENCE_SCORE:
        warnings.append(
            f"Low confidence score ({data.metadata.confidence_score:.2f}) — "
            "flag for manual review"
        )

    # Phase 4: mesh-presence guardrail — if mesh provided, ≥80% faces need 3D polygons
    if data.mesh_uri:
        faces_with_3d = sum(
            1 for f in data.roof.faces if f.polygon_vertices_3d is not None
        )
        total_faces = len(data.roof.faces)
        if total_faces > 0:
            ratio = faces_with_3d / total_faces
            if ratio < 0.8:
                errors.append(
                    ValidationError(
                        code="MISSING_3D_POLYGONS",
                        message=(
                            f"mesh_uri is set but only {faces_with_3d}/{total_faces} faces "
                            f"({ratio:.0%}) have polygon_vertices_3d — required ≥80%"
                        ),
                        field="roof.faces",
                        severity=ErrorSeverity.ERROR,
                    )
                )

    # Total usable area must not exceed sum of face areas
    face_area_sum = sum(f.area_m2 for f in data.roof.faces)
    if data.roof.total_usable_area_m2 > face_area_sum * 1.1:  # 10% tolerance
        errors.append(
            ValidationError(
                code="AREA_INCONSISTENCY",
                message=(
                    f"Total usable area ({data.roof.total_usable_area_m2} m²) exceeds "
                    f"sum of face areas ({face_area_sum:.1f} m²) by >10%"
                ),
                field="roof.total_usable_area_m2",
                severity=ErrorSeverity.ERROR,
            )
        )

    # Obstacle face_ids must reference existing faces
    face_ids = {f.id for f in data.roof.faces}
    for obs in data.roof.obstacles:
        if obs.face_id not in face_ids:
            errors.append(
                ValidationError(
                    code="INVALID_FACE_REF",
                    message=f"Obstacle references unknown face_id '{obs.face_id}'",
                    field="roof.obstacles",
                    severity=ErrorSeverity.ERROR,
                )
            )

    # Utility room volume sanity
    calculated_volume = data.utility_room.length_m * data.utility_room.width_m * data.utility_room.height_m
    if data.utility_room.available_volume_m3 > calculated_volume:
        errors.append(
            ValidationError(
                code="VOLUME_INCONSISTENCY",
                message=(
                    f"Available volume ({data.utility_room.available_volume_m3} m³) exceeds "
                    f"room dimensions ({calculated_volume:.1f} m³)"
                ),
                field="utility_room.available_volume_m3",
                severity=ErrorSeverity.ERROR,
            )
        )


# ============================================================================
# ElectricalData checks
# ============================================================================


def _check_electrical_data(
    data: ElectricalData,
    errors: list[ValidationError],
    warnings: list[str],
) -> None:
    # Confidence floor
    if data.metadata.confidence_score < MIN_CONFIDENCE_SCORE:
        warnings.append(
            f"Low confidence score ({data.metadata.confidence_score:.2f}) — "
            "flag for manual review"
        )

    # Phases and voltage consistency
    if data.main_supply.phases == 1 and data.main_supply.voltage_V != 230:
        errors.append(
            ValidationError(
                code="VOLTAGE_PHASE_MISMATCH",
                message="Single-phase supply must be 230V",
                field="main_supply.voltage_V",
                severity=ErrorSeverity.ERROR,
            )
        )
    if data.main_supply.phases == 3 and data.main_supply.voltage_V != 400:
        errors.append(
            ValidationError(
                code="VOLTAGE_PHASE_MISMATCH",
                message="Three-phase supply must be 400V",
                field="main_supply.voltage_V",
                severity=ErrorSeverity.ERROR,
            )
        )

    # Breaker ratings must be standard values
    for i, breaker in enumerate(data.breakers):
        if breaker.rating_A not in VALID_BREAKER_RATINGS:
            errors.append(
                ValidationError(
                    code="INVALID_BREAKER_RATING",
                    message=(
                        f"Breaker '{breaker.label}' has non-standard rating "
                        f"{breaker.rating_A}A. Valid: {sorted(VALID_BREAKER_RATINGS)}"
                    ),
                    field=f"breakers[{i}].rating_A",
                    severity=ErrorSeverity.ERROR,
                )
            )


# ============================================================================
# ConsumptionData checks
# ============================================================================


def _check_consumption_data(
    data: ConsumptionData,
    errors: list[ValidationError],
    warnings: list[str],
) -> None:
    # Confidence floor
    if data.metadata.confidence_score < MIN_CONFIDENCE_SCORE:
        warnings.append(
            f"Low confidence score ({data.metadata.confidence_score:.2f}) — "
            "flag for manual review"
        )

    # Monthly breakdown should approximately sum to annual
    monthly_sum = sum(m.kwh for m in data.monthly_breakdown)
    tolerance = data.annual_kwh * 0.1  # 10% tolerance
    if abs(monthly_sum - data.annual_kwh) > tolerance:
        errors.append(
            ValidationError(
                code="CONSUMPTION_MISMATCH",
                message=(
                    f"Monthly sum ({monthly_sum:.0f} kWh) differs from annual "
                    f"({data.annual_kwh:.0f} kWh) by more than 10%"
                ),
                field="monthly_breakdown",
                severity=ErrorSeverity.ERROR,
            )
        )

    # All 12 months must be represented
    months_present = {m.month for m in data.monthly_breakdown}
    if months_present != set(range(1, 13)):
        missing = set(range(1, 13)) - months_present
        errors.append(
            ValidationError(
                code="MISSING_MONTHS",
                message=f"Missing months: {sorted(missing)}",
                field="monthly_breakdown",
                severity=ErrorSeverity.ERROR,
            )
        )


# ============================================================================
# ModuleLayout checks
# ============================================================================


def _check_module_layout(
    data: ModuleLayout,
    errors: list[ValidationError],
    warnings: list[str],
) -> None:
    # DC voltage limit — CRITICAL SAFETY CHECK
    for i, string in enumerate(data.string_config.strings):
        if string.voc_string_V > MAX_DC_VOLTAGE:
            errors.append(
                ValidationError(
                    code="VOLTAGE_EXCEEDED",
                    message=(
                        f"String '{string.string_id}' Voc={string.voc_string_V}V "
                        f"exceeds {MAX_DC_VOLTAGE}V DC residential limit"
                    ),
                    field=f"string_config.strings[{i}].voc_string_V",
                    severity=ErrorSeverity.CRITICAL,
                )
            )

    # Total kWp must match panel count × watt peak
    calculated_kwp = sum(
        (face.count * face.panel_watt_peak / 1000.0) for face in data.panels
    )
    if abs(calculated_kwp - data.total_kwp) > 0.1:
        errors.append(
            ValidationError(
                code="KWP_MISMATCH",
                message=(
                    f"Declared total_kwp ({data.total_kwp}) doesn't match "
                    f"calculated ({calculated_kwp:.2f} kWp)"
                ),
                field="total_kwp",
                severity=ErrorSeverity.ERROR,
            )
        )

    # Total panel count consistency
    calculated_panels = sum(face.count for face in data.panels)
    if calculated_panels != data.total_panels:
        errors.append(
            ValidationError(
                code="PANEL_COUNT_MISMATCH",
                message=(
                    f"Declared total_panels ({data.total_panels}) doesn't match "
                    f"sum of face counts ({calculated_panels})"
                ),
                field="total_panels",
                severity=ErrorSeverity.ERROR,
            )
        )


# ============================================================================
# ThermalLoad checks
# ============================================================================


def _check_thermal_load(
    data: ThermalLoad,
    errors: list[ValidationError],
    warnings: list[str],
) -> None:
    # Heat pump COP sanity
    if data.heat_pump_recommendation.cop_estimate is not None:
        if not (1.0 <= data.heat_pump_recommendation.cop_estimate <= 7.0):
            errors.append(
                ValidationError(
                    code="COP_OUT_OF_RANGE",
                    message=(
                        f"COP {data.heat_pump_recommendation.cop_estimate} is outside "
                        "valid range [1.0, 7.0]"
                    ),
                    field="heat_pump_recommendation.cop_estimate",
                    severity=ErrorSeverity.ERROR,
                )
            )

    # DHW cylinder must be a standard size
    if data.dhw_requirement.cylinder_volume_litres not in VALID_CYLINDER_SIZES:
        errors.append(
            ValidationError(
                code="INVALID_CYLINDER_SIZE",
                message=(
                    f"Cylinder size {data.dhw_requirement.cylinder_volume_litres}L is "
                    f"non-standard. Valid: {sorted(VALID_CYLINDER_SIZES)}"
                ),
                field="dhw_requirement.cylinder_volume_litres",
                severity=ErrorSeverity.ERROR,
            )
        )

    # Transmission + ventilation should approximately equal design heat load
    if data.transmission_loss_kw is not None and data.ventilation_loss_kw is not None:
        component_sum = data.transmission_loss_kw + data.ventilation_loss_kw
        # Allow for safety factor
        max_factor = data.heat_pump_recommendation.safety_factor + 0.05
        if data.design_heat_load_kw > component_sum * max_factor:
            warnings.append(
                f"Design heat load ({data.design_heat_load_kw} kW) significantly exceeds "
                f"sum of components ({component_sum:.1f} kW) even with safety factor"
            )


# ============================================================================
# ElectricalAssessment checks
# ============================================================================


def _check_electrical_assessment(
    data: ElectricalAssessment,
    errors: list[ValidationError],
    warnings: list[str],
) -> None:
    # If capacity is insufficient, there must be upgrades
    if not data.current_capacity_sufficient and len(data.upgrades_required) == 0:
        errors.append(
            ValidationError(
                code="MISSING_UPGRADE_DETAILS",
                message="Capacity marked insufficient but no upgrades listed",
                field="upgrades_required",
                severity=ErrorSeverity.ERROR,
            )
        )


# ============================================================================
# BehavioralProfile checks
# ============================================================================


def _check_behavioral_profile(
    data: BehavioralProfile,
    errors: list[ValidationError],
    warnings: list[str],
) -> None:
    # Battery capacity range (already in schema, but double-check)
    if data.battery_recommendation.capacity_kwh < 0.5:
        errors.append(
            ValidationError(
                code="BATTERY_TOO_SMALL",
                message=f"Battery {data.battery_recommendation.capacity_kwh} kWh below 0.5 kWh minimum",
                field="battery_recommendation.capacity_kwh",
                severity=ErrorSeverity.ERROR,
            )
        )
    if data.battery_recommendation.capacity_kwh > 50:
        errors.append(
            ValidationError(
                code="BATTERY_TOO_LARGE",
                message=f"Battery {data.battery_recommendation.capacity_kwh} kWh exceeds 50 kWh residential max",
                field="battery_recommendation.capacity_kwh",
                severity=ErrorSeverity.ERROR,
            )
        )

    # Charge/discharge windows should not overlap
    rec = data.battery_recommendation
    if (
        rec.charge_window_start is not None
        and rec.charge_window_end is not None
        and rec.discharge_window_start is not None
        and rec.discharge_window_end is not None
    ):
        charge_range = set(
            range(rec.charge_window_start, rec.charge_window_end + 1)
            if rec.charge_window_start <= rec.charge_window_end
            else range(rec.charge_window_start, 24) | range(0, rec.charge_window_end + 1)
        )
        discharge_range = set(
            range(rec.discharge_window_start, rec.discharge_window_end + 1)
            if rec.discharge_window_start <= rec.discharge_window_end
            else range(rec.discharge_window_start, 24) | range(0, rec.discharge_window_end + 1)
        )
        overlap = charge_range & discharge_range
        if overlap:
            errors.append(
                ValidationError(
                    code="BATTERY_WINDOW_OVERLAP",
                    message=f"Battery charge and discharge windows overlap at hours: {sorted(overlap)}",
                    field="battery_recommendation",
                    severity=ErrorSeverity.ERROR,
                )
            )


# ============================================================================
# FinalProposal checks — THE MOST CRITICAL GUARDRAIL
# ============================================================================


def _check_final_proposal(
    data: FinalProposal,
    errors: list[ValidationError],
    warnings: list[str],
) -> None:
    # MANDATORY: human_signoff.required must ALWAYS be True
    if not data.human_signoff.required:
        errors.append(
            ValidationError(
                code="HUMAN_SIGNOFF_BYPASSED",
                message=(
                    "CRITICAL: human_signoff.required is False. "
                    "No proposal may bypass human installer review. "
                    "This is a non-negotiable safety requirement."
                ),
                field="human_signoff.required",
                severity=ErrorSeverity.CRITICAL,
            )
        )

    # PV capacity sanity — typical residential max is ~25kWp
    if data.system_design.pv.total_kwp > 25:
        warnings.append(
            f"PV capacity {data.system_design.pv.total_kwp} kWp exceeds typical "
            "residential maximum (25 kWp) — verify with installer"
        )

    # Battery capacity sanity
    if data.system_design.battery.included and data.system_design.battery.capacity_kwh > 30:
        warnings.append(
            f"Battery {data.system_design.battery.capacity_kwh} kWh is unusually large "
            "for residential — verify with installer"
        )

    # Payback period sanity — warn if over 20 years
    if data.financial_summary.payback_years > 20:
        warnings.append(
            f"Payback period of {data.financial_summary.payback_years:.1f} years "
            "exceeds typical equipment warranty — review financial assumptions"
        )


# ============================================================================
# WeatherProfile checks  (Req 9.3)
# ============================================================================


def _check_weather_profile(
    data: WeatherProfile,
    errors: list[ValidationError],
    warnings: list[str],
) -> None:
    """
    Domain-specific guardrail checks for WeatherProfile.

    Validates:
    - Latitude/longitude within Germany bounding box
    - All monthly arrays have exactly 12 elements
    - Annual irradiance within plausible range for Germany (700–1400 kWh/m²/year)
    - quarter_rankings is a permutation of [1, 2, 3, 4]
    - quarter_rankings[0] == optimal_installation_quarter
    """

    # Latitude/longitude within Germany bbox
    # (Pydantic Field constraints already enforce this, but we double-check
    # here so the guardrail layer is self-contained and testable independently)
    if not (GERMANY_LAT_MIN <= data.latitude <= GERMANY_LAT_MAX):
        errors.append(
            ValidationError(
                code="WEATHER_LAT_OUT_OF_RANGE",
                message=(
                    f"Latitude {data.latitude} is outside Germany bounding box "
                    f"[{GERMANY_LAT_MIN}, {GERMANY_LAT_MAX}]"
                ),
                field="latitude",
                severity=ErrorSeverity.ERROR,
            )
        )

    if not (GERMANY_LON_MIN <= data.longitude <= GERMANY_LON_MAX):
        errors.append(
            ValidationError(
                code="WEATHER_LON_OUT_OF_RANGE",
                message=(
                    f"Longitude {data.longitude} is outside Germany bounding box "
                    f"[{GERMANY_LON_MIN}, {GERMANY_LON_MAX}]"
                ),
                field="longitude",
                severity=ErrorSeverity.ERROR,
            )
        )

    # All monthly arrays must have exactly 12 elements
    monthly_fields = {
        "monthly_sunshine_hours": data.monthly_sunshine_hours,
        "monthly_precipitation_mm": data.monthly_precipitation_mm,
        "monthly_cloud_cover_pct": data.monthly_cloud_cover_pct,
        "monthly_wind_speed_ms": data.monthly_wind_speed_ms,
        "monthly_avg_temperature_c": data.monthly_avg_temperature_c,
    }
    for field_name, monthly_list in monthly_fields.items():
        if len(monthly_list) != 12:
            errors.append(
                ValidationError(
                    code="WEATHER_MONTHLY_ARRAY_LENGTH",
                    message=(
                        f"{field_name} has {len(monthly_list)} elements; expected exactly 12"
                    ),
                    field=field_name,
                    severity=ErrorSeverity.ERROR,
                )
            )

    # Annual irradiance within plausible range for Germany
    if not (GERMANY_IRRADIANCE_MIN <= data.annual_irradiance_kwh_m2 <= GERMANY_IRRADIANCE_MAX):
        errors.append(
            ValidationError(
                code="WEATHER_IRRADIANCE_OUT_OF_RANGE",
                message=(
                    f"Annual irradiance {data.annual_irradiance_kwh_m2:.0f} kWh/m²/year "
                    f"is outside plausible Germany range "
                    f"[{GERMANY_IRRADIANCE_MIN:.0f}, {GERMANY_IRRADIANCE_MAX:.0f}]"
                ),
                field="annual_irradiance_kwh_m2",
                severity=ErrorSeverity.ERROR,
            )
        )

    # quarter_rankings must be a permutation of [1, 2, 3, 4]
    if sorted(data.quarter_rankings) != [1, 2, 3, 4]:
        errors.append(
            ValidationError(
                code="WEATHER_QUARTER_RANKINGS_INVALID",
                message=(
                    f"quarter_rankings {data.quarter_rankings} is not a permutation "
                    "of [1, 2, 3, 4]"
                ),
                field="quarter_rankings",
                severity=ErrorSeverity.ERROR,
            )
        )
    elif data.quarter_rankings[0] != data.optimal_installation_quarter:
        # Only check this if rankings are otherwise valid
        errors.append(
            ValidationError(
                code="WEATHER_OPTIMAL_QUARTER_MISMATCH",
                message=(
                    f"quarter_rankings[0]={data.quarter_rankings[0]} does not match "
                    f"optimal_installation_quarter={data.optimal_installation_quarter}"
                ),
                field="optimal_installation_quarter",
                severity=ErrorSeverity.ERROR,
            )
        )
