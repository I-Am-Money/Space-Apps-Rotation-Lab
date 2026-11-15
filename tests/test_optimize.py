# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
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
    cur = r["three_strategy_report"]["current"]          # bajra x4 is blocked by the team rule: compared, never recommended
    assert cur["evidence"]["offered"] is False and cur["evidence"]["rank"] == 0 and "comparison only" in cur["why"]
    assert r["top"]["id"] != "bajra-bajra-bajra-bajra" and bool(r["top"]["offered"])
    assert int(r["metrics"]["offered"].sum()) == len(opt.ALL_PLANS)


def test_economics_units_and_no_water_charge():
    sim = fake_simulate_plan(api.boot_set().scen, ["rice"] * 4, 140, 500)
    pr = economics.load_prices()
    e = economics.plan_economics(["rice"] * 4, sim, 1.0, pr, n_credit=np.zeros(4))
    # rice yield is milled rice; it is sold as paddy (yield / milled_rice_per_paddy) at the paddy MSP
    expect = sim["yield_kg_ha"] / pr["milled_rice_per_paddy"] * economics.HA_PER_ACRE * pr["price_rs_per_quintal"]["rice"] / 100
    assert np.allclose(e["revenue"], expect)
    # v3 section 5.7: profit = revenue - operating cost (+ N saving); no irrigation or water charge
    assert np.allclose(e["profit_year"], e["revenue"] - pr["operating_cost_rs_per_acre"]["rice"])
    assert "irrigation_cost" not in e and "irrigation_cost_rs_per_m3" not in pr
    e2 = economics.plan_economics(["rice"] * 4, sim, 2.0, pr, n_credit=np.zeros(4))
    assert np.allclose(e2["revenue"], 2 * e["revenue"])
    ec = economics.plan_economics(["rice"] * 4, sim, 1.0, pr, n_credit=np.full(4, 30.0))
    assert np.all(ec["profit"] > e["profit"])


def test_millet_plan_uses_less_irrigation_than_rice_only():
    s, df = api._table(api.norm_params())
    a = df[df.id == "rice-rice-rice-rice"].iloc[0]; m = df[df.id == opt.plan_id(opt.REF["B"])].iloc[0]
    assert m.irrigation_mm < a.irrigation_mm


def test_water_slider_never_picks_a_thirstier_plan():
    p = api.norm_params({"lam": 0.3})
    ss, df = api._table(p)
    irr = [opt.offered(opt.rescore(df, 0.3, w)).sort_values("J", ascending=False).iloc[0].irrigation_mm for w in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert all(b <= a + 1e-9 for a, b in zip(irr, irr[1:]))


def test_objective_matches_v3_formula_by_hand():
    # J = (1 - lam) * mean + lam * worst10 - w * irrigation * water_price_proxy
    assert opt.objective(1000.0, 400.0, 500.0, 0.25, 0.5, 2.0) == 0.75 * 1000 + 0.25 * 400 - 0.5 * 500 * 2.0


def test_candidate_set_follows_selection_and_refs():
    opt.configure(["ragi"])
    try:
        # 3 crops, 4 years = 81 rotations, minus pigeonpea x4 and ragi x4 (team rule: same non-rice crop 4 years running)
        assert len(opt.ALL_PLANS) == 79 and set(opt.CROPS) == {"rice", "pigeonpea", "ragi"}
        assert ["rice"] * 4 in opt.ALL_PLANS and ["ragi"] * 4 not in opt.ALL_PLANS and ["pigeonpea"] * 4 not in opt.ALL_PLANS
        assert opt.REF["B"] == ["rice", "ragi", "rice", "ragi"] and opt.REF["C"] == ["rice", "pigeonpea", "ragi", "rice"]
    finally:
        opt.configure(None) if False else None
        opt._SEL_MTIME = None; opt.CROPS = []; opt.configure()


def test_current_defaults_to_A_and_water_source_flag():
    r = api.recommend({"water_source": "unset"})
    assert r["params"]["current_rotation"] == ["rice"] * 4
    assert r["water_source"]["confirm_required"] and "confirm your rice water source" in r["water_source"]["flag"]
    assert set(r["three_strategy_report"]) == {"A", "B", "C"}


def test_combine_profit_worst10_is_not_mix_of_worst10s():
    # two rotations with opposite scenario luck: 10 scenarios; A bad in scenario 0, B bad in scenario 1
    pa = np.array([0., 10, 10, 10, 10, 10, 10, 10, 10, 10])
    pb = np.array([10., 0, 10, 10, 10, 10, 10, 10, 10, 10])
    tot = opt.combine_profit(pa, pb, 2)          # rows: 0, 1, 2 acres in rice
    w = np.array([opt.worst_fraction_mean(r) for r in tot])
    mix_of_worst = 1 * opt.worst_fraction_mean(pa) + 1 * opt.worst_fraction_mean(pb)   # 0 + 0
    assert w[1] == 10.0 and mix_of_worst == 0.0 and w[1] > mix_of_worst
    assert w[0] == opt.worst_fraction_mean(2 * pb) and w[2] == opt.worst_fraction_mean(2 * pa)


def test_land_split_all_rice_equals_A_times_acres_and_totals():
    farm = api.farm_info()
    N = int(farm["acres"])
    ls = api.land_split("B", {"irrigation_mm": 400})
    c = api.compare(["A"], {"irrigation_mm": 400})["rotations"]["A"]
    assert ls["acres_rice"][0] == 0 and ls["acres_rice"][-1] == N and ls["baseline_index"] == N
    assert abs(ls["total_profit_mean"][-1] - c["mean_profit"] * N) < 1e-6
    assert abs(ls["total_profit_worst10"][-1] - c["worst10_profit"] * N) < 1e-6
    m3 = farm["m3_per_acre_per_mm"]
    assert abs(ls["total_irrigation_m3"][-1] - c["irrigation_mm"] * N * m3) < 1e-6
    assert abs(ls["irrigation_canal_m3"][-1] + ls["irrigation_well_m3"][-1] - ls["total_irrigation_m3"][-1]) < 1e-6
    assert ls["delta_vs_baseline"]["total_profit_mean"][N] == 0
    assert abs(c["farm_totals"]["total_profit_mean"] - c["mean_profit"] * N) < 1e-6
    # linear in acres for means
    mid = ls["total_profit_mean"][N // 2]
    assert abs(mid - (ls["total_profit_mean"][0] + ls["total_profit_mean"][N]) / 2) < 1e-6 or N % 2 == 1


def test_land_split_fast_when_cached():
    import time
    api.land_split("C", {"irrigation_mm": 400})
    t = time.time(); api.land_split("C", {"irrigation_mm": 400}); assert time.time() - t < 0.5
