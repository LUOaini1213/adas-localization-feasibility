"""Simple ego controller for the mirrored LHT / RHT check.  Not a production design.

Everything that depends on the traffic side goes through ONE number, RuleSet.overtaking_side:
  +1 -> overtaking lanes lie to the vehicle's LEFT  (right-hand traffic)
  -1 -> overtaking lanes lie to the vehicle's RIGHT (left-hand traffic)
The controller works in a normalised lateral coordinate eta = overtaking_side * (y_obj - y_ego), so
eta > 0 always means "towards the overtaking side".  Running the RHT rule set in an LHT world is the
"unmirrored" configuration.

Functions:
  ACC            constant-time-gap following + cruise; brake up to 3.5 m/s2, up to 8 m/s2 when TTC < 2.5 s
  cut-in         adjacent-lane vehicle moving towards the own lane and predicted to enter within 1.0 s;
                 mode "symmetric" (both sides) or "overtaking_side_only"
  no undertaking if the rule set forbids passing on the inside, a slower vehicle ahead in a lane on the
                 overtaking side acts as a soft virtual lead (no congestion exception modelled)
  auto overtake  system-initiated lane change towards the overtaking side when held up by a slower lead:
                 signal 3 s (UN R171 6.2.7), rear check at manoeuvre start (UN R171 6.2.4.1: approaching
                 vehicle <= 3 m/s2 after A s, gap >= own 1 s travel; 6.2.4.2 when nothing is detected),
                 give up if not started within 7 s of initiation (6.2.9.5), 4 s sinusoidal lateral motion
                 (peak lateral acceleration 1.08 m/s2 <= 1.5 m/s2, 6.2.3)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from feasib.requirements import (R171_A_TRACKED_S, R171_A_UNTRACKED_S, lane_change_rear_required,
                                 r171_assumed_approach_kph)

LANE_W = 3.5
EGO_CX, EGO_L, EGO_W = 1.4, 4.7, 1.85
KPH = 1.0 / 3.6

SIM_ASSUMPTIONS = {
    "A-21": "仿真感知用真值：无噪声、无漏检、无时延；横向速度用相邻两步差分",
    "A-22": "ACC：定时距 + 定速巡航，间距增益 0.25、速度增益 0.8；常规制动上限 3.5 m/s²，TTC < 2.5 s 时放开到 8 m/s²；纵向执行一阶滞后 0.3 s",
    "A-23": "切入判定：相邻车道车辆朝本车道横向速度 > 0.2 m/s 且预计 1.0 s 内进入，或已压线",
    "A-24": "不得内侧超车：超车侧车道上更慢的前方车辆作为软约束，目标为落后其车尾 5 m + 0.5 s × 本车速；不建模拥堵例外",
    "A-25": "系统发起变道：被慢车压速 2 s 后发起，打灯 3 s 后做后向检查，4 s 正弦横移；后向雷达量程 80 m（同 A-17）",
    "A-26": "场景几何：三车道双向分隔道路，车道宽 3.5 m，车长 4.7 m、宽 1.85 m，摩托车长 2.0 m、宽 0.8 m；步长 0.02 s",
}


@dataclass(frozen=True)
class RuleSet:
    name: str
    overtaking_side: int            # +1 left (RHT), -1 right (LHT)
    undertaking_allowed: bool
    basis: str
    time_gap_s: float = 1.8
    speed_limit_kph: float | None = None


RULESETS = {
    "RHT_BASE": RuleSet("RHT 基线（与 GB 对称的项目假设）", +1, False, "项目假设：GB 规则的镜像"),
    "GB": RuleSet("GB", -1, False, "Highway Code r264（靠左）、r268（高速不得从左侧超车）"),
    "AU": RuleSet("AU", -1, True, "Australian Road Rules r141(1)(a)（多车道可在标线车道内从左侧超越）"),
    "ID": RuleSet("ID", -1, False, "UU 22/2009 Pasal 109(1)(2)（从右侧超车，左侧仅限特定情形）"),
}


@dataclass
class CtrlConfig:
    rules: RuleSet
    cutin_mode: str = "symmetric"           # "symmetric" | "overtaking_side_only"
    set_speed_kph: float = 110.0
    auto_overtake: bool = False
    rear_range_m: float = 80.0              # rear corner radar far lobe (assumption A-17)
    signal_s: float = 3.0                   # R171 6.2.7
    max_wait_s: float = 7.0                 # R171 6.2.9.5
    lc_duration_s: float = 4.0
    tau_s: float = 0.3                      # longitudinal actuator lag (project assumption)


@dataclass
class Track:
    first_seen: float
    y_prev: float
    y_dot: float = 0.0


@dataclass
class Controller:
    cfg: CtrlConfig
    lane_centres: list                      # own-direction lane centre positions t (from the map)
    dt: float
    a_act: float = 0.0
    tracks: dict = field(default_factory=dict)
    lc: dict | None = None                  # active lane-change procedure
    held_s: float = 0.0
    lead_name: str | None = None
    log: list = field(default_factory=list)
    lc_done: bool = False

    # ------------------------------------------------------------------ helpers
    def _eta(self, dy: float) -> float:
        return self.cfg.rules.overtaking_side * dy

    def _lane_exists(self, y: float) -> bool:
        return any(abs(y - c) < 0.5 for c in self.lane_centres)

    def _own_lane_centre(self, y: float) -> float:
        return min(self.lane_centres, key=lambda c: abs(c - y))

    # ------------------------------------------------------------------ main step
    def step(self, t: float, ego: dict, objs: dict) -> tuple[float, float]:
        """Return (acceleration command after actuator lag [m/s2], lateral position y for the next step)."""
        x_e, y_e, v = ego["x"], ego["y"], ego["v"]
        e_front, e_rear = x_e + EGO_CX + EGO_L / 2, x_e + EGO_CX - EGO_L / 2
        v_set = self.cfg.set_speed_kph * KPH
        if self.cfg.rules.speed_limit_kph:
            v_set = min(v_set, self.cfg.rules.speed_limit_kph * KPH)
        # ---- perception (ground truth positions, finite-difference lateral speed, track age)
        for n, o in objs.items():
            tr = self.tracks.get(n)
            if tr is None:
                self.tracks[n] = Track(t, o["y"])
            else:
                tr.y_dot = (o["y"] - tr.y_prev) / self.dt
                tr.y_prev = o["y"]
        ego_ydot = self.lc["ydot"] if self.lc and self.lc.get("moving") else 0.0
        # ---- lead / cut-in selection
        lead, lead_gap = None, math.inf
        half_band = LANE_W / 2.0
        for n, o in objs.items():
            o_rear, o_front = o["x"] + o["cx"] - o["length"] / 2, o["x"] + o["cx"] + o["length"] / 2
            gap = o_rear - e_front
            if gap < -0.5 or gap > 150:
                continue
            dy = o["y"] - y_e
            in_path = abs(dy) < (EGO_W + o["width"]) / 2.0 + 0.3 if self.lc else abs(dy) < half_band
            cut = False
            if not in_path and abs(round(dy / LANE_W)) == 1 and gap < 80:
                v_toward = -math.copysign(1.0, dy) * (self.tracks[n].y_dot - ego_ydot)
                d_edge = abs(dy) - o["width"] / 2.0 - LANE_W / 2.0
                allowed_side = self.cfg.cutin_mode == "symmetric" or self._eta(dy) > 0
                if allowed_side and (d_edge < 0 or (v_toward > 0.2 and d_edge / v_toward < 1.0)):
                    cut = True
            if (in_path or cut) and gap < lead_gap:
                lead, lead_gap = (n, o), gap
        self.lead_name = lead[0] if lead else None
        # ---- longitudinal command
        a_cmd = max(-2.0, min(1.5, 0.4 * (v_set - v)))
        if lead:
            _, o = lead
            gap_des = 5.0 + v * self.cfg.rules.time_gap_s
            a_f = 0.25 * (lead_gap - gap_des) + 0.8 * (o["v"] - v)
            closing = v - o["v"]
            ttc = lead_gap / closing if closing > 0.1 and lead_gap > 0 else math.inf
            a_min = -8.0 if ttc < 2.5 else -3.5
            a_cmd = min(a_cmd, max(a_min, min(1.5, a_f)))
        if not self.cfg.rules.undertaking_allowed:
            for n, o in objs.items():
                dy = o["y"] - y_e
                o_rear = o["x"] + o["cx"] - o["length"] / 2
                if self._eta(dy) > LANE_W / 2.0 and -10.0 < o_rear - e_front < 150.0 and o["v"] < v + 0.5:
                    gap_v = o_rear - e_front
                    a_u = 0.25 * (gap_v - (5.0 + 0.5 * v)) + 0.8 * (o["v"] - v)
                    a_cmd = min(a_cmd, max(-2.0, min(1.5, a_u)))
        # ---- system-initiated overtaking lane change
        y_next = y_e
        if self.cfg.auto_overtake:
            y_next = self._lane_change(t, x_e, y_e, v, v_set, e_rear, objs, lead, lead_gap)
        # ---- actuator lag
        self.a_act += (a_cmd - self.a_act) * min(1.0, self.dt / self.cfg.tau_s)
        return self.a_act, y_next

    def _lane_change(self, t, x_e, y_e, v, v_set, e_rear, objs, lead, lead_gap) -> float:
        if self.lc is None and not self.lc_done:
            held = lead is not None and lead[1]["v"] < v_set - 10 * KPH and lead_gap < 120
            self.held_s = self.held_s + self.dt if held else 0.0
            if self.held_s >= 2.0:
                y_tgt = self._own_lane_centre(y_e) + self.cfg.rules.overtaking_side * LANE_W
                if not self._lane_exists(y_tgt):
                    if not any(e[1] == "target lane unavailable" for e in self.log):
                        self.log.append((round(t, 2), "target lane unavailable", round(y_tgt, 2)))
                    return y_e
                self.lc = {"t_init": t, "y0": y_e, "y_tgt": y_tgt, "moving": False, "ydot": 0.0}
                self.log.append((round(t, 2), "signal on", round(y_tgt, 2)))
            return y_e
        if self.lc is None:
            return y_e
        lc = self.lc
        if not lc["moving"]:
            if t - lc["t_init"] < self.cfg.signal_s:
                return y_e
            ok, info = self.rear_check(t, v, e_rear, lc["y_tgt"], objs)
            if ok:
                lc.update(moving=True, t_start=t, check=info)
                self.log.append((round(t, 2), "manoeuvre start", info))
            elif t - lc["t_init"] > self.cfg.max_wait_s:
                self.log.append((round(t, 2), "cancelled (not started within 7 s)", info))
                self.lc, self.held_s = None, 0.0
                return y_e
            else:
                if not lc.get("suppressed"):
                    self.log.append((round(t, 2), "suppressed (R171 6.2.4)", info))
                    lc["suppressed"] = True
                return y_e
        tau = t + self.dt - lc["t_start"]
        f = min(1.0, tau / self.cfg.lc_duration_s)
        dy = lc["y_tgt"] - lc["y0"]
        y_new = lc["y0"] + dy * (1.0 - math.cos(math.pi * f)) / 2.0
        lc["ydot"] = (y_new - y_e) / self.dt
        if f >= 1.0:
            self.log.append((round(t, 2), "manoeuvre end", None))
            self.lc, self.lc_done = None, True
        return y_new

    def rear_check(self, t, v, e_rear, y_tgt, objs) -> tuple[bool, dict]:
        """UN R171 6.2.4.1 / 6.2.4.2 at manoeuvre start for the target lane."""
        worst = {"veh": None, "gap": None, "need": None}
        found = False
        for n, o in objs.items():
            if abs(o["y"] - y_tgt) > LANE_W / 2.0:
                continue
            o_front = o["x"] + o["cx"] + o["length"] / 2
            o_rear = o["x"] + o["cx"] - o["length"] / 2
            if o_rear > e_rear + EGO_L + 1.0:          # ahead of the own front: front check only
                if o_rear - (e_rear + EGO_L) < v * 1.0:
                    return False, {"veh": n, "gap": round(o_rear - e_rear - EGO_L, 1), "need": "front"}
                continue
            found = True
            gap = e_rear - o_front
            if gap <= 0:
                return False, {"veh": n, "gap": round(gap, 1), "need": "alongside"}
            a_s = R171_A_TRACKED_S if t - self.tracks[n].first_seen >= 1.0 else R171_A_UNTRACKED_S
            need = lane_change_rear_required(v / KPH, o["v"] / KPH, a_s)
            dv = o["v"] - v
            room = gap - v * 1.0 - max(dv, 0.0) * a_s
            a_req = 0.0 if dv <= 0 else (dv * dv / (2.0 * room) if room > 0 else math.inf)
            info = {"veh": n, "gap": round(gap, 1), "need": round(need, 1), "dv": round(dv, 2),
                    "A": a_s, "a_req": round(a_req, 2) if a_req != math.inf else math.inf}
            if gap < need:
                return False, info
            worst = info
        if not found:                                   # 6.2.4.2: virtual vehicle at the rear range
            v_app = r171_assumed_approach_kph(self.cfg.rules.speed_limit_kph, driver_confirmed=False)
            need = lane_change_rear_required(v / KPH, v_app, R171_A_TRACKED_S)
            ok = self.cfg.rear_range_m >= need
            return ok, {"veh": "virtual", "gap": self.cfg.rear_range_m, "need": round(need, 1)}
        return True, worst
