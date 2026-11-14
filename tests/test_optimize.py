import numpy as np
import pytest
from engine import api, economics
from engine import optimize as opt
from tests.decision_fakes import fake_simulate_plan, synthetic_annual


@pytest.fixture(autouse=True)
def fake():
    opt.set_simulator(fake_simulate_plan)
    api.set_annual(synthetic_annual(30))
    api.N_SCEN = 80
    api.BOUNDARY_N_SCEN = 80
    api._scensets.clear()
    yield
    opt.set_simulator(None)
    api.set_annual(None)
    api.N_SCEN = 500


def test_worst10_hand_value():
    x = np.arange(1, 21, dtype=float)       # worst 10% = 2 lowest -> mean(1,2) = 1.5
    assert opt.worst_fraction_mean(x) == 1.5
    assert opt.worst_fraction_mean(np.array([5., 3., 9.])) == 3.0   # at least 1


def test_lam0_highest_mean_lam1_highest_worst10():
    p = api.norm_params({"w": 0.0})
    ss, df = api._table({**p, "lam": 0.0})
    top0 = opt.rescore(df, 0.0, 0.0).sort_values("J", ascending=False).iloc[0]
    assert top0.mean_profit == df.mean_profit.max()
    top1 = opt.rescore(df, 1.0, 0.0).sort_values("J", ascending=False).iloc[0]
    assert top1.worst10_profit == df.worst10_profit.max()
    assert len(df) == len(opt.ALL_PLANS)


def test_frontier_non_dominated():
    ss, df = api._table(api.norm_params())
    f = df[df.on_frontier]
    for _, r in f.iterrows():
        dom = df[(df.mean_profit > r.mean_profit + 1e-9) & (df.worst10_profit > r.worst10_profit + 1e-9)]
        assert dom.empty


def test_recommend_and_report_structure():
    r = api.recommend({"current_rotation": ["bajra"] * 4})
    assert set(r["three_strategy_report"]) == {"A", "B", "C", "current"}
    assert r["baseline_id"] == "A" and "d_mean_profit" in r["metrics"].columns
    a = r["metrics"][r["metrics"].id == "rice-rice-rice-rice"].iloc[0]
    assert a.d_mean_profit == 0 and r["top_delta_vs_baseline"]["d_mean_profit"] == r["top"]["mean_profit"] - a.mean_profit
    for v in r["three_strategy_report"].values():
        assert v["why"] and v["benefits"] and v["info_gaps"] and v["risks_for_local_review"] and v["evidence"]
    assert r["top"]["rank"] == 1


def test_economics_units_and_irrigation_cost():
    sim = fake_simulate_plan(api.boot_set().scen, ["rice"] * 4, 140, 500)
    pr = economics.load_prices()
    e = economics.plan_economics(["rice"] * 4, sim, 1.0, pr, n_credit=np.zeros(4))
    expect = sim["yield_kg_ha"] * economics.HA_PER_ACRE * pr["price_rs_per_quintal"]["rice"] / 100
    assert np.allclose(e["revenue"], expect)
    e2 = economics.plan_economics(["rice"] * 4, sim, 2.0, pr, n_credit=np.zeros(4))
    assert np.allclose(e2["revenue"], 2 * e["revenue"])
    ec = economics.plan_economics(["rice"] * 4, sim, 1.0, pr, n_credit=np.full(4, 30.0))
    assert np.all(ec["profit"] > e["profit"])


def test_less_irrigation_cost_for_millet_plan():
    s, df = api._table(api.norm_params())
    a = df[df.id == "rice-rice-rice-rice"].iloc[0]; m = df[df.id == "-".join([opt.MILLETS[0]] * 4)].iloc[0]
    assert m.irrigation_mm < a.irrigation_mm


def test_candidate_set_follows_selection_and_refs():
    opt.configure(["ragi"])
    try:
        assert len(opt.ALL_PLANS) == 81 and set(opt.CROPS) == {"rice", "pigeonpea", "ragi"}
        assert opt.REF["B"] == ["rice", "ragi", "rice", "ragi"] and opt.REF["C"] == ["rice", "pigeonpea", "ragi", "rice"]
    finally:
        opt.configure(None) if False else None
        opt._SEL_MTIME = None; opt.CROPS = []; opt.configure()


def test_current_defaults_to_A_and_water_source_flag():
    r = api.recommend({"water_source": "unset"})
    assert r["params"]["current_rotation"] == ["rice"] * 4
    assert r["water_source"]["confirm_required"] and "confirm your rice water source" in r["water_source"]["flag"]
    assert set(r["three_strategy_report"]) == {"A", "B", "C"}
