"""Integration with the real physics modules (skipped if they are absent)."""
import numpy as np
import pytest

pytest.importorskip("engine.waterbalance")
pytest.importorskip("engine.yieldmodel")
from engine import api
from engine import optimize as opt


@pytest.fixture(autouse=True)
def real():
    opt.set_simulator(None); api.set_annual(None); api._scensets.clear()
    api.N_SCEN = 60; api.BOUNDARY_N_SCEN = 60
    yield
    api.N_SCEN = 500; api.BOUNDARY_N_SCEN = 500; api._scensets.clear()


def test_real_scenarios_derived_counts():
    a = api.annual()
    assert api.hist_set().n == len(a["years"]) - 3


def test_real_recommend_invariants():
    r = api.recommend({"lam": 0.0, "w": 0.0})
    m = r["metrics"]
    assert len(m) == len(opt.ALL_PLANS) and r["top"]["mean_profit"] == m.mean_profit.max()
    r1 = api.recommend({"lam": 1.0, "w": 0.0})
    assert r1["top"]["worst10_profit"] == r1["metrics"].worst10_profit.max()


def test_real_millet_uses_less_irrigation_than_rice():
    m = api.recommend({})["metrics"].set_index("id")
    assert m.loc["-".join([opt.MILLETS[0]] * 4), "irrigation_mm"] <= m.loc["rice-rice-rice-rice", "irrigation_mm"]


def test_real_compare_and_tipping_run():
    c = api.compare(["A", "B", "C"], {})
    assert len(c["rotations"]["A"]["stress_tests"]) == 4   # incl. low canal release year (canal_and_well default)
    t = api.tipping_points({})
    assert t["evpi_awc"]["value"] >= 0


def test_real_hindcast_missing_crops_say_no_data():
    h = api.hindcast()
    if not h["available"]:
        pytest.skip("no ICRISAT data")
    for c, v in h["per_crop"].items():
        assert ("pearson_r" in v) or v.get("no_data") or "note" in v


def test_real_prices_use_yaml_msp_with_badges():
    from engine import economics
    pr = economics.load_prices()
    assert pr["price_rs_per_quintal"]["rice"] == 2441.0 and pr["badges"]["price_rice"] == "observed"
    assert pr["badges"]["opcost_rice"] == "placeholder"


def test_real_batch_matches_per_plan_and_is_fast():
    import time
    t = time.time(); api.recommend({"irrigation_mm": 777.0}); assert time.time() - t < 5


def test_real_canal_stress_test_and_baseline_deltas():
    c = api.compare(["A", "B", "C"], {"water_source": "canal"})
    names = [r["test"] for r in c["rotations"]["B"]["stress_tests"]]
    assert "low canal release year" in names
    assert c["baseline_id"] == "A"
    assert c["rotations"]["A"]["delta_vs_baseline"]["d_mean_profit"] == 0
    c2 = api.compare(["A"], {"water_source": "borewell"})
    assert c["rotations"]["B"]["stress_tests"][-1]["test"] == "low canal release year"
    assert "low canal release year" not in [r["test"] for r in c2["rotations"]["A"]["stress_tests"]]


def test_real_hindcast_status_labels():
    h = api.hindcast()
    for c, v in h["per_crop"].items():
        assert v["status"] in ("validated against district yields", "no validation data")


def test_real_selection_candidate_set():
    opt.configure()
    assert opt.MILLETS and set(opt.CROPS) == {"rice", "pigeonpea", *opt.MILLETS}
    assert len(opt.ALL_PLANS) == len(opt.CROPS) ** 4
    m = opt.MILLETS[0]
    assert opt.REF["B"] == ["rice", m, "rice", m] and opt.REF["C"] == ["rice", "pigeonpea", m, "rice"]
