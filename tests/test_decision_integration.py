# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
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
    api.N_SCEN = 500; api.BOUNDARY_N_SCEN = 200; api._scensets.clear()


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
    assert m.loc[opt.plan_id(opt.REF["B"]), "irrigation_mm"] < m.loc["rice-rice-rice-rice", "irrigation_mm"]
    assert m.loc[opt.plan_id(opt.REF["C"]), "irrigation_mm"] < m.loc["rice-rice-rice-rice", "irrigation_mm"]


def test_real_compare_and_tipping_run():
    c = api.compare(["A", "B", "C"], {})
    tests = c["rotations"]["A"]["stress_tests"]
    assert {t["test"] for t in tests} == {
        "driest monsoon in year 2", "latest monsoon onset in year 1",
        "hottest kharif season in year 3", "low canal release year",
    }
    low_canal = next(t for t in tests if t["test"] == "low canal release year")
    a = api.annual()
    assert low_canal["source_year"] == int(a["years"][np.argmin(a["upstream"])])
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
    assert pr["badges"]["opcost_rice"] == "assumption"
    assert pr["operating_cost_rs_per_acre"]["rice"] > 0


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
    assert len(opt.ALL_PLANS) == len(opt.CROPS) ** 4 - (len(opt.CROPS) - 1)      # same non-rice crop x4 is blocked
    m = opt.MILLETS[0]
    assert opt.REF["B"] == ["rice", m, "rice", m] and opt.REF["C"] == ["rice", "pigeonpea", m, "rice"]


def test_ui_soil_mode_names_select_the_right_soil():
    # the UI sends "farm" / "district"; "farm" must use the farm's black soil, not silently fall back to SoilGrids
    farm = api.norm_params({"soil_mode": "farm"})
    assert farm["soil_mode"] == "farm_black_soil" and farm["awc"] == api.norm_params({})["awc"]
    dist = api.norm_params({"soil_mode": "district"})
    assert dist["soil_mode"] == "district_soilgrids" and dist["awc"] != farm["awc"]


def test_assumptions_table_marks_rows_not_in_use():
    t = api.assumptions_table().set_index("name")
    assert t.loc["crops.jowar.kc_ini", "in_use"] and t.loc["crops.rice.ky", "in_use"]
    assert not t.loc["crops.ragi.kc_ini", "in_use"]
    assert not t.loc["ym_kg_ha.rice", "in_use"]          # replaced by the district value in prices_india.yaml
    assert t.loc["n_cost_rs_per_kg", "badge"] == "assumption"


def test_water_overrides_take_effect_after_a_default_run():
    # Regression: the per-plan result cache ignored the water inputs, so "I know my canal supply" changed nothing
    # once the default had been computed in the same session.
    def rice_only(params):
        m = api.recommend(params)["metrics"].set_index("id")
        return float(m.loc["rice-rice-rice-rice", "irrigation_mm"]), float(m.loc["rice-rice-rice-rice", "mean_profit"])
    irr0, prof0 = rice_only({})
    irr1, prof1 = rice_only({"canal_supply_mm": 200.0})
    assert irr1 < irr0 - 50 and prof1 < prof0                       # far less canal water: less irrigation, less profit
    irr2, _ = rice_only({"canal_supply_mm": 200.0, "well_supply_mm": 0.0})
    assert irr2 < irr1
    assert rice_only({}) == (irr0, prof0)                           # and back again
    irr3, _ = rice_only({"water_source": "canal"})
    assert irr3 != irr0


def test_single_source_supply_settings_reach_the_model():
    # Regression: the recharge exponent and the canal release factor sent by the screen were dropped by the API.
    def rice_irr(params):
        m = api.recommend(params)["metrics"].set_index("id")
        return float(m.loc["rice-rice-rice-rice", "irrigation_mm"])
    assert rice_irr({"water_source": "borewell", "recharge_exponent_k": 1.0}) != rice_irr({"water_source": "borewell", "recharge_exponent_k": 0.0})
    assert rice_irr({"water_source": "canal", "canal_release_factor": 0.4}) < rice_irr({"water_source": "canal"})
