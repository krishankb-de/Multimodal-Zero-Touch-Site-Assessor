"""
GLB-grounded roof validator (E1).

Parses Datasets/Exp 3D-Modells/*.glb to cross-check Gemini-extracted
SpatialData against the 3D models.

Limitation: The GLBs use KHR_draco_mesh_compression, so vertex positions
(face areas / orientations) cannot be extracted without a native Draco
decoder. This module validates what is accessible from the GLTF JSON layer:
  - File existence and GLB format integrity
  - Primitive count vs. detected roof face count
  - CESIUM_RTC centre coordinates (sanity check for correct region)

A full geometry cross-check (area tolerance, azimuth tolerance) would
require adding the 'DracoPy' package and is left as a future enhancement.
"""

from __future__ import annotations

import json
import logging
import struct
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Maps region names (matching climate.py) to GLB filenames
REGION_GLB_MAP: dict[str, str] = {
    "Brandenburg": "3D_Modell Brandenburg.glb",
    "Hamburg": "3D_Modell Hamburg.glb",
    "North Germany": "3D_Modell North Germany.glb",
    "Ruhr": "3D_Modell Ruhr.glb",
}

# Default dataset directory (relative to repo root, resolved at runtime)
_DEFAULT_GLB_DIR = Path(__file__).resolve().parents[2] / "Datasets" / "Exp 3D-Modells"

# CESIUM_RTC centre sanity bounds (UTM Zone 32N — Germany)
_UTM32N_EASTING_BOUNDS = (280_000, 920_000)
_UTM32N_NORTHING_BOUNDS = (5_200_000, 6_100_000)


@dataclass
class GLBValidationIssue:
    code: str
    message: str
    severity: str = "warning"  # "error" | "warning"


@dataclass
class GLBValidationResult:
    valid: bool
    region: str
    glb_path: str
    primitive_count: int = 0
    gemini_face_count: int = 0
    issues: list[GLBValidationIssue] = field(default_factory=list)


def _parse_gltf_json(glb_bytes: bytes) -> dict:
    """Extract the GLTF JSON chunk from a GLB binary."""
    if len(glb_bytes) < 12 or glb_bytes[:4] != b"glTF":
        raise ValueError("Not a valid GLB file (bad magic)")
    version = struct.unpack_from("<I", glb_bytes, 4)[0]
    if version != 2:
        raise ValueError(f"Unsupported GLB version {version} (expected 2)")

    offset = 12
    while offset < len(glb_bytes):
        chunk_length = struct.unpack_from("<I", glb_bytes, offset)[0]
        chunk_type = struct.unpack_from("<I", glb_bytes, offset + 4)[0]
        chunk_data = glb_bytes[offset + 8 : offset + 8 + chunk_length]
        if chunk_type == 0x4E4F534A:  # JSON chunk
            return json.loads(chunk_data)
        offset += 8 + chunk_length
    raise ValueError("No JSON chunk found in GLB")


def validate_spatial_data_against_glb(
    gemini_face_count: int,
    gemini_total_area_m2: float,
    region: str,
    glb_dir: Path | None = None,
) -> GLBValidationResult:
    """
    Cross-check Gemini-extracted SpatialData against the regional 3D model.

    Args:
        gemini_face_count: Number of roof faces reported by Gemini.
        gemini_total_area_m2: Total usable roof area from SpatialData.
        region: Region string (must match a key in REGION_GLB_MAP).
        glb_dir: Override for the GLB dataset directory.

    Returns:
        GLBValidationResult with issues list.
    """
    glb_dir = glb_dir or _DEFAULT_GLB_DIR
    issues: list[GLBValidationIssue] = []

    # 1. Region lookup
    glb_filename = REGION_GLB_MAP.get(region)
    if glb_filename is None:
        return GLBValidationResult(
            valid=False,
            region=region,
            glb_path="",
            issues=[
                GLBValidationIssue(
                    code="UNKNOWN_REGION",
                    message=f"No GLB model for region '{region}'. "
                            f"Known regions: {list(REGION_GLB_MAP)}",
                    severity="error",
                )
            ],
        )

    glb_path = glb_dir / glb_filename

    # 2. File existence
    if not glb_path.exists():
        return GLBValidationResult(
            valid=False,
            region=region,
            glb_path=str(glb_path),
            issues=[
                GLBValidationIssue(
                    code="GLB_NOT_FOUND",
                    message=f"GLB file not found: {glb_path}",
                    severity="error",
                )
            ],
        )

    # 3. Parse GLTF JSON
    try:
        gltf = _parse_gltf_json(glb_path.read_bytes())
    except (ValueError, struct.error) as exc:
        return GLBValidationResult(
            valid=False,
            region=region,
            glb_path=str(glb_path),
            issues=[
                GLBValidationIssue(
                    code="GLB_PARSE_ERROR",
                    message=f"Failed to parse GLB: {exc}",
                    severity="error",
                )
            ],
        )

    # 4. Extract primitive count (each primitive = one roof surface material)
    primitive_count = sum(
        len(mesh.get("primitives", [])) for mesh in gltf.get("meshes", [])
    )
    logger.info(
        "GLB validator [%s]: %d primitives, Gemini reports %d faces, %.1f m² total",
        region, primitive_count, gemini_face_count, gemini_total_area_m2,
    )

    # 5. Sanity: Gemini shouldn't report more faces than GLB primitives
    if gemini_face_count > primitive_count:
        issues.append(
            GLBValidationIssue(
                code="FACE_COUNT_EXCEEDS_MODEL",
                message=(
                    f"Gemini reported {gemini_face_count} roof faces but the "
                    f"{region} 3D model has only {primitive_count} surface primitives"
                ),
                severity="warning",
            )
        )

    # 6. CESIUM_RTC centre check (coordinates must be within Germany UTM32N bounds)
    rtc = gltf.get("extensions", {}).get("CESIUM_RTC", {}).get("center", [])
    if len(rtc) >= 2:
        easting, northing = rtc[0], rtc[1]
        if not (_UTM32N_EASTING_BOUNDS[0] <= easting <= _UTM32N_EASTING_BOUNDS[1]):
            issues.append(
                GLBValidationIssue(
                    code="RTC_EASTING_OUT_OF_BOUNDS",
                    message=f"CESIUM_RTC easting {easting:.0f} outside Germany bounds "
                            f"{_UTM32N_EASTING_BOUNDS}",
                    severity="warning",
                )
            )
        if not (_UTM32N_NORTHING_BOUNDS[0] <= northing <= _UTM32N_NORTHING_BOUNDS[1]):
            issues.append(
                GLBValidationIssue(
                    code="RTC_NORTHING_OUT_OF_BOUNDS",
                    message=f"CESIUM_RTC northing {northing:.0f} outside Germany bounds "
                            f"{_UTM32N_NORTHING_BOUNDS}",
                    severity="warning",
                )
            )

    # Note: full geometry (area/orientation tolerance) requires Draco decoding.
    # KHR_draco_mesh_compression is used — add DracoPy for face-level validation.
    if "KHR_draco_mesh_compression" in gltf.get("extensionsUsed", []):
        logger.debug(
            "GLB validator [%s]: geometry is Draco-compressed — "
            "area/orientation cross-check skipped (add DracoPy for full validation)",
            region,
        )

    has_errors = any(i.severity == "error" for i in issues)
    return GLBValidationResult(
        valid=not has_errors,
        region=region,
        glb_path=str(glb_path),
        primitive_count=primitive_count,
        gemini_face_count=gemini_face_count,
        issues=issues,
    )
