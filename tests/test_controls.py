"""Regression checks for controls, caching and shared whole-farm weather risk."""
import numpy as np
import pandas as pd
import pytest

from engine import api, boundaries, optimize as opt
from tests.decision_fakes import synthetic_annual


@pytest.fixture(autouse=True)
def small_real_engine():
    old_n, old_boundary = api.N_SCEN, api.BOUNDARY_N_SCEN
    opt.set_simulator(None)
    api.set_annual(synthetic_annual(12))
    api.N_SCEN = api.BOUNDARY_N_SCEN = 12
    yield
    api.N_SCEN, api.BOUNDARY_N_SCEN = old_n, old_boundary
    api.set_annual(None)
    opt.set_sim_params()


def rice_arrays(params):
    p = api.norm_params(params)
    api._apply_sim_params(p)
    return opt.rotation_arrays(opt.REF["A"], api.boot_set(), p["awc"], p["irrigation_mm"])


def test_supply_controls_invalidate_cached_economics():
    low = rice_arrays({"water_source": "canal_and_well", "canal_supply_mm": 0, "well_supply_mm": 0})
    high = rice_arrays({"water_source": "canal_and_well", "canal_supply_mm": 2000, "well_supply_mm": 0})
    assert np.all(high["yield"] >= low["yield"])
    assert high["irrig"].mean() > low["irrig"].mean()
    assert not np.allclose(high["profit"], low["profit"])
    again = rice_arrays({"water_source": "canal_and_well", "canal_supply_mm": 0, "well_supply_mm": 0})
    np.testing.assert_array_equal(again["profit"], low["profit"])


def test_single_source_release_and_recharge_controls_reach_physics():
    low = rice_arrays({"water_source": "canal", "canal_release_factor": 0.0})
    high = rice_arrays({"water_source": "canal", "canal_release_factor": 1.5})
    assert high["irrig"].mean() > low["irrig"].mean()
    flat = rice_arrays({"water_source": "borewell", "recharge_exponent_k": 0.0})
    linked = rice_arrays({"water_source": "borewell", "recharge_exponent_k": 1.0})
    assert not np.allclose(flat["irrig"], linked["irrig"])


def test_soil_selector_aliases_and_input_provenance():
    farm = api.norm_params({"soil_mode": "farm"})
    district = api.norm_params({"soil_mode": "district"})
    assert farm["soil_mode"] == "farm_black_soil"
    assert district["soil_mode"] == "district_soilgrids"
    assert farm["awc"] != district["awc"]
    assert api._badges(farm)["irrigation_mm"] == "assumption"
    assert api._badges(api.norm_params({"irrigation_mm": 750}))["irrigation_mm"] == "local"


def test_water_priority_rewards_less_irrigation_even_with_more_stress():
    df = pd.DataFrame([
        dict(id=opt.plan_id(opt.REF["A"]), mean_profit=100., worst10_profit=50.,
             irrigation_mm=1000., water_stress_mm=0., total_water_mm=1500.),
        dict(id="bajra-bajra-bajra-bajra", mean_profit=100., worst10_profit=50.,
             irrigation_mm=0., water_stress_mm=500., total_water_mm=500.),
    ])
    ranked = opt.rescore(df, lam=0.5, w=1., scale=1.)
    assert ranked.loc[1, "J"] > ranked.loc[0, "J"]
    scores = boundaries._J(np.array([[100., 50.], [100., 50.]]),
                           np.array([[1000., 1000.], [0., 0.]]), 0.5, 1., 1.)
    assert scores[1] > scores[0]


def test_land_split_endpoints_and_combined_bad_year_profit():
    params = {"water_source": "canal_and_well", "lam": 0.7, "w": 0.3}
    c = api.compare(["A", "B"], params)
    split = api.land_split("B", params)
    a, b = c["rotations"]["A"], c["rotations"]["B"]
    acres = split["acres_total"]
    assert split["total_profit_mean"][-1] == pytest.approx(acres * a["mean_profit"])
    assert split["total_profit_mean"][0] == pytest.approx(acres * b["mean_profit"])
    assert split["total_irrigation_m3"][-1] == pytest.approx(a["farm_totals"]["total_irrigation_m3"])
    assert split["delta_vs_baseline"]["total_profit_worst10"][-1] == 0
    mid = acres // 2
    combined = mid * a["profit"] + (acres - mid) * b["profit"]
    assert split["total_profit_worst10"][mid] == pytest.approx(opt.worst_fraction_mean(combined))
    assert split["J_total"][-1] == pytest.approx(acres * a["J"])


def test_upstream_grid_is_unavailable_for_single_source_modes():
    p = api.norm_params({"water_source": "borewell"})
    grid = boundaries.upstream_local_grid(api.boot_set(), p["awc"], p["irrigation_mm"], p, 1., [])
    assert grid["available"] is False


def test_assumptions_table_includes_missing_prices_without_fabricating_values():
    table = api.assumptions_table().set_index("name")
    assert table.loc["price.rice", "value"] == 2441
    assert table.loc["price.ragi", "badge"] == "observed"
    assert table.loc["price.ragi", "value"] == 5205
