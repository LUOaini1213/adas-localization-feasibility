"""Calculator tests: regulatory formulas against hand calculations, rain model, coverage geometry."""
import math

import pytest

from feasib import requirements as rq
from feasib.feasibility import check, rain_sweep, run_all
from feasib.sensors import ITU_77GHZ, Sensor, effective_range, rain_gamma_db_per_km
from feasib.suites import reference_suites

KPH = 1 / 3.6


def test_r171_rear_gap_hand_calculation():
    # own 80 km/h, approaching 130 km/h, A = 0.4 s (R171 6.2.4.1(i)), a = 3 m/s2, 1 s gap
    dv = 50 * KPH
    expected = dv * 0.4 + dv ** 2 / 6.0 + 80 * KPH * 1.0
    assert rq.lane_change_rear_required(80, 130, 0.4) == pytest.approx(expected)
    assert expected == pytest.approx(59.93, abs=0.01)
    # A = 1.4 s if the approaching vehicle was not tracked for 1 s (6.2.4.1(ii))
    assert rq.lane_change_rear_required(80, 130, 1.4) == pytest.approx(expected + dv * 1.0)


def test_r171_equals_r79_critical_distance_structure():
    # R79 5.6.4.7: S = (v_rear - v)*tB + (v_rear - v)^2/(2a) + v*tG with tB = 0.4, tG = 1, a = 3
    for v_e, v_r in ((60, 130), (90, 120), (100, 130)):
        d = (v_r - v_e) * KPH
        s79 = d * rq.R79_TB_S + d * d / (2 * rq.R79_A_MPS2) + v_e * KPH * rq.R79_TG_S
        assert rq.lane_change_rear_required(v_e, v_r, rq.R171_A_TRACKED_S) == pytest.approx(s79)


def test_r79_vsmin_inverts_the_critical_distance():
    for s_rear in (55.0, 70.0, 100.0):
        v = rq.r79_vsmin_mps(s_rear)
        assert rq.lane_change_rear_required(v / KPH, rq.R79_VAPP_MPS / KPH, 0.4) == pytest.approx(s_rear, abs=1e-6)
    assert rq.r79_vsmin_mps(55.0) * 3.6 == pytest.approx(84.6, abs=0.05)
    assert rq.r79_vsmin_mps(100.0) < rq.r79_vsmin_mps(55.0)        # longer rear range -> lower minimum speed


def test_r171_assumed_approach_speed():
    gb = rq.GB_MOTORWAY_LIMIT_KPH                                     # 70 mph
    assert gb == pytest.approx(112.65, abs=0.01)
    assert rq.r171_assumed_approach_kph(gb, driver_confirmed=False) == pytest.approx(112.65, abs=0.01)
    assert rq.r171_assumed_approach_kph(gb, driver_confirmed=True) == pytest.approx(123.92, abs=0.01)
    assert rq.r171_assumed_approach_kph(None, driver_confirmed=False) == 130.0
    assert rq.r171_assumed_approach_kph(130.0, driver_confirmed=True) == 130.0   # capped


def test_aeb_and_acc_ranges():
    v = 80 * KPH                                                      # CCRs 80 with FCW lead 0.8 s, 6 m/s2
    expected = v * (0.15 + 0.2 + 0.8 + 0.2) + v * v / 12.0 + 2.0
    assert rq.aeb_required_range(80, 0, fcw_lead_s=0.8) == pytest.approx(expected)
    # the latency budget is the inverse of the range requirement
    d = rq.aeb_required_range(80, 0, fcw_lead_s=0.8)
    assert rq.aeb_latency_budget(d, 80, 0, fcw_lead_s=0.8) == pytest.approx(0.55)
    # ACC: 130 km/h to standstill at 2.0 m/s2, 0.5 s latency, 5 m stopping gap
    v = 130 * KPH
    assert rq.acc_required_range(130, 0) == pytest.approx(v * 0.5 + v * v / 4.0 + 5.0)


def test_cutin_geometry():
    assert rq.half_fov_deg(2.0, 2.6) == pytest.approx(52.43, abs=0.01)
    assert rq.cutin_time_to_line_s(2.6) == pytest.approx(0.85)
    assert rq.cutin_time_to_path_s(1.35) == pytest.approx(0.425)


def test_requirement_ids_unique_and_basis_present():
    reqs = rq.requirement_list()
    assert len({r.rid for r in reqs}) == len(reqs) == 25
    assert all(r.basis for r in reqs)


def test_itu_coefficients_and_rain_monotonic():
    assert ITU_77GHZ["kH"] == 1.1320 and ITU_77GHZ["aH"] == 0.7177            # ITU-R P.838-3 Table 5
    assert rain_gamma_db_per_km(100.0) == pytest.approx(1.1320 * 100 ** 0.7177)
    for mod in ("radar", "lidar", "camera"):
        rs = [effective_range(mod, 150.0, r) for r in (0, 10, 25, 50, 100)]
        assert rs[0] == 150.0 and all(a > b for a, b in zip(rs, rs[1:]))
    # radar: range^4 law with two-way path loss is self-consistent at the solution
    r = effective_range("radar", 200.0, 50.0)
    loss_db = 2 * rain_gamma_db_per_km(50.0) * r / 1000.0
    assert 40 * math.log10(200.0 / r) == pytest.approx(loss_db, abs=1e-4)
    # lidar assumption A-13 is calibrated to about 20 % loss at 25 mm/h for 210 m
    assert effective_range("lidar", 210.0, 25.0) / 210.0 == pytest.approx(0.80, abs=0.01)


def test_target_factor_motorcycle():
    assert effective_range("radar", 100.0, 0.0, target="motorcycle") == pytest.approx(70.0)


def test_sensor_bearing_and_lobes():
    s = Sensor("t", "radar", 0.0, 0.0, 0.0, ((200.0, 9.0), (60.0, 60.0)), "x")
    assert s.available_range(150.0, 0.0)[0] == 200.0               # far lobe
    avail, dist = s.available_range(30.0, 30.0)                     # 45 deg: only the wide lobe
    assert avail == 60.0 and dist == pytest.approx(math.hypot(30, 30))
    assert s.available_range(-10.0, 0.0)[0] == 0.0                  # behind: no lobe
    rear = Sensor("r", "radar", -4.7, 0.85, 135.0, ((80.0, 45.0),), "x")
    _, rel = rear.bearing(-4.7 - 60.0, 3.5)
    assert abs(rel) < 45.0                                          # adjacent lane 60 m behind is inside


def test_suites_cost_tiers_and_symmetry():
    tiers = {s.sid: s.cost_tier for s in reference_suites()}
    assert tiers == {"1V1R": 1, "5R1V": 2, "11V5R1L": 4}
    for s in reference_suites():                                    # left and right coverage identical
        for x, y in ((-60.0, 3.5), (-5.0, 2.0), (3.0, 2.6)):
            assert s.sensors and all(
                a.available_range(x, y)[0] == b.available_range(x, -y)[0]
                for a in s.sensors for b in s.sensors if a.name != b.name and a.lobes == b.lobes
                and a.x == b.x and a.y == -b.y and a.boresight_deg == -b.boresight_deg)


def test_key_feasibility_results():
    req = {r.rid: r for r in rq.requirement_list()}
    suites = {s.sid: s for s in reference_suites()}
    # no rear sensor in 1V1R: lane-change rear coverage and blind spot impossible
    assert not check(req["LC-1"], suites["1V1R"], "晴天").covered
    assert not check(req["BSD-1"], suites["1V1R"], "晴天").covered
    assert check(req["BSD-1"], suites["5R1V"], "晴天").covered
    # A = 1.4 s lane change at 80 km/h: covered in clear weather, lost in 50 mm/h rain (corner radar)
    assert check(req["LC-2"], suites["5R1V"], "晴天").covered
    assert not check(req["LC-2"], suites["5R1V"], "暴雨 50 mm/h").covered
    # ACC to a stationary vehicle at 130 km/h with comfort deceleration: beyond every suite
    assert not any(check(req["ACC-4"], s, c).covered for s in suites.values() for c in ("晴天",))
    # all AEB cases covered by the cheapest suite, also in rain
    for rid in ("AEB-1", "AEB-2", "AEB-3", "AEB-4", "AEB-5", "AEB-6"):
        assert check(req[rid], suites["1V1R"], "暴雨 50 mm/h").covered


def test_run_all_shape_and_rain_sweep():
    res = run_all()
    assert len(res) == 25 * 3 * 3
    sweep = {r["传感器"]: r for r in rain_sweep()}
    assert sweep["角雷达远波瓣"]["50 mm/h"] == pytest.approx(68.9, abs=0.05)
