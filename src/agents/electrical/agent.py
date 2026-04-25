"""
Electrical Agent

Takes ElectricalData from the Ingestion Agent and produces an ElectricalAssessment.
Deterministic capacity analysis, upgrade recommendations, and inverter sizing — no LLM calls.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.common.schemas import (
    BoardCondition,
    BreakerType,
    ElectricalAssessment,
    ElectricalData,
    InverterRecommendation,
    InverterType,
    SimpleMetadata,
    UpgradeRequired,
    UpgradeType,
)

logger = logging.getLogger(__name__)

# Minimum main supply amperage before a board upgrade is required
MIN_BOARD_AMPERAGE_A = 63

# Single-phase threshold for three-phase conversion (32A × 230V = 7.36 kW)
SINGLE_PHASE_MAX_LOAD_A = 32

# Estimated costs for each upgrade type (EUR)
UPGRADE_COSTS_EUR = {
    UpgradeType.BOARD_UPGRADE: 1500.0,
    UpgradeType.THREE_PHASE_CONVERSION: 3000.0,
    UpgradeType.RCD_ADDITION: 300.0,
}

# Minimum inverter AC output (kW) — clamp floor
MIN_INVERTER_OUTPUT_KW = 3.0

# Voltage used for kW ↔ A conversion (single-phase 230V)
NOMINAL_VOLTAGE_V = 230


def run(electrical_data: ElectricalData) -> ElectricalAssessment:
    """
    Execute the Electrical Agent assessment.

    1. Calculate available headroom (max_additional_load_A)
    2. Determine which upgrades are required
    3. Recommend inverter type based on supply phase count
    4. Evaluate EV charger compatibility
    5. Set current_capacity_sufficient flag

    Args:
        electrical_data: Validated ElectricalData from the Ingestion Agent.

    Returns:
        ElectricalAssessment ready for validation by the Safety Agent.
    """
    logger.info(
        "Electrical Agent: assessing %d-phase supply at %dA with %d breakers",
        electrical_data.main_supply.phases,
        electrical_data.main_supply.amperage_A,
        len(electrical_data.breakers),
    )

    # -------------------------------------------------------------------------
    # 1. Calculate max additional load headroom
    # -------------------------------------------------------------------------
    total_breaker_load_A = sum(b.rating_A for b in electrical_data.breakers)
    max_additional_load_A = (
        electrical_data.main_supply.amperage_A - total_breaker_load_A
    )

    logger.info(
        "  Main supply: %dA, total breaker load: %dA, headroom: %.1fA",
        electrical_data.main_supply.amperage_A,
        total_breaker_load_A,
        max_additional_load_A,
    )

    # -------------------------------------------------------------------------
    # 2. Determine required upgrades
    # -------------------------------------------------------------------------
    upgrades_required: list[UpgradeRequired] = []

    # Board upgrade: low amperage
    if electrical_data.main_supply.amperage_A < MIN_BOARD_AMPERAGE_A:
        upgrades_required.append(
            UpgradeRequired(
                type=UpgradeType.BOARD_UPGRADE,
                reason=(
                    f"Main supply amperage ({electrical_data.main_supply.amperage_A}A) "
                    f"is below the minimum {MIN_BOARD_AMPERAGE_A}A required for a "
                    "solar + heat pump system."
                ),
                estimated_cost_eur=UPGRADE_COSTS_EUR[UpgradeType.BOARD_UPGRADE],
            )
        )
        logger.info("  Board upgrade required: amperage below %dA", MIN_BOARD_AMPERAGE_A)

    # Board upgrade: poor board condition (only add if not already added for amperage)
    board_condition = electrical_data.board_condition
    if board_condition in (BoardCondition.POOR, BoardCondition.REQUIRES_REPLACEMENT):
        # Avoid duplicate board_upgrade entries
        already_flagged = any(
            u.type == UpgradeType.BOARD_UPGRADE for u in upgrades_required
        )
        if not already_flagged:
            upgrades_required.append(
                UpgradeRequired(
                    type=UpgradeType.BOARD_UPGRADE,
                    reason=(
                        f"Board condition is '{board_condition.value}' and must be "
                        "replaced before installing solar or heat pump equipment."
                    ),
                    estimated_cost_eur=UPGRADE_COSTS_EUR[UpgradeType.BOARD_UPGRADE],
                )
            )
            logger.info("  Board upgrade required: board condition is '%s'", board_condition.value)
        else:
            # Update the existing board upgrade reason to also mention condition
            existing = next(u for u in upgrades_required if u.type == UpgradeType.BOARD_UPGRADE)
            upgrades_required.remove(existing)
            upgrades_required.append(
                UpgradeRequired(
                    type=UpgradeType.BOARD_UPGRADE,
                    reason=(
                        f"Main supply amperage ({electrical_data.main_supply.amperage_A}A) "
                        f"is below the minimum {MIN_BOARD_AMPERAGE_A}A and board condition "
                        f"is '{board_condition.value}'. Full board replacement required."
                    ),
                    estimated_cost_eur=UPGRADE_COSTS_EUR[UpgradeType.BOARD_UPGRADE],
                )
            )

    # Three-phase conversion: single-phase with insufficient headroom for planned load
    if electrical_data.main_supply.phases == 1 and max_additional_load_A < SINGLE_PHASE_MAX_LOAD_A:
        upgrades_required.append(
            UpgradeRequired(
                type=UpgradeType.THREE_PHASE_CONVERSION,
                reason=(
                    f"Single-phase supply has only {max_additional_load_A:.1f}A of headroom, "
                    f"which is below the {SINGLE_PHASE_MAX_LOAD_A}A ({SINGLE_PHASE_MAX_LOAD_A * NOMINAL_VOLTAGE_V / 1000:.2f} kW) "
                    "required for the planned solar + heat pump load."
                ),
                estimated_cost_eur=UPGRADE_COSTS_EUR[UpgradeType.THREE_PHASE_CONVERSION],
            )
        )
        logger.info(
            "  Three-phase conversion required: single-phase headroom %.1fA < %dA",
            max_additional_load_A,
            SINGLE_PHASE_MAX_LOAD_A,
        )

    # RCD addition: no RCD or RCBO breaker present
    has_rcd = any(
        b.type in (BreakerType.RCD, BreakerType.RCBO) for b in electrical_data.breakers
    )
    if not has_rcd:
        upgrades_required.append(
            UpgradeRequired(
                type=UpgradeType.RCD_ADDITION,
                reason=(
                    "No RCD or RCBO breaker found in the panel. An RCD is required "
                    "for protection of solar and heat pump circuits."
                ),
                estimated_cost_eur=UPGRADE_COSTS_EUR[UpgradeType.RCD_ADDITION],
            )
        )
        logger.info("  RCD addition required: no RCD/RCBO breaker present")

    # -------------------------------------------------------------------------
    # 3. Inverter recommendation
    # -------------------------------------------------------------------------
    if electrical_data.main_supply.phases == 1:
        inverter_type = InverterType.HYBRID
    else:
        inverter_type = InverterType.THREE_PHASE

    # max_ac_output_kw: headroom in amps × 230V, clamped to minimum 3.0 kW
    # Use absolute value of headroom for sizing (even if negative, size to minimum)
    headroom_for_sizing = max(max_additional_load_A, 0.0)
    max_ac_output_kw = max(headroom_for_sizing * NOMINAL_VOLTAGE_V / 1000, MIN_INVERTER_OUTPUT_KW)

    inverter_recommendation = InverterRecommendation(
        type=inverter_type,
        max_ac_output_kw=round(max_ac_output_kw, 2),
    )

    logger.info(
        "  Inverter recommendation: %s, %.2f kW AC output",
        inverter_type.value,
        max_ac_output_kw,
    )

    # -------------------------------------------------------------------------
    # 4. EV charger compatibility
    # -------------------------------------------------------------------------
    has_ev = getattr(electrical_data, "has_ev", None)
    spare_ways = electrical_data.spare_ways

    # has_ev lives on ConsumptionData, not ElectricalData — check spare_ways only here
    ev_charger_compatible: bool | None = None
    if spare_ways is not None:
        ev_charger_compatible = spare_ways >= 2
    # Note: has_ev from ConsumptionData is not available in ElectricalData;
    # the orchestrator may enrich this field if needed. We handle the
    # ElectricalData-only case here per the schema definition.

    logger.info(
        "  EV charger compatible: %s (spare_ways=%s)",
        ev_charger_compatible,
        spare_ways,
    )

    # -------------------------------------------------------------------------
    # 5. Current capacity sufficient
    # -------------------------------------------------------------------------
    current_capacity_sufficient = (
        len(upgrades_required) == 0 and max_additional_load_A > 0
    )

    logger.info(
        "Electrical Agent: complete — capacity_sufficient=%s, %d upgrades required",
        current_capacity_sufficient,
        len(upgrades_required),
    )

    return ElectricalAssessment(
        current_capacity_sufficient=current_capacity_sufficient,
        max_additional_load_A=max(max_additional_load_A, 0.0),
        upgrades_required=upgrades_required,
        inverter_recommendation=inverter_recommendation,
        ev_charger_compatible=ev_charger_compatible,
        metadata=SimpleMetadata(timestamp=datetime.now(timezone.utc)),
    )
