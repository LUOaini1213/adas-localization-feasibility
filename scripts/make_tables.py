"""Build results/tables.md and results/sor_summary.csv from the curated CSVs and the script outputs.

Run (after run_feasibility.py and run_sim.py):  python -X utf8 -B -I scripts/make_tables.py
Every number in the tables comes from results/*.csv, results/sim_summary.json or the curated CSVs;
the SOR template's {..} placeholders are filled from the same files.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from feasib import requirements as rq  # noqa: E402
from feasib.sensors import SENSOR_ASSUMPTIONS  # noqa: E402
from feasib.suites import SUITE_ASSUMPTIONS  # noqa: E402
from sim.controller import SIM_ASSUMPTIONS  # noqa: E402

RES = ROOT / "results"
MARKETS = ["EU", "GB", "AU", "MY", "TH", "ID"]
FEATURES = [("AEB-C2C", "AEB 车对车"), ("AEB-VRU", "AEB 行人/骑行者"), ("AEB-MC", "AEB 摩托车"),
            ("LSS", "车道支持 / ELKS"), ("ISA", "ISA / 限速"), ("DMS", "疲劳与分心 / DMS"), ("EDR", "EDR"),
            ("L2", "L2 / 变道"), ("BSD", "盲区"), ("RMA", "倒车检测"), ("HV", "重型车 AEB"), ("GEN", "总体与认证路径")]
SHORT = {"强制（已生效）": "强制", "强制（已立法、未生效）": "已立法", "已决定、待立法": "已决定待立法",
         "若装配须合规": "装配则须合规", "接受 UN 认证（非装配强制）": "接受 UN 认证", "评级计分": "评级",
         "未见强制要求（仅限所查文件）": "未见要求", "未核实": "未核实", "未加入": "未加入 1958 协定",
         "认证依据": "认证依据", "规程背景（不计分）": "背景"}
MOD_CN = {"radar": "雷达", "camera": "摄像头", "lidar": "激光雷达"}


def read(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def md_table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x).replace("|", "/").replace("\n", " ") for x in r) + " |")
    return "\n".join(out)


def mods_cn(s: str) -> str:
    return "+".join(MOD_CN.get(m, m) for m in s.split("+") if m) or "—"


class Data:
    def __init__(self):
        self.matrix = read(ROOT / "regulation_matrix.csv")
        self.deltas = read(ROOT / "lht_deltas.csv")
        self.sources = read(ROOT / "data" / "sources.csv")
        self.sor_t = read(ROOT / "data" / "sor_template.csv")
        self.reqs = {r.rid: r for r in rq.requirement_list()}
        self.feas = read(RES / "feasibility.csv")
        self.rain = read(RES / "rain_sweep.csv")
        self.curve = read(RES / "lc_rear_curve.csv")
        self.vsmin = read(RES / "r79_vsmin.csv")
        self.suites = read(RES / "suites.csv")
        self.sim = {r["run_id"]: r for r in read(RES / "sim_runs.csv")}
        self.mirror = read(RES / "sim_mirror_check.csv")
        self.backend = read(RES / "sim_backend_check.csv") if (RES / "sim_backend_check.csv").exists() else []
        self.sim_summary = json.loads((RES / "sim_summary.json").read_text(encoding="utf-8"))
        if self.sim_summary.get("primary_backend") != "esmini" or not self.backend:
            raise SystemExit("results/sim_summary.json is not from an esmini run (primary_backend="
                             f"{self.sim_summary.get('primary_backend')!r}); the tables are built from the committed "
                             "esmini results. Restore them with `git checkout -- results/` or rerun run_sim.py "
                             "--esmini-lib <esminiLib>.")

    def feas_row(self, rid, suite, cond):
        for r in self.feas:
            if r["编号"] == rid and r["方案"] == suite and r["工况"] == cond:
                return r
        raise KeyError((rid, suite, cond))


# ----------------------------------------------------------------------------- placeholders
def fill(text: str, d: Data) -> str:
    def rep(m):
        kind, arg = m.group(1), m.group(2).split(":")
        if kind == "REQ":
            r = d.reqs[arg[0]]
            if len(arg) == 1:
                return f"{r.required_m:.1f}"
            return f"{r.detail[arg[1]]}"
        if kind == "FEAS":
            row = d.feas_row(arg[0], arg[1], arg[2])
            field = {"margin_m": "余量 m", "modalities": "覆盖的模态", "covered": "满足"}[arg[3]]
            return mods_cn(row[field]) if arg[3] == "modalities" else row[field]
        if kind == "SIM":
            return d.sim[arg[0]][arg[1]]
        if kind == "SIMDIFF":
            return f"{float(d.sim[arg[0]][arg[2]]) - float(d.sim[arg[1]][arg[2]]):.2f}"
        if kind == "RAIN":
            for r in d.rain:
                if r["传感器"] == arg[0]:
                    return r[f"{arg[1]} mm/h"]
            raise KeyError(arg)
        raise KeyError(kind)

    out = re.sub(r"\{(REQ|FEAS|SIM|SIMDIFF|RAIN):([^}]*)\}", rep, text)
    if "{" in out and re.search(r"\{[A-Z]+:", out):
        raise ValueError(f"unresolved placeholder in: {out}")
    return out


def sor_rows(d: Data) -> list[dict]:
    return [{k: fill(v, d) for k, v in r.items()} for r in d.sor_t]


# ----------------------------------------------------------------------------- sections
def pivot(d: Data) -> str:
    rows = []
    for key, label in FEATURES:
        cells = []
        for mk in MARKETS:
            items = []
            for r in d.matrix:
                if key not in r["功能键"].split(";"):
                    continue
                if not (r["市场"] == mk or (mk in ("MY", "TH", "ID") and r["市场"] == "MY TH ID")):
                    continue
                node = f"（{r['节点']}）" if r["节点"] not in ("", "—") else ""
                items.append(f"{SHORT.get(r['要求状态'], r['要求状态'])}{node} {r['编号']}")
            cells.append("<br>".join(items) if items else "—")
        rows.append([label] + cells)
    return md_table(["功能"] + MARKETS, rows)


def unverified(d: Data) -> list[list]:
    out = []
    for r in d.matrix:
        if r["核实状态"] != "已核实":
            text = r["要求摘要"] + (f"（{r['备注']}）" if r["备注"] else "")
            out.append([r["编号"], r["功能"], r["核实状态"], text])
        elif "未核实" in r["备注"]:
            out.append([r["编号"], r["功能"], "已核实，但备注中有未核实项", r["备注"]])
    for r in d.deltas:
        if r["核实状态"] != "已核实" or "未核实" in r["备注"]:
            out.append([r["编号"], r["差异项"], r["核实状态"], r["备注"]])
    return out


def cutin_budget_table(d: Data) -> str:
    sense = rq.T_SENSE_S + rq.T_CONFIRM_S
    rows = []
    for rid, r in d.reqs.items():
        if not rid.startswith("CUT"):
            continue
        t = r.detail.get("t_to_line_s", r.detail.get("t_to_path_s"))
        basis = "到车道线" if "t_to_line_s" in r.detail else "到本车路径"
        rows.append([rid, r.case, f"{basis} {t:.2f}", f"{sense:.2f}", f"{t - sense:.2f}"])
    return (md_table(["编号", "工况", "横向 1.0 m/s 时可用时间 s", "感知 + 确认 s（A-02）", "剩余决策与执行时间 s"], rows)
            + "\n\n轿车按近侧边缘到车道线计（A-07），摩托车穿行按近侧边缘到本车路径（半车宽）计（A-08）。")


def feas_table(d: Data) -> str:
    suites = ["1V1R", "5R1V", "11V5R1L"]
    rows = []
    for rid, r in d.reqs.items():
        cells = []
        for s in suites:
            parts = []
            for cond in ("晴天", "暴雨 50 mm/h"):
                f = d.feas_row(rid, s, cond)
                if f["满足"] == "True":
                    parts.append(f"✓ +{float(f['余量 m']):.1f}")
                elif f["余量 m"] in ("nan", ""):
                    parts.append("✗ 不在视场内")
                else:
                    parts.append(f"✗ {float(f['余量 m']):.1f}")
            clear = d.feas_row(rid, s, "晴天")
            cells.append(f"{parts[0]} / {parts[1]}（{mods_cn(clear['覆盖的模态'])}）")
        need = f"{r.required_m:.1f} m" + (f"，±{r.detail['half_fov_deg']}°" if "half_fov_deg" in r.detail else "")
        rows.append([rid, r.function, r.case, need] + cells)
    return md_table(["编号", "功能", "工况", "需求（距离；视场为半角）"] + [f"{s}：晴天 / 暴雨" for s in suites], rows)


def feas_summary(d: Data) -> str:
    conds = ["晴天", "暴雨 50 mm/h", "暴雨 50 mm/h + 水膜 3 dB"]
    rows = []
    for s in ("1V1R", "5R1V", "11V5R1L"):
        row = [s]
        for c in conds:
            sub = [r for r in d.feas if r["方案"] == s and r["工况"] == c]
            fail = [r["编号"] for r in sub if r["满足"] != "True"]
            row.append(f"{len(sub) - len(fail)}/{len(sub)}（不满足：{'、'.join(fail) or '无'}）")
        rows.append(row)
    return md_table(["方案"] + [f"{c} 满足数" for c in conds], rows)


def latency_table(d: Data) -> str:
    rows = []
    for rid, r in d.reqs.items():
        if r.function not in ("AEB", "AEB 摩托车"):
            continue
        row = [rid, r.case]
        for s in ("1V1R", "5R1V", "11V5R1L"):
            a, b = d.feas_row(rid, s, "晴天"), d.feas_row(rid, s, "暴雨 50 mm/h")
            row.append(f"{a['允许总时延 s']} / {b['允许总时延 s']}")
        rows.append(row)
    total = rq.T_SENSE_S + rq.T_CONFIRM_S + rq.T_ACT_S
    return (md_table(["编号", "工况", "1V1R 晴天/暴雨 s", "5R1V 晴天/暴雨 s", "11V5R1L 晴天/暴雨 s"], rows)
            + f"\n\n假设的总时延为 {total:.2f} s（感知 {rq.T_SENSE_S} + 确认 {rq.T_CONFIRM_S} + 执行 {rq.T_ACT_S}，A-02/A-03）。"
              "表中是在各方案最远探测距离下、为满足该工况还能容忍的总时延。")


def sim_tables(d: Data) -> str:
    s = d.sim
    f1 = [[k, v["world"], v["rules"], "对称" if v["cutin_mode"] == "symmetric" else "只看超车侧",
           "是" if v["mirrored_ok"] == "True" else "否（未镜像）", v["t_detect_cutter_s"], v["min_gap_m"],
           v["min_ttc_s"] or "—", v["max_decel_mps2"], v["min_speed_kph"], "是" if v["collision"] == "True" else "否"]
          for k, v in s.items() if k.startswith("F1")]
    f2 = [[k, v["world"], v["rules"], v["note"], "是" if v["inside_pass"] == "True" else "否",
           v["min_speed_kph"], v["max_decel_mps2"]] for k, v in s.items() if k.startswith("F2")]
    f3 = [[k, v["world"], v["rules"], v["note"], v["lc_side"], v["lc_start_s"], v["suppressed_by"] or "—",
           v["start_check"], "是（" + v["inside_pass_vehicle"] + "）" if v["inside_pass"] == "True" else "否",
           v["normal_pass"] or "—", v["max_lat_acc_mps2"]] for k, v in s.items() if k.startswith("F3")]
    txt = ["**F1 切入**（切入车 1.0 s 开始变道，2.0 s 起以 5 m/s² 减速到 40 km/h；检测时刻从切入车开始变道起算）\n",
           md_table(["运行", "世界", "规则集", "切入检测", "镜像正确", "检测时刻 s", "最小间距 m", "最小 TTC s",
                     "最大减速度 m/s²", "最低车速 km/h", "碰撞"], f1),
           "\n\n**F2 超车道有慢车：是否从内侧超越**\n",
           md_table(["运行", "世界", "规则集", "说明", "从内侧超越", "最低车速 km/h", "最大减速度 m/s²"], f2),
           "\n\n**F3 系统发起超车变道（R171 6.2.4 后向检查）**\n",
           md_table(["运行", "世界", "规则集", "说明", "变道方向", "开始横移 s", "被抑制原因", "开始时的后向检查",
                     "从内侧超越", "正常超越", "最大横向加速度 m/s²"], f3)]
    return "\n".join(txt)


def check_tables(d: Data) -> str:
    m = md_table(list(d.mirror[0]), [list(r.values()) for r in d.mirror])
    sm = d.sim_summary
    txt = [m, f"\n镜像对 {sm['mirror_pairs']} 组，指标全部一致：{sm['mirror_all_identical']}；"
              f"最大轨迹偏差 Δx = {sm['mirror_max_dx']} m，Δ(镜像 y) = {sm['mirror_max_dy']} m。"]
    if d.backend:
        txt.append(f"\n**esmini 与纯 Python 后端**（{sm['runs']} 次运行）：离散结果（碰撞、内侧超越、变道方向与时刻、"
                   f"切入检测时刻）全部一致：{sm['backend_all_discrete_equal']}；最大 |Δx| = {sm['backend_max_dx']} m，"
                   f"最大 |Δv| = {sm['backend_max_dv']} m/s。逐次结果见 results/sim_backend_check.csv。")
    return "\n".join(txt)


def assumptions_table() -> str:
    allx = {**rq.ASSUMPTIONS, **SENSOR_ASSUMPTIONS, **SUITE_ASSUMPTIONS, **SIM_ASSUMPTIONS}
    return md_table(["编号", "假设"], [[k, v] for k, v in sorted(allx.items())])


def build() -> str:
    d = Data()
    sor = sor_rows(d)
    with open(RES / "sor_summary.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(sor[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(sor)
    srcs = {r["编号"] for r in d.sources}
    for r in d.matrix + d.deltas:
        for sid in filter(None, r["来源"].split(";")):
            if sid not in srcs:
                raise ValueError(f"{r['编号']}: unknown source {sid}")
    n_ver = sum(r["核实状态"] == "已核实" for r in d.matrix)
    parts = [
        "# adas-localization-feasibility（P9）结果表（由 scripts/make_tables.py 生成，请勿手改）\n",
        f"法规矩阵 {len(d.matrix)} 行（已核实 {n_ver}，部分核实 "
        f"{sum(r['核实状态'] == '部分核实' for r in d.matrix)}，未核实 {sum(r['核实状态'] == '未核实' for r in d.matrix)}）；"
        f"左行/右舵差异 {len(d.deltas)} 项；来源 {len(d.sources)} 条；需求 {len(d.reqs)} 条 × 方案 3 × 工况 3 = "
        f"{len(d.feas)} 项检查；仿真 {d.sim_summary['runs']} 次。\n",
        "## 表 1  市场 × 功能：法规与评级要求（细节与条款见 regulation_matrix.csv）\n",
        "状态简写：强制 = 已对新车生效；已立法 = 法规已发布但日期未到；已决定待立法 = 政府已决定、法律文本未出；"
        "接受 UN 认证 = 1958 协定下接受按该法规颁发的认证，不等于强制装配；未见要求 = 仅限所查文件。括号内为关键日期。\n",
        pivot(d),
        "\n\n## 表 2  UNECE 技术法规中与本地化相关的条款\n",
        md_table(["编号", "内容", "条款", "核实"], [[r["编号"], r["要求摘要"], r["条款"], r["核实状态"]]
                                                for r in d.matrix if r["市场"] == "UN"]),
        "\n\n## 表 3  左行 / 右舵与本地环境差异（详见 lht_deltas.csv）\n",
        md_table(["编号", "差异项", "受影响功能", "改动类型", "验证方法", "本项目证据"],
                 [[r["编号"], r["差异项"], r["受影响功能"], r["改动类型"], r["验证方法"], r["本项目证据"]]
                  for r in d.deltas]),
        "\n\n## 表 4  功能需求推导（feasib/requirements.py）\n",
        md_table(["编号", "功能", "工况", "需求 m", "半视场角 °", "依据", "重点市场"],
                 [[r.rid, r.function, r.case, f"{r.required_m:.1f}", r.detail.get("half_fov_deg", ""), r.basis,
                   r.markets] for r in d.reqs.values()]),
        "\n\n## 表 5  参考方案\n",
        md_table(["方案", "说明", "摄像头", "毫米波雷达", "激光雷达", "相对成本档"],
                 [[s["方案"], s["说明"], s["摄像头"], s["毫米波雷达"], s["激光雷达"], s["相对成本档"]] for s in d.suites]),
        "\n\n相对成本档按 A-20 的规则给出，只比较高低，不代表价格。各传感器波瓣与来源见 results/suites.csv。\n",
        "\n## 表 6  可行性：需求 × 方案（✓ 满足，后面是余量 m；✗ 不满足，后面是缺口 m）\n",
        feas_table(d),
        "\n\n括号内是晴天时覆盖该点的模态。50 mm/h 加 3 dB 水膜的逐项结果见 results/feasibility.csv。\n",
        "\n**汇总：各方案满足的需求数（共 25 条）**\n",
        feas_summary(d),
        "\n## 表 7  时延预算\n",
        "**AEB：各方案最远探测距离下还能容忍的总时延（s）**\n",
        latency_table(d),
        "\n\n**切入：从目标开始横移到进入车道线或本车路径的时间预算**\n",
        cutin_budget_table(d),
        "\n\n## 表 8  降雨敏感性：有效探测距离（m，轿车目标）\n",
        md_table(list(d.rain[0]), [list(r.values()) for r in d.rain]),
        "\n\n雷达一行按 ITU-R P.838-3（77 GHz）计算路径衰减；激光雷达与摄像头是假设（A-13、A-14）。\n",
        "\n## 表 9  变道后向需求（来车 130 km/h，R171 6.2.4.1）与 R79 最低变道车速\n",
        md_table(list(d.curve[0]), [list(r.values()) for r in d.curve]),
        "\n\n" + md_table(list(d.vsmin[0]), [list(r.values()) for r in d.vsmin]),
        "\n\n## 表 10  镜像仿真结果（esmini，模型内）\n",
        sim_tables(d),
        "\n\n## 表 11  镜像检查与后端一致性\n",
        check_tables(d),
        "\n\n## 表 12  SOR 一页表：市场 × 功能 → 需求差异 → 可行性 / 验证 → 优先级\n",
        "优先级：P0 = 不做会影响准入或核心评级；P1 = 明显影响评级或需要较大工程改动；P2 = 改善项。\n",
        md_table(list(sor[0]), [list(r.values()) for r in sor]),
        "\n\n## 表 13  假设清单\n",
        assumptions_table(),
        "\n\n## 表 14  未核实与部分核实清单\n",
        md_table(["编号", "项目", "状态", "说明"], unverified(d)),
        "\n\n## 表 15  来源清单\n",
        md_table(["编号", "文件", "版本或日期", "核实方式", "URL"],
                 [[r["编号"], r["文件"], r["版本或日期"], r["核实方式"], r["URL"]] for r in d.sources]),
        "",
    ]
    return "\n".join(parts)


def main() -> int:
    text = build()
    with open(RES / "tables.md", "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"wrote results/tables.md ({len(text.splitlines())} lines) and results/sor_summary.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
