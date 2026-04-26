"""
Pydantic models for all inter-agent handoff schemas.

Every model here corresponds 1:1 to a JSON Schema defined in CLAUDE.md.
All agents MUST use these models for serialization/deserialization.
Validation is strict — no coercion, no extra fields.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ============================================================================
# Enums
# ============================================================================


class RoofTypology(str, Enum):
    GABLE = "gable"
    HIP = "hip"
    FLAT = "flat"
    MANSARD = "mansard"
    GAMBREL = "gambrel"
    SHED = "shed"
    COMBINATION = "combination"


class ObstacleType(str, Enum):
    DORMER = "dormer"
    VENT_PIPE = "vent_pipe"
    CHIMNEY = "chimney"
    SKYLIGHT = "skylight"
    ANTENNA = "antenna"
    FOLIAGE_SHADOW = "foliage_shadow"
    OTHER = "other"


class SourceType(str, Enum):
    VIDEO = "video"
    IMAGE = "image"
    PHOTO = "photo"
    PDF = "pdf"
    MANUAL = "manual"


class BreakerType(str, Enum):
    MCB = "MCB"
    RCBO = "RCBO"
    RCD = "RCD"
    MCCB = "MCCB"
    ISOLATOR = "isolator"
    UNKNOWN = "unknown"


class BoardCondition(str, Enum):
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    REQUIRES_REPLACEMENT = "requires_replacement"


class Currency(str, Enum):
    EUR = "EUR"
    GBP = "GBP"
    USD = "USD"
    CHF = "CHF"


class HeatingFuel(str, Enum):
    GAS = "gas"
    OIL = "oil"
    ELECTRIC = "electric"
    LPG = "lpg"
    DISTRICT = "district"
    NONE = "none"


class PanelOrientation(str, Enum):
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


class HeatPumpType(str, Enum):
    AIR_SOURCE = "air_source"
    GROUND_SOURCE = "ground_source"
    WATER_SOURCE = "water_source"


class OccupancyPattern(str, Enum):
    HOME_ALL_DAY = "home_all_day"
    AWAY_DAYTIME = "away_daytime"
    SHIFT_WORKER = "shift_worker"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class OptimizationFrequency(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    BIANNUAL = "biannual"


class InverterType(str, Enum):
    SINGLE_PHASE = "single_phase"
    THREE_PHASE = "three_phase"
    MICRO_INVERTER = "micro_inverter"
    HYBRID = "hybrid"


class UpgradeType(str, Enum):
    BOARD_UPGRADE = "board_upgrade"
    METER_UPGRADE = "meter_upgrade"
    THREE_PHASE_CONVERSION = "three_phase_conversion"
    EARTHING_UPGRADE = "earthing_upgrade"
    RCD_ADDITION = "rcd_addition"
    EV_CIRCUIT = "ev_circuit"


class SignoffStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISION_REQUESTED = "revision_requested"


class ErrorSeverity(str, Enum):
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"


# Standard breaker ratings (amps)
VALID_BREAKER_RATINGS = frozenset([6, 10, 13, 16, 20, 25, 32, 40, 50, 63, 80, 100, 125])

# Standard DHW cylinder sizes (litres)
VALID_CYLINDER_SIZES = frozenset([150, 170, 200, 210, 250, 300])


# ============================================================================
# Metadata sub-models
# ============================================================================


class IngestionMetadata(BaseModel):
    """Metadata attached to Ingestion Agent outputs."""

    model_config = {"extra": "forbid"}

    source_type: SourceType
    confidence_score: float = Field(ge=0.0, le=1.0)
    timestamp: datetime
    gemini_model_version: Optional[str] = None
    bill_period_start: Optional[date] = None
    bill_period_end: Optional[date] = None


class CalculationMetadata(BaseModel):
    """Metadata for calculation-based agent outputs."""

    model_config = {"extra": "forbid"}

    algorithm_version: Optional[str] = None
    calculation_method: Optional[str] = None
    timestamp: datetime


class SimpleMetadata(BaseModel):
    """Minimal metadata with just a timestamp."""

    model_config = {"extra": "forbid"}

    timestamp: datetime


# ============================================================================
# 1. SpatialData  (Ingestion → Structural, Thermodynamic)
# ============================================================================


class RoofFace(BaseModel):
    model_config = {"extra": "forbid"}

    id: str
    orientation_deg: float = Field(ge=0, le=360, description="Azimuth: 0=N, 90=E, 180=S, 270=W")
    tilt_deg: float = Field(ge=0, le=90)
    area_m2: float = Field(ge=1)
    length_m: Optional[float] = Field(default=None, ge=0.5)
    width_m: Optional[float] = Field(default=None, ge=0.5)
    # Phase 4 — 3D extension (nullable, backward compatible)
    polygon_vertices_3d: Optional[list[list[float]]] = None
    polygon_vertices_image: Optional[list[list[float]]] = None


class Obstacle(BaseModel):
    model_config = {"extra": "forbid"}

    type: ObstacleType
    face_id: str
    area_m2: float = Field(ge=0)
    buffer_m: float = Field(default=0.3, ge=0, description="Safety buffer around obstacle")


class RoofData(BaseModel):
    model_config = {"extra": "forbid"}

    typology: RoofTypology
    faces: list[RoofFace] = Field(min_length=1)
    total_usable_area_m2: float = Field(ge=1)
    obstacles: list[Obstacle] = Field(default_factory=list)


class UtilityRoom(BaseModel):
    model_config = {"extra": "forbid"}

    length_m: float = Field(ge=0.5)
    width_m: float = Field(ge=0.5)
    height_m: float = Field(ge=1.5)
    available_volume_m3: float = Field(ge=0)
    existing_pipework: Optional[bool] = None
    spatial_constraints: list[str] = Field(default_factory=list)


class SpatialData(BaseModel):
    """Output of the Ingestion Agent from roofline video analysis."""

    model_config = {"extra": "forbid"}

    roof: RoofData
    utility_room: UtilityRoom
    metadata: IngestionMetadata
    # Phase 4 — 3D reconstruction artifacts (nullable, backward compatible)
    mesh_uri: Optional[str] = None
    point_cloud_uri: Optional[str] = None
    reconstruction_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


# ============================================================================
# 2. ElectricalData  (Ingestion → Electrical Agent)
# ============================================================================


class MainSupply(BaseModel):
    model_config = {"extra": "forbid"}

    amperage_A: int = Field(ge=16, le=200)
    phases: int = Field(description="1 or 3 phase supply")
    voltage_V: int = Field(description="230 or 400 volts")


class Breaker(BaseModel):
    model_config = {"extra": "forbid"}

    label: str
    rating_A: int
    type: BreakerType
    circuit_description: Optional[str] = None


class ElectricalData(BaseModel):
    """Output of the Ingestion Agent from electrical panel photo."""

    model_config = {"extra": "forbid"}

    main_supply: MainSupply
    breakers: list[Breaker]
    board_condition: Optional[BoardCondition] = None
    spare_ways: Optional[int] = Field(default=None, ge=0)
    metadata: IngestionMetadata


# ============================================================================
# 3. ConsumptionData  (Ingestion → Thermodynamic, Behavioral)
# ============================================================================


class MonthlyConsumption(BaseModel):
    model_config = {"extra": "forbid"}

    month: int = Field(ge=1, le=12)
    kwh: float = Field(ge=0)


class TimeOfUse(BaseModel):
    model_config = {"extra": "forbid"}

    peak_rate: float
    off_peak_rate: float
    peak_hours_start: int = Field(ge=0, le=23)
    peak_hours_end: int = Field(ge=0, le=23)


class Tariff(BaseModel):
    model_config = {"extra": "forbid"}

    currency: Currency
    rate_per_kwh: float = Field(ge=0)
    feed_in_tariff_per_kwh: Optional[float] = Field(default=None, ge=0)
    time_of_use: Optional[TimeOfUse] = None


class ConsumptionData(BaseModel):
    """Output of the Ingestion Agent from utility bill PDF parsing."""

    model_config = {"extra": "forbid"}

    annual_kwh: float = Field(ge=500, le=100000)
    monthly_breakdown: list[MonthlyConsumption] = Field(min_length=12, max_length=12)
    tariff: Tariff
    heating_fuel: Optional[HeatingFuel] = None
    annual_heating_kwh: Optional[float] = Field(default=None, ge=0)
    has_ev: Optional[bool] = None
    metadata: IngestionMetadata


# ============================================================================
# 4. ModuleLayout  (Structural Agent → Design Synthesis)
# ============================================================================


class PanelDimensions(BaseModel):
    model_config = {"extra": "forbid"}

    length: int
    width: int


class FaceLayout(BaseModel):
    model_config = {"extra": "forbid"}

    face_id: str
    count: int = Field(ge=0)
    orientation: PanelOrientation
    panel_watt_peak: int = Field(ge=250, le=700)
    panel_dimensions_mm: Optional[PanelDimensions] = None


class StringConfig(BaseModel):
    model_config = {"extra": "forbid"}

    string_id: str
    panels_in_series: int
    voc_string_V: float = Field(le=1000, description="Must not exceed 1000V DC")
    isc_string_A: float


class StringLayout(BaseModel):
    model_config = {"extra": "forbid"}

    strings: list[StringConfig]


class ModuleLayout(BaseModel):
    """Output of the Structural Agent."""

    model_config = {"extra": "forbid"}

    panels: list[FaceLayout]
    total_kwp: float = Field(ge=0, le=100)
    total_panels: int = Field(ge=0)
    string_config: StringLayout
    exclusion_zones_applied: list[str] = Field(default_factory=list)
    metadata: CalculationMetadata


# ============================================================================
# 5. ThermalLoad  (Thermodynamic Agent → Design Synthesis)
# ============================================================================


class UValues(BaseModel):
    """Standardized U-values used when exact building data is unavailable."""

    model_config = {"extra": "forbid"}

    walls_w_m2k: Optional[float] = None
    roof_w_m2k: Optional[float] = None
    floor_w_m2k: Optional[float] = None
    windows_w_m2k: Optional[float] = None


class HeatPumpRecommendation(BaseModel):
    model_config = {"extra": "forbid"}

    capacity_kw: float = Field(ge=2, le=50)
    type: HeatPumpType
    cop_estimate: Optional[float] = Field(default=None, ge=1.0, le=7.0)
    safety_factor: float = Field(default=1.15, ge=1.0, le=1.5)


class DHWRequirement(BaseModel):
    model_config = {"extra": "forbid"}

    daily_litres: float = Field(ge=50)
    cylinder_volume_litres: int
    fits_in_utility_room: Optional[bool] = None


class ThermalLoad(BaseModel):
    """Output of the Thermodynamic Agent — DIN EN 12831 simplified."""

    model_config = {"extra": "forbid"}

    design_heat_load_kw: float = Field(ge=1, le=100, description="Φ_HL per DIN EN 12831")
    transmission_loss_kw: Optional[float] = Field(default=None, ge=0)
    ventilation_loss_kw: Optional[float] = Field(default=None, ge=0)
    design_outdoor_temp_c: float = Field(ge=-30, le=10)
    design_indoor_temp_c: float = Field(default=20, ge=18, le=24)
    u_values_used: Optional[UValues] = None
    heat_pump_recommendation: HeatPumpRecommendation
    dhw_requirement: DHWRequirement
    metadata: CalculationMetadata


# ============================================================================
# 6. ElectricalAssessment  (Electrical Agent → Design Synthesis)
# ============================================================================


class UpgradeRequired(BaseModel):
    model_config = {"extra": "forbid"}

    type: UpgradeType
    reason: str
    estimated_cost_eur: float = Field(ge=0)


class InverterRecommendation(BaseModel):
    model_config = {"extra": "forbid"}

    type: InverterType
    max_ac_output_kw: float = Field(ge=0)


class ElectricalAssessment(BaseModel):
    """Output of the Electrical Agent."""

    model_config = {"extra": "forbid"}

    current_capacity_sufficient: bool
    max_additional_load_A: Optional[float] = Field(default=None, ge=0)
    upgrades_required: list[UpgradeRequired] = Field(default_factory=list)
    inverter_recommendation: InverterRecommendation
    ev_charger_compatible: Optional[bool] = None
    metadata: SimpleMetadata


# ============================================================================
# 7. BehavioralProfile  (Behavioral Agent → Design Synthesis)
# ============================================================================


class BatteryRecommendation(BaseModel):
    model_config = {"extra": "forbid"}

    capacity_kwh: float = Field(ge=0.5, le=50)
    rationale: str
    charge_window_start: Optional[int] = Field(default=None, ge=0, le=23)
    charge_window_end: Optional[int] = Field(default=None, ge=0, le=23)
    discharge_window_start: Optional[int] = Field(default=None, ge=0, le=23)
    discharge_window_end: Optional[int] = Field(default=None, ge=0, le=23)
    arbitrage_savings_eur_annual: Optional[float] = Field(default=None, ge=0)


class OptimizationSchedule(BaseModel):
    model_config = {"extra": "forbid"}

    frequency: OptimizationFrequency
    next_review: date
    hems_integration: Optional[bool] = None


class BehavioralProfile(BaseModel):
    """Output of the Behavioral Agent."""

    model_config = {"extra": "forbid"}

    occupancy_pattern: OccupancyPattern
    self_consumption_ratio: Optional[float] = Field(default=None, ge=0, le=1)
    battery_recommendation: BatteryRecommendation
    optimization_schedule: OptimizationSchedule
    estimated_annual_savings_eur: Optional[float] = Field(default=None, ge=0, le=5000)
    metadata: SimpleMetadata


# ============================================================================
# 8. FinalProposal  (Design Synthesis → Human Handoff)
# ============================================================================


class PVDesign(BaseModel):
    model_config = {"extra": "forbid"}

    total_kwp: float
    panel_count: int
    panel_model: Optional[str] = None
    inverter_type: str
    inverter_model: Optional[str] = None
    annual_yield_kwh: Optional[float] = None


class BatteryDesign(BaseModel):
    model_config = {"extra": "forbid"}

    included: bool
    capacity_kwh: float
    model: Optional[str] = None


class HeatPumpDesign(BaseModel):
    model_config = {"extra": "forbid"}

    included: bool
    capacity_kw: float
    type: Optional[str] = None
    model: Optional[str] = None
    cop: Optional[float] = None
    cylinder_litres: Optional[int] = None


class EVChargerDesign(BaseModel):
    model_config = {"extra": "forbid"}

    included: bool
    capacity_kw: Optional[float] = None


class SystemDesign(BaseModel):
    model_config = {"extra": "forbid"}

    pv: PVDesign
    battery: BatteryDesign
    heat_pump: HeatPumpDesign
    ev_charger: Optional[EVChargerDesign] = None


class FinancialSummary(BaseModel):
    model_config = {"extra": "forbid"}

    total_cost_eur: float = Field(ge=0)
    annual_savings_eur: float
    payback_years: float = Field(ge=0)
    roi_percent: Optional[float] = None


class Compliance(BaseModel):
    model_config = {"extra": "forbid"}

    electrical_upgrades: list[str] = Field(default_factory=list)
    regulatory_notes: list[str] = Field(default_factory=list)
    single_line_diagram_ref: Optional[str] = None


class HumanSignoff(BaseModel):
    model_config = {"extra": "forbid"}

    required: bool = Field(
        default=True,
        description="MUST always be True — no proposal bypasses human review",
    )
    status: SignoffStatus = SignoffStatus.PENDING
    installer_id: Optional[str] = None
    signed_at: Optional[datetime] = None
    notes: Optional[str] = None


class ProposalMetadata(BaseModel):
    model_config = {"extra": "forbid"}

    version: str
    generated_at: datetime
    pipeline_run_id: str
    all_validations_passed: Optional[bool] = None


class FinalProposal(BaseModel):
    """Output of the Design Synthesis Agent — the complete system proposal."""

    model_config = {"extra": "forbid"}

    system_design: SystemDesign
    financial_summary: FinancialSummary
    compliance: Compliance
    human_signoff: HumanSignoff
    metadata: ProposalMetadata


# ============================================================================
# 9. ValidationResult  (Safety Agent output)
# ============================================================================


class ValidationError(BaseModel):
    model_config = {"extra": "forbid"}

    code: str = Field(description="E.g. VOLTAGE_EXCEEDED, MISSING_FIELD, RANGE_VIOLATION")
    message: str
    field: str
    severity: ErrorSeverity = ErrorSeverity.ERROR


class ValidationResult(BaseModel):
    """Output of the Safety / Validation Agent."""

    model_config = {"extra": "forbid"}

    valid: bool
    agent_source: str
    schema_name: str
    errors: list[ValidationError] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    timestamp: datetime


# ============================================================================
# 10. HEMS — EEBus-compatible telemetry + optimization delta
# ============================================================================


class TelemetryPoint(BaseModel):
    """EEBus-style smart meter reading (SMGW / EMC measurement)."""

    model_config = {"extra": "forbid"}

    timestamp: datetime
    kwh_imported: float = Field(ge=0, description="Grid import since last reading")
    kwh_exported: float = Field(ge=0, description="Grid export (PV surplus) since last reading")
    occupancy_hint: Optional[OccupancyPattern] = None


class InstallationRecord(BaseModel):
    """Post-install record linking a pipeline run to live telemetry."""

    model_config = {"extra": "forbid"}

    installation_id: str
    pipeline_run_id: str
    baseline_consumption: ConsumptionData
    baseline_profile: BehavioralProfile
    telemetry: list[TelemetryPoint] = Field(default_factory=list)
    created_at: datetime


class OptimizationDelta(BaseModel):
    """Output of the HEMS quarterly reoptimization pass."""

    model_config = {"extra": "forbid"}

    installation_id: str
    drift_detected: bool
    drift_reason: str
    old_occupancy: OccupancyPattern
    new_occupancy: OccupancyPattern
    old_battery_kwh: float
    new_battery_kwh: float
    battery_delta_kwh: float
    old_savings_eur: Optional[float]
    new_savings_eur: Optional[float]
    savings_delta_eur: Optional[float]
    new_profile: BehavioralProfile
    optimized_at: datetime
