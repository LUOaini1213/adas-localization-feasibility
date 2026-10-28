"""Closed loop (world backend + ego controller), run list and metrics."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .controller import EGO_CX, EGO_L, EGO_W, LANE_W, RULESETS, Controller, CtrlConfig
from .scenario import Spec, lane_t, scenario_specs, xosc_name

KPH = 1.0 / 3.6
DT = 0.02


@dataclass(frozen=True)
class RunSpec:
    run_id: str
    case_id: str
    world: str                 # "RHT" | "LHT"
    rules: str                 # key of RULESETS
    cutin_mode: str = "symmetric"
    auto_overtake: bool = False
    set_speed_kph: float = 110.0
    note: str = ""

    @property
    def mirrored_ok(self) -> bool:
        """True when the rule set's overtaking side matches the world."""
        side = RULESETS[self.rules].overtaking_side
        return (side == +1) == (self.world == "RHT")


def run_list() -> list[RunSpec]:
    runs = []
    for case in ("OS", "KS", "MC"):
        for mode in ("symmetric", "overtaking_side_only"):
            for world, rules in (("RHT", "RHT_BASE"), ("LHT", "GB")):
                runs.append(RunSpec(f"F1-{case}-{mode[:3]}-{world}", f"F1_CUTIN_{case}", world, rules, mode,
                                    set_speed_kph=100.0, note="镜像正确"))
            runs.append(RunSpec(f"F1-{case}-{mode[:3]}-LHT-unmirrored", f"F1_CUTIN_{case}", "LHT", "RHT_BASE", mode,
                                set_speed_kph=100.0, note="LHT 世界用 RHT 规则（未镜像）"))
    for world, rules, note in (("RHT", "RHT_BASE", "镜像正确"), ("LHT", "GB", "镜像正确"),
                               ("LHT", "RHT_BASE", "未镜像"), ("LHT", "AU", "澳大利亚规则"),
                               ("LHT", "ID", "印尼规则")):
        runs.append(RunSpec(f"F2-{world}-{rules}", "F2_UNDERTAKE", world, rules, note=note))
    for world, rules, note in (("RHT", "RHT_BASE", "镜像正确"), ("LHT", "GB", "镜像正确"), ("LHT", "RHT_BASE", "未镜像")):
        runs.append(RunSpec(f"F3-{world}-{rules}", "F3_OVERTAKE", world, rules, auto_overtake=True, note=note))
    return runs


SPECS = {s.case_id: s for s in scenario_specs()}


def make_backend(kind: str, spec: Spec, world: str, esmini_lib: str | None):
    if kind == "esmini":
        from .esmini_backend import EsminiBackend
        if not esmini_lib:
            raise SystemExit("--esmini-lib <path to esminiLib.dll> is required for the esmini backend")
        return EsminiBackend(esmini_lib)
    from .python_backend import PythonBackend
    return PythonBackend(spec, world)


def _box(o):
    return o["x"] + o["cx"] - o["length"] / 2, o["x"] + o["cx"] + o["length"] / 2


def run(rs: RunSpec, kind: str = "python", esmini_lib: str | None = None, record: bool = False,
        log_stem: str | None = None) -> dict:
    spec = SPECS[rs.case_id]
    rules = RULESETS[rs.rules]
    backend = make_backend(kind, spec, rs.world, esmini_lib)
    names = [a.name for a in spec.actors]
    backend.start(xosc_name(spec, rs.world), names, DT, log_stem)
    try:
        return _loop(rs, spec, rules, backend, record)
    finally:
        backend.close()


def _loop(rs, spec, rules, backend, record) -> dict:
    centres = [lane_t(k, rs.world) for k in (1, 2, 3)]
    ctrl = Controller(CtrlConfig(rules, rs.cutin_mode, rs.set_speed_kph, rs.auto_overtake), centres, DT)
    x, y, v = backend.ego_init
    sigma_w = +1 if rs.world == "RHT" else -1           # TRUE overtaking side of the world
    m = {"run_id": rs.run_id, "case_id": rs.case_id, "world": rs.world, "rules": rs.rules,
         "cutin_mode": rs.cutin_mode, "mirrored_ok": rs.mirrored_ok, "backend": backend.name, "note": rs.note,
         "collision": False, "min_gap_m": math.inf, "min_ttc_s": math.inf, "max_decel_mps2": 0.0,
         "t_detect_cutter_s": None, "inside_pass": False, "inside_pass_vehicle": "", "normal_pass": "",
         "lc_side": "", "lc_start_s": None, "lc_events": "", "app_gap_m": None, "app_dv_mps": None,
         "app_required_decel_mps2": None, "min_speed_kph": v / KPH, "max_lat_acc_mps2": 0.0, "end_x_m": None}
    passed = {}
    series = {k: [] for k in ("t", "x", "y", "v", "a", "lead")} if record else None
    y_hist = [y, y]
    n_steps = int(round(spec.t_end / DT))
    for k in range(n_steps):
        t = k * DT
        objs = backend.objects()
        a, y_next = ctrl.step(t, {"x": x, "y": y, "v": v}, objs)
        e_rear, e_front = x + EGO_CX - EGO_L / 2, x + EGO_CX + EGO_L / 2
        for n, o in objs.items():
            o_rear, o_front = _box(o)
            dy = o["y"] - y
            if abs(dy) < (EGO_W + o["width"]) / 2.0:     # lateral overlap -> longitudinal gap and TTC
                gap = o_rear - e_front
                if gap > -o["length"]:
                    m["min_gap_m"] = min(m["min_gap_m"], max(gap, 0.0))
                    closing = v - o["v"]
                    if gap > 0 and closing > 0.1:
                        m["min_ttc_s"] = min(m["min_ttc_s"], gap / closing)
            now_passed = e_rear > o_front
            if k == 0:                                    # initial order is not a passing event
                passed[n] = now_passed
            if now_passed and not passed[n]:
                eta_w = sigma_w * dy                      # >0: the passed vehicle is on the overtaking side
                if eta_w > LANE_W / 2.0:
                    m["inside_pass"], m["inside_pass_vehicle"] = True, n
                elif eta_w < -LANE_W / 2.0:
                    m["normal_pass"] = n
            passed[n] = now_passed
        if m["t_detect_cutter_s"] is None and ctrl.lead_name == "Cutter":
            m["t_detect_cutter_s"] = round(t - 1.0, 2)
        m["max_decel_mps2"] = max(m["max_decel_mps2"], -a)
        if record:
            for key, val in (("t", t), ("x", x), ("y", y), ("v", v), ("a", a), ("lead", ctrl.lead_name or "")):
                series[key].append(val)
        # ---- ego plant
        v_new = max(0.0, v + a * DT)
        x_new = x + 0.5 * (v + v_new) * DT
        h = math.atan2(y_next - y, max(1e-6, x_new - x))
        backend.advance(DT, x_new, y_next, h, v_new)
        if k > 0:
            m["max_lat_acc_mps2"] = max(m["max_lat_acc_mps2"], abs(y_next - 2 * y_hist[1] + y_hist[0]) / DT ** 2)
        y_hist = [y_hist[1], y_next]
        x, y, v = x_new, y_next, v_new
        m["min_speed_kph"] = min(m["min_speed_kph"], v / KPH)
        if backend.collision:
            m["collision"] = True
    m["end_x_m"] = round(x, 2)
    # ---- lane-change bookkeeping (F3)
    m["lc_events"] = "; ".join(f"{t}:{ev}" for t, ev, _ in ctrl.log)
    start = next((e for e in ctrl.log if e[1] == "manoeuvre start"), None)
    sig = next((e for e in ctrl.log if e[1] == "signal on"), None)
    if sig is not None:
        y_tgt = sig[2]
        m["lc_side"] = "超车侧" if sigma_w * (y_tgt - lane_t(spec.ego_lane, rs.world)) > 0 else "路缘侧"
    sup = next((e for e in ctrl.log if e[1].startswith("suppressed")), None)
    if sup is not None and isinstance(sup[2], dict):
        need = sup[2].get("need")
        need_txt = {"alongside": "并排，不可变道", "front": "目标车道前方车距不足"}.get(need, f"需要 {need} m")
        a_req = sup[2].get("a_req")
        extra = f"，来车所需减速度 {a_req} m/s²" if isinstance(a_req, (int, float)) else ""
        m["suppressed_by"] = f"{sup[2].get('veh')}：间距 {sup[2].get('gap')} m，{need_txt}{extra}"
    else:
        m["suppressed_by"] = ""
    if start is not None:
        m["lc_start_s"] = start[0]
        info = start[2] or {}
        m["app_gap_m"] = info.get("gap")
        who = "无来车（按 6.2.4.2 假设来车在后向量程处）" if info.get("veh") == "virtual" else info.get("veh")
        m["start_check"] = f"{who}：间距 {info.get('gap')} m ≥ 需要 {info.get('need')} m"
    else:
        m["start_check"] = ""
    m.update(_approach_check(ctrl, spec, rs))
    for key in ("min_gap_m", "min_ttc_s"):
        m[key] = None if m[key] == math.inf else round(m[key], 2)
    m["max_decel_mps2"] = round(m["max_decel_mps2"], 2)
    m["max_lat_acc_mps2"] = round(m["max_lat_acc_mps2"], 2)
    m["min_speed_kph"] = round(m["min_speed_kph"], 1)
    if record:
        m["series"] = series
    return m


def _approach_check(ctrl, spec, rs) -> dict:
    """Required deceleration of the approaching vehicle in the target lane at manoeuvre start, using the
    UN R171 6.2.4.1 criterion (A = 0.4 s, 1 s gap): a = dv^2 / (2 (gap - v_e*1 s - dv*A))."""
    start = next((e for e in ctrl.log if e[1] == "manoeuvre start"), None)
    if start is None:
        return {"app_required_decel_mps2": None}
    info = start[2] or {}
    if info.get("veh") in (None, "virtual"):
        return {"app_required_decel_mps2": 0.0, "app_dv_mps": None}
    return {"app_required_decel_mps2": info.get("a_req"), "app_dv_mps": info.get("dv")}
