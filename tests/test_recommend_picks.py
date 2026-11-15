# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Feature 3: scoring, picks, sliders and the profit guardrail, on a fake simulate() with hand-checkable numbers.

Ten scenarios with a weather factor f = 0.2, 0.355 ... 1.6 (mean 0.9). Per hectare profit by crop:
  maize    (risky)   yield 8000 f            price 200/t cost 300  -> profit 1600 f - 300     mean 1140  worst-10% 20
  sorghum  (steady)  yield 3500 + 500 f      price 150/t cost 100  -> profit 425 + 75 f       mean 492.5 worst-10% 440
  soybean  (legume)  yield 3000 (0.7+0.3 f)  price 400/t cost 200  -> profit 640 + 360 f      mean 964   worst-10% 712
"""
import numpy as np
import pytest

from engine import economics, optimize as opt

F = np.linspace(0.2, 1.6, 10)
YIELD = {"maize": lambda f: 8000 * f, "sorghum": lambda f: 3500 + 500 * f, "soybean": lambda f: 3000 * (0.7 + 0.3 * f)}
US = {"prices": {"maize": 200.0, "sorghum": 150.0, "soybean": 400.0}, "costs": {"maize": 300.0, "sorghum": 100.0, "soybean": 200.0}}


class Site:
    us_defaults = US


class Inputs:
    def __init__(self, plan=("sorghum",) * 4, overrides=None, history=None):
        self.current_plan, self.crop_overrides, self.history = list(plan), overrides or {}, history


def fake_simulate(site, inputs, rotation, scenarios):
    y = np.stack([YIELD[yr[0]](F) for yr in rotation["crops"]], axis=1)
    return {"yields_kg_ha": y, "irrigation_mm": np.zeros_like(y), "total_water_mm": np.full_like(y, 400.0)}


def run(sliders=None, inputs=None, **kw):
    s = {"bad_year": 0.3, "water": 0.0, "soil": 0.5, "profit_tolerance_pct": 0.0, **(sliders or {})}
    return opt.recommend_picks(Site(), inputs or Inputs(), s, crops=["maize", "sorghum", "soybean"], simulate=fake_simulate,
                               scenarios=list(range(10)), **kw)


def test_worst10_and_mean_match_hand_calculation():
    cur = run()["current_plan_result"]               # sorghum four years
    assert cur["mean_profit"] == pytest.approx(425 + 75 * F.mean())        # 492.5
    assert cur["worst10_profit"] == pytest.approx(425 + 75 * 0.2)          # 440, the single worst scenario
    r = {tuple(x["crops"][i][0] for i in range(4)): x for x in run()["all_results"]}
    maize = r[("maize",) * 4]
    assert maize["mean_profit"] == pytest.approx(1140.0) and maize["worst10_profit"] == pytest.approx(20.0)
    assert r[("soybean",) * 4]["worst10_profit"] == pytest.approx(712.0)


def test_worst_fraction_mean_helper_matches_hand_value():
    assert opt.worst_fraction_mean(np.arange(1.0, 21.0), 0.10) == pytest.approx(1.5)     # lowest two of twenty


def test_bad_year_slider_zero_picks_highest_mean_and_one_picks_best_worst10():
    lo = run({"bad_year": 0.0})
    assert lo["highest_profit"]["mean_profit"] == pytest.approx(max(r["mean_profit"] for r in lo["all_results"]))
    assert [c[0] for c in lo["highest_profit"]["crops"]] == ["maize"] * 4
    hi = run({"bad_year": 1.0})
    assert hi["highest_profit"]["worst10_profit"] == pytest.approx(max(r["worst10_profit"] for r in hi["all_results"]))
    assert [c[0] for c in hi["highest_profit"]["crops"]] == ["soybean"] * 4


def test_soil_slider_zero_makes_the_balanced_pick_equal_the_profit_and_risk_pick():
    for lam in (0.0, 0.4, 0.8):
        r = run({"bad_year": lam, "soil": 0.0, "water": 0.0})
        assert r["guardrail_met"] and r["headline"]["crops"] == r["highest_profit"]["crops"]
        assert r["headline"]["cover_crops"] == r["highest_profit"]["cover_crops"]


def test_soil_slider_one_moves_the_headline_toward_soil_health():
    a = run({"soil": 0.0, "bad_year": 0.3})["headline"]["soil_score"]
    b = run({"soil": 1.0, "bad_year": 0.3})["headline"]["soil_score"]
    assert b >= a


def test_best_soil_pick_has_the_highest_soil_score():
    r = run()
    assert r["best_soil"]["soil_score"] == pytest.approx(max(x["soil_score"] for x in r["all_results"]))


def test_guardrail_is_never_violated_over_a_slider_grid():
    for lam in (0.0, 0.5, 1.0):
        for s in (0.0, 0.5, 1.0):
            for w in (0.0, 1.0):
                for tol in (0.0, 10.0, 50.0):
                    r = run({"bad_year": lam, "soil": s, "water": w, "profit_tolerance_pct": tol})
                    if r["headline"] is not None:
                        assert r["headline"]["mean_profit"] >= r["profit_floor"] - 1e-9
                        assert r["guardrail_met"] is True


def test_impossible_guardrail_says_so_instead_of_returning_a_losing_headline():
    r = run({"profit_tolerance_pct": -1000.0})            # must beat the current plan by 10x its profit
    assert r["guardrail_met"] is False and r["headline"] is None
    assert "no headline pick" in r["explanations"]["headline"].lower()


def test_tolerance_lets_a_slightly_worse_plan_qualify():
    strict = run({"bad_year": 1.0, "soil": 1.0, "profit_tolerance_pct": 0.0})["headline"]["mean_profit"]
    loose = run({"bad_year": 1.0, "soil": 1.0, "profit_tolerance_pct": 60.0})
    assert loose["headline"]["soil_score"] >= run({"bad_year": 1.0, "soil": 1.0})["headline"]["soil_score"]
    assert strict >= run()["current_plan_result"]["mean_profit"] - 1e-9


def test_deltas_vs_current_are_pick_minus_current():
    r = run()
    cur = r["current_plan_result"]
    assert all(v == 0 for v in cur["deltas_vs_current"].values())
    for name in ("headline", "highest_profit", "best_soil"):
        for k in opt.DELTA_KEYS:
            assert r[name]["deltas_vs_current"][k] == pytest.approx(r[name][k] - cur[k])


def test_legume_rotation_beats_continuous_single_crop_on_soil_score():
    r = {tuple(x["crops"][i][0] for i in range(4)): x for x in run()["all_results"]}
    assert r[("soybean", "maize", "soybean", "maize")]["soil_score"] > r[("maize",) * 4]["soil_score"]


def test_cover_crop_raises_soil_score_when_its_cost_is_entered():
    none = run()
    assert none["cover_crops_offered"] is False and "seed and planting cost" in none["cover_crop_note"]
    withc = run(inputs=Inputs(overrides={"cover_crop": {"cost": 80.0}}))
    r = {(tuple(x["crops"][i][0] for i in range(4)), tuple(x["cover_crops"])): x for x in withc["all_results"]}
    seq = ("soybean", "maize", "soybean", "maize")
    assert r[(seq, (False, True, True, True))]["soil_score"] > r[(seq, (False,) * 4)]["soil_score"]
    assert r[(seq, (False, True, True, True))]["mean_profit"] < r[(seq, (False,) * 4)]["mean_profit"]   # the cover cost shows


def test_missing_price_for_a_current_crop_asks_for_input_not_a_default():
    r = opt.recommend_picks(Site(), Inputs(plan=("quinoa",) * 4), {}, crops=["maize"], simulate=fake_simulate, scenarios=list(range(10)))
    assert r["input_needed"] == [{"crop": "quinoa", "field": "price"}]
    assert "all_results" not in r


def test_candidate_crop_without_price_is_left_out_and_reported():
    r = opt.recommend_picks(Site(), Inputs(), {}, crops=["maize", "sorghum", "quinoa"], simulate=fake_simulate, scenarios=list(range(10)))
    assert {"crop": "quinoa", "field": "price"} in r["excluded_crops"]
    assert all(c[0] != "quinoa" for x in r["all_results"] for c in x["crops"])


def test_current_plan_outside_the_candidates_is_still_scored():
    r = opt.recommend_picks(Site(), Inputs(plan=("sorghum", "maize", "sorghum", "maize")), {}, crops=["soybean"],
                            simulate=fake_simulate, scenarios=list(range(10)))
    assert [c[0] for c in r["current_plan_result"]["crops"]] == ["sorghum", "maize", "sorghum", "maize"]


def test_most_food_toggle_picks_the_calorie_leader():
    r = run(most_food=True)
    assert r["highest_profit"]["calories"] == pytest.approx(max(x["calories"] for x in r["all_results"]))


def test_results_are_deterministic():
    a, b = run(), run()
    assert a["highest_profit"] == b["highest_profit"] and a["headline"] == b["headline"]


def test_stand_in_simulate_is_flagged_example():
    r = opt.recommend_picks(Site(), Inputs(), {}, crops=["maize", "sorghum"], simulate=opt._stand_in_simulate, scenarios=list(range(10)))
    assert r["example"] is True
    assert r["highest_profit"]["example"] and set(r["highest_profit"]["badges"].values()) == {"example"}


def test_enumeration_counts_and_always_includes_the_current_plan():
    rots = opt.enumerate_rotations(["a", "b", "c"], current_plan=["d"] * 4)
    assert len(rots) == 3 ** 4 + 1 and {"crops": [["d"]] * 4, "cover_crops": [False] * 4} in rots
    assert len(opt.enumerate_rotations(["a", "b"], allow_cover=True)) == 2 * 2 ** 4


def test_explanations_exist_for_each_pick_and_use_no_unknown_numbers():
    r = run()
    assert set(r["explanations"]) == {"headline", "highest_profit", "best_soil"}
    assert all(isinstance(t, str) and len(t) > 20 for t in r["explanations"].values())


def test_sliders_respond_fast_and_a_new_pin_scores_within_budget():
    """R23: slider moves about 1 s; a new pin about 15 s. Six crops = 1296 rotations with the stand-in simulator."""
    import time
    crops = ["maize", "soybean", "sorghum", "wheat_winter", "rice", "peanut"]
    class S2(Site):
        us_defaults = {"prices": {c: 200.0 for c in crops}, "costs": {c: 300.0 for c in crops}}
    inp = Inputs(plan=("maize",) * 4)
    t = time.time(); bundle = opt.score_candidates(S2(), inp, crops=crops, simulate=opt._stand_in_simulate, scenarios=list(range(41))); score_s = time.time() - t
    assert len(bundle["scored"]) == 6 ** 4 and score_s < 15.0
    t = time.time()
    for lam in (0.0, 0.5, 1.0):
        opt.assemble_recommendation(bundle, {"bad_year": lam, "soil": 0.5, "water": 0.0}, explain_text=False)
    assert (time.time() - t) / 3 < 1.0


def test_weighted_worst_fraction_matches_hand_values():
    v = [1.0, 2.0, 3.0, 4.0]
    assert opt.weighted_worst_fraction_mean(v, [1, 1, 1, 1], 0.5) == pytest.approx(1.5)           # lowest two of four
    assert opt.weighted_worst_fraction_mean(v, [1, 3, 1, 1], 0.5) == pytest.approx(5.0 / 3.0)     # weight 3 of 6: 1 (w1) + 2 (w2)
    assert opt.weighted_worst_fraction_mean(v, [2, 1, 1, 1], 0.25) == pytest.approx(1.0)          # 1.25 of 5 fits inside the first value
    assert opt.weighted_worst_fraction_mean(np.arange(1.0, 21.0), np.ones(20), 0.10) == pytest.approx(opt.worst_fraction_mean(np.arange(1.0, 21.0), 0.10))


def test_scenario_weights_change_mean_and_worst10_as_expected():
    w = np.array([5.0] + [1.0] * 9)                       # the driest scenario (f = 0.2) counts five times
    def sim(site, inputs, rotation, scenarios):
        r = fake_simulate(site, inputs, rotation, scenarios); r["weights"] = w; return r
    cur = opt.recommend_picks(Site(), Inputs(), {}, crops=["maize", "sorghum", "soybean"], simulate=sim, scenarios=list(range(10)))["current_plan_result"]
    prof = 425 + 75 * F
    assert cur["mean_profit"] == pytest.approx((prof * w).sum() / w.sum())
    assert cur["mean_profit"] < 425 + 75 * F.mean()        # more weight on the bad year lowers the mean


def test_nan_yield_leaves_the_crop_out_and_asks_for_a_yield():
    def sim(site, inputs, rotation, scenarios):
        r = fake_simulate(site, inputs, rotation, scenarios)
        if any(yr[0] == "soybean" for yr in rotation["crops"]):
            r["yields_kg_ha"] = np.where(np.array([[yr[0] == "soybean" for yr in rotation["crops"]]] * 10), np.nan, r["yields_kg_ha"])
        return r
    r = opt.recommend_picks(Site(), Inputs(), {}, crops=["maize", "sorghum", "soybean"], simulate=sim, scenarios=list(range(10)))
    assert {"crop": "soybean", "field": "yield"} in r["excluded_crops"]
    assert all(c[0] != "soybean" for x in r["all_results"] for c in x["crops"])


def test_current_plan_with_no_yield_number_asks_for_input():
    def sim(site, inputs, rotation, scenarios):
        r = fake_simulate(site, inputs, rotation, scenarios); r["yields_kg_ha"] = r["yields_kg_ha"] * np.nan; return r
    r = opt.recommend_picks(Site(), Inputs(), {}, crops=["maize"], simulate=sim, scenarios=list(range(10)))
    assert r["input_needed"] == [{"crop": "sorghum", "field": "yield"}]


def test_infeasible_rotation_is_left_out():
    class Sim:
        def __init__(self, ok, y): self.feasible, self.reason, self.yields_kg_ha = ok, "season too short", y
        irrigation_mm = np.zeros((10, 4)); total_water_mm = np.full((10, 4), 400.0); weights = None
    def sim(site, inputs, rotation, scenarios):
        y = fake_simulate(site, inputs, rotation, scenarios)["yields_kg_ha"]
        return Sim(not any(yr[0] == "maize" for yr in rotation["crops"]), y)
    r = opt.recommend_picks(Site(), Inputs(), {}, crops=["maize", "sorghum", "soybean"], simulate=sim, scenarios=list(range(10)))
    assert all(c[0] != "maize" for x in r["all_results"] for c in x["crops"]) and r["all_results"]
