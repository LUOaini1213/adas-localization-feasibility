"""Sensor coverage model, target-class factors and the parametric rain-degradation factor.

A sensor is a set of range lobes (range_m, half_angle_deg) around a boresight, mounted at (x, y) in the
vehicle frame (origin: front bumper centre, x forward, y left).  A point is covered when its bearing
relative to the boresight lies inside a lobe and its distance is within that lobe's effective range.

Rain model (the only physics-based part is the radar path attenuation):
  radar  : ITU-R P.838-3 specific attenuation gamma = k * R^alpha [dB/km], Table 5 at 77 GHz,
           horizontal polarisation k = 1.1320, alpha = 0.7177.  Two-way path loss plus an optional
           radome/bumper water-film loss (assumption A-12) enter the radar equation (range^4):
               R_eff = R_clear * 10^(-(2*gamma*R_eff/1000 + L_film)/40)      (solved by iteration)
  lidar  : two-way extinction, lidar equation (range^2):  R_eff = R_clear * exp(-sigma * R_eff),
           sigma = 0.19 * R^0.6 [1/km]  -- assumption A-13 (chosen so that 25 mm/h costs ~20 % at 210 m)
  camera : R_eff = R_clear / (1 + R/100)  -- assumption A-14 (no physical model; wipers, spray, night ignored)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

# ITU-R P.838-3 (2005) Table 5, f = 77 GHz
ITU_77GHZ = {"kH": 1.1320, "aH": 0.7177, "kV": 1.1276, "aV": 0.7073}

SENSOR_ASSUMPTIONS = {
    "A-12": "雷达罩/保险杠水膜附加双程损耗 L_film：基线 0 dB，敏感性 3 dB",
    "A-13": "激光雷达雨中消光系数 σ = 0.19·R^0.6 km⁻¹（为使 25 mm/h 时 210 m 量程损失约 20 % 而取，无引用来源）",
    "A-14": "摄像头雨中有效距离 = 晴天距离 / (1 + R/100)（纯假设，未计雨刮、水雾、夜间）",
    "A-15": "摩托车相对轿车的探测距离系数：雷达 0.7（RCS 小，距离 ∝ RCS^(1/4)）、摄像头 0.8、激光雷达 0.85",
}

TARGET_FACTOR = {"car": {"radar": 1.0, "camera": 1.0, "lidar": 1.0},
                 "motorcycle": {"radar": 0.7, "camera": 0.8, "lidar": 0.85}}
LIDAR_SIGMA_A = 0.19
LIDAR_SIGMA_B = 0.6
CAMERA_HALF_RAIN = 100.0


def rain_gamma_db_per_km(rain_mmph: float, pol: str = "H") -> float:
    k, a = ITU_77GHZ["k" + pol], ITU_77GHZ["a" + pol]
    return k * rain_mmph ** a if rain_mmph > 0 else 0.0


def radar_range_in_rain(r_clear_m: float, rain_mmph: float, film_loss_db: float = 0.0) -> float:
    g = rain_gamma_db_per_km(rain_mmph)
    r = r_clear_m
    for _ in range(200):
        r_new = r_clear_m * 10 ** (-(2.0 * g * r / 1000.0 + film_loss_db) / 40.0)
        if abs(r_new - r) < 1e-6:
            break
        r = r_new
    return r


def lidar_range_in_rain(r_clear_m: float, rain_mmph: float) -> float:
    sigma = LIDAR_SIGMA_A * rain_mmph ** LIDAR_SIGMA_B / 1000.0 if rain_mmph > 0 else 0.0
    r = r_clear_m
    for _ in range(200):
        r_new = r_clear_m * math.exp(-sigma * r)
        if abs(r_new - r) < 1e-6:
            break
        r = r_new
    return r


def camera_range_in_rain(r_clear_m: float, rain_mmph: float) -> float:
    return r_clear_m / (1.0 + max(0.0, rain_mmph) / CAMERA_HALF_RAIN)


@lru_cache(maxsize=None)
def effective_range(modality: str, r_clear_m: float, rain_mmph: float = 0.0, film_loss_db: float = 0.0,
                    target: str = "car") -> float:
    r = r_clear_m * TARGET_FACTOR[target][modality]
    if modality == "radar":
        return radar_range_in_rain(r, rain_mmph, film_loss_db)
    if modality == "lidar":
        return lidar_range_in_rain(r, rain_mmph)
    if modality == "camera":
        return camera_range_in_rain(r, rain_mmph)
    raise ValueError(modality)


@dataclass(frozen=True)
class Sensor:
    name: str
    modality: str                 # "radar" | "camera" | "lidar"
    x: float
    y: float
    boresight_deg: float
    lobes: tuple                  # ((range_m, half_angle_deg), ...)
    source: str                   # citation id (S-xx) or assumption id (A-xx)

    def bearing(self, px: float, py: float) -> tuple[float, float]:
        dx, dy = px - self.x, py - self.y
        rel = math.degrees(math.atan2(dy, dx)) - self.boresight_deg
        rel = (rel + 180.0) % 360.0 - 180.0
        return math.hypot(dx, dy), rel

    def available_range(self, px: float, py: float, rain_mmph: float = 0.0, film_loss_db: float = 0.0,
                        target: str = "car") -> tuple[float, float]:
        """(effective range available along the bearing of the point, distance to the point)."""
        dist, rel = self.bearing(px, py)
        best = 0.0
        for r_lobe, half in self.lobes:
            if abs(rel) <= half + 1e-9:
                best = max(best, effective_range(self.modality, r_lobe, rain_mmph, film_loss_db, target))
        return best, dist
