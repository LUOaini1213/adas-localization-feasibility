"""Run the mirrored LHT / RHT simulation set (esmini primary, Python backend as cross-check).

Run:  python -X utf8 -B -I scripts/run_sim.py --esmini-lib <path to esminiLib.dll>
      python -X utf8 -B -I scripts/run_sim.py --backend python          (no esmini)
Single process on purpose (24 short runs per backend); no worker pool.

Outputs (results/):
  sim_runs.csv           metrics of every run (primary backend)
  sim_mirror_check.csv   RHT run vs mirrored LHT run with the matching rule set: trajectory deviation
  sim_backend_check.csv  esmini vs Python backend for every run
  sim_timeseries/*.csv   ego time series of every run (primary backend)
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim.runner import run, run_list  # noqa: E402

RES = ROOT / "results"
FIELDS = ["run_id", "case_id", "world", "rules", "cutin_mode", "mirrored_ok", "backend", "note", "collision",
          "min_gap_m", "min_ttc_s", "max_decel_mps2", "t_detect_cutter_s", "inside_pass", "inside_pass_vehicle",
          "normal_pass", "lc_side", "lc_start_s", "suppressed_by", "start_check", "lc_events", "min_speed_kph",
          "max_lat_acc_mps2", "end_x_m"]


def write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def series_dev(a, b, mirror: bool):
    """max |dx|, max |dy| (y mirrored when comparing RHT with LHT), max |dv| between two ego series."""
    n = min(len(a["t"]), len(b["t"]))
    sy = -1.0 if mirror else 1.0
    dx = max(abs(a["x"][i] - b["x"][i]) for i in range(n))
    dy = max(abs(a["y"][i] - sy * b["y"][i]) for i in range(n))
    dv = max(abs(a["v"][i] - b["v"][i]) for i in range(n))
    return round(dx, 4), round(dy, 4), round(dv, 4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--esmini-lib")
    ap.add_argument("--backend", choices=["esmini", "python"], default=None)
    args = ap.parse_args()
    primary = args.backend or ("esmini" if args.esmini_lib else "python")
    cross = "python" if primary == "esmini" else None
    (RES / "sim_timeseries").mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    runs = run_list()
    prim, sec = {}, {}
    for rs in runs:
        prim[rs.run_id] = run(rs, primary, args.esmini_lib, record=True,
                              log_stem=rs.run_id if primary == "esmini" else None)
        if cross:
            sec[rs.run_id] = run(rs, cross, None, record=True)
    rows = []
    for rs in runs:
        m = dict(prim[rs.run_id])
        s = m.pop("series")
        rows.append(m)
        with open(RES / "sim_timeseries" / f"{rs.run_id}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(list(s))
            for r in zip(*s.values()):
                w.writerow([f"{v:.4f}" if isinstance(v, float) else v for v in r])
    write_csv(RES / "sim_runs.csv", rows, FIELDS)

    # ---- mirror check: RHT run vs the LHT run with the matching (mirrored) rule set
    mirror_rows = []
    by_id = {r.run_id: r for r in runs}
    for rs in runs:
        if rs.world != "RHT":
            continue
        twin = rs.run_id.replace("-RHT_BASE", "-GB").replace("-RHT", "-LHT")
        if twin not in by_id:
            continue
        a, b = prim[rs.run_id], prim[twin]
        dx, dy, dv = series_dev(a["series"], b["series"], mirror=True)
        same = all(a[k] == b[k] for k in ("collision", "min_gap_m", "max_decel_mps2", "t_detect_cutter_s",
                                          "inside_pass", "lc_side", "lc_start_s"))
        mirror_rows.append({"RHT 运行": rs.run_id, "LHT 运行": twin, "max|Δx| m": dx, "max|Δ(镜像 y)| m": dy,
                            "max|Δv| m/s": dv, "指标完全一致": same})
    write_csv(RES / "sim_mirror_check.csv", mirror_rows, list(mirror_rows[0]) if mirror_rows else ["none"])

    # ---- backend check
    back_rows = []
    if cross:
        for rs in runs:
            a, b = prim[rs.run_id], sec[rs.run_id]
            dx, dy, dv = series_dev(a["series"], b["series"], mirror=False)
            keys = ("collision", "inside_pass", "lc_side", "lc_start_s", "t_detect_cutter_s")
            back_rows.append({"运行": rs.run_id, "max|Δx| m": dx, "max|Δy| m": dy, "max|Δv| m/s": dv,
                              "最小间距 esmini/Python": f"{a['min_gap_m']}/{b['min_gap_m']}",
                              "离散结果一致": all(a[k] == b[k] for k in keys)})
        write_csv(RES / "sim_backend_check.csv", back_rows, list(back_rows[0]))
    summary = {"primary_backend": primary, "cross_backend": cross, "runs": len(runs),
               "elapsed_s": round(time.time() - t0, 1),
               "mirror_pairs": len(mirror_rows), "mirror_all_identical": all(r["指标完全一致"] for r in mirror_rows),
               "mirror_max_dx": max((r["max|Δx| m"] for r in mirror_rows), default=None),
               "mirror_max_dy": max((r["max|Δ(镜像 y)| m"] for r in mirror_rows), default=None),
               "backend_all_discrete_equal": all(r["离散结果一致"] for r in back_rows) if back_rows else None,
               "backend_max_dx": max((r["max|Δx| m"] for r in back_rows), default=None),
               "backend_max_dv": max((r["max|Δv| m/s"] for r in back_rows), default=None)}
    (RES / "sim_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
