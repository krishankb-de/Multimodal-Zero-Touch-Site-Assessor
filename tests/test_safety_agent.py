"""
Comprehensive test suite for the Safety / Validation Agent.

Tests cover:
- Schema validation (valid data, missing fields, extra fields, wrong types)
- Domain guardrail checks (voltage limits, area sanity, breaker ratings, etc.)
- Critical safety invariants (human sign-off can never be bypassed)
- Edge cases (empty arrays, boundary values, inconsistent data)
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timezone

import pytest

from src.agents.safety.validator import validate_handoff


# ============================================================================
# Test fixtures — valid baseline payloads
# ============================================================================


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_spatial_data() -> dict:
    return {
        "roof": {
            "typology": "gable",
            "faces": [
                {
                    "id": "south",
                    "orientation_deg": 180,
                    "tilt_deg": 35,
                    "area_m2": 40,
                    "length_m": 8,
                    "width_m": 5,
                }
            ],
            "total_usable_area_m2": 38,
            "obstacles": [
                {"type": "chimney", "face_id": "south", "area_m2": 2, "buffer_m": 0.3}
            ],
        },
        "utility_room": {
            "length_m": 3,
            "width_m": 2.5,
            "height_m": 2.4,
            "available_volume_m3": 12,
            "existing_pipework": True,
            "spatial_constraints": ["Boiler on east wall"],
        },
        "metadata": {
            "source_type": "video",
            "confidence_score": 0.85,
            "timestamp": _now(),
            "gemini_model_version": "gemini-1.5-pro",
        },
    }


def _valid_electrical_data() -> dict:
    return {
        "main_supply": {"amperage_A": 100, "phases": 1, "voltage_V": 230},
        "breakers": [
            {"label": "Lighting", "rating_A": 6, "type": "MCB"},
            {"label": "Ring Main", "rating_A": 32, "type": "RCBO"},
            {"label": "Cooker", "rating_A": 40, "type": "MCB"},
        ],
        "board_condition": "good",
        "spare_ways": 4,
        "metadata": {
            "source_type": "photo",
            "confidence_score": 0.92,
            "timestamp": _now(),
        },
    }


def _valid_consumption_data() -> dict:
    monthly = [{"month": m, "kwh": 350} for m in range(1, 13)]
    return {
        "annual_kwh": 4200,
        "monthly_breakdown": monthly,
        "tariff": {
            "currency": "EUR",
            "rate_per_kwh": 0.32,
            "feed_in_tariff_per_kwh": 0.08,
        },
        "heating_fuel": "gas",
        "annual_heating_kwh": 12000,
        "has_ev": False,
        "metadata": {
            "source_type": "pdf",
            "confidence_score": 0.95,
            "timestamp": _now(),
        },
    }


def _valid_module_layout() -> dict:
    return {
        "panels": [
            {
                "face_id": "south",
                "count": 16,
                "orientation": "portrait",
                "panel_watt_peak": 400,
                "panel_dimensions_mm": {"length": 1722, "width": 1134},
            }
        ],
        "total_kwp": 6.4,
        "total_panels": 16,
        "string_config": {
            "strings": [
                {
                    "string_id": "S1",
                    "panels_in_series": 8,
                    "voc_string_V": 380,
                    "isc_string_A": 11.5,
                },
                {
                    "string_id": "S2",
                    "panels_in_series": 8,
                    "voc_string_V": 380,
                    "isc_string_A": 11.5,
                },
            ]
        },
        "exclusion_zones_applied": ["chimney_buffer"],
        "metadata": {
            "algorithm_version": "1.0.0",
            "timestamp": _now(),
        },
    }


def _valid_thermal_load() -> dict:
    return {
        "design_heat_load_kw": 8.5,
        "transmission_loss_kw": 5.5,
        "ventilation_loss_kw": 2.0,
        "design_outdoor_temp_c": -12,
        "design_indoor_temp_c": 20,
        "u_values_used": {
            "walls_w_m2k": 0.28,
            "roof_w_m2k": 0.16,
            "floor_w_m2k": 0.22,
            "windows_w_m2k": 1.3,
        },
        "heat_pump_recommendation": {
            "capacity_kw": 10,
            "type": "air_source",
            "cop_estimate": 3.5,
            "safety_factor": 1.15,
        },
        "dhw_requirement": {
            "daily_litres": 150,
            "cylinder_volume_litres": 200,
            "fits_in_utility_room": True,
        },
        "metadata": {
            "calculation_method": "DIN_EN_12831_simplified",
            "timestamp": _now(),
        },
    }


def _valid_electrical_assessment() -> dict:
    return {
        "current_capacity_sufficient": True,
        "max_additional_load_A": 40,
        "upgrades_required": [],
        "inverter_recommendation": {"type": "hybrid", "max_ac_output_kw": 6.0},
        "ev_charger_compatible": True,
        "metadata": {"timestamp": _now()},
    }


def _valid_behavioral_profile() -> dict:
    return {
        "occupancy_pattern": "away_daytime",
        "self_consumption_ratio": 0.35,
        "battery_recommendation": {
            "capacity_kwh": 10,
            "rationale": "Away during peak solar hours — store for evening use",
            "charge_window_start": 9,
            "charge_window_end": 16,
            "discharge_window_start": 17,
            "discharge_window_end": 23,
            "arbitrage_savings_eur_annual": 280,
        },
        "optimization_schedule": {
            "frequency": "quarterly",
            "next_review": date.today().isoformat(),
            "hems_integration": False,
        },
        "estimated_annual_savings_eur": 780,
        "metadata": {"timestamp": _now()},
    }


def _valid_final_proposal() -> dict:
    return {
        "system_design": {
            "pv": {
                "total_kwp": 6.4,
                "panel_count": 16,
                "panel_model": "JA Solar JAM54S30-400",
                "inverter_type": "hybrid",
                "inverter_model": "SolarEdge SE6000H",
                "annual_yield_kwh": 6100,
            },
            "battery": {
                "included": True,
                "capacity_kwh": 10,
                "model": "BYD HVS 10.2",
            },
            "heat_pump": {
                "included": True,
                "capacity_kw": 10,
                "type": "air_source",
                "model": "Vaillant aroTHERM plus",
                "cop": 3.5,
                "cylinder_litres": 200,
            },
            "ev_charger": {"included": False},
        },
        "financial_summary": {
            "total_cost_eur": 28500,
            "annual_savings_eur": 2100,
            "payback_years": 13.6,
            "roi_percent": 7.4,
        },
        "compliance": {
            "electrical_upgrades": [],
            "regulatory_notes": ["MCS certification required for RHI"],
            "single_line_diagram_ref": "sld_2024_001.pdf",
        },
        "human_signoff": {
            "required": True,
            "status": "pending",
        },
        "metadata": {
            "version": "1.0.0",
            "generated_at": _now(),
            "pipeline_run_id": "run_abc123",
            "all_validations_passed": True,
        },
    }


# ============================================================================
# Tests: Valid data passes validation
# ============================================================================


class TestValidData:
    """All valid baseline payloads should pass validation."""

    def test_spatial_data_valid(self):
        instance, result = validate_handoff(
            _valid_spatial_data(), "SpatialData", "ingestion"
        )
        assert result.valid is True
        assert instance is not None
        assert len(result.errors) == 0

    def test_electrical_data_valid(self):
        instance, result = validate_handoff(
            _valid_electrical_data(), "ElectricalData", "ingestion"
        )
        assert result.valid is True
        assert instance is not None

    def test_consumption_data_valid(self):
        instance, result = validate_handoff(
            _valid_consumption_data(), "ConsumptionData", "ingestion"
        )
        assert result.valid is True
        assert instance is not None

    def test_module_layout_valid(self):
        instance, result = validate_handoff(
            _valid_module_layout(), "ModuleLayout", "structural"
        )
        assert result.valid is True
        assert instance is not None

    def test_thermal_load_valid(self):
        instance, result = validate_handoff(
            _valid_thermal_load(), "ThermalLoad", "thermodynamic"
        )
        assert result.valid is True
        assert instance is not None

    def test_electrical_assessment_valid(self):
        instance, result = validate_handoff(
            _valid_electrical_assessment(), "ElectricalAssessment", "electrical"
        )
        assert result.valid is True
        assert instance is not None

    def test_behavioral_profile_valid(self):
        instance, result = validate_handoff(
            _valid_behavioral_profile(), "BehavioralProfile", "behavioral"
        )
        assert result.valid is True
        assert instance is not None

    def test_final_proposal_valid(self):
        instance, result = validate_handoff(
            _valid_final_proposal(), "FinalProposal", "synthesis"
        )
        assert result.valid is True
        assert instance is not None


# ============================================================================
# Tests: Schema validation catches bad data
# ============================================================================


class TestSchemaValidation:
    """Schema-level validation must reject structurally invalid data."""

    def test_missing_required_field(self):
        data = _valid_spatial_data()
        del data["roof"]
        _, result = validate_handoff(data, "SpatialData", "ingestion")
        assert result.valid is False
        assert any(e.code == "SCHEMA_VALIDATION_FAILED" for e in result.errors)

    def test_extra_field_rejected(self):
        data = _valid_spatial_data()
        data["unexpected_field"] = "should fail"
        _, result = validate_handoff(data, "SpatialData", "ingestion")
        assert result.valid is False

    def test_wrong_type(self):
        data = _valid_spatial_data()
        data["roof"]["typology"] = 12345  # Should be string enum
        _, result = validate_handoff(data, "SpatialData", "ingestion")
        assert result.valid is False

    def test_invalid_enum_value(self):
        data = _valid_spatial_data()
        data["roof"]["typology"] = "pyramid"  # Not in enum
        _, result = validate_handoff(data, "SpatialData", "ingestion")
        assert result.valid is False

    def test_unknown_schema_name(self):
        _, result = validate_handoff({}, "NonexistentSchema", "test")
        assert result.valid is False
        assert any(e.code == "UNKNOWN_SCHEMA" for e in result.errors)

    def test_value_below_minimum(self):
        data = _valid_spatial_data()
        data["roof"]["faces"][0]["area_m2"] = 0  # Minimum is 1
        _, result = validate_handoff(data, "SpatialData", "ingestion")
        assert result.valid is False

    def test_empty_faces_array(self):
        data = _valid_spatial_data()
        data["roof"]["faces"] = []  # min_length=1
        _, result = validate_handoff(data, "SpatialData", "ingestion")
        assert result.valid is False


# ============================================================================
# Tests: Domain guardrails
# ============================================================================


class TestGuardrails:
    """Domain-specific guardrail checks must catch semantically invalid data."""

    # --- Voltage limits ---

    def test_dc_voltage_exceeds_1000v(self):
        """Voltage >1000V is caught at schema level (Pydantic le=1000) as a first
        line of defense. The guardrail provides a second layer for edge cases."""
        data = _valid_module_layout()
        data["string_config"]["strings"][0]["voc_string_V"] = 1050  # DANGER
        _, result = validate_handoff(data, "ModuleLayout", "structural")
        assert result.valid is False
        # Caught by Pydantic schema constraint (le=1000) before guardrails run
        assert any(
            e.code in ("SCHEMA_VALIDATION_FAILED", "VOLTAGE_EXCEEDED")
            for e in result.errors
        )

    def test_dc_voltage_at_limit(self):
        data = _valid_module_layout()
        data["string_config"]["strings"][0]["voc_string_V"] = 1000  # Exactly at limit
        instance, result = validate_handoff(data, "ModuleLayout", "structural")
        # Should pass — 1000V is the limit, not exceeded
        voltage_errors = [e for e in result.errors if e.code == "VOLTAGE_EXCEEDED"]
        assert len(voltage_errors) == 0

    # --- Breaker ratings ---

    def test_non_standard_breaker_rating(self):
        data = _valid_electrical_data()
        data["breakers"][0]["rating_A"] = 15  # Not a standard rating
        _, result = validate_handoff(data, "ElectricalData", "ingestion")
        assert result.valid is False
        assert any(e.code == "INVALID_BREAKER_RATING" for e in result.errors)

    # --- Phase/voltage consistency ---

    def test_single_phase_wrong_voltage(self):
        data = _valid_electrical_data()
        data["main_supply"]["phases"] = 1
        data["main_supply"]["voltage_V"] = 400  # Wrong for single-phase
        _, result = validate_handoff(data, "ElectricalData", "ingestion")
        assert result.valid is False
        assert any(e.code == "VOLTAGE_PHASE_MISMATCH" for e in result.errors)

    def test_three_phase_wrong_voltage(self):
        data = _valid_electrical_data()
        data["main_supply"]["phases"] = 3
        data["main_supply"]["voltage_V"] = 230  # Wrong for three-phase
        _, result = validate_handoff(data, "ElectricalData", "ingestion")
        assert result.valid is False

    # --- Area consistency ---

    def test_usable_area_exceeds_face_sum(self):
        data = _valid_spatial_data()
        data["roof"]["total_usable_area_m2"] = 100  # Face sum is only 40
        _, result = validate_handoff(data, "SpatialData", "ingestion")
        assert result.valid is False
        assert any(e.code == "AREA_INCONSISTENCY" for e in result.errors)

    # --- Obstacle face_id references ---

    def test_obstacle_references_unknown_face(self):
        data = _valid_spatial_data()
        data["roof"]["obstacles"][0]["face_id"] = "nonexistent_face"
        _, result = validate_handoff(data, "SpatialData", "ingestion")
        assert result.valid is False
        assert any(e.code == "INVALID_FACE_REF" for e in result.errors)

    # --- Volume consistency ---

    def test_available_volume_exceeds_room(self):
        data = _valid_spatial_data()
        data["utility_room"]["available_volume_m3"] = 100  # Room is only ~18m³
        _, result = validate_handoff(data, "SpatialData", "ingestion")
        assert result.valid is False
        assert any(e.code == "VOLUME_INCONSISTENCY" for e in result.errors)

    # --- Consumption mismatch ---

    def test_monthly_sum_differs_from_annual(self):
        data = _valid_consumption_data()
        data["monthly_breakdown"][0]["kwh"] = 5000  # Throws off the sum
        _, result = validate_handoff(data, "ConsumptionData", "ingestion")
        assert result.valid is False
        assert any(e.code == "CONSUMPTION_MISMATCH" for e in result.errors)

    # --- kWp mismatch ---

    def test_kwp_doesnt_match_panels(self):
        data = _valid_module_layout()
        data["total_kwp"] = 99.0  # Actual is 6.4
        _, result = validate_handoff(data, "ModuleLayout", "structural")
        assert result.valid is False
        assert any(e.code == "KWP_MISMATCH" for e in result.errors)

    # --- Panel count mismatch ---

    def test_panel_count_mismatch(self):
        data = _valid_module_layout()
        data["total_panels"] = 999
        _, result = validate_handoff(data, "ModuleLayout", "structural")
        assert result.valid is False
        assert any(e.code == "PANEL_COUNT_MISMATCH" for e in result.errors)

    # --- Cylinder size ---

    def test_invalid_cylinder_size(self):
        data = _valid_thermal_load()
        data["dhw_requirement"]["cylinder_volume_litres"] = 175  # Not standard
        _, result = validate_handoff(data, "ThermalLoad", "thermodynamic")
        assert result.valid is False
        assert any(e.code == "INVALID_CYLINDER_SIZE" for e in result.errors)

    # --- Missing upgrade details ---

    def test_insufficient_capacity_no_upgrades(self):
        data = _valid_electrical_assessment()
        data["current_capacity_sufficient"] = False
        data["upgrades_required"] = []  # Inconsistent
        _, result = validate_handoff(data, "ElectricalAssessment", "electrical")
        assert result.valid is False
        assert any(e.code == "MISSING_UPGRADE_DETAILS" for e in result.errors)


# ============================================================================
# Tests: CRITICAL — Human sign-off can NEVER be bypassed
# ============================================================================


class TestHumanSignoff:
    """The most important guardrail: human sign-off is mandatory."""

    def test_signoff_bypass_rejected(self):
        data = _valid_final_proposal()
        data["human_signoff"]["required"] = False  # NEVER allowed
        _, result = validate_handoff(data, "FinalProposal", "synthesis")
        assert result.valid is False
        assert any(e.code == "HUMAN_SIGNOFF_BYPASSED" for e in result.errors)
        assert any(e.severity == "critical" for e in result.errors)

    def test_signoff_required_true_passes(self):
        data = _valid_final_proposal()
        data["human_signoff"]["required"] = True
        instance, result = validate_handoff(data, "FinalProposal", "synthesis")
        assert result.valid is True
        assert instance is not None


# ============================================================================
# Tests: Low-confidence warnings
# ============================================================================


class TestConfidenceWarnings:
    """Low Gemini confidence scores should produce warnings."""

    def test_low_confidence_spatial(self):
        data = _valid_spatial_data()
        data["metadata"]["confidence_score"] = 0.4
        instance, result = validate_handoff(data, "SpatialData", "ingestion")
        assert result.valid is True  # Warning, not error
        assert len(result.warnings) > 0
        assert any("confidence" in w.lower() for w in result.warnings)

    def test_low_confidence_electrical(self):
        data = _valid_electrical_data()
        data["metadata"]["confidence_score"] = 0.5
        _, result = validate_handoff(data, "ElectricalData", "ingestion")
        assert result.valid is True
        assert len(result.warnings) > 0


# ============================================================================
# Tests: Edge cases
# ============================================================================


class TestEdgeCases:
    """Edge cases and boundary values."""

    def test_orientation_at_boundaries(self):
        data = _valid_spatial_data()
        data["roof"]["faces"][0]["orientation_deg"] = 0  # North
        instance, result = validate_handoff(data, "SpatialData", "ingestion")
        assert result.valid is True

        data["roof"]["faces"][0]["orientation_deg"] = 360  # Also valid
        instance, result = validate_handoff(data, "SpatialData", "ingestion")
        assert result.valid is True

    def test_minimum_annual_kwh(self):
        data = _valid_consumption_data()
        data["annual_kwh"] = 500
        monthly_kwh = 500 / 12
        data["monthly_breakdown"] = [
            {"month": m, "kwh": round(monthly_kwh, 1)} for m in range(1, 13)
        ]
        instance, result = validate_handoff(data, "ConsumptionData", "ingestion")
        assert result.valid is True

    def test_completely_empty_payload(self):
        _, result = validate_handoff({}, "SpatialData", "ingestion")
        assert result.valid is False

    def test_validation_result_has_timestamp(self):
        _, result = validate_handoff(_valid_spatial_data(), "SpatialData", "ingestion")
        assert result.timestamp is not None
        assert result.agent_source == "ingestion"
        assert result.schema_name == "SpatialData"
