"""Simulation tests: mirroring of the scenario files, controller side logic, mirror invariance, and
(when ESMINI_LIB points to esminiLib.dll) esmini against the Python backend."""
import math
import os
import xml.etree.ElementTree as ET

import pytest

from sim.controller import RULESETS, Controller, CtrlConfig
from sim.runner import run, run_list
from sim.scenario import SCEN_DIR, SIDES, lane_id, lane_ids_in_xosc, lane_t, scenario_specs, write_all

RUNS = {r.run_id: r for r in run_list()}


@pytest.fixture(scope="module", autouse=True)
def scenarios_written():
    write_all()


def test_lane_mapping_is_a_mirror():
    for k in (1, 2, 3):
        assert lane_id(k, "RHT") == -lane_id(k, "LHT") == -k
        assert lane_t(k, "RHT") == pytest.approx(-lane_t(k, "LHT"))
    assert lane_t(1, "RHT") == pytest.approx(-1.75) and lane_t(3, "LHT") == pytest.approx(8.75)


def test_written_files_are_mirrored():
    for side in SIDES:
        road = ET.parse(SCEN_DIR / f"road_{side}.xodr").getroot().find("road")
        assert road.get("rule") == side
    for spec in scenario_specs():
        rht = lane_ids_in_xosc(SCEN_DIR / f"{spec.case_id}_RHT.xosc")
        lht = lane_ids_in_xosc(SCEN_DIR / f"{spec.case_id}_LHT.xosc")
        assert rht == [-x for x in lht] and all(x < 0 for x in rht)


def test_controller_normalised_side():
    ctrl_r = Controller(CtrlConfig(RULESETS["RHT_BASE"]), [-1.75, -5.25, -8.75], 0.02)
    ctrl_l = Controller(CtrlConfig(RULESETS["GB"]), [1.75, 5.25, 8.75], 0.02)
    # a vehicle one lane towards the centre line is on the overtaking side in both worlds
    assert ctrl_r._eta(-1.75 - (-5.25)) > 0 and ctrl_l._eta(1.75 - 5.25) > 0
    assert RULESETS["AU"].undertaking_allowed and not RULESETS["GB"].undertaking_allowed


def test_rear_check_uses_r171_numbers():
    ctrl = Controller(CtrlConfig(RULESETS["GB"]), [1.75, 5.25, 8.75], 0.02)
    v = 80 / 3.6
    approacher = {"x": 0.0, "y": 1.75, "v": 130 / 3.6, "cx": 1.4, "length": 4.7, "width": 1.85}
    ctrl.tracks["A"] = type("T", (), {"first_seen": -5.0})()          # tracked for > 1 s -> A = 0.4 s
    e_rear = 3.75 + 40.0                                                # gap 40 m < 59.9 m needed
    ok, info = ctrl.rear_check(0.0, v, e_rear, 1.75, {"A": approacher})
    assert not ok and info["need"] == pytest.approx(59.9, abs=0.05) and info["A"] == 0.4
    ok, _ = ctrl.rear_check(0.0, v, 3.75 + 70.0, 1.75, {"A": approacher})
    assert ok


@pytest.mark.parametrize("rht,lht", [("F1-KS-ove-RHT", "F1-KS-ove-LHT"), ("F2-RHT-RHT_BASE", "F2-LHT-GB"),
                                     ("F3-RHT-RHT_BASE", "F3-LHT-GB")])
def test_mirror_invariance_python_backend(rht, lht):
    a = run(RUNS[rht], "python", record=True)
    b = run(RUNS[lht], "python", record=True)
    sa, sb = a["series"], b["series"]
    assert max(abs(x - y) for x, y in zip(sa["x"], sb["x"])) < 1e-9
    assert max(abs(x + y) for x, y in zip(sa["y"], sb["y"])) < 1e-9
    for k in ("min_gap_m", "inside_pass", "lc_side", "lc_start_s", "t_detect_cutter_s"):
        assert a[k] == b[k]


def test_unmirrored_logic_breaks_and_market_rules_differ():
    gb = run(RUNS["F2-LHT-GB"], "python")
    bad = run(RUNS["F2-LHT-RHT_BASE"], "python")
    au = run(RUNS["F2-LHT-AU"], "python")
    assert not gb["inside_pass"] and gb["min_speed_kph"] == pytest.approx(80.0, abs=0.5)
    assert bad["inside_pass"] and au["inside_pass"]
    f3_ok, f3_bad = run(RUNS["F3-LHT-GB"], "python"), run(RUNS["F3-LHT-RHT_BASE"], "python")
    assert f3_ok["lc_side"] == "超车侧" and not f3_ok["inside_pass"] and f3_ok["suppressed_by"]
    assert f3_bad["lc_side"] == "路缘侧" and f3_bad["inside_pass"]
    assert f3_ok["max_lat_acc_mps2"] <= 1.5                            # R171 6.2.3 additional lateral acc.


def test_one_sided_cutin_detection_is_late_for_kerb_side():
    sym = run(RUNS["F1-KS-sym-RHT"], "python")
    one = run(RUNS["F1-KS-ove-RHT"], "python")
    assert one["t_detect_cutter_s"] > sym["t_detect_cutter_s"] + 0.5
    assert one["min_gap_m"] < sym["min_gap_m"] and one["max_decel_mps2"] > sym["max_decel_mps2"]


def test_python_backend_collision_detection():
    from sim.python_backend import PythonBackend
    from sim.scenario import Actor, Spec
    spec = Spec("T", "t", "t", 2, 100.0, 10.0, (Actor("X", "car", 2, 104.0, 0.0),), t_end=1.0)
    be = PythonBackend(spec, "RHT")
    be.start("", ["X"], 0.02)
    be.advance(0.02, 100.0, lane_t(2, "RHT"), 0.0, 10.0)              # boxes overlap (4 m apart, 4.7 m long)
    assert be.collision


LIB = os.environ.get("ESMINI_LIB")


@pytest.mark.skipif(not LIB, reason="set ESMINI_LIB to esminiLib.dll to run the esmini cross-check")
def test_esmini_matches_python_and_mirrors():
    for rid in ("F1-KS-ove-RHT", "F3-LHT-GB", "F3-LHT-RHT_BASE"):
        e = run(RUNS[rid], "esmini", LIB, record=True)
        p = run(RUNS[rid], "python", record=True)
        for k in ("collision", "inside_pass", "lc_side", "lc_start_s", "t_detect_cutter_s"):
            assert e[k] == p[k]
        assert max(abs(a - b) for a, b in zip(e["series"]["x"], p["series"]["x"])) < 0.5
    a = run(RUNS["F3-RHT-RHT_BASE"], "esmini", LIB, record=True)
    b = run(RUNS["F3-LHT-GB"], "esmini", LIB, record=True)
    assert max(abs(x + y) for x, y in zip(a["series"]["y"], b["series"]["y"])) < 1e-9
    assert not math.isnan(a["max_lat_acc_mps2"])
