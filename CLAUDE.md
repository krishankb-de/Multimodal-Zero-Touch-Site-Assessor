# CLAUDE.md — Multimodal Zero-Touch Site Assessor

## Project Overview

An agentic, multimodal system that transforms homeowner-provided media (roofline video, electrical panel photo, utility bill PDF) into an engineering-grade solar + heat pump proposal — without a physical site visit.

## Mandatory Setup (ALWAYS DO FIRST)

```bash
# 1. Activate the project virtual environment — EVERY session
source .venv/bin/activate

# 2. Install/update dependencies
pip install -e ".[dev]"

# 3. Run safety tests to verify environment
python -m pytest tests/test_safety_agent.py -v
```

> **RULE**: All `pip install`, `pip uninstall`, `pytest`, and `python` commands
> MUST be run inside the activated `.venv`. Never use the system Python.

## Datasets

The `Datasets/` directory contains training and reference data:

```
Datasets/
├── Project Data/
│   ├── 23c108b7/              # Small sample (~335 KB)
│   │   ├── projects_status_quo.csv    # Customer baseline: energy_demand, tariffs, heating, EV, solar
│   │   └── project_options_parts.csv  # Expert designs: components, brands, capacities
│   └── 2a8ba8e2/              # Large sample (~2.3 MB)
│       ├── projects_status_quo.csv
│       └── project_options_parts.csv
└── Exp 3D-Modells/
    ├── 3D_Modell Brandenburg.glb
    ├── 3D_Modell Hamburg.glb
    ├── 3D_Modell North Germany.glb
    └── 3D_Modell Ruhr.glb
```

**Key CSV columns** (Reonic format):
- `projects_status_quo.csv`: `project_id`, `energy_demand_wh`, `energy_price_per_wh`, `has_ev`, `has_solar`, `solar_size_kwp`, `heating_existing_type`, `house_size_sqm`
- `project_options_parts.csv`: `project_id`, `option_id`, `technology`, `component_type`, `component_name`, `component_brand`, `module_watt_peak`, `inverter_power_kw`, `battery_capacity_kwh`, `heatpump_nominal_power_kw`

## Architecture

8 independent sub-agents communicate **exclusively** via validated JSON matching the schemas below. The Safety/Validation Agent intercepts **every** handoff.

```
Ingestion → [Structural ‖ Electrical ‖ Thermodynamic ‖ Behavioral] → Design Synthesis → Human Handoff
                        ↑ Safety Agent validates every transition ↑
```

## Technology Stack

- **Backend**: Python 3.12+, FastAPI, Pydantic v2
- **Frontend**: Next.js 14 (React), TypeScript
- **AI/ML**: Google Gemini 1.5 Pro (multimodal), Pioneer SLM (design synthesis)
- **Validation**: JSON Schema Draft 2020-12, Pydantic strict mode
- **Testing**: pytest, mypy --strict

## Coding Conventions

- All agent outputs MUST be validated against the schemas below before handoff
- Use Pydantic `model_validate()` with `strict=True` for all deserialization
- Every agent function must return a `Result[T, ValidationError]` type
- No agent may directly call another agent — all routing goes through the Orchestrator
- Log every handoff payload at DEBUG level for audit trail

---

# INTER-AGENT HANDOFF SCHEMAS

> **RULE**: The output of every agent MUST be a valid JSON object matching the
> corresponding schema below. Any deviation is a hard failure — the Safety Agent
> will reject the payload and the Orchestrator will retry or halt.

---

## 1. SpatialData (Ingestion Agent → Structural Agent, Thermodynamic Agent)

The Ingestion Agent produces this from roofline video analysis via Gemini 1.5 Pro.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "SpatialData",
  "type": "object",
  "required": ["roof", "utility_room", "metadata"],
  "additionalProperties": false,
  "properties": {
    "roof": {
      "type": "object",
      "required": ["typology", "faces", "total_usable_area_m2", "obstacles"],
      "properties": {
        "typology": {
          "type": "string",
          "enum": ["gable", "hip", "flat", "mansard", "gambrel", "shed", "combination"]
        },
        "faces": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "required": ["id", "orientation_deg", "tilt_deg", "area_m2"],
            "properties": {
              "id": { "type": "string" },
              "orientation_deg": { "type": "number", "minimum": 0, "maximum": 360, "description": "Azimuth: 0=N, 90=E, 180=S, 270=W" },
              "tilt_deg": { "type": "number", "minimum": 0, "maximum": 90 },
              "area_m2": { "type": "number", "minimum": 1 },
              "length_m": { "type": "number", "minimum": 0.5 },
              "width_m": { "type": "number", "minimum": 0.5 }
            }
          }
        },
        "total_usable_area_m2": { "type": "number", "minimum": 1 },
        "obstacles": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["type", "face_id", "area_m2"],
            "properties": {
              "type": { "type": "string", "enum": ["dormer", "vent_pipe", "chimney", "skylight", "antenna", "foliage_shadow", "other"] },
              "face_id": { "type": "string" },
              "area_m2": { "type": "number", "minimum": 0 },
              "buffer_m": { "type": "number", "minimum": 0, "default": 0.3, "description": "Safety buffer around obstacle" }
            }
          }
        }
      }
    },
    "utility_room": {
      "type": "object",
      "required": ["length_m", "width_m", "height_m", "available_volume_m3"],
      "properties": {
        "length_m": { "type": "number", "minimum": 0.5 },
        "width_m": { "type": "number", "minimum": 0.5 },
        "height_m": { "type": "number", "minimum": 1.5 },
        "available_volume_m3": { "type": "number", "minimum": 0 },
        "existing_pipework": { "type": "boolean" },
        "spatial_constraints": {
          "type": "array",
          "items": { "type": "string" }
        }
      }
    },
    "metadata": {
      "type": "object",
      "required": ["source_type", "confidence_score", "timestamp"],
      "properties": {
        "source_type": { "type": "string", "enum": ["video", "image", "manual"] },
        "confidence_score": { "type": "number", "minimum": 0, "maximum": 1 },
        "timestamp": { "type": "string", "format": "date-time" },
        "gemini_model_version": { "type": "string" }
      }
    }
  }
}
```

---

## 2. ElectricalData (Ingestion Agent → Electrical Agent)

Produced from electrical panel photo analysis.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ElectricalData",
  "type": "object",
  "required": ["main_supply", "breakers", "metadata"],
  "additionalProperties": false,
  "properties": {
    "main_supply": {
      "type": "object",
      "required": ["amperage_A", "phases", "voltage_V"],
      "properties": {
        "amperage_A": { "type": "integer", "minimum": 16, "maximum": 200 },
        "phases": { "type": "integer", "enum": [1, 3] },
        "voltage_V": { "type": "integer", "enum": [230, 400] }
      }
    },
    "breakers": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["label", "rating_A", "type"],
        "properties": {
          "label": { "type": "string" },
          "rating_A": { "type": "integer", "enum": [6, 10, 13, 16, 20, 25, 32, 40, 50, 63, 80, 100, 125] },
          "type": { "type": "string", "enum": ["MCB", "RCBO", "RCD", "MCCB", "isolator", "unknown"] },
          "circuit_description": { "type": "string" }
        }
      }
    },
    "board_condition": {
      "type": "string",
      "enum": ["good", "fair", "poor", "requires_replacement"]
    },
    "spare_ways": { "type": "integer", "minimum": 0 },
    "metadata": {
      "type": "object",
      "required": ["source_type", "confidence_score", "timestamp"],
      "properties": {
        "source_type": { "type": "string", "enum": ["photo", "manual"] },
        "confidence_score": { "type": "number", "minimum": 0, "maximum": 1 },
        "timestamp": { "type": "string", "format": "date-time" }
      }
    }
  }
}
```

---

## 3. ConsumptionData (Ingestion Agent → Thermodynamic Agent, Behavioral Agent)

Produced from utility bill PDF parsing.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ConsumptionData",
  "type": "object",
  "required": ["annual_kwh", "monthly_breakdown", "tariff", "metadata"],
  "additionalProperties": false,
  "properties": {
    "annual_kwh": { "type": "number", "minimum": 500, "maximum": 100000 },
    "monthly_breakdown": {
      "type": "array",
      "minItems": 12,
      "maxItems": 12,
      "items": {
        "type": "object",
        "required": ["month", "kwh"],
        "properties": {
          "month": { "type": "integer", "minimum": 1, "maximum": 12 },
          "kwh": { "type": "number", "minimum": 0 }
        }
      }
    },
    "tariff": {
      "type": "object",
      "required": ["currency", "rate_per_kwh"],
      "properties": {
        "currency": { "type": "string", "enum": ["EUR", "GBP", "USD", "CHF"] },
        "rate_per_kwh": { "type": "number", "minimum": 0 },
        "feed_in_tariff_per_kwh": { "type": "number", "minimum": 0 },
        "time_of_use": {
          "type": "object",
          "properties": {
            "peak_rate": { "type": "number" },
            "off_peak_rate": { "type": "number" },
            "peak_hours_start": { "type": "integer", "minimum": 0, "maximum": 23 },
            "peak_hours_end": { "type": "integer", "minimum": 0, "maximum": 23 }
          }
        }
      }
    },
    "heating_fuel": {
      "type": "string",
      "enum": ["gas", "oil", "electric", "lpg", "district", "none"]
    },
    "annual_heating_kwh": { "type": "number", "minimum": 0 },
    "has_ev": { "type": "boolean" },
    "metadata": {
      "type": "object",
      "required": ["source_type", "confidence_score", "timestamp"],
      "properties": {
        "source_type": { "type": "string", "enum": ["pdf", "manual"] },
        "confidence_score": { "type": "number", "minimum": 0, "maximum": 1 },
        "timestamp": { "type": "string", "format": "date-time" },
        "bill_period_start": { "type": "string", "format": "date" },
        "bill_period_end": { "type": "string", "format": "date" }
      }
    }
  }
}
```

---

## 4. ModuleLayout (Structural Agent → Design Synthesis Agent)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ModuleLayout",
  "type": "object",
  "required": ["panels", "total_kwp", "total_panels", "string_config", "metadata"],
  "additionalProperties": false,
  "properties": {
    "panels": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["face_id", "count", "orientation", "panel_watt_peak"],
        "properties": {
          "face_id": { "type": "string" },
          "count": { "type": "integer", "minimum": 0 },
          "orientation": { "type": "string", "enum": ["portrait", "landscape"] },
          "panel_watt_peak": { "type": "integer", "minimum": 250, "maximum": 700 },
          "panel_dimensions_mm": {
            "type": "object",
            "properties": {
              "length": { "type": "integer" },
              "width": { "type": "integer" }
            }
          }
        }
      }
    },
    "total_kwp": { "type": "number", "minimum": 0, "maximum": 100 },
    "total_panels": { "type": "integer", "minimum": 0 },
    "string_config": {
      "type": "object",
      "required": ["strings"],
      "properties": {
        "strings": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "string_id": { "type": "string" },
              "panels_in_series": { "type": "integer" },
              "voc_string_V": { "type": "number", "maximum": 1000, "description": "Must not exceed 1000V DC" },
              "isc_string_A": { "type": "number" }
            }
          }
        }
      }
    },
    "exclusion_zones_applied": {
      "type": "array",
      "items": { "type": "string" }
    },
    "metadata": {
      "type": "object",
      "required": ["algorithm_version", "timestamp"],
      "properties": {
        "algorithm_version": { "type": "string" },
        "timestamp": { "type": "string", "format": "date-time" }
      }
    }
  }
}
```

---

## 5. ThermalLoad (Thermodynamic Agent → Design Synthesis Agent)

DIN EN 12831 simplified calculation output.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ThermalLoad",
  "type": "object",
  "required": ["design_heat_load_kw", "heat_pump_recommendation", "dhw_requirement", "metadata"],
  "additionalProperties": false,
  "properties": {
    "design_heat_load_kw": { "type": "number", "minimum": 1, "maximum": 100, "description": "Φ_HL per DIN EN 12831" },
    "transmission_loss_kw": { "type": "number", "minimum": 0 },
    "ventilation_loss_kw": { "type": "number", "minimum": 0 },
    "design_outdoor_temp_c": { "type": "number", "minimum": -30, "maximum": 10 },
    "design_indoor_temp_c": { "type": "number", "minimum": 18, "maximum": 24, "default": 20 },
    "u_values_used": {
      "type": "object",
      "properties": {
        "walls_w_m2k": { "type": "number" },
        "roof_w_m2k": { "type": "number" },
        "floor_w_m2k": { "type": "number" },
        "windows_w_m2k": { "type": "number" }
      }
    },
    "heat_pump_recommendation": {
      "type": "object",
      "required": ["capacity_kw", "type"],
      "properties": {
        "capacity_kw": { "type": "number", "minimum": 2, "maximum": 50 },
        "type": { "type": "string", "enum": ["air_source", "ground_source", "water_source"] },
        "cop_estimate": { "type": "number", "minimum": 1, "maximum": 7 },
        "safety_factor": { "type": "number", "minimum": 1.0, "maximum": 1.5, "default": 1.15 }
      }
    },
    "dhw_requirement": {
      "type": "object",
      "required": ["daily_litres", "cylinder_volume_litres"],
      "properties": {
        "daily_litres": { "type": "number", "minimum": 50 },
        "cylinder_volume_litres": { "type": "integer", "enum": [150, 170, 200, 210, 250, 300] },
        "fits_in_utility_room": { "type": "boolean" }
      }
    },
    "metadata": {
      "type": "object",
      "required": ["calculation_method", "timestamp"],
      "properties": {
        "calculation_method": { "type": "string", "const": "DIN_EN_12831_simplified" },
        "timestamp": { "type": "string", "format": "date-time" }
      }
    }
  }
}
```

---

## 6. ElectricalAssessment (Electrical Agent → Design Synthesis Agent)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ElectricalAssessment",
  "type": "object",
  "required": ["current_capacity_sufficient", "upgrades_required", "inverter_recommendation", "metadata"],
  "additionalProperties": false,
  "properties": {
    "current_capacity_sufficient": { "type": "boolean" },
    "max_additional_load_A": { "type": "number", "minimum": 0 },
    "upgrades_required": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["type", "reason", "estimated_cost_eur"],
        "properties": {
          "type": { "type": "string", "enum": ["board_upgrade", "meter_upgrade", "three_phase_conversion", "earthing_upgrade", "rcd_addition", "ev_circuit"] },
          "reason": { "type": "string" },
          "estimated_cost_eur": { "type": "number", "minimum": 0 }
        }
      }
    },
    "inverter_recommendation": {
      "type": "object",
      "required": ["type", "max_ac_output_kw"],
      "properties": {
        "type": { "type": "string", "enum": ["single_phase", "three_phase", "micro_inverter", "hybrid"] },
        "max_ac_output_kw": { "type": "number", "minimum": 0 }
      }
    },
    "ev_charger_compatible": { "type": "boolean" },
    "metadata": {
      "type": "object",
      "required": ["timestamp"],
      "properties": {
        "timestamp": { "type": "string", "format": "date-time" }
      }
    }
  }
}
```

---

## 7. BehavioralProfile (Behavioral Agent → Design Synthesis Agent)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "BehavioralProfile",
  "type": "object",
  "required": ["occupancy_pattern", "battery_recommendation", "optimization_schedule", "metadata"],
  "additionalProperties": false,
  "properties": {
    "occupancy_pattern": {
      "type": "string",
      "enum": ["home_all_day", "away_daytime", "shift_worker", "mixed", "unknown"]
    },
    "self_consumption_ratio": { "type": "number", "minimum": 0, "maximum": 1 },
    "battery_recommendation": {
      "type": "object",
      "required": ["capacity_kwh", "rationale"],
      "properties": {
        "capacity_kwh": { "type": "number", "minimum": 0.5, "maximum": 50 },
        "rationale": { "type": "string" },
        "charge_window_start": { "type": "integer", "minimum": 0, "maximum": 23 },
        "charge_window_end": { "type": "integer", "minimum": 0, "maximum": 23 },
        "discharge_window_start": { "type": "integer", "minimum": 0, "maximum": 23 },
        "discharge_window_end": { "type": "integer", "minimum": 0, "maximum": 23 },
        "arbitrage_savings_eur_annual": { "type": "number", "minimum": 0 }
      }
    },
    "optimization_schedule": {
      "type": "object",
      "required": ["frequency", "next_review"],
      "properties": {
        "frequency": { "type": "string", "enum": ["monthly", "quarterly", "biannual"] },
        "next_review": { "type": "string", "format": "date" },
        "hems_integration": { "type": "boolean" }
      }
    },
    "estimated_annual_savings_eur": { "type": "number", "minimum": 0, "maximum": 5000 },
    "metadata": {
      "type": "object",
      "required": ["timestamp"],
      "properties": {
        "timestamp": { "type": "string", "format": "date-time" }
      }
    }
  }
}
```

---

## 8. FinalProposal (Design Synthesis Agent → Human Handoff)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "FinalProposal",
  "type": "object",
  "required": ["system_design", "financial_summary", "compliance", "human_signoff", "metadata"],
  "additionalProperties": false,
  "properties": {
    "system_design": {
      "type": "object",
      "required": ["pv", "battery", "heat_pump"],
      "properties": {
        "pv": {
          "type": "object",
          "required": ["total_kwp", "panel_count", "inverter_type"],
          "properties": {
            "total_kwp": { "type": "number" },
            "panel_count": { "type": "integer" },
            "panel_model": { "type": "string" },
            "inverter_type": { "type": "string" },
            "inverter_model": { "type": "string" },
            "annual_yield_kwh": { "type": "number" }
          }
        },
        "battery": {
          "type": "object",
          "required": ["capacity_kwh", "included"],
          "properties": {
            "included": { "type": "boolean" },
            "capacity_kwh": { "type": "number" },
            "model": { "type": "string" }
          }
        },
        "heat_pump": {
          "type": "object",
          "required": ["capacity_kw", "type", "included"],
          "properties": {
            "included": { "type": "boolean" },
            "capacity_kw": { "type": "number" },
            "type": { "type": "string" },
            "model": { "type": "string" },
            "cop": { "type": "number" },
            "cylinder_litres": { "type": "integer" }
          }
        },
        "ev_charger": {
          "type": "object",
          "properties": {
            "included": { "type": "boolean" },
            "capacity_kw": { "type": "number" }
          }
        }
      }
    },
    "financial_summary": {
      "type": "object",
      "required": ["total_cost_eur", "annual_savings_eur", "payback_years"],
      "properties": {
        "total_cost_eur": { "type": "number", "minimum": 0 },
        "annual_savings_eur": { "type": "number" },
        "payback_years": { "type": "number", "minimum": 0 },
        "roi_percent": { "type": "number" }
      }
    },
    "compliance": {
      "type": "object",
      "required": ["electrical_upgrades", "regulatory_notes"],
      "properties": {
        "electrical_upgrades": { "type": "array", "items": { "type": "string" } },
        "regulatory_notes": { "type": "array", "items": { "type": "string" } },
        "single_line_diagram_ref": { "type": "string", "description": "Reference to generated SLD document" }
      }
    },
    "human_signoff": {
      "type": "object",
      "required": ["required", "status"],
      "properties": {
        "required": { "type": "boolean", "const": true, "description": "MUST always be true — no proposal bypasses human review" },
        "status": { "type": "string", "enum": ["pending", "approved", "rejected", "revision_requested"] },
        "installer_id": { "type": "string" },
        "signed_at": { "type": "string", "format": "date-time" },
        "notes": { "type": "string" }
      }
    },
    "metadata": {
      "type": "object",
      "required": ["version", "generated_at", "pipeline_run_id"],
      "properties": {
        "version": { "type": "string" },
        "generated_at": { "type": "string", "format": "date-time" },
        "pipeline_run_id": { "type": "string" },
        "all_validations_passed": { "type": "boolean" }
      }
    }
  }
}
```

---

## 9. ValidationResult (Safety Agent output)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ValidationResult",
  "type": "object",
  "required": ["valid", "agent_source", "schema_name", "errors", "warnings", "timestamp"],
  "additionalProperties": false,
  "properties": {
    "valid": { "type": "boolean" },
    "agent_source": { "type": "string" },
    "schema_name": { "type": "string" },
    "errors": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["code", "message", "field"],
        "properties": {
          "code": { "type": "string", "description": "E.g. VOLTAGE_EXCEEDED, MISSING_FIELD, RANGE_VIOLATION" },
          "message": { "type": "string" },
          "field": { "type": "string" },
          "severity": { "type": "string", "enum": ["critical", "error", "warning"] }
        }
      }
    },
    "warnings": {
      "type": "array",
      "items": { "type": "string" }
    },
    "timestamp": { "type": "string", "format": "date-time" }
  }
}
```

---

## Safety Guardrails (MANDATORY)

These rules are **non-negotiable**. The Safety Agent enforces them on every handoff:

| Rule | Check | Failure Action |
|------|-------|----------------|
| DC Voltage Limit | `voc_string_V ≤ 1000` | HALT pipeline |
| AC Voltage Limit | system AC ≤ 400V | HALT pipeline |
| Roof Area Sanity | `total_kwp / total_usable_area_m2 ≤ 0.22` (kWp/m²) | REJECT layout |
| Heat Pump Range | `2 ≤ capacity_kw ≤ 50` | REJECT thermal calc |
| Battery Range | `0.5 ≤ capacity_kwh ≤ 50` | REJECT sizing |
| Human Sign-off | `human_signoff.required === true` | HALT — cannot be overridden |
| Confidence Floor | `confidence_score ≥ 0.6` for Gemini outputs | FLAG for manual review |
| Schema Compliance | Every payload passes JSON Schema validation | REJECT payload |
| Breaker Ratings | Only standard values (6–125A) | REJECT electrical data |
| COP Sanity | `1.0 ≤ cop ≤ 7.0` | REJECT thermal recommendation |

---

## Agent File Structure

```
src/
├── agents/
│   ├── ingestion/
│   │   ├── agent.py          # Gemini 1.5 Pro integration
│   │   ├── media_handler.py  # Upload & format validation
│   │   └── prompts/          # Structured prompts per media type
│   ├── structural/
│   │   ├── agent.py          # Module layout orchestration
│   │   └── layout_engine.py  # Bin-packing algorithm
│   ├── thermodynamic/
│   │   ├── agent.py          # Heat load orchestration
│   │   └── din_en_12831.py   # DIN EN 12831 simplified calc
│   ├── electrical/
│   │   └── agent.py          # Panel assessment logic
│   ├── behavioral/
│   │   ├── agent.py          # Profile & battery sizing
│   │   └── arbitrage.py      # TOU tariff optimization
│   ├── synthesis/
│   │   ├── agent.py          # Final design generation
│   │   └── pioneer_client.py # Pioneer SLM integration
│   ├── safety/
│   │   ├── validator.py      # Core validation engine
│   │   ├── guardrails.py     # Regulatory checks
│   │   └── schemas/          # JSON Schema files
│   └── orchestrator/
│       ├── agent.py          # Workflow execution
│       └── dag.py            # Pipeline DAG definition
├── common/
│   ├── schemas.py            # Pydantic models for all schemas
│   └── config.py             # Environment & API config
└── web/                      # Next.js frontend
```

---

## Build Order

1. **CLAUDE.md** (this file) + Pydantic schema models
2. **Safety/Validation Agent** + comprehensive tests
3. **Ingestion Agent** (Gemini integration)
4. **Domain Agents** in parallel (Structural, Electrical, Thermodynamic, Behavioral)
5. **Orchestrator Agent**
6. **Design Synthesis Agent** (Pioneer integration)
7. **Customer Web App + Installer Dashboard**
