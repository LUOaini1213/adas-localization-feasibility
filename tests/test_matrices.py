"""Checks on the curated CSVs: every row has a document, a clause and a known source; statuses use the
fixed vocabulary; the SOR template only references known ids; the generated tables resolve."""
import csv
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATUS = {"已核实", "部分核实", "未核实"}
REQ_STATUS = {"强制（已生效）", "强制（已立法、未生效）", "已决定、待立法", "若装配须合规", "接受 UN 认证（非装配强制）",
              "评级计分", "未见强制要求（仅限所查文件）", "未核实", "未加入", "认证依据", "规程背景（不计分）"}
FEATURE_KEYS = {"AEB-C2C", "AEB-VRU", "AEB-MC", "LSS", "ISA", "DMS", "EDR", "L2", "BSD", "RMA", "HV", "GEN"}
MARKETS = {"EU", "GB", "AU", "MY", "TH", "ID", "MY TH ID", "UN"}


def read(p):
    with open(ROOT / p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def sources():
    return {r["编号"] for r in read("data/sources.csv")}


def test_csvs_have_bom_and_consistent_columns():
    for p in ("regulation_matrix.csv", "lht_deltas.csv", "data/sources.csv", "data/sor_template.csv"):
        assert (ROOT / p).read_bytes().startswith(b"\xef\xbb\xbf"), p
        rows = read(p)
        assert rows and all(None not in r and all(v is not None for v in r.values()) for r in rows), p


def test_regulation_matrix_rows(sources):
    rows = read("regulation_matrix.csv")
    ids = [r["编号"] for r in rows]
    assert len(ids) == len(set(ids))
    for r in rows:
        assert r["市场"] in MARKETS, r["编号"]
        assert set(r["功能键"].split(";")) <= FEATURE_KEYS, r["编号"]
        assert r["要求状态"] in REQ_STATUS, r["编号"]
        assert r["核实状态"] in STATUS, r["编号"]
        assert r["文件"].strip() and r["条款"].strip(), r["编号"]          # document + clause in every row
        srcs = [s for s in r["来源"].split(";") if s]
        assert srcs and all(s in sources for s in srcs), r["编号"]
        if r["要求状态"] == "未核实":
            assert r["核实状态"] != "已核实", r["编号"]


def test_every_market_has_rows():
    rows = read("regulation_matrix.csv")
    for mk in ("EU", "GB", "AU", "MY", "TH", "ID"):
        assert any(r["市场"] == mk for r in rows), mk
    assert any(r["市场"] == "MY TH ID" for r in rows)


def test_deltas_complete(sources):
    rows = read("lht_deltas.csv")
    required = ["差异项", "适用市场", "事实依据", "受影响功能", "改动类型", "需要改什么", "验证方法"]
    titles = " ".join(r["差异项"] for r in rows)
    for word in ("超车", "环岛", "ISA", "车道线", "摩托车", "降雨"):     # the six items of the task
        assert word in titles, word
    for r in rows:
        assert all(r[k].strip() for k in required), r["编号"]
        assert r["核实状态"] in STATUS
        assert all(s in sources for s in r["来源"].split(";") if s), r["编号"]


def test_sor_template_references(sources):
    matrix = {r["编号"] for r in read("regulation_matrix.csv")}
    deltas = {r["编号"] for r in read("lht_deltas.csv")}
    for r in read("data/sor_template.csv"):
        assert r["优先级"].split("（")[0] in {"P0", "P1", "P2"}
        for ref in re.findall(r"\b(?:EU|GB|AU|MY|TH|ID|AN|UN)-\d{2}\b|\bD-\d{2}\b", r["依据"]):
            assert ref in matrix | deltas, (r["编号"], ref)


def test_generated_tables_resolve():
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_tables", ROOT / "scripts" / "make_tables.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not (ROOT / "results" / "sim_runs.csv").exists():
        pytest.skip("run scripts/run_feasibility.py and scripts/run_sim.py first")
    text = mod.build()
    assert "## 表 12  SOR" in text and not re.search(r"\{(REQ|FEAS|SIM|SIMDIFF|RAIN):", text)
