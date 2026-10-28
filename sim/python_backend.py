"""Pure-Python re-integration of the same storyboard (cross-check of esmini, and tests without esmini).

Semantics copied from what esmini v3.10.2 does with these files (checked against its CSV log):
  - an event fires at the first step whose start time t_k satisfies t_k >= trigger time;
  - speed: the target speed is approached at the given rate, then x += v_new * dt;
  - lane change: sinusoidal lateral profile y0 + dy * (1 - cos(pi * tau / T)) / 2, tau counted from the
    firing step.
Collision: axis-aligned bounding boxes (all headings stay within a few degrees).
"""
from __future__ import annotations

import math

from .scenario import GEOM, Spec, lane_t


class PythonBackend:
    name = "python"

    def __init__(self, spec: Spec, side: str):
        self.spec, self.side = spec, side

    def start(self, xosc: str, actor_names: list[str], dt: float, log_stem: str | None = None) -> None:
        self.t = 0.0
        self.act = {}
        for a in self.spec.actors:
            self.act[a.name] = {"x": a.s0, "y": lane_t(a.lane, self.side), "v": a.v0, "cat": a.category,
                                "v_goal": a.v0, "rate": 0.0, "lc": None, "events": list(a.events)}
        g = GEOM["car"]
        self.ego_init = (self.spec.ego_s0, lane_t(self.spec.ego_lane, self.side), self.spec.ego_v0)
        self.ego_box = (g["cx"], g["length"], g["width"])
        self.collision = False

    def objects(self) -> dict[str, dict]:
        out = {}
        for n, a in self.act.items():
            g = GEOM[a["cat"]]
            out[n] = {"x": a["x"], "y": a["y"], "v": a["v"], "h": 0.0, "lane_id": None,
                      "cx": g["cx"], "length": g["length"], "width": g["width"]}
        return out

    def advance(self, dt: float, x: float, y: float, h: float, v: float) -> None:
        for a in self.act.values():
            for e in [e for e in a["events"] if self.t >= e.t - 1e-9]:
                a["events"].remove(e)
                if e.kind == "speed":
                    a["v_goal"], a["rate"] = e.value, e.param
                else:
                    a["lc"] = {"y0": a["y"], "dy": lane_t(int(e.value), self.side) - a["y"], "T": e.param, "tau": 0.0}
            if a["v"] != a["v_goal"]:
                if a["rate"] <= 0:
                    a["v"] = a["v_goal"]
                else:
                    step = a["rate"] * dt
                    a["v"] = a["v_goal"] if abs(a["v_goal"] - a["v"]) <= step else a["v"] + math.copysign(step, a["v_goal"] - a["v"])
            a["x"] += a["v"] * dt
            if a["lc"] is not None:
                lc = a["lc"]
                lc["tau"] += dt
                f = min(1.0, lc["tau"] / lc["T"])
                a["y"] = lc["y0"] + lc["dy"] * (1.0 - math.cos(math.pi * f)) / 2.0
                if f >= 1.0:
                    a["lc"] = None
        self.t += dt
        if not self.collision:
            cx, ln, wd = self.ego_box
            for a in self.act.values():
                g = GEOM[a["cat"]]
                if (abs((x + cx) - (a["x"] + g["cx"])) < (ln + g["length"]) / 2.0
                        and abs(y - a["y"]) < (wd + g["width"]) / 2.0):
                    self.collision = True

    def time(self) -> float:
        return self.t

    def close(self) -> None:
        pass
