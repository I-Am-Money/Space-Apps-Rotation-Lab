"""Onset, heat, cache isolation and explicit local-cost regression coverage."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import numpy as np
import pytest

from engine import api, optimize as opt
from engine import boundaries, fetch_icrisat
from engine.cache import ArrayCache
from engine.monsoon import detect_onset
from engine.waterbalance import simulate_batch, simulate_plan, _simulate_fixed_reference
from tests.synth import make_scen


def test_onset_rejects_false_start_and_reports_no_planting():
    rain = np.zeros((2, 365))
    rain[0, 151:156] = 5
    rain[0, 181:220] = 5
    onset = detect_onset(rain)
    assert onset.tolist() == [185, 365]


def test_sowing_moves_with_delayed_onset_and_accounting_closes():
    s = make_scen(S=4)
    s["onset_doy"] = np.full((4, 4), 165)
    a = simulate_plan(s, ["rice", "bajra", "pigeonpea", "rice"], 180, 900)
    delayed = dict(s, onset_doy=s["onset_doy"] + 20)
    b = simulate_plan(delayed, ["rice", "bajra", "pigeonpea", "rice"], 180, 900)
    np.testing.assert_array_equal(b["sowing_doy"] - a["sowing_doy"], 20)
    assert np.max(np.abs(b["closure_error_mm"])) < 1e-6
    none = simulate_plan(dict(s, onset_doy=np.full((4, 4), 365)), ["rice"] * 4, 180, 900)
    assert not none["yield_kg_ha"].any() and not none["irrig_mm"].any()


def test_heat_toggle_only_reduces_yield_and_preserves_water_balance():
    s = make_scen(S=3)
    s["tmax"][:] = 45
    cold = simulate_plan(s, ["rice"] * 4, 150, 2000, {"heat.enabled": False})
    hot = simulate_plan(s, ["rice"] * 4, 150, 2000, {"heat.enabled": True})
    np.testing.assert_allclose(hot["yield_kg_ha"], cold["yield_kg_ha"] * .8)
    np.testing.assert_allclose(hot["irrig_mm"], cold["irrig_mm"])
    assert (hot["heat_days"] == 20).all()


def test_compiled_kernel_matches_reference_equations():
    s = make_scen(S=4)
    plans = [["rice"] * 4, ["bajra"] * 4, ["rice", "pigeonpea", "bajra", "rice"]]
    actual = simulate_batch(s, plans, 150, 900, {"heat.enabled": False})
    reference = _simulate_fixed_reference(s, plans, 150, 900)
    for key in ("yield_kg_ha", "eta_mm", "irrig_mm", "rain_total_mm", "eta_total_mm", "runoff_total_mm", "storage_change_mm"):
        np.testing.assert_allclose(actual[key], reference[key], atol=1e-9)


def test_request_parameters_are_isolated_between_threads():
    barrier = Barrier(2)
    def request(value):
        opt.set_sim_params(water_source="canal", canal_release_factor=value)
        opt.set_economic_params({"cost.rice": value * 1000})
        barrier.wait()
        return opt.params_for(500)["canal_release_factor"], opt.current_prices()["operating_cost_rs_per_acre"]["rice"]
    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(request, [.2, .8])) == [(.2, 200.), (.8, 800.)]


def test_array_cache_evicts_old_values_within_limit():
    cache = ArrayCache(160)
    cache["a"] = np.zeros(10)
    cache["b"] = np.zeros(10)
    cache["c"] = np.zeros(10)
    assert "a" not in cache and "b" in cache and "c" in cache
    assert cache.bytes == 160
    with pytest.raises(ValueError):
        cache["b"][0] = 1


@pytest.mark.parametrize("params", [{"lam": 2}, {"awc_mm_per_m": float("nan")}, {"irrigation_mm": -1}, {"current_rotation": ["rice"]}])
def test_invalid_api_inputs_fail_clearly(params):
    with pytest.raises(ValueError):
        api.norm_params(params)


def test_local_costs_change_economics_without_repeating_physics():
    old_n = api.N_SCEN
    api.N_SCEN = 12
    try:
        low = api.compare(["A"], {"operating_costs": {"rice": 1000}})["rotations"]["A"]
        high = api.compare(["A"], {"operating_costs": {"rice": 2000}})["rotations"]["A"]
        assert low["mean_profit"] - high["mean_profit"] == pytest.approx(4000)
        np.testing.assert_array_equal(low["yield_kg_ha"], high["yield_kg_ha"])
    finally:
        api.N_SCEN = old_n
        opt.set_economic_params()
        api.set_annual(None)


def test_bootstrap_count_scores_match_explicit_resampling():
    profit = np.array([[10., 20., 30., 40., 50.], [1., 2., 3., 4., 5.]])
    irrigation = np.array([[50., 40., 30., 20., 10.], [10., 10., 10., 10., 10.]])
    indices = np.array([[0, 0, 1, 3, 4], [1, 2, 2, 4, 4]])
    counts = np.stack([np.bincount(row, minlength=5) for row in indices])
    scores = boundaries._bootstrap_scores(profit, irrigation, counts, .6, .2, 3.)
    for b, idx in enumerate(indices):
        p, water = profit[:, idx], irrigation[:, idx]
        expected = .4 * p.mean(1) + .6 * p.min(1) - .2 * 3 * water.mean(1)
        np.testing.assert_allclose(scores[b], expected)


def test_entered_source_capacities_scale_with_total_supply_sweep():
    p = api.norm_params({"canal_supply_mm": 200., "well_supply_mm": 100.})
    assert p["irrigation_mm"] == 300
    api._apply_sim_params(p)
    with opt.irrigation_sweep(600, 300):
        assert opt.params_for(600)["canal_supply_mm"] == 400
        assert opt.params_for(600)["well_supply_mm"] == 200
    assert opt.params_for(300)["canal_supply_mm"] == 200


def test_archived_dld_has_one_kharif_record_per_crop_year():
    frame = fetch_icrisat.load_district_yields()
    assert not frame.duplicated(["crop", "year"]).any()
    assert fetch_icrisat.year_counts(frame) == {"rice": 52, "jowar": 52, "bajra": 52, "ragi": 17, "pigeonpea": 52}
    assert frame.query("crop == 'jowar' and year == 2017").yield_kg_ha.iloc[0] == pytest.approx(494.31)


def test_farm_record_validation_drops_identifying_columns():
    from engine.records import validate_records
    frame = validate_records([dict(year=2020, crop="paddy", area_acres=2., yield_quintals=30., name="test-only identifier")])
    assert "name" not in frame and frame.crop.iloc[0] == "rice"
    assert frame.yield_kg_ha.iloc[0] == pytest.approx(3000 / (2 * .404686))
    with pytest.raises(ValueError):
        validate_records([dict(year=2020, crop="rice", area_acres=0, yield_quintals=30)])


def test_unknown_measurement_quote_does_not_create_purchase_verdict():
    result = {"value": 12., "test_cost": None}
    assert "No verified" in boundaries.evpi_text_awc(result)
    assert "No verified" in boundaries.evpi_text_irr(result)


def test_equal_frontier_points_are_all_nondominated():
    assert opt.pareto_mask([1, 1, 0, 2], [2, 2, 2, 1]).tolist() == [True, True, False, True]


def test_assumption_export_includes_current_local_costs_and_water():
    table = api.assumptions_table({"operating_costs": {"rice": 12345}, "canal_supply_mm": 250}).set_index("name")
    assert table.loc["current.cost.rice", "value"] == 12345
    assert table.loc["current.cost.rice", "badge"] == "local"
    assert table.loc["current.canal_supply_mm", "value"] == 250


def test_validation_holdout_does_not_influence_potential_yield():
    from engine import hindcast as hc
    import pandas as pd
    from tests.decision_fakes import synthetic_annual
    annual = synthetic_annual(20)
    years = annual["years"]
    observed = pd.DataFrame({"year": years, "crop": "rice", "yield_kg_ha": 2000 + np.arange(20) * 20 + np.sin(np.arange(20)) * 100})
    first = hc.hindcast(annual, 150, 500, observed=observed)["per_crop"]["rice"]
    changed = observed.copy()
    changed.loc[changed.year.isin(first["heldout_years"]), "yield_kg_ha"] *= 2
    second = hc.hindcast(annual, 150, 500, observed=changed)["per_crop"]["rice"]
    assert first["ym_training_kg_ha"] == second["ym_training_kg_ha"]
    assert max(first["training_years"]) < min(first["heldout_years"])
    np.testing.assert_array_equal(first["modeled"], second["modeled"])
