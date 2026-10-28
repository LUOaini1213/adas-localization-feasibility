"""Run the sensor-suite feasibility calculator and write its tables.

Run:  python -X utf8 -B -I scripts/run_feasibility.py
Outputs (results/): requirements.csv, feasibility.csv, rain_sweep.csv, lc_rear_curve.csv, suites.csv
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from feasib import requirements as rq  # noqa: E402
from feasib.feasibility import rain_sweep, run_all  # noqa: E402
from feasib.suites import reference_suites  # noqa: E402

RES = ROOT / "results"


def write(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    RES.mkdir(exist_ok=True)
    reqs = rq.requirement_list()
    write(RES / "requirements.csv", [
        {"编号": r.rid, "功能": r.function, "工况": r.case, "类型": r.kind, "目标": r.target,
         "需求 m": round(r.required_m, 1), "半视场角 °": r.detail.get("half_fov_deg", ""),
         "到车道线 s": r.detail.get("t_to_line_s", ""), "到本车路径 s": r.detail.get("t_to_path_s", ""),
         "依据": r.basis, "重点市场": r.markets} for r in reqs])
    checks = run_all()
    write(RES / "feasibility.csv", [
        {"编号": c.rid, "方案": c.suite, "工况": c.condition, "需求 m": c.required, "满足": c.covered,
         "余量 m": c.margin_m, "覆盖的模态": c.modalities, "冗余模态数": c.redundancy,
         "允许总时延 s": "" if c.latency_budget_s is None else c.latency_budget_s, "覆盖的传感器": c.sensors}
        for c in checks])
    write(RES / "rain_sweep.csv", rain_sweep())
    curve = []
    for v_e in (60, 70, 80, 90, 100, 110, 120):
        curve.append({"本车 km/h": v_e,
                      "A=0.4 s 需求 m": round(rq.lane_change_rear_required(v_e, 130, rq.R171_A_TRACKED_S), 1),
                      "A=1.4 s 需求 m": round(rq.lane_change_rear_required(v_e, 130, rq.R171_A_UNTRACKED_S), 1)})
    write(RES / "lc_rear_curve.csv", curve)
    write(RES / "r79_vsmin.csv", [{"申报后向距离 S_rear m": s, "最低变道车速 km/h": round(rq.r79_vsmin_mps(s) * 3.6, 1)}
                                  for s in (55, 60, 70, 80, 100)])
    write(RES / "suites.csv", [
        {"方案": s.sid, "说明": s.label, "摄像头": s.count("camera"), "毫米波雷达": s.count("radar"),
         "激光雷达": s.count("lidar"), "相对成本档": s.cost_tier,
         "传感器": "；".join(f"{x.name}（{x.modality}，{'/'.join(f'{r:g} m±{h:g}°' for r, h in x.lobes)}，{x.source}）"
                           for x in s.sensors)} for s in reference_suites()])
    n_ok = sum(c.covered for c in checks)
    print(f"{len(reqs)} requirements x {len(reference_suites())} suites x 3 conditions = {len(checks)} checks, "
          f"{n_ok} covered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
