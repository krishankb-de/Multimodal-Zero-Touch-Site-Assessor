"""
Single-Line Diagram (SLD) generator (E2).

Produces a text-format SLD from a FinalProposal and returns its content.
The SLD reference path is stored in compliance.single_line_diagram_ref.

Diagram topology (left to right):
  Grid → Main Meter → Consumer DB
                    ↓
              [Inverter] ← [PV Array]
                    ↓
              [Battery] (if included)
                    ↓
              [Heat Pump] (if included)
                    ↓
              [EV Charger] (if included)
"""

from __future__ import annotations

from pathlib import Path

from src.common.schemas import FinalProposal


def generate_sld(proposal: FinalProposal) -> str:
    """
    Generate an ASCII single-line diagram for the proposal.

    Returns:
        Multi-line string containing the diagram.
    """
    pv = proposal.system_design.pv
    battery = proposal.system_design.battery
    heat_pump = proposal.system_design.heat_pump
    ev_charger = proposal.system_design.ev_charger

    lines: list[str] = []

    lines.append("=" * 60)
    lines.append("  SINGLE-LINE DIAGRAM — Zero-Touch Site Assessor")
    lines.append(f"  Pipeline Run: {proposal.metadata.pipeline_run_id}")
    lines.append("=" * 60)
    lines.append("")

    # PV Array
    pv_label = f"PV Array: {pv.total_kwp:.1f} kWp / {pv.panel_count} panels"
    if pv.panel_model:
        pv_label += f" ({pv.panel_model})"
    lines.append(f"  [{pv_label}]")
    lines.append("         |")
    lines.append("         | DC")
    lines.append("         ↓")

    # Inverter
    inv_label = f"Inverter ({pv.inverter_type})"
    if pv.inverter_model:
        inv_label += f" — {pv.inverter_model}"
    lines.append(f"  [{inv_label}]")
    lines.append("         |")
    lines.append("         | AC")
    lines.append("         ↓")

    # Battery (if included)
    if battery and battery.included:
        bat_label = f"Battery: {battery.capacity_kwh:.1f} kWh"
        if battery.model:
            bat_label += f" ({battery.model})"
        lines.append(f"  ├── [{bat_label}]")
        lines.append("  |")

    # Main AC bus
    lines.append("  [Main AC Bus / Consumer Distribution Board]")
    lines.append("         |")

    # Grid connection
    lines.append("         | ←→ Grid (bi-directional metering)")
    lines.append("         ↓")
    lines.append("  [Smart Meter / Main Meter]")
    lines.append("         |")
    lines.append("  [Grid]")
    lines.append("")

    # Heat pump branch
    if heat_pump and heat_pump.included:
        hp_label = f"Heat Pump: {heat_pump.capacity_kw:.0f} kW {heat_pump.type}"
        if heat_pump.model:
            hp_label += f" ({heat_pump.model})"
        lines.append(f"  Branch A: [{hp_label}]")
        dhw = f"  Branch B: [DHW Cylinder: {heat_pump.cylinder_litres} L]" if heat_pump.cylinder_litres else ""
        if dhw:
            lines.append(dhw)

    # EV charger branch
    if ev_charger and ev_charger.included:
        ev_label = f"EV Charger: {ev_charger.capacity_kw:.1f} kW"
        lines.append(f"  Branch C: [{ev_label}]")

    lines.append("")
    lines.append("=" * 60)
    lines.append("  NOTES")
    lines.append("=" * 60)

    for note in proposal.compliance.regulatory_notes:
        lines.append(f"  • {note}")
    for upgrade in proposal.compliance.electrical_upgrades:
        lines.append(f"  ⚡ Electrical upgrade required: {upgrade}")

    lines.append("")
    lines.append(f"  Human sign-off: {proposal.human_signoff.status.value.upper()}")
    if proposal.human_signoff.installer_id:
        lines.append(f"  Installer: {proposal.human_signoff.installer_id}")

    lines.append("=" * 60)

    return "\n".join(lines)


def write_sld(proposal: FinalProposal, output_dir: Path) -> Path:
    """
    Generate the SLD and write it to output_dir/{pipeline_run_id}.sld.txt.

    Returns:
        Path to the written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = proposal.metadata.pipeline_run_id
    out_path = output_dir / f"{run_id}.sld.txt"
    out_path.write_text(generate_sld(proposal), encoding="utf-8")
    return out_path
