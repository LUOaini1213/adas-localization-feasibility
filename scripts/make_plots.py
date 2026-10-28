"""Figure of the mirrored simulation (results/fig_mirror.png), from results/sim_timeseries/*.csv.

Run (after run_sim.py):  python -X utf8 -B -I scripts/make_plots.py
English labels so the figure renders with any font set.  Model-internal results.
Colours: first three categorical slots of the reference palette (validated all-pairs; the aqua slot
is below 3:1 contrast, so every line also has its own dash style and a direct label).
"""
import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TS = ROOT / "results" / "sim_timeseries"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def load(run_id):
    with open(TS / f"{run_id}.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {k: [float(r[k]) for r in rows] for k in ("t", "x", "y", "v", "a")}


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(INK2)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def main() -> int:
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1.35, 1]})
    fig.patch.set_facecolor("#fcfcfb")
    # ---- panel A: F3 lateral position vs distance travelled
    runs = [("F3-RHT-RHT_BASE", BLUE, "-", "RHT world, RHT rules"),
            ("F3-LHT-GB", ORANGE, "--", "LHT world, GB rules (mirrored)"),
            ("F3-LHT-RHT_BASE", AQUA, ":", "LHT world, RHT rules (not mirrored)")]
    for lane_t in (-8.75, -5.25, -1.75, 1.75, 5.25, 8.75):
        a1.axhline(lane_t, color=GRID, linewidth=0.8, linestyle=(0, (4, 4)))
    a1.axhline(0.0, color=INK2, linewidth=0.8)
    for rid, col, ls, lab in runs:
        s = load(rid)
        x0 = s["x"][0]
        xs = [x - x0 for x in s["x"]]
        a1.plot(xs, s["y"], color=col, linestyle=ls, linewidth=2.0, label=lab)
        a1.text(xs[-1] + 8, s["y"][-1], lab.split(",")[0] + ("" if "not" not in lab else " (unmirrored)"),
                color=INK2, fontsize=7.5, va="center")
    a1.text(5, 0.35, "centre line", color=INK2, fontsize=7)
    a1.set_xlim(0, max(load(runs[0][0])["x"]) - load(runs[0][0])["x"][0] + 170)
    a1.set_ylim(-10.5, 10.5)
    a1.set_xlabel("distance travelled [m]", color=INK2, fontsize=8.5)
    a1.set_ylabel("lateral position t [m] (+ = left of reference line)", color=INK2, fontsize=8.5)
    a1.set_title("F3 system-initiated overtaking lane change (esmini)", loc="left", fontsize=10, color=INK)
    style(a1)
    a1.legend(fontsize=7.5, frameon=False, loc="lower left")
    # ---- panel B: F1 kerb-side cut-in, ego acceleration
    for rid, col, ls, lab, off in (("F1-KS-sym-RHT", BLUE, "-", "two-sided cut-in detection", (-60, 10)),
                                   ("F1-KS-ove-RHT", ORANGE, "--", "overtaking-side-only detection", (10, -4))):
        s = load(rid)
        a2.plot(s["t"], s["a"], color=col, linestyle=ls, linewidth=2.0, label=lab)
        i = min(range(len(s["a"])), key=lambda k: s["a"][k])
        a2.annotate(f"min {s['a'][i]:.1f} m/s²", (s["t"][i], s["a"][i]), xytext=off, textcoords="offset points",
                    fontsize=7.5, color=INK2)
    a2.axvline(1.0, color=INK2, linewidth=0.8, linestyle=":")
    a2.text(1.05, 1.0, "cutter starts\nlane change", fontsize=7, color=INK2, va="top")
    a2.set_xlabel("time [s]", color=INK2, fontsize=8.5)
    a2.set_ylabel("ego acceleration [m/s²]", color=INK2, fontsize=8.5)
    a2.set_title("F1 cut-in from the kerb-side lane (esmini)", loc="left", fontsize=10, color=INK)
    a2.set_xlim(0, 8)
    style(a2)
    a2.legend(fontsize=7.5, frameon=False, loc="lower left")
    fig.text(0.01, 0.01, "Model-internal simulation (P9); controller and sensors are idealised.", fontsize=7,
             color=INK2)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    out = ROOT / "results" / "fig_mirror.png"
    fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
