"""Function requirements -> required detection range, field of view and latency budget.

Every regulatory number carries its clause.  Every other number is a project assumption with an id
"A-xx"; the assumption register is ASSUMPTIONS below and is printed into results/tables.md.

Vehicle frame (ISO 8855 style): origin at the centre of the front bumper, x forward, y to the left.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

KPH = 1.0 / 3.6

# ----------------------------------------------------------------------------- regulatory constants
# UN R171 (OJ L 2024/2689, 00 series), 6.2.4.1: an approaching vehicle in the target lane must not be
# forced to decelerate by more than 3 m/s2, A seconds after the lane change manoeuvre starts, and the
# distance between the vehicles must never be less than the distance the DCAS vehicle travels in 1 s.
# A = 0.4 s if the full width of the approaching vehicle was detected for >= 1.0 s before the
# manoeuvre started, otherwise A = 1.4 s.
R171_APPROACH_DECEL_MPS2 = 3.0
R171_A_TRACKED_S = 0.4
R171_A_UNTRACKED_S = 1.4
R171_GAP_TIME_S = 1.0
# 6.2.4.2: if no vehicle is detected, assume one at the actual rearward detection range travelling at
# the allowed maximum speed or 130 km/h, whichever is lower.  6.2.9.1.2 (driver-confirmed lane
# change): allowed maximum speed + 10 % or 130 km/h, whichever is lower.
R171_VAPP_CAP_KPH = 130.0
R171_DRIVER_CONFIRMED_FACTOR = 1.10
# UN R79 (OJ L 2018/1947, 03 series), 5.6.4.7 critical distance
#   S_critical = (v_rear - v_ACSF) * tB + (v_rear - v_ACSF)^2 / (2 a) + v_ACSF * tG,
# a = 3 m/s2, tB = 0.4 s, tG = 1 s; 5.6.4.8.1: declared rear detection range S_rear >= 55 m,
# v_app = 36.1 m/s (130 km/h) for M1/N1.
R79_A_MPS2 = 3.0
R79_TB_S = 0.4
R79_TG_S = 1.0
R79_VAPP_MPS = 36.1
R79_SREAR_MIN_M = 55.0
# UN R152 (OJ L 2024/2497, 02 series Suppl. 3): 5.2.1.1 collision warning at least 0.8 s before the
# emergency braking phase; 5.2.1.2 braking demand >= 5.0 m/s2; 5.2.1.3 active at least 10-60 km/h.
R152_FCW_LEAD_S = 0.8
R152_DECEL_MIN_MPS2 = 5.0
R152_V_MAX_KPH = 60.0
# Euro NCAP Crash Avoidance - Frontal Collisions v1.2 (2026-07) 3.1.1.1, as used in P5:
# CCRs VUT 10-80 km/h (AEB <= 50 km/h, FCW 60-80 km/h); CCRm VUT up to 130 km/h with target 70 km/h.
NCAP_CCRS_AEB_MAX_KPH = 50.0
NCAP_CCRS_FCW_MAX_KPH = 80.0
NCAP_CCRM_TOP = (130.0, 70.0)
# ASEAN NCAP Motorcyclist Safety v2.0, 7 / Table 5: AEB CM points up to 60 km/h, FCW points up to 80 km/h.
ASEAN_CM_AEB_MAX_KPH = 60.0
# ASEAN NCAP Motorcyclist Safety v2.0, 3.4.1 Table 1: blind-spot motorcycle at 2-3 m lateral distance
# must be detected, at 6.0 m it must not be detected.
ASEAN_BST_LATERAL_DETECT_M = (2.0, 3.0)
# The Highway Code (GB), rule 124: 70 mph on motorways and dual carriageways for cars;
# rule 126: "at least a two-second gap" on high-speed roads, "at least doubled on wet roads".
GB_MOTORWAY_LIMIT_KPH = 70 * 1.609344
GB_MIN_GAP_S = 2.0

# ----------------------------------------------------------------------------- project assumptions
ASSUMPTIONS: dict[str, str] = {
    "A-01": "整车长 4.7 m、宽 1.85 m；目标车宽 1.8 m；车道宽 3.5 m",
    "A-02": "感知时延 t_sense = 0.15 s（传感器周期 + 处理），目标确认 t_confirm = 0.2 s",
    "A-03": "制动执行等效时延 t_act = 0.20 s（取 P5 执行器模型：80 ms 纯延迟 + τ 0.12 s）",
    "A-04": "AEB 设计减速度 6.0 m/s²（干路）；湿路 5.0 m/s²（P5 附着模型 min(9, 10μ)，μ = 0.5）",
    "A-05": "ACC 舒适减速度 2.0 m/s²（另算 3.5 m/s²），ACC 总时延 0.5 s，ACC 时距 1.8 s，停车间距 5 m",
    "A-06": "AEB 停车余量 2.0 m",
    "A-07": "切入目标居中行驶于相邻车道，近侧边缘距本车中线 2.6 m；横向速度 1.0 m/s",
    "A-08": "摩托车穿行（filtering）时近侧边缘距本车中线 1.35 m",
    "A-09": "城市拥堵中摩托车从后方穿行：本车 30 km/h、摩托车 60 km/h（东盟场景，无官方数据）",
    "A-10": "盲区摩托车（长 2.0 m）位置：中心在后保险杠前 0.5 m 或后 2.0 m；横向 2 m / 3 m 按距本车中线取"
            "（较严的读法；ASEAN NCAP Table 1 的横向距离口径与 ISO 17387 区域定义均未核实）；车身任一点被看到即算检出",
    "A-11": "CMRm 摩托车目标车速取 0（保守；规程中 CMRm 的目标车速未核实）；25 % 重叠时摩托车中线距本车中线 0.46 m",
}

T_SENSE_S = 0.15
T_CONFIRM_S = 0.20
T_ACT_S = 0.20
AEB_DECEL_DRY = 6.0
AEB_DECEL_WET = 5.0
AEB_MARGIN_M = 2.0
ACC_DECEL_COMFORT = 2.0
ACC_DECEL_FIRM = 3.5
ACC_LATENCY_S = 0.5
ACC_TIME_GAP_S = 1.8
ACC_STOP_GAP_M = 5.0
VEH_LENGTH_M = 4.7
VEH_WIDTH_M = 1.85
TARGET_WIDTH_M = 1.8
LANE_WIDTH_M = 3.5
CUTIN_LAT_SPEED_MPS = 1.0
MC_FILTER_EDGE_M = 1.35
CMRM_25PCT_OFFSET_M = 0.25 * VEH_WIDTH_M


# ----------------------------------------------------------------------------- formulas
def braking_distance(v_rel_mps: float, decel_mps2: float) -> float:
    return v_rel_mps * v_rel_mps / (2.0 * decel_mps2)


def aeb_required_range(v_ego_kph: float, v_target_kph: float = 0.0, decel: float = AEB_DECEL_DRY,
                       fcw_lead_s: float = 0.0, t_sense: float = T_SENSE_S, t_confirm: float = T_CONFIRM_S,
                       t_act: float = T_ACT_S, margin_m: float = AEB_MARGIN_M) -> float:
    """Range at which a confirmed track must exist so that (warning lead +) braking removes the
    closing speed before contact.  Target assumed to keep its speed."""
    v_rel = max(0.0, (v_ego_kph - v_target_kph) * KPH)
    return v_rel * (t_sense + t_confirm + fcw_lead_s + t_act) + braking_distance(v_rel, decel) + margin_m


def aeb_latency_budget(range_m: float, v_ego_kph: float, v_target_kph: float = 0.0,
                       decel: float = AEB_DECEL_DRY, fcw_lead_s: float = 0.0,
                       margin_m: float = AEB_MARGIN_M) -> float:
    """Largest total latency (sense + confirm + actuation) that a given detection range allows."""
    v_rel = max(1e-9, (v_ego_kph - v_target_kph) * KPH)
    return (range_m - braking_distance(v_rel, decel) - margin_m) / v_rel - fcw_lead_s


def acc_required_range(v_ego_kph: float, v_lead_kph: float, decel: float = ACC_DECEL_COMFORT,
                       latency_s: float = ACC_LATENCY_S, time_gap_s: float = ACC_TIME_GAP_S,
                       stop_gap_m: float = ACC_STOP_GAP_M) -> float:
    """Detect a slower (or stopped) lead early enough to slow down at a comfortable deceleration and
    end at the set time gap (or the stopping gap for a stopped lead)."""
    v_rel = max(0.0, (v_ego_kph - v_lead_kph) * KPH)
    final_gap = max(v_lead_kph * KPH * time_gap_s, stop_gap_m)
    return v_rel * latency_s + braking_distance(v_rel, decel) + final_gap


def lane_change_rear_required(v_ego_kph: float, v_app_kph: float, a_s: float = R171_A_TRACKED_S,
                              decel: float = R171_APPROACH_DECEL_MPS2,
                              gap_time_s: float = R171_GAP_TIME_S) -> float:
    """Minimum distance (approaching vehicle front to own rear) at manoeuvre start, UN R171 6.2.4.1;
    same structure as the UN R79 5.6.4.7 critical distance with tB = A."""
    v_e = v_ego_kph * KPH
    dv = max(0.0, (v_app_kph - v_ego_kph) * KPH)
    return dv * a_s + braking_distance(dv, decel) + v_e * gap_time_s


def r171_assumed_approach_kph(speed_limit_kph: float | None, driver_confirmed: bool) -> float:
    """UN R171 6.2.4.2 / 6.2.9.1.2: speed assumed for an undetected approaching vehicle."""
    if speed_limit_kph is None:
        return R171_VAPP_CAP_KPH
    v = speed_limit_kph * (R171_DRIVER_CONFIRMED_FACTOR if driver_confirmed else 1.0)
    return min(v, R171_VAPP_CAP_KPH)


def r79_vsmin_mps(s_rear_m: float, v_app_mps: float = R79_VAPP_MPS, a: float = R79_A_MPS2,
                  t_b: float = R79_TB_S, t_g: float = R79_TG_S) -> float:
    """Lowest own speed at which a declared rear range S_rear still covers the R79 5.6.4.7 critical
    distance for an approaching vehicle at v_app.  Derived in this project by solving
    S_rear = d*tB + d^2/(2a) + (v_app - d)*tG for the closing speed d (the official 5.6.4.8.1 formula
    is printed as an image in the OJ HTML and was not transcribed)."""
    disc = (t_g - t_b) ** 2 - 2.0 * (v_app_mps * t_g - s_rear_m) / a
    if disc < 0:
        return 0.0
    d = a * ((t_g - t_b) + math.sqrt(disc))
    return max(0.0, v_app_mps - d)


def half_fov_deg(x_m: float, y_m: float) -> float:
    """Bearing of a point seen from the front-bumper origin, in degrees from the x axis."""
    return math.degrees(math.atan2(abs(y_m), x_m))


def cutin_time_to_line_s(edge_offset_m: float, lat_speed_mps: float = CUTIN_LAT_SPEED_MPS,
                         lane_width_m: float = LANE_WIDTH_M) -> float:
    """Time from the start of lateral motion until the target's near edge reaches the lane line."""
    return max(0.0, edge_offset_m - lane_width_m / 2.0) / lat_speed_mps


def cutin_time_to_path_s(edge_offset_m: float, lat_speed_mps: float = CUTIN_LAT_SPEED_MPS,
                         own_width_m: float = VEH_WIDTH_M) -> float:
    """Time until the target's near edge reaches the own vehicle's swept path (half vehicle width)."""
    return max(0.0, edge_offset_m - own_width_m / 2.0) / lat_speed_mps


# ----------------------------------------------------------------------------- requirement list
@dataclass(frozen=True)
class Requirement:
    rid: str
    function: str
    case: str
    kind: str                       # "forward" | "rear_adjacent" | "fov"
    points: tuple                   # ((x, y), ...) in the vehicle frame; y sign = side
    required_m: float               # required range (forward / rear) or distance to the FOV point
    basis: str                      # clause or assumption ids
    markets: str                    # markets where the case matters most
    target: str = "car"             # "car" | "motorcycle"
    both_sides: bool = False        # check the mirrored point too
    any_point: bool = False         # covered if ANY point of the set is covered (extended target)
    detail: dict = field(default_factory=dict)


def requirement_list() -> list[Requirement]:
    reqs: list[Requirement] = []

    def fwd(rid, function, case, d, basis, markets, target="car", y=0.0, **detail):
        reqs.append(Requirement(rid, function, case, "forward", ((d, y),), d, basis, markets, target,
                                both_sides=y != 0.0, detail=detail))

    # ---- AEB
    d = aeb_required_range(R152_V_MAX_KPH, 0.0, decel=R152_DECEL_MIN_MPS2, fcw_lead_s=R152_FCW_LEAD_S)
    fwd("AEB-1", "AEB", "R152 上限 60 km/h 静止目标，FCW 提前 0.8 s，5.0 m/s²", d,
        "R152 5.2.1.1/5.2.1.2/5.2.1.3；A-02/03/06", "EU GB AU MY TH", decel=R152_DECEL_MIN_MPS2, v=60)
    d = aeb_required_range(NCAP_CCRS_AEB_MAX_KPH, 0.0)
    fwd("AEB-2", "AEB", "CCRs 50 km/h 只制动（Euro NCAP AEB 上限）", d, "Euro NCAP v1.2 3.1.1.1；A-02/03/04/06",
        "EU GB AU", v=50)
    d = aeb_required_range(NCAP_CCRS_FCW_MAX_KPH, 0.0, fcw_lead_s=R152_FCW_LEAD_S)
    fwd("AEB-3", "AEB", "CCRs 80 km/h，FCW 提前 0.8 s 后制动", d, "Euro NCAP v1.2 3.1.1.1；R152 5.2.1.1；A-02/03/04/06",
        "EU GB AU", v=80)
    d = aeb_required_range(NCAP_CCRM_TOP[0], NCAP_CCRM_TOP[1], fcw_lead_s=R152_FCW_LEAD_S)
    fwd("AEB-4", "AEB", "CCRm 130 → 70 km/h（Δv 60），FCW 0.8 s", d, "Euro NCAP v1.2 3.1.1.1；A-02/03/04/06",
        "EU GB AU", v=130)
    d = aeb_required_range(NCAP_CCRS_FCW_MAX_KPH, 0.0, decel=AEB_DECEL_WET, fcw_lead_s=R152_FCW_LEAD_S)
    fwd("AEB-5", "AEB", "同 AEB-3，湿路 5.0 m/s²", d, "A-04（湿路）", "MY TH ID GB", v=80)
    d = aeb_required_range(ASEAN_CM_AEB_MAX_KPH, 0.0, fcw_lead_s=R152_FCW_LEAD_S)
    fwd("AEB-6", "AEB 摩托车", "CMRm 60 km/h，25 % 重叠，FCW 0.8 s", d,
        "ASEAN NCAP MS v2.0 Table 5；A-02/03/04/06/11", "MY TH ID", target="motorcycle", y=CMRM_25PCT_OFFSET_M, v=60)

    # ---- ACC
    d = acc_required_range(130, 80)
    fwd("ACC-1", "ACC", "130 km/h 接近 80 km/h 前车，2.0 m/s²，时距 1.8 s", d, "A-05", "EU", v=130)
    d = acc_required_range(GB_MOTORWAY_LIMIT_KPH, 80, time_gap_s=GB_MIN_GAP_S)
    fwd("ACC-2", "ACC", "英国 70 mph 接近 80 km/h 前车，2.0 m/s²，时距 2 s", d,
        "Highway Code r124/r126；A-05", "GB", v=round(GB_MOTORWAY_LIMIT_KPH, 1))
    d = acc_required_range(GB_MOTORWAY_LIMIT_KPH, 80, time_gap_s=2 * GB_MIN_GAP_S)
    fwd("ACC-3", "ACC", "同 ACC-2，湿路时距加倍到 4 s", d, "Highway Code r126；A-05", "GB",
        v=round(GB_MOTORWAY_LIMIT_KPH, 1))
    d = acc_required_range(130, 0)
    fwd("ACC-4", "ACC", "130 km/h 对静止车（队尾），舒适 2.0 m/s²", d, "A-05", "EU", v=130)
    d = acc_required_range(130, 0, decel=ACC_DECEL_FIRM)
    fwd("ACC-5", "ACC", "130 km/h 对静止车，3.5 m/s²", d, "A-05", "EU", v=130)

    # ---- lane change rear coverage (adjacent lane behind the own rear bumper)
    def rear(rid, case, v_e, v_app, a_s, basis, markets, target="car", y=LANE_WIDTH_M, **detail):
        s = lane_change_rear_required(v_e, v_app, a_s)
        reqs.append(Requirement(rid, "变道", case, "rear_adjacent", ((-VEH_LENGTH_M - s, y),), s, basis,
                                markets, target, both_sides=True,
                                detail={"v_ego": v_e, "v_app": round(v_app, 1), "A": a_s, **detail}))

    rear("LC-1", "系统发起，本车 80、来车 130 km/h，A = 0.4 s", 80, 130, R171_A_TRACKED_S,
         "R171 6.2.4.1/6.2.4.2", "EU")
    rear("LC-2", "同 LC-1，来车未持续跟踪 1 s，A = 1.4 s", 80, 130, R171_A_UNTRACKED_S, "R171 6.2.4.1(ii)", "EU")
    rear("LC-3", "系统发起，本车 100、来车 130 km/h，A = 0.4 s", 100, 130, R171_A_TRACKED_S, "R171 6.2.4.1/6.2.4.2",
         "EU")
    v_gb_dc = r171_assumed_approach_kph(GB_MOTORWAY_LIMIT_KPH, driver_confirmed=True)
    rear("LC-4", f"英国，驾驶员确认，本车 80、假设来车 {v_gb_dc:.1f} km/h（70 mph + 10 %）", 80, v_gb_dc,
         R171_A_TRACKED_S, "R171 6.2.9.1.2；Highway Code r124", "GB")
    v_gb_si = r171_assumed_approach_kph(GB_MOTORWAY_LIMIT_KPH, driver_confirmed=False)
    rear("LC-5", f"英国，系统发起，本车 80、假设来车 {v_gb_si:.1f} km/h（70 mph）", 80, v_gb_si,
         R171_A_TRACKED_S, "R171 6.2.4.2；Highway Code r124", "GB")
    rear("LC-6", "拥堵中摩托车从后方穿行：本车 30、摩托车 60 km/h，A = 0.4 s", 30, 60, R171_A_TRACKED_S,
         "R171 6.2.4.1 结构；A-09", "MY TH ID", target="motorcycle", y=LANE_WIDTH_M / 2.0)

    # ---- cut-in / near-field lateral coverage
    def fov(rid, function, case, x, y, basis, markets, target="car", **detail):
        reqs.append(Requirement(rid, function, case, "fov", ((x, y),), math.hypot(x, y), basis, markets,
                                target, both_sides=True, detail={"half_fov_deg": round(half_fov_deg(x, y), 1),
                                                                 **detail}))

    edge = LANE_WIDTH_M - TARGET_WIDTH_M / 2.0
    timing = {"t_to_line_s": round(cutin_time_to_line_s(edge), 2), "t_to_path_s": round(cutin_time_to_path_s(edge), 2)}
    fov("CUT-1", "切入", "100 km/h，切入车距 0.5 s（13.9 m）", 0.5 * 100 * KPH, edge, "A-01/07", "全部", **timing)
    fov("CUT-2", "切入", "拥堵切入，车距 5 m", 5.0, edge, "A-01/07", "全部", **timing)
    fov("CUT-3", "切入", "近距加塞，车距 2 m", 2.0, edge, "A-01/07", "全部", **timing)
    fov("CUT-4", "切入（摩托车）", "摩托车穿行后切入，距 3 m", 3.0, MC_FILTER_EDGE_M, "A-08；ASEAN NCAP MS v2.0 4.1",
        "MY TH ID", target="motorcycle", t_to_path_s=round(cutin_time_to_path_s(MC_FILTER_EDGE_M), 2))
    mc_half = 1.0
    for i, (xc, y) in enumerate(((-VEH_LENGTH_M + 0.5, 2.0), (-VEH_LENGTH_M + 0.5, 3.0),
                                 (-VEH_LENGTH_M - 2.0, 2.0), (-VEH_LENGTH_M - 2.0, 3.0)), 1):
        pts = tuple((xc + dx, y) for dx in (mc_half, 0.0, -mc_half))
        reqs.append(Requirement(f"BSD-{i}", "盲区（摩托车）", f"摩托车中心 x = {xc:.1f} m、横向 {y:.0f} m",
                                "fov", pts, math.hypot(xc, y), "ASEAN NCAP MS v2.0 3.4.1 Table 1；A-10",
                                "MY TH ID", "motorcycle", both_sides=True, any_point=True,
                                detail={"half_fov_deg": round(half_fov_deg(xc, y), 1)}))
    return reqs
