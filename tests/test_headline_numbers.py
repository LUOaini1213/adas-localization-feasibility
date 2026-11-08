"""Pin the headline numbers of README.md to the committed result files, and check that the generated
tables and report.md are exactly what the scripts produce from those files.

Each number is asserted twice: once against the committed artifact it comes from, and once as text in
README.md, so neither side can drift without a test failing.  Values are the esmini results committed
under results/ (the Python-only fallback of run_sim.py writes to results/python_only/ instead).
"""
import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
README = (ROOT / "README.md").read_text(encoding="utf-8")


def read(p):
    with open(ROOT / p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def in_readme(*snippets):
    for s in snippets:
        assert s in README, f"README.md no longer states {s!r}"


@pytest.fixture(scope="module")
def feas():
    return read("results/feasibility.csv")


def cell(feas, rid, suite, cond):
    rows = [r for r in feas if r["编号"] == rid and r["方案"] == suite and r["工况"] == cond]
    assert len(rows) == 1, (rid, suite, cond)
    return rows[0]


def test_matrix_and_source_counts():
    m = read("regulation_matrix.csv")
    status = [r["核实状态"] for r in m]
    counts = (len(m), status.count("已核实"), status.count("部分核实"), status.count("未核实"))
    assert counts == (88, 71, 11, 6)
    assert len(read("data/sources.csv")) == 67
    assert len(read("lht_deltas.csv")) == 10
    in_readme("88 行（已核实 71、部分核实 11、未核实 6）", "来源 67 条", "| 10 项：", "88-row")


def test_suite_coverage_counts(feas):
    def n_ok(suite, cond):
        return sum(r["满足"] == "True" for r in feas if r["方案"] == suite and r["工况"] == cond)

    assert len({r["编号"] for r in feas}) == 25
    assert n_ok("1V1R", "晴天") == 13
    assert (n_ok("5R1V", "晴天"), n_ok("5R1V", "暴雨 50 mm/h")) == (23, 22)
    assert (n_ok("11V5R1L", "晴天"), n_ok("11V5R1L", "暴雨 50 mm/h")) == (24, 22)
    in_readme("（共 25 条）", "1V1R：晴天 13；5R1V：晴天 23、暴雨 50 mm/h 22；11V5R1L：晴天 24、暴雨 22")


def test_rain_and_range_headlines(feas):
    lc2 = cell(feas, "LC-2", "5R1V", "暴雨 50 mm/h")
    assert lc2["需求 m"] == "73.8" and lc2["满足"] == "False" and lc2["余量 m"] == "-4.9"
    corner = [r for r in read("results/rain_sweep.csv") if r["传感器"] == "角雷达远波瓣"]
    assert corner[0]["晴天量程 m"] == "80.0" and corner[0]["50 mm/h"] == "68.9"
    for suite in ("1V1R", "5R1V", "11V5R1L"):
        assert cell(feas, "ACC-4", suite, "晴天")["满足"] == "False"
    assert cell(feas, "ACC-4", "1V1R", "晴天")["需求 m"] == "349.1"
    acc5 = {s: cell(feas, "ACC-5", s, "晴天") for s in ("1V1R", "5R1V", "11V5R1L")}
    assert acc5["11V5R1L"]["需求 m"] == "209.3" and acc5["11V5R1L"]["余量 m"] == "38.8"
    assert [acc5[s]["满足"] for s in ("1V1R", "5R1V", "11V5R1L")] == ["False", "False", "True"]
    aeb_rain = [float(r["余量 m"]) for r in feas
                if r["方案"] == "1V1R" and r["工况"] == "暴雨 50 mm/h" and r["编号"].startswith("AEB")]
    assert len(aeb_rain) == 6 and min(aeb_rain) == 58.0
    in_readme("后向 73.8 m", "降到 68.9 m", "需要 349.1 m", "需要 209.3 m", "最小余量 58.0 m")


def test_simulation_headlines():
    s = json.loads((RES / "sim_summary.json").read_text(encoding="utf-8"))
    assert s["primary_backend"] == "esmini" and s["cross_backend"] == "python" and s["runs"] == 26
    assert s["mirror_pairs"] == 8 and s["mirror_all_identical"] is True and s["mirror_max_dx"] == 0.0
    assert s["backend_all_discrete_equal"] is True and round(s["backend_max_dx"], 2) == 0.12
    runs = {r["run_id"]: r for r in read("results/sim_runs.csv")}
    sym, one = runs["F1-KS-sym-RHT"], runs["F1-KS-ove-RHT"]
    late = round(float(one["t_detect_cutter_s"]) - float(sym["t_detect_cutter_s"]), 2)
    assert late == 0.98
    assert (sym["min_gap_m"], one["min_gap_m"]) == ("14.21", "5.77")
    assert (sym["max_decel_mps2"], one["max_decel_mps2"]) == ("3.5", "7.62")
    assert len(read("results/sim_mirror_check.csv")) == 8
    assert len(read("results/sim_backend_check.csv")) == 26
    in_readme("8 组右行 / 左行运行的轨迹逐点一致（偏差 0.0 m）", "晚 0.98 s", "从 14.21 m 降到 5.77 m",
              "从 3.5 m/s² 升到 7.62 m/s²", "26 次运行的离散结果全部一致，自车位置最大差 0.12 m")


def test_tables_and_report_regenerate_exactly():
    sys.path.insert(0, str(ROOT / "scripts"))
    import make_tables
    import sync_report

    tables = make_tables.build()
    assert tables == (RES / "tables.md").read_text(encoding="utf-8"), \
        "results/tables.md differs from make_tables.build(); run scripts/make_tables.py"
    report = (ROOT / "report.md").read_text(encoding="utf-8")
    new, n = sync_report.synchronise(report, sync_report.sections(tables))
    assert n == 15 and new == report, "report.md is out of sync; run scripts/sync_report.py"
