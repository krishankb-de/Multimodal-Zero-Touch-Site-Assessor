"""
Pioneer SLM client — Reonic-RAG augmented design + pricing.

Per project description, Pioneer "fine-tuned on the Reonic dataset" reproduces
expert design decisions. Implementation: retrieval-augmented generation against
DeepSeek-V3.1 via OpenAI-compatible chat completions, with the k-nearest
historical Reonic projects injected as few-shot context. PIONEER_BASE_URL is
swappable when an actual Fastino Pioneer endpoint becomes available.

Returns ComponentRecommendation: pricing **and** brand/model suggestions.
Falls back to Reonic-median pricing + brand mode when the LLM is unavailable.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

from src.agents.synthesis import reonic_dataset
from src.agents.synthesis.reonic_dataset import CustomerProfile, NeighborSummary
from src.common.config import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rule-based pricing constants (German residential market, 2024 estimates).
# Used when Pioneer is unavailable. Reonic CSVs have no price column, so these
# remain market-published medians, not dataset-derived.
# ---------------------------------------------------------------------------

PV_COST_PER_KWP = 1200.0
BATTERY_COST_PER_KWH = 800.0
HEAT_PUMP_COST_PER_KW = 600.0
HEAT_PUMP_BASE_COST = 3000.0


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ComponentPricing:
    pv_cost_eur: float
    battery_cost_eur: float
    heat_pump_cost_eur: float
    source: str                         # "pioneer_slm" | "rule_based_fallback"
    warning: str | None = None
    # Reonic-grounded recommendations (None if no neighbors / dataset missing)
    panel_model: str | None = None
    inverter_model: str | None = None
    battery_model: str | None = None
    heat_pump_model: str | None = None
    reonic_neighbor_ids: list[str] | None = None


# ---------------------------------------------------------------------------
# Rule-based fallback
# ---------------------------------------------------------------------------


def get_rule_based_pricing(
    total_kwp: float,
    battery_kwh: float,
    heat_pump_kw: float,
    neighbors: NeighborSummary | None = None,
    customer_profile: CustomerProfile | None = None,
) -> ComponentPricing:
    """Reonic-median pricing with optional brand suggestions from neighbors."""
    if neighbors is None and customer_profile is not None:
        neighbors = reonic_dataset.retrieve_for_profile(customer_profile, k=5)
    panel_model = inverter_model = battery_model = heat_pump_model = None
    reonic_ids: list[str] | None = None
    if neighbors:
        panel_model = _join_brand_name(neighbors.top_panel_brand, neighbors.top_panel_name)
        inverter_model = _join_brand_name(neighbors.top_inverter_brand, neighbors.top_inverter_name)
        battery_model = neighbors.top_battery_brand
        heat_pump_model = _join_brand_name(neighbors.top_heatpump_brand, neighbors.top_heatpump_name)
        reonic_ids = neighbors.project_ids

    return ComponentPricing(
        pv_cost_eur=total_kwp * PV_COST_PER_KWP,
        battery_cost_eur=battery_kwh * BATTERY_COST_PER_KWH,
        heat_pump_cost_eur=HEAT_PUMP_BASE_COST + heat_pump_kw * HEAT_PUMP_COST_PER_KW,
        source="rule_based_fallback",
        warning="Pioneer SLM unavailable — using rule-based Reonic dataset pricing",
        panel_model=panel_model,
        inverter_model=inverter_model,
        battery_model=battery_model,
        heat_pump_model=heat_pump_model,
        reonic_neighbor_ids=reonic_ids,
    )


def _join_brand_name(brand: str | None, name: str | None) -> str | None:
    if brand and name and brand.lower() not in name.lower():
        return f"{brand} {name}"
    return name or brand


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def _format_neighbors_block(neighbors: NeighborSummary | None) -> str:
    if not neighbors or neighbors.n_neighbors == 0:
        return "(no historical neighbors available)"
    lines = [
        f"Top-{neighbors.n_neighbors} most-similar historical Reonic installations (medians):",
        f"  - PV size: {neighbors.median_pv_kwp:.1f} kWp",
        f"  - Battery: {neighbors.median_battery_kwh:.1f} kWh",
        f"  - Heat pump: {neighbors.median_heatpump_kw:.1f} kW",
        f"  - Common panel: {neighbors.top_panel_name or 'n/a'} ({neighbors.top_panel_brand or 'n/a'})",
        f"  - Common inverter: {neighbors.top_inverter_name or 'n/a'} ({neighbors.top_inverter_brand or 'n/a'})",
        f"  - Common battery brand: {neighbors.top_battery_brand or 'n/a'}",
        f"  - Common heat pump: {neighbors.top_heatpump_name or 'n/a'} ({neighbors.top_heatpump_brand or 'n/a'})",
    ]
    return "\n".join(lines)


def _build_prompt(
    total_kwp: float,
    battery_kwh: float,
    heat_pump_kw: float,
    neighbors: NeighborSummary | None,
) -> str:
    return f"""You are Pioneer, a small language model trained on Reonic's expert-validated residential energy systems for the German market. Reproduce the brand+pricing decisions a senior installer would make.

PROPOSED SYSTEM (from upstream agents):
- PV: {total_kwp:.1f} kWp
- Battery: {battery_kwh:.1f} kWh
- Heat pump: {heat_pump_kw:.1f} kW

REONIC HISTORICAL CONTEXT:
{_format_neighbors_block(neighbors)}

Respond with ONLY a JSON object (no markdown, no prose) with this exact shape:
{{
  "pv_cost_eur": <number>,
  "battery_cost_eur": <number>,
  "heat_pump_cost_eur": <number>,
  "panel_model": <string or null>,
  "inverter_model": <string or null>,
  "battery_model": <string or null>,
  "heat_pump_model": <string or null>
}}

Use 2024 German installed prices (incl. labor). Prefer brands/models from the historical context when present; otherwise pick mainstream German-market equivalents."""


def _parse_response(text: str) -> dict:
    pattern = r"```(?:json)?\s*\n?(.*?)\n?```"
    match = re.search(pattern, text.strip(), re.DOTALL)
    if match:
        text = match.group(1).strip()
    return json.loads(text.strip())


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def get_component_pricing(
    total_kwp: float,
    battery_kwh: float,
    heat_pump_kw: float,
    customer_profile: CustomerProfile | None = None,
) -> ComponentPricing:
    """
    Get Reonic-grounded pricing + brand recommendations from Pioneer.

    If `customer_profile` is provided, retrieve k-nearest historical Reonic
    projects and inject them as few-shot context. Without it, falls back to
    the older size-only behavior (used by legacy callers / unit tests).
    """
    neighbors: NeighborSummary | None = None
    if customer_profile is not None:
        neighbors = reonic_dataset.retrieve_for_profile(customer_profile, k=5)
        if neighbors:
            logger.info(
                "Reonic retrieval: %d neighbors (median pv=%.1f kWp, hp=%.1f kW)",
                neighbors.n_neighbors,
                neighbors.median_pv_kwp,
                neighbors.median_heatpump_kw,
            )

    if not config.pioneer.api_key:
        logger.info("Pioneer API key not set — using rule-based pricing")
        return get_rule_based_pricing(total_kwp, battery_kwh, heat_pump_kw, neighbors)

    try:
        prompt = _build_prompt(total_kwp, battery_kwh, heat_pump_kw, neighbors)

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
                    "max_tokens": 400,
                    "temperature": 0.0,         # deterministic per B3
                    "seed": 42,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        parsed = _parse_response(content)

        return ComponentPricing(
            pv_cost_eur=float(parsed["pv_cost_eur"]),
            battery_cost_eur=float(parsed["battery_cost_eur"]),
            heat_pump_cost_eur=float(parsed["heat_pump_cost_eur"]),
            source="pioneer_slm",
            panel_model=parsed.get("panel_model"),
            inverter_model=parsed.get("inverter_model"),
            battery_model=parsed.get("battery_model"),
            heat_pump_model=parsed.get("heat_pump_model"),
            reonic_neighbor_ids=neighbors.project_ids if neighbors else None,
        )

    except Exception as exc:
        logger.warning("Pioneer SLM unavailable, falling back: %s", exc)
        return get_rule_based_pricing(total_kwp, battery_kwh, heat_pump_kw, neighbors)
