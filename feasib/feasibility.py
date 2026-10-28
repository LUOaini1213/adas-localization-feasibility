"""Check every requirement against every reference suite, in clear weather and in rain."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from . import requirements as rq
from .sensors import effective_range
from .suites import Suite, reference_suites

CONDITIONS = {            # name -> (rain mm/h, film loss dB)
    "晴天": (0.0, 0.0),
    "暴雨 50 mm/h": (50.0, 0.0),
    "暴雨 50 mm/h + 水膜 3 dB": (50.0, 3.0),
}
RAIN_SWEEP_MMPH = (0.0, 10.0, 25.0, 50.0, 100.0)
AEB_FUNCS = ("AEB", "AEB 摩托车")


@dataclass
class Check:
    rid: str
    suite: str
    condition: str
    required: float          # metres: required range, or distance from the bumper to the FOV point
    covered: bool
    margin_m: float          # worst point: best available range minus distance to the point
    sensors: str             # sensors that cover at least one point
    modalities: str          # modalities that cover every point
    redundancy: int
    latency_budget_s: float | None = None   # AEB only: largest total latency the suite's reach allows


def _aeb_params(req: rq.Requirement, rain_mmph: float) -> tuple[float, float, float, float]:
    """(v_ego, v_target, decel, fcw_lead) of an AEB requirement; wet deceleration in rain (A-04)."""
    v = req.detail["v"]
    v_t = rq.NCAP_CCRM_TOP[1] if req.rid == "AEB-4" else 0.0
    fcw = 0.0 if req.rid == "AEB-2" else rq.R152_FCW_LEAD_S
    decel = req.detail.get("decel", rq.AEB_DECEL_DRY)
    if rain_mmph > 0:
        decel = min(decel, rq.AEB_DECEL_WET)
    return v, v_t, decel, fcw


def requirement_in_condition(req: rq.Requirement, rain_mmph: float) -> rq.Requirement:
    if rain_mmph <= 0 or req.function not in AEB_FUNCS:
        return req
    v, v_t, decel, fcw = _aeb_params(req, rain_mmph)
    d = rq.aeb_required_range(v, v_t, decel=decel, fcw_lead_s=fcw)
    (_, y), = req.points
    return replace(req, points=((d, y),), required_m=d, detail={**req.detail, "decel": decel})


def _groups(req: rq.Requirement) -> list[list[tuple[float, float]]]:
    """Point groups: every group must be covered; inside a group one point is enough when
    req.any_point (extended target), otherwise each point is its own group."""
    sides = [list(req.points)]
    if req.both_sides:
        sides.append([(x, -y) for x, y in req.points])
    if req.any_point:
        return sides
    return [[p] for side in sides for p in side]


def _cover_info(suite: Suite, px: float, py: float, rain: float, film: float, target: str):
    best, names, mods = None, [], set()
    for s in suite.sensors:
        avail, dist = s.available_range(px, py, rain, film, target)
        if avail <= 0:
            continue                                  # point outside every lobe of this sensor
        m = avail - dist
        best = m if best is None else max(best, m)
        if m >= 0:
            names.append(s.name)
            mods.add(s.modality)
    return best, names, mods


def check(req: rq.Requirement, suite: Suite, condition: str) -> Check:
    rain, film = CONDITIONS[condition]
    req = requirement_in_condition(req, rain)
    infos = []
    for group in _groups(req):                      # best point of each group, then worst group
        parts = [_cover_info(suite, px, py, rain, film, req.target) for px, py in group]
        valid = [p for p in parts if p[0] is not None]
        if not valid:
            infos.append((None, [], set()))
            continue
        best = max(p[0] for p in valid)
        names = sorted(set().union(*[set(p[1]) for p in valid]))
        mods = set().union(*[p[2] for p in valid])
        infos.append((best, names, mods))
    margins = [b for b, _, _ in infos]
    worst = None if any(b is None for b in margins) else min(margins)
    common = set.intersection(*[m for _, _, m in infos])
    names = sorted(set().union(*[set(n) for _, n, _ in infos]))
    out = Check(req.rid, suite.sid, condition, round(req.required_m, 1), worst is not None and worst >= 0,
                round(worst, 1) if worst is not None else float("nan"), "、".join(names),
                "+".join(sorted(common)), len(common))
    if req.function in AEB_FUNCS:
        out.latency_budget_s = round(latency_budget(req, suite, rain, film), 2)
    return out


def max_forward_reach(req: rq.Requirement, suite: Suite, rain: float, film: float) -> float:
    """Largest distance d ahead of the front bumper at which (d, y) is covered (analytic per lobe)."""
    (_, y), = req.points
    best = 0.0
    for s in suite.sensors:
        dy = y - s.y
        for r_lobe, half in s.lobes:
            r = effective_range(s.modality, r_lobe, rain, film, req.target)
            if r <= abs(dy):
                continue
            dx = math.sqrt(r * r - dy * dy)          # far end of the lobe on the line y = const
            rel = math.degrees(math.atan2(dy, dx)) - s.boresight_deg
            rel = (rel + 180.0) % 360.0 - 180.0
            if abs(rel) <= half:
                best = max(best, s.x + dx)
    return best


def latency_budget(req: rq.Requirement, suite: Suite, rain: float, film: float) -> float:
    v, v_t, decel, fcw = _aeb_params(req, rain)
    return rq.aeb_latency_budget(max_forward_reach(req, suite, rain, film), v, v_t, decel=decel, fcw_lead_s=fcw)


def run_all() -> list[Check]:
    return [check(req, suite, cond) for req in rq.requirement_list() for suite in reference_suites()
            for cond in CONDITIONS]


def rain_sweep() -> list[dict]:
    """Effective range of each sensor class vs rain rate (car target)."""
    classes = [("前向雷达远波瓣", "radar", 200.0, 0.0), ("前向雷达远波瓣（水膜 3 dB）", "radar", 200.0, 3.0),
               ("角雷达远波瓣", "radar", 80.0, 0.0), ("激光雷达 AT128", "lidar", 210.0, 0.0),
               ("前视摄像头中心", "camera", 150.0, 0.0)]
    rows = []
    for name, mod, r0, film in classes:
        row = {"传感器": name, "晴天量程 m": r0}
        for r in RAIN_SWEEP_MMPH:
            row[f"{r:g} mm/h"] = round(effective_range(mod, r0, r, film), 1)
        rows.append(row)
    return rows
