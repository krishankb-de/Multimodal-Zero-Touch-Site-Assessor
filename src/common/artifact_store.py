"""Per-run artifact directory management."""

from __future__ import annotations

from pathlib import Path

_BASE = Path(__file__).resolve().parents[2] / "artifacts"


def run_dir(run_id: str) -> Path:
    d = _BASE / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def frames_dir(run_id: str) -> Path:
    d = run_dir(run_id) / "frames"
    d.mkdir(parents=True, exist_ok=True)
    return d


def mesh_path(run_id: str) -> Path:
    return run_dir(run_id) / "mesh.glb"


def point_cloud_path(run_id: str) -> Path:
    return run_dir(run_id) / "point_cloud.ply"


def reconstruction_json_path(run_id: str) -> Path:
    return run_dir(run_id) / "reconstruction.json"
