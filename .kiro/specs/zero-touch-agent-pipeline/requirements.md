# Requirements Document

## Introduction

The Multimodal Zero-Touch Site Assessor is an agentic pipeline that transforms homeowner-provided media (roofline video, electrical panel photo, utility bill PDF) into an engineering-grade solar + heat pump proposal without a physical site visit. The system uses 8 independent sub-agents communicating exclusively via validated JSON, with a Safety Agent intercepting every handoff. The pipeline flow is: Ingestion → [Structural ‖ Electrical ‖ Thermodynamic ‖ Behavioral] → Design Synthesis → Human Handoff.

This requirements document covers the complete pipeline build-out: the Thermodynamic Agent wrapper, Electrical Agent, Behavioral Agent, Ingestion Agent, Design Synthesis Agent, Orchestrator Agent, FastAPI web layer, and comprehensive test coverage for all agents.

## Glossary

- **Pipeline**: The end-to-end data flow from media upload through proposal generation
- **Ingestion_Agent**: The agent responsible for processing multimodal media (video, photo, PDF) via Gemini 1.5 Pro and producing SpatialData, ElectricalData, and ConsumptionData
- **Structural_Agent**: The agent that takes SpatialData and produces a ModuleLayout with panel placement and string configuration (already implemented)
- **Electrical_Agent**: The agent that takes ElectricalData and produces an ElectricalAssessment with capacity analysis, upgrade recommendations, and inverter sizing
- **Thermodynamic_Agent**: The agent that takes SpatialData and ConsumptionData and produces a ThermalLoad using the DIN EN 12831 simplified calculation engine (engine exists, wrapper missing)
- **Behavioral_Agent**: The agent that takes ConsumptionData and produces a BehavioralProfile with occupancy detection, battery sizing, and TOU arbitrage optimization
- **Synthesis_Agent**: The agent that takes outputs from all domain agents and produces a FinalProposal using the Pioneer SLM
- **Safety_Agent**: The agent that validates every inter-agent handoff against Pydantic schemas and domain guardrails (already implemented)
- **Orchestrator_Agent**: The agent that manages pipeline DAG execution, routes data between agents, and ensures Safety_Agent validates every transition
- **Handoff**: A validated JSON payload passed from one agent to the next through the Orchestrator_Agent
- **DAG**: Directed Acyclic Graph defining the execution order and parallelism of agents in the pipeline
- **SpatialData**: Schema for roof geometry, obstacles, and utility room dimensions extracted from video
- **ElectricalData**: Schema for main supply, breakers, and board condition extracted from panel photo
- **ConsumptionData**: Schema for annual/monthly energy usage and tariff extracted from utility bill PDF
- **ModuleLayout**: Schema for panel placement, string configuration, and total kWp
- **ThermalLoad**: Schema for DIN EN 12831 heat load, heat pump recommendation, and DHW requirement
- **ElectricalAssessment**: Schema for capacity analysis, required upgrades, and inverter recommendation
- **BehavioralProfile**: Schema for occupancy pattern, battery recommendation, and optimization schedule
- **FinalProposal**: Schema for complete system design, financials, compliance, and human sign-off
- **ValidationResult**: Schema for Safety_Agent output with pass/fail verdict, errors, and warnings
- **Gemini_API**: Google Gemini 1.5 Pro multimodal API used by the Ingestion_Agent
- **Pioneer_SLM**: Pioneer Small Language Model fine-tuned on the Reonic dataset, used by the Synthesis_Agent
- **DIN_EN_12831**: German standard for residential heat load calculation (simplified method)
- **TOU_Tariff**: Time-of-Use electricity tariff with peak and off-peak rates
- **HEMS**: Home Energy Management System for adaptive optimization
- **Installer_Dashboard**: Web interface for certified installers to review and approve proposals
- **Customer_Portal**: Web interface for homeowners to upload media and view proposals

## Requirements

### Requirement 1: Thermodynamic Agent Wrapper

**User Story:** As a pipeline operator, I want the Thermodynamic_Agent to wrap the existing DIN EN 12831 calculation engine, so that SpatialData and ConsumptionData are transformed into a validated ThermalLoad.

#### Acceptance Criteria

1. WHEN SpatialData and ConsumptionData are provided, THE Thermodynamic_Agent SHALL produce a ThermalLoad containing design_heat_load_kw, transmission_loss_kw, ventilation_loss_kw, heat_pump_recommendation, and dhw_requirement
2. THE Thermodynamic_Agent SHALL delegate heat load calculation to the existing `din_en_12831.calculate_design_heat_load` function
3. THE Thermodynamic_Agent SHALL delegate DHW sizing to the existing `din_en_12831.estimate_dhw_requirement` function
4. THE Thermodynamic_Agent SHALL delegate heat pump capacity selection to the existing `din_en_12831.recommend_heat_pump_capacity` function
5. WHEN a building_year is not available from the input data, THE Thermodynamic_Agent SHALL use the default U-values from the DIN EN 12831 engine
6. THE Thermodynamic_Agent SHALL set the calculation_method metadata field to "DIN_EN_12831_simplified"
7. WHEN the utility room volume is available in SpatialData, THE Thermodynamic_Agent SHALL evaluate whether the recommended DHW cylinder fits in the utility room
8. FOR ALL valid SpatialData and ConsumptionData inputs, producing a ThermalLoad and then serializing and deserializing the ThermalLoad SHALL yield an equivalent object (round-trip property)

### Requirement 2: Electrical Agent

**User Story:** As a pipeline operator, I want the Electrical_Agent to assess the existing electrical installation, so that the system can determine capacity sufficiency, required upgrades, and inverter compatibility.

#### Acceptance Criteria

1. WHEN ElectricalData is provided, THE Electrical_Agent SHALL produce an ElectricalAssessment containing current_capacity_sufficient, upgrades_required, and inverter_recommendation
2. THE Electrical_Agent SHALL calculate max_additional_load_A as the difference between the main supply amperage and the sum of existing breaker ratings
3. WHEN the main supply amperage is below 63A and a solar + heat pump system is planned, THE Electrical_Agent SHALL include a board_upgrade in upgrades_required
4. WHEN the board_condition is "poor" or "requires_replacement", THE Electrical_Agent SHALL include a board_upgrade in upgrades_required with the reason referencing the board condition
5. WHEN the supply is single-phase and the total planned load exceeds 7.36 kW (32A at 230V), THE Electrical_Agent SHALL include a three_phase_conversion in upgrades_required
6. WHEN no RCD or RCBO breaker is present in the breaker list, THE Electrical_Agent SHALL include an rcd_addition in upgrades_required
7. THE Electrical_Agent SHALL recommend an inverter type based on the supply phase count: hybrid for single-phase systems, three_phase for three-phase systems
8. WHEN the ElectricalData indicates has_ev is true or spare_ways is at least 2, THE Electrical_Agent SHALL set ev_charger_compatible to true
9. WHEN current_capacity_sufficient is false, THE Electrical_Agent SHALL include at least one entry in upgrades_required

### Requirement 3: Behavioral Agent and TOU Arbitrage

**User Story:** As a pipeline operator, I want the Behavioral_Agent to analyze consumption patterns and optimize battery sizing with TOU arbitrage, so that the proposal maximizes self-consumption and financial savings.

#### Acceptance Criteria

1. WHEN ConsumptionData is provided, THE Behavioral_Agent SHALL produce a BehavioralProfile containing occupancy_pattern, battery_recommendation, and optimization_schedule
2. THE Behavioral_Agent SHALL detect occupancy_pattern by analyzing the monthly consumption distribution: high winter consumption relative to summer indicates "home_all_day", low daytime consumption indicates "away_daytime"
3. WHEN a TOU tariff is present in ConsumptionData, THE Behavioral_Agent SHALL calculate arbitrage_savings_eur_annual based on the peak-to-off-peak rate differential and estimated shiftable load
4. THE Behavioral_Agent SHALL size the battery capacity_kwh based on the average daily consumption, self-consumption ratio, and occupancy pattern
5. WHEN a TOU tariff is present, THE Behavioral_Agent SHALL set charge_window_start and charge_window_end to the off-peak hours and discharge_window_start and discharge_window_end to the peak hours
6. THE Behavioral_Agent SHALL set the optimization_schedule frequency to "quarterly" and calculate the next_review date as 90 days from the current date
7. THE Behavioral_Agent SHALL estimate annual savings based on self-consumption ratio, feed-in tariff revenue, and arbitrage savings
8. WHEN the battery charge and discharge windows are set, THE Behavioral_Agent SHALL ensure the charge window and discharge window do not overlap

### Requirement 4: Ingestion Agent with Gemini Integration

**User Story:** As a homeowner, I want to upload a roofline video, electrical panel photo, and utility bill PDF, so that the system can extract structured data without a physical site visit.

#### Acceptance Criteria

1. WHEN a roofline video file is provided, THE Ingestion_Agent SHALL call the Gemini_API to extract roof geometry and produce a valid SpatialData object
2. WHEN an electrical panel photo is provided, THE Ingestion_Agent SHALL call the Gemini_API to extract breaker information and produce a valid ElectricalData object
3. WHEN a utility bill PDF is provided, THE Ingestion_Agent SHALL call the Gemini_API to extract consumption data and produce a valid ConsumptionData object
4. THE Ingestion_Agent SHALL include a confidence_score between 0.0 and 1.0 in the metadata of every output, reflecting the Gemini_API extraction confidence
5. IF the Gemini_API returns an error or times out, THEN THE Ingestion_Agent SHALL return a structured error with the source_type and a descriptive message
6. IF the uploaded file format is not one of MP4, MOV, WEBM (video), JPEG, PNG, HEIC (photo), or PDF (bill), THEN THE Ingestion_Agent SHALL reject the file with a descriptive error before calling the Gemini_API
7. THE Ingestion_Agent SHALL set the gemini_model_version metadata field to the model version string returned by the Gemini_API
8. WHEN a utility bill PDF is provided, THE Ingestion_Agent SHALL extract bill_period_start and bill_period_end dates and include them in the ConsumptionData metadata
9. FOR ALL valid SpatialData produced by the Ingestion_Agent, serializing to JSON and deserializing back SHALL yield an equivalent SpatialData object (round-trip property)
10. FOR ALL valid ElectricalData produced by the Ingestion_Agent, serializing to JSON and deserializing back SHALL yield an equivalent ElectricalData object (round-trip property)
11. FOR ALL valid ConsumptionData produced by the Ingestion_Agent, serializing to JSON and deserializing back SHALL yield an equivalent ConsumptionData object (round-trip property)

### Requirement 5: Design Synthesis Agent with Pioneer SLM

**User Story:** As a pipeline operator, I want the Synthesis_Agent to combine all domain agent outputs into an optimal FinalProposal, so that the homeowner receives a complete, financially viable system design.

#### Acceptance Criteria

1. WHEN ModuleLayout, ThermalLoad, ElectricalAssessment, and BehavioralProfile are provided, THE Synthesis_Agent SHALL produce a FinalProposal containing system_design, financial_summary, compliance, and human_signoff
2. THE Synthesis_Agent SHALL populate the PV design section from the ModuleLayout total_kwp, total_panels, and inverter recommendation from the ElectricalAssessment
3. THE Synthesis_Agent SHALL populate the heat pump design section from the ThermalLoad heat_pump_recommendation capacity_kw, type, and cop_estimate
4. THE Synthesis_Agent SHALL populate the battery design section from the BehavioralProfile battery_recommendation capacity_kwh
5. THE Synthesis_Agent SHALL calculate financial_summary.total_cost_eur by summing component costs from the Pioneer_SLM pricing response and any electrical upgrade costs from the ElectricalAssessment
6. THE Synthesis_Agent SHALL calculate financial_summary.annual_savings_eur from the BehavioralProfile estimated_annual_savings_eur plus heat pump operational savings
7. THE Synthesis_Agent SHALL calculate financial_summary.payback_years as total_cost_eur divided by annual_savings_eur
8. THE Synthesis_Agent SHALL always set human_signoff.required to true and human_signoff.status to "pending"
9. THE Synthesis_Agent SHALL include all electrical upgrades from the ElectricalAssessment in the compliance.electrical_upgrades list
10. IF the Pioneer_SLM API returns an error or is unavailable, THEN THE Synthesis_Agent SHALL fall back to rule-based component selection using the Reonic dataset pricing
11. THE Synthesis_Agent SHALL generate a unique pipeline_run_id in the metadata for traceability

### Requirement 6: Orchestrator Agent and Pipeline DAG

**User Story:** As a pipeline operator, I want the Orchestrator_Agent to manage the execution order of all agents, so that data flows correctly through the pipeline with safety validation at every step.

#### Acceptance Criteria

1. THE Orchestrator_Agent SHALL define a DAG with the following execution order: Ingestion_Agent first, then Structural_Agent, Electrical_Agent, Thermodynamic_Agent, and Behavioral_Agent in parallel, then Synthesis_Agent last
2. WHEN the Ingestion_Agent completes, THE Orchestrator_Agent SHALL route SpatialData to the Structural_Agent and Thermodynamic_Agent, ElectricalData to the Electrical_Agent, and ConsumptionData to the Thermodynamic_Agent and Behavioral_Agent
3. THE Orchestrator_Agent SHALL pass every agent output through the Safety_Agent validate_handoff function before forwarding the output to the next agent
4. IF the Safety_Agent rejects a handoff, THEN THE Orchestrator_Agent SHALL halt the pipeline and return the ValidationResult with all errors
5. WHEN all four domain agents complete successfully, THE Orchestrator_Agent SHALL pass their combined outputs to the Synthesis_Agent
6. THE Orchestrator_Agent SHALL execute the four domain agents (Structural, Electrical, Thermodynamic, Behavioral) concurrently using asyncio.gather
7. THE Orchestrator_Agent SHALL generate a unique pipeline_run_id at the start of each pipeline execution and include the pipeline_run_id in all log messages
8. IF any agent raises an unhandled exception, THEN THE Orchestrator_Agent SHALL catch the exception, log the error with the pipeline_run_id, and return a structured error response
9. THE Orchestrator_Agent SHALL log the start time, end time, and duration of each agent execution at INFO level

### Requirement 7: Safety Validation at Every Handoff

**User Story:** As a safety engineer, I want every inter-agent data transfer to be validated against schemas and domain guardrails, so that no invalid or dangerous data propagates through the pipeline.

#### Acceptance Criteria

1. THE Safety_Agent SHALL validate every handoff payload against the corresponding Pydantic schema using strict mode
2. THE Safety_Agent SHALL enforce that no string voltage exceeds 1000V DC in any ModuleLayout
3. THE Safety_Agent SHALL enforce that human_signoff.required is always true in every FinalProposal
4. THE Safety_Agent SHALL flag any Gemini_API output with confidence_score below 0.6 as a warning for manual review
5. THE Safety_Agent SHALL reject any ElectricalData containing non-standard breaker ratings
6. THE Safety_Agent SHALL reject any ConsumptionData where the monthly breakdown sum differs from annual_kwh by more than 10 percent
7. THE Safety_Agent SHALL reject any ThermalLoad with a DHW cylinder size not in the standard set of 150, 170, 200, 210, 250, or 300 litres
8. THE Safety_Agent SHALL reject any ElectricalAssessment where current_capacity_sufficient is false but upgrades_required is empty

### Requirement 8: FastAPI Web Layer

**User Story:** As a homeowner, I want a web API to upload my media files and receive a proposal, so that I can get a solar and heat pump assessment without scheduling a site visit.

#### Acceptance Criteria

1. THE Web_Layer SHALL expose a POST /api/v1/assess endpoint that accepts multipart file uploads for video, photo, and PDF
2. WHEN files are uploaded to the /api/v1/assess endpoint, THE Web_Layer SHALL validate file types and sizes before passing the files to the Orchestrator_Agent
3. IF any uploaded file exceeds 100 MB, THEN THE Web_Layer SHALL return HTTP 413 with a descriptive error message
4. THE Web_Layer SHALL expose a GET /api/v1/proposals/{pipeline_run_id} endpoint that returns the FinalProposal for a completed pipeline run
5. THE Web_Layer SHALL expose a POST /api/v1/proposals/{pipeline_run_id}/signoff endpoint that allows an authenticated installer to approve or reject a proposal
6. WHEN an installer submits a sign-off, THE Web_Layer SHALL update the human_signoff status, installer_id, and signed_at timestamp in the FinalProposal
7. IF the pipeline fails at any stage, THEN THE Web_Layer SHALL return HTTP 422 with the ValidationResult errors from the Safety_Agent
8. THE Web_Layer SHALL return HTTP 401 for unauthenticated requests to the signoff endpoint

### Requirement 9: Comprehensive Test Coverage

**User Story:** As a developer, I want comprehensive tests for all agents, so that regressions are caught early and domain logic is verified.

#### Acceptance Criteria

1. THE Test_Suite SHALL include unit tests for the Structural_Agent that verify panel placement counts for known roof geometries
2. THE Test_Suite SHALL include unit tests for the Thermodynamic_Agent that verify heat load calculations against known DIN EN 12831 reference values
3. THE Test_Suite SHALL include unit tests for the Electrical_Agent that verify upgrade recommendations for known electrical configurations
4. THE Test_Suite SHALL include unit tests for the Behavioral_Agent that verify battery sizing and arbitrage calculations for known consumption profiles
5. THE Test_Suite SHALL include integration tests for the Orchestrator_Agent that verify end-to-end pipeline execution with mock agent outputs
6. THE Test_Suite SHALL include tests that verify the Safety_Agent rejects payloads violating each guardrail rule in the safety guardrails table
7. FOR ALL valid ThermalLoad objects, serializing to JSON and deserializing back SHALL produce an equivalent ThermalLoad (round-trip property)
8. FOR ALL valid ElectricalAssessment objects, serializing to JSON and deserializing back SHALL produce an equivalent ElectricalAssessment (round-trip property)
9. FOR ALL valid BehavioralProfile objects, serializing to JSON and deserializing back SHALL produce an equivalent BehavioralProfile (round-trip property)
10. FOR ALL valid FinalProposal objects, serializing to JSON and deserializing back SHALL produce an equivalent FinalProposal (round-trip property)

### Requirement 10: Installer Dashboard and Human Sign-off Flow

**User Story:** As a certified installer, I want a dashboard to review AI-generated proposals and approve or reject them, so that no proposal reaches a customer without professional human review.

#### Acceptance Criteria

1. THE Installer_Dashboard SHALL display a list of pending proposals with status "pending" for the authenticated installer
2. WHEN an installer selects a proposal, THE Installer_Dashboard SHALL display the complete FinalProposal including system_design, financial_summary, and compliance details
3. THE Installer_Dashboard SHALL provide "Approve" and "Reject" actions that call the signoff API endpoint
4. WHEN an installer approves a proposal, THE Installer_Dashboard SHALL update the status to "approved" and record the installer_id and signed_at timestamp
5. WHEN an installer rejects a proposal, THE Installer_Dashboard SHALL require a notes field explaining the rejection reason and update the status to "rejected"
6. THE Installer_Dashboard SHALL prevent any proposal from being delivered to the customer while human_signoff.status is "pending"

### Requirement 11: Error Handling and Resilience

**User Story:** As a pipeline operator, I want the system to handle failures gracefully, so that partial failures do not corrupt data or leave the pipeline in an inconsistent state.

#### Acceptance Criteria

1. IF the Gemini_API is unavailable or returns a rate limit error, THEN THE Ingestion_Agent SHALL retry the request up to 3 times with exponential backoff before returning an error
2. IF the Pioneer_SLM API is unavailable, THEN THE Synthesis_Agent SHALL fall back to rule-based component selection and set a warning in the FinalProposal metadata
3. IF any domain agent fails, THEN THE Orchestrator_Agent SHALL cancel the remaining parallel agents and return a structured error with the failed agent name and error details
4. THE Orchestrator_Agent SHALL enforce a timeout of 120 seconds per agent execution and 300 seconds for the full pipeline
5. IF a timeout occurs, THEN THE Orchestrator_Agent SHALL log the timeout event and return a structured error indicating which agent timed out
