"""
Sun-path shading simulation.

Computes a per-face monthly irradiance factor (0–1) given face tilt/azimuth and
obstacle silhouettes derived from the reconstructed mesh.

Uses a hand-rolled sun-position model (Spencer / Iqbal equations) equivalent to
pvlib's get_solarposition, with no external API calls required.

Output:
    monthly_irradiance_factor: dict mapping face_id → list[float] (len=12),
    where 1.0 = unshaded, 0.0 = fully shaded.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Hours of the day to sample (representative mid-day hours)
_SAMPLE_HOURS = [8, 9, 10, 11, 12, 13, 14, 15, 16]

# Representative day-of-year for each month (mid-month)
_MONTH_DOY = [15, 46, 75, 105, 135, 162, 198, 228, 258, 288, 318, 344]

# Average latitude for German regions (degrees North)
DEFAULT_LATITUDE_DEG = 52.5


@dataclass
class FaceSpec:
    face_id: str
    tilt_deg: float        # 0=horizontal, 90=vertical
    azimuth_deg: float     # 0=N, 90=E, 180=S, 270=W
    obstacle_area_m2: float = 0.0
    face_area_m2: float = 1.0


def _solar_declination(doy: int) -> float:
    """Spencer equation — solar declination in radians."""
    b = 2 * math.pi * (doy - 1) / 365
    return (0.006918 - 0.399912 * math.cos(b) + 0.070257 * math.sin(b)
            - 0.006758 * math.cos(2 * b) + 0.000907 * math.sin(2 * b)
            - 0.002697 * math.cos(3 * b) + 0.00148 * math.sin(3 * b))


def _hour_angle_rad(hour: float) -> float:
    """Hour angle in radians. Solar noon = 0."""
    return math.radians((hour - 12) * 15)


def _solar_elevation(lat_rad: float, decl_rad: float, hour_angle_rad: float) -> float:
    """Solar elevation angle in radians (negative = below horizon)."""
    sin_elev = (math.sin(lat_rad) * math.sin(decl_rad)
                + math.cos(lat_rad) * math.cos(decl_rad) * math.cos(hour_angle_rad))
    return math.asin(max(-1.0, min(1.0, sin_elev)))


def _solar_azimuth(lat_rad: float, decl_rad: float, elev_rad: float, hour_angle_rad: float) -> float:
    """
    Solar azimuth in radians from North (0=N, π/2=E, π=S, 3π/2=W).
    """
    cos_az = (math.sin(decl_rad) - math.sin(elev_rad) * math.sin(lat_rad)) / (
        math.cos(elev_rad) * math.cos(lat_rad) + 1e-12
    )
    az = math.acos(max(-1.0, min(1.0, cos_az)))
    if hour_angle_rad > 0:
        az = 2 * math.pi - az
    return az


def _angle_of_incidence(
    elev_rad: float,
    solar_az_rad: float,
    face_tilt_rad: float,
    face_az_rad: float,
) -> float:
    """
    Angle of incidence (radians) of sunlight on a tilted surface.
    Returns math.pi/2 when sun is below horizon (cos AOI ≤ 0).
    """
    cos_aoi = (
        math.sin(elev_rad) * math.cos(face_tilt_rad)
        + math.cos(elev_rad) * math.sin(face_tilt_rad) * math.cos(solar_az_rad - face_az_rad)
    )
    if cos_aoi <= 0:
        return math.pi / 2
    return math.acos(min(1.0, cos_aoi))


def _obstacle_shade_fraction(obstacle_area_m2: float, face_area_m2: float) -> float:
    """Simple ratio-based shade fraction from obstacle silhouette."""
    if face_area_m2 <= 0:
        return 0.0
    return min(1.0, obstacle_area_m2 / face_area_m2)


def compute_monthly_irradiance_factors(
    faces: list[FaceSpec],
    latitude_deg: float = DEFAULT_LATITUDE_DEG,
) -> dict[str, list[float]]:
    """
    Compute per-face monthly irradiance factor (0–1) for 12 months.

    Factor accounts for:
      - Face tilt and azimuth vs sun position (cosine of AOI)
      - Obstacle shading (simple silhouette fraction)

    Returns dict: face_id → [jan_factor, feb_factor, ..., dec_factor]
    """
    lat_rad = math.radians(latitude_deg)
    result: dict[str, list[float]] = {f.face_id: [] for f in faces}

    for month_idx, doy in enumerate(_MONTH_DOY):
        decl = _solar_declination(doy)

        for face in faces:
            face_tilt_rad = math.radians(face.tilt_deg)
            # Convert azimuth: our convention is 0=N,90=E,180=S; convert to radians
            # Solar azimuth from _solar_azimuth is also 0=N convention
            face_az_rad = math.radians(face.azimuth_deg)
            obs_shade = _obstacle_shade_fraction(face.obstacle_area_m2, face.face_area_m2)

            irr_sum = 0.0
            weight_sum = 0.0

            for hour in _SAMPLE_HOURS:
                ha = _hour_angle_rad(float(hour))
                elev = _solar_elevation(lat_rad, decl, ha)
                if elev <= 0:
                    continue
                sol_az = _solar_azimuth(lat_rad, decl, elev, ha)
                aoi = _angle_of_incidence(elev, sol_az, face_tilt_rad, face_az_rad)
                cos_aoi = math.cos(aoi)
                if cos_aoi <= 0:
                    continue
                # Weight by elevation (proxy for beam irradiance)
                w = math.sin(elev)
                irr_sum += cos_aoi * w * (1.0 - obs_shade)
                weight_sum += w

            if weight_sum > 0:
                factor = irr_sum / weight_sum
            else:
                factor = 0.0

            result[face.face_id].append(round(min(1.0, max(0.0, factor)), 4))

    return result


def annual_shading_factor(monthly_factors: list[float]) -> float:
    """Return the simple mean of monthly irradiance factors."""
    if not monthly_factors:
        return 1.0
    return sum(monthly_factors) / len(monthly_factors)
