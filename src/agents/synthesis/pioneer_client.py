"""
Pioneer SLM API client for component pricing.

Uses the Pioneer OpenAI-compatible chat completions endpoint with DeepSeek-V3.1
to get component pricing for solar + heat pump proposals.

Falls back to rule-based Reonic dataset pricing if Pioneer is unavailable.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

from src.common.config import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rule-based pricing constants (Reonic dataset averages, EUR)
# ---------------------------------------------------------------------------

PV_COST_PER_KWP = 1200.0        # EUR per kWp installed
BATTERY_COST_PER_KWH = 800.0    # EUR per kWh capacity
HEAT_PUMP_COST_PER_KW = 600.0   # EUR per kW capacity
HEAT_PUMP_BASE_COST = 3000.0    # Base installation cost


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ComponentPricing:
    pv_cost_eur: float          # Cost for PV system
    battery_cost_eur: float     # Cost for battery
    heat_pump_cost_eur: float   # Cost for heat pump
    source: str                 # "pioneer_slm" or "rule_based_fallback"
    warning: str | None = None  # Set when fallback is used


# ---------------------------------------------------------------------------
# Rule-based fallback
# ---------------------------------------------------------------------------


def get_rule_based_pricing(
    total_kwp: float,
    battery_kwh: float,
    heat_pump_kw: float,
) -> ComponentPricing:
    """Calculate component pricing using Reonic dataset averages."""
    return ComponentPricing(
        pv_cost_eur=total_kwp * PV_COST_PER_KWP,
        battery_cost_eur=battery_kwh * BATTERY_COST_PER_KWH,
        heat_pump_cost_eur=HEAT_PUMP_BASE_COST + heat_pump_kw * HEAT_PUMP_COST_PER_KW,
        source="rule_based_fallback",
        warning="Pioneer SLM unavailable — using rule-based Reonic dataset pricing",
    )


def _build_pricing_prompt(total_kwp: float, battery_kwh: float, heat_pump_kw: float) -> str:
    """Build the pricing prompt for the Pioneer SLM."""
    return f"""You are a solar and heat pump installation cost estimator for the German residential market.

Given the following system specifications, provide component pricing in EUR:
- PV system: {total_kwp:.1f} kWp
- Battery storage: {battery_kwh:.1f} kWh
- Heat pump: {heat_pump_kw:.1f} kW

Respond ONLY with a JSON object in this exact format (no markdown, no explanation):
{{
  "pv_cost_eur": <number>,
  "battery_cost_eur": <number>,
  "heat_pump_cost_eur": <number>
}}

Use realistic 2024 German market prices including installation labor."""


def _parse_pricing_response(text: str) -> dict:
    """Extract JSON from the model response, stripping any markdown fences."""
    # Strip markdown code fences if present
    pattern = r"```(?:json)?\s*\n?(.*?)\n?```"
    match = re.search(pattern, text.strip(), re.DOTALL)
    if match:
        text = match.group(1).strip()
    return json.loads(text.strip())


# ---------------------------------------------------------------------------
# Pioneer SLM API client (OpenAI-compatible chat completions)
# ---------------------------------------------------------------------------


async def get_component_pricing(
    total_kwp: float,
    battery_kwh: float,
    heat_pump_kw: float,
) -> ComponentPricing:
    """
    Get component pricing from Pioneer SLM (DeepSeek-V3.1 via chat completions).
    Falls back to rule-based Reonic dataset pricing if Pioneer is unavailable.
    """
    if not config.pioneer.api_key:
        logger.info("Pioneer API key not set, using rule-based pricing")
        return get_rule_based_pricing(total_kwp, battery_kwh, heat_pump_kw)

    try:
        prompt = _build_pricing_prompt(total_kwp, battery_kwh, heat_pump_kw)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{config.pioneer.api_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.pioneer.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.pioneer.model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200,
                    "temperature": 0.1,  # Low temperature for consistent pricing
                },
            )
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        pricing_data = _parse_pricing_response(content)

        logger.info(
            "Pioneer SLM pricing: PV=€%.0f, battery=€%.0f, heat_pump=€%.0f",
            pricing_data["pv_cost_eur"],
            pricing_data["battery_cost_eur"],
            pricing_data["heat_pump_cost_eur"],
        )

        return ComponentPricing(
            pv_cost_eur=float(pricing_data["pv_cost_eur"]),
            battery_cost_eur=float(pricing_data["battery_cost_eur"]),
            heat_pump_cost_eur=float(pricing_data["heat_pump_cost_eur"]),
            source="pioneer_slm",
        )

    except Exception as exc:
        logger.warning(
            "Pioneer SLM pricing unavailable, falling back to rule-based pricing: %s",
            exc,
        )
        return get_rule_based_pricing(total_kwp, battery_kwh, heat_pump_kw)
