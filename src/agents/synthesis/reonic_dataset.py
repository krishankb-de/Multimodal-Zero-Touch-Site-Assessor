"""
Reonic dataset loader and kNN retrieval.

Loads both Reonic sample directories under `Datasets/Project Data/`, joins
status-quo customer profiles with their installed-component line items, and
exposes a kNN retrieval over normalized customer features. Used by the
Synthesis Agent to ground component recommendations (brands, capacities)
in real expert designs — the project description's "Pioneer fine-tuned on
Reonic" requirement, satisfied as retrieval-augmented generation.
"""

from __future__ import annotations

import csv
import logging
import math
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from statistics import median

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "Datasets" / "Project Data"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CustomerProfile:
    """Feature vector used for kNN retrieval."""

    energy_demand_wh: float          # annual_kwh * 1000
    energy_price_per_wh: float       # tariff EUR/kWh / 1000
    has_ev: bool
    heating_existing_type: str       # "gas" | "oil" | "electric" | "lpg" | "district" | "none"
    house_size_sqm: float | None     # may be unknown — handled by feature scaler


@dataclass
class ReonicProject:
    """A single historical Reonic project — customer profile + installed parts."""

    project_id: str
    profile: CustomerProfile
    pv_kwp: float
    battery_kwh: float
    heatpump_kw: float
    panel_brand: str | None
    panel_name: str | None
    inverter_brand: str | None
    inverter_name: str | None
    battery_brand: str | None
    heatpump_brand: str | None
    heatpump_name: str | None


@dataclass
class NeighborSummary:
    """Aggregated view of the k nearest historical projects."""

    n_neighbors: int
    median_pv_kwp: float
    median_battery_kwh: float
    median_heatpump_kw: float
    top_panel_brand: str | None
    top_panel_name: str | None
    top_inverter_brand: str | None
    top_inverter_name: str | None
    top_battery_brand: str | None
    top_heatpump_brand: str | None
    top_heatpump_name: str | None
    project_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _to_float(s: str | None) -> float | None:
    if s is None or s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_bool(s: str | None) -> bool:
    return str(s).strip().lower() == "true"


def _normalize_heating(raw: str | None) -> str:
    if not raw:
        return "none"
    val = raw.strip().lower()
    if "gas" in val:
        return "gas"
    if "oil" in val:
        return "oil"
    if "electric" in val or "resistance" in val:
        return "electric"
    if "lpg" in val or "propane" in val:
        return "lpg"
    if "district" in val or "fern" in val:
        return "district"
    return "none"


def _load_status_quo(path: Path) -> dict[str, CustomerProfile]:
    """Read projects_status_quo.csv → {project_id: CustomerProfile}."""
    profiles: dict[str, CustomerProfile] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            pid = row.get("project_id", "").strip()
            if not pid:
                continue
            energy_demand_wh = _to_float(row.get("energy_demand_wh")) or 0.0
            energy_price_per_wh = _to_float(row.get("energy_price_per_wh")) or 0.0
            has_ev = _to_bool(row.get("has_ev"))
            heating_type = _normalize_heating(row.get("heating_existing_type"))
            house_size = _to_float(row.get("house_size_sqm"))
            if energy_demand_wh <= 0 or energy_price_per_wh <= 0:
                continue  # skip incomplete rows
            profiles[pid] = CustomerProfile(
                energy_demand_wh=energy_demand_wh,
                energy_price_per_wh=energy_price_per_wh,
                has_ev=has_ev,
                heating_existing_type=heating_type,
                house_size_sqm=house_size,
            )
    return profiles


def _load_parts(
    path: Path,
) -> dict[str, dict]:
    """Aggregate project_options_parts.csv into per-project installed totals."""
    by_project: dict[str, dict] = defaultdict(
        lambda: {
            "pv_kwp": 0.0,
            "battery_kwh": 0.0,
            "heatpump_kw": 0.0,
            "panel_brand": None,
            "panel_name": None,
            "inverter_brand": None,
            "inverter_name": None,
            "battery_brand": None,
            "heatpump_brand": None,
            "heatpump_name": None,
        }
    )
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            pid = (row.get("project_id") or "").strip()
            if not pid:
                continue
            comp_type = (row.get("component_type") or "").strip()
            comp_name = (row.get("component_name") or "").strip() or None
            brand = (row.get("component_brand") or "").strip() or None
            qty = _to_float(row.get("quantity")) or 0.0
            module_wp = _to_float(row.get("module_watt_peak"))
            battery_kwh = _to_float(row.get("battery_capacity_kwh"))
            hp_kw = _to_float(row.get("heatpump_nominal_power_kw"))

            agg = by_project[pid]
            if comp_type == "Module" and module_wp:
                agg["pv_kwp"] += (module_wp * qty) / 1000.0
                agg["panel_brand"] = agg["panel_brand"] or brand
                agg["panel_name"] = agg["panel_name"] or comp_name
            elif comp_type == "Inverter":
                agg["inverter_brand"] = agg["inverter_brand"] or brand
                agg["inverter_name"] = agg["inverter_name"] or comp_name
            elif comp_type == "Battery" and battery_kwh:
                agg["battery_kwh"] += battery_kwh * (qty or 1.0)
                agg["battery_brand"] = agg["battery_brand"] or brand
            elif comp_type == "Heatpump" and hp_kw:
                # heatpump_nominal_power_kw is in WATTS in the dataset (e.g. 10000.0)
                hp_kw_real = hp_kw / 1000.0 if hp_kw > 100 else hp_kw
                agg["heatpump_kw"] = max(agg["heatpump_kw"], hp_kw_real)
                agg["heatpump_brand"] = agg["heatpump_brand"] or brand
                agg["heatpump_name"] = agg["heatpump_name"] or comp_name
    return by_project


@lru_cache(maxsize=1)
def load_dataset(data_dir: str | None = None) -> list[ReonicProject]:
    """
    Load + join all Reonic sample directories.

    Returns a flat list of ReonicProject. Cached on first call.
    """
    root = Path(data_dir or os.getenv("REONIC_DATA_DIR") or DEFAULT_DATA_DIR)
    if not root.exists():
        logger.warning("Reonic data dir missing: %s — retrieval disabled", root)
        return []

    projects: list[ReonicProject] = []
    for sample_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        sq_path = sample_dir / "projects_status_quo.csv"
        parts_path = sample_dir / "project_options_parts.csv"
        if not (sq_path.exists() and parts_path.exists()):
            continue
        profiles = _load_status_quo(sq_path)
        parts = _load_parts(parts_path)
        for pid, profile in profiles.items():
            agg = parts.get(pid)
            if not agg:
                continue
            # Skip projects with no installed components at all
            if agg["pv_kwp"] == 0 and agg["battery_kwh"] == 0 and agg["heatpump_kw"] == 0:
                continue
            projects.append(
                ReonicProject(
                    project_id=pid,
                    profile=profile,
                    pv_kwp=round(agg["pv_kwp"], 2),
                    battery_kwh=round(agg["battery_kwh"], 2),
                    heatpump_kw=round(agg["heatpump_kw"], 2),
                    panel_brand=agg["panel_brand"],
                    panel_name=agg["panel_name"],
                    inverter_brand=agg["inverter_brand"],
                    inverter_name=agg["inverter_name"],
                    battery_brand=agg["battery_brand"],
                    heatpump_brand=agg["heatpump_brand"],
                    heatpump_name=agg["heatpump_name"],
                )
            )
    logger.info("Reonic dataset loaded: %d projects from %s", len(projects), root)
    return projects


# ---------------------------------------------------------------------------
# kNN retrieval
# ---------------------------------------------------------------------------


def _feature_vector(profile: CustomerProfile, house_size_default: float = 140.0) -> tuple[float, ...]:
    """Convert a CustomerProfile to a normalized feature vector for distance."""
    # Normalization scales chosen so each feature contributes O(1) to L2 distance
    return (
        math.log1p(profile.energy_demand_wh) / 16.0,           # ~ln(1e7) ≈ 16
        profile.energy_price_per_wh * 1000.0,                  # → EUR/kWh, O(0.1-1)
        1.0 if profile.has_ev else 0.0,
        (profile.house_size_sqm or house_size_default) / 200.0,
    )


def _heating_compatible(a: str, b: str) -> bool:
    """Heating type acts as a hard filter when both sides are known."""
    if a == "none" or b == "none":
        return True
    return a == b


def find_similar(
    profile: CustomerProfile,
    k: int = 5,
    data_dir: str | None = None,
) -> list[ReonicProject]:
    """Return the k nearest historical Reonic projects by L2 distance."""
    projects = load_dataset(data_dir)
    if not projects:
        return []

    target = _feature_vector(profile)

    def dist(p: ReonicProject) -> float:
        if not _heating_compatible(profile.heating_existing_type, p.profile.heating_existing_type):
            return math.inf
        v = _feature_vector(p.profile)
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(target, v)))

    ranked = sorted(projects, key=dist)
    return [p for p in ranked[:k] if not math.isinf(dist(p))]


def _mode_or_none(values: list[str | None]) -> str | None:
    """Most-common non-null value, or None."""
    filtered = [v for v in values if v]
    if not filtered:
        return None
    return Counter(filtered).most_common(1)[0][0]


def summarize_neighbors(neighbors: list[ReonicProject]) -> NeighborSummary | None:
    """Aggregate kNN results: median capacities + most-common brands."""
    if not neighbors:
        return None
    pv = [n.pv_kwp for n in neighbors if n.pv_kwp > 0]
    bat = [n.battery_kwh for n in neighbors if n.battery_kwh > 0]
    hp = [n.heatpump_kw for n in neighbors if n.heatpump_kw > 0]
    return NeighborSummary(
        n_neighbors=len(neighbors),
        median_pv_kwp=median(pv) if pv else 0.0,
        median_battery_kwh=median(bat) if bat else 0.0,
        median_heatpump_kw=median(hp) if hp else 0.0,
        top_panel_brand=_mode_or_none([n.panel_brand for n in neighbors]),
        top_panel_name=_mode_or_none([n.panel_name for n in neighbors]),
        top_inverter_brand=_mode_or_none([n.inverter_brand for n in neighbors]),
        top_inverter_name=_mode_or_none([n.inverter_name for n in neighbors]),
        top_battery_brand=_mode_or_none([n.battery_brand for n in neighbors]),
        top_heatpump_brand=_mode_or_none([n.heatpump_brand for n in neighbors]),
        top_heatpump_name=_mode_or_none([n.heatpump_name for n in neighbors]),
        project_ids=[n.project_id for n in neighbors],
    )


def retrieve_for_profile(
    profile: CustomerProfile,
    k: int = 5,
    data_dir: str | None = None,
) -> NeighborSummary | None:
    """One-shot helper: kNN + summarize."""
    return summarize_neighbors(find_similar(profile, k=k, data_dir=data_dir))
