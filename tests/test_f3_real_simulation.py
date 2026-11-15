# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Feature 3 on Feature 2's real simulate_many(): synthetic weather, no network. Checks the whole chain:
candidate rotations -> simulation -> profit, risk, water, soil -> three picks -> value of information."""
import sys
import time
import types

import numpy as np
import pytest

sys.path.insert(0, "tests")
from test_p2_simulation import make_weather          # noqa: E402  (Feature 2's synthetic climate)

from engine import evpi, optimize as opt, scenarios as SC   # noqa: E402

CROPS = ["maize", "soybean", "sorghum"]
OVERRIDES = {"maize": {"yield": 10000, "price": 200.0, "cost": 1100.0}, "soybean": {"yield": 3500, "price": 430.0, "cost": 650.0},
             "sorghum": {"yield": 5000, "price": 190.0, "cost": 700.0}}


@pytest.fixture(scope="module")
def weather():
    return make_weather()


@pytest.fixture(scope="module")
def site(weather):
    return {"weather": weather, "lat": 41.0, "elevation_m": 300.0, "soil": {"awc_mm_per_m": 140.0, "hydrologic_group": "B"}, "us_defaults": None}


def inputs(plan=("maize",) * 4, overrides=None):
    return types.SimpleNamespace(current_plan=list(plan), crop_overrides=overrides or OVERRIDES, history=None,
                                 water={"mode": "rain", "normal_mm": None, "dry_mm": None})


@pytest.fixture(scope="module")
def scen(weather):
    return SC.bootstrap(weather, n=60)


@pytest.fixture(scope="module")
def bundle(site, scen):
    return opt.score_candidates(site, inputs(), crops=CROPS, scenarios=scen)


def test_real_simulation_is_used_and_not_flagged_example(bundle):
    assert bundle["example"] is False and len(bundle["scored"]) == 3 ** 4
    assert all(r["example"] is False for r in bundle["scored"])


def test_picks_from_the_real_simulation_are_consistent(bundle):
    cur = bundle["current"]
    for lam in (0.0, 0.5, 1.0):
        for soil in (0.0, 1.0):
            r = opt.assemble_recommendation(bundle, {"bad_year": lam, "soil": soil, "water": 0.0, "profit_tolerance_pct": 0.0}, explain_text=False)
            assert r["current_plan_result"] is cur
            if r["headline"] is not None:
                assert r["headline"]["mean_profit"] >= cur["mean_profit"] - 1e-9          # the guardrail
            assert r["best_soil"]["soil_score"] == pytest.approx(max(x["soil_score"] for x in r["all_results"]))
    lo = opt.assemble_recommendation(bundle, {"bad_year": 0.0, "soil": 0.0}, explain_text=False)
    assert lo["highest_profit"]["mean_profit"] == pytest.approx(max(x["mean_profit"] for x in lo["all_results"]))
    hi = opt.assemble_recommendation(bundle, {"bad_year": 1.0, "soil": 0.0}, explain_text=False)
    assert hi["highest_profit"]["worst10_profit"] == pytest.approx(max(x["worst10_profit"] for x in hi["all_results"]))


def test_worst10_is_never_above_the_mean_and_numbers_are_finite(bundle):
    for r in bundle["scored"]:
        assert r["worst10_profit"] <= r["mean_profit"] + 1e-9
        assert all(np.isfinite(r[k]) for k in ("mean_profit", "worst10_profit", "calories", "irrigation_mm", "total_water_mm", "soil_score"))
        assert 0 <= r["soil_score"] <= 100 and r["total_water_mm"] > 0


def test_monoculture_scores_lower_on_soil_than_a_legume_rotation(bundle):
    by = {tuple(c[0] for c in r["crops"]): r for r in bundle["scored"]}
    assert by[("soybean", "maize", "soybean", "maize")]["soil_score"] > by[("maize",) * 4]["soil_score"]


def test_crop_without_a_yield_number_is_left_out_and_reported(site, scen):
    ov = {k: dict(v) for k, v in OVERRIDES.items()}
    del ov["soybean"]["yield"]                                     # price and cost known, no yield number
    r = opt.recommend_picks(site, inputs(overrides=ov), {}, crops=CROPS, scenarios=scen, explain_text=False)
    assert {"crop": "soybean", "field": "yield"} in r["excluded_crops"]
    assert all(c[0] != "soybean" for x in r["all_results"] for c in x["crops"])


def test_current_crop_without_a_yield_number_asks_for_it(site, scen):
    ov = {k: dict(v) for k, v in OVERRIDES.items()}
    del ov["maize"]["yield"]
    r = opt.recommend_picks(site, inputs(overrides=ov), {}, crops=CROPS, scenarios=scen, explain_text=False)
    assert {"crop": "maize", "field": "yield"} in r["input_needed"]


def test_results_are_deterministic_with_the_real_simulation(site, scen):
    a = opt.recommend_picks(site, inputs(), {"bad_year": 0.3}, crops=CROPS, scenarios=scen, explain_text=False)
    b = opt.recommend_picks(site, inputs(), {"bad_year": 0.3}, crops=CROPS, scenarios=scen, explain_text=False)
    assert a["highest_profit"] == b["highest_profit"] and a["headline"] == b["headline"]


def test_slider_moves_are_fast_after_scoring(bundle):
    t = time.time()
    for lam in np.linspace(0, 1, 5):
        opt.assemble_recommendation(bundle, {"bad_year": float(lam), "soil": 0.5}, explain_text=False)
    assert (time.time() - t) / 5 < 1.0


def test_value_of_information_on_the_real_simulation(site, scen):
    rows = evpi.question_value(site, inputs(), {"bad_year": 0.3}, crops=CROPS, scenarios=scen)
    assert {r["input"] for r in rows} == {"soil_water", "water_supply", "organic_matter"}
    assert all(r["evpi_per_acre"] >= 0 for r in rows)
    sw = next(r for r in rows if r["input"] == "soil_water")
    assert sw["computed"] is True and sw["could_change_answer"] in (True, False)
    assert next(r for r in rows if r["input"] == "water_supply")["applicable"] is False     # rain-only farm
