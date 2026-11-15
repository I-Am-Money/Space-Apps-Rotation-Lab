# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Feature 2 (Person 2): climate shift modes (Build Spec v4 R8). Offline: synthetic weather."""
import numpy as np
import pytest

from engine import climate_shift as CS
from engine import scenarios as SC
from engine import simulate as SIM
from tests.test_p2_simulation import ROT, inputs, make_weather


@pytest.fixture(scope="module")
def weather():
    return make_weather(1981, 2025, seed=11)


@pytest.fixture(scope="module")
def site(weather):
    return {"weather": weather, "lat": 41.0, "elevation_m": 300.0,
            "soil": {"awc_mm_per_m": 140.0, "hydrologic_group": "B"}}


def test_historical_mode_reproduces_unweighted_results(site, weather):
    base = SIM.default_scenarios(site)
    hist = CS.apply(base, "historical", weather)
    assert hist is base and CS.scenarios_for(site, "Historical") is base
    assert np.allclose(base.weights, 1.0 / base.n)                     # every plan counts once
    inp = inputs("rain", maize={"yield": 9000.0})
    plain = SIM.simulate(site, inp, ROT)                                # no climate setting at all
    shifted = SIM.simulate(site, inp, ROT, hist)
    with CS.use("historical"):
        inside = SIM.simulate(site, inp, ROT)
    for name in ("rel_yield", "yield_kg_ha", "irrigation_mm", "total_water_mm", "weights"):
        assert np.array_equal(getattr(plain, name), getattr(shifted, name), equal_nan=True)
        assert np.array_equal(getattr(plain, name), getattr(inside, name), equal_nan=True)
    # the scenario-weighted mean under historical mode is the plain, unweighted mean over the plans
    assert np.allclose(shifted.mean("rel_yield"), shifted.rel_yield.mean(axis=0))
    assert np.allclose(shifted.mean("irrigation_mm"), shifted.irrigation_mm.mean(axis=0))


def test_recent_mode_counts_last_20_years_twice(site, weather):
    annual = SC.site_years(weather)
    w = CS.year_weights(annual["years"])
    assert w.sum() == 25 + 2 * 20 and (w[-20:] == 2).all() and (w[:-20] == 1).all()
    base = SIM.default_scenarios(site)
    rec = CS.apply(base, "recent", weather)
    assert rec.climate_mode == "recent" and rec.n == base.n and np.allclose(rec.weights, 1.0 / rec.n)
    assert set(np.unique(rec.years)) <= set(annual["years"].tolist())   # still only real years
    share = (rec.years > 2005).mean()
    assert abs(share - 40 / 65) < 0.04 and abs((base.years > 2005).mean() - 20 / 45) < 0.04
    assert "what-if" in rec.note
    # a weight of 1 is the historical bootstrap, plan for plan
    same = CS.recent(base, annual, recent_weight=1.0)
    assert np.array_equal(same.years, base.years) and np.array_equal(same.precip, base.precip)
    # deterministic (seed 42)
    again = CS.apply(base, "recent", weather)
    assert np.array_equal(again.years, rec.years)
    # blocks of real consecutive years cannot be redrawn: they are re-weighted instead
    hist = CS.apply(SC.historical(weather), "recent", weather)
    assert np.isclose(hist.weights.sum(), 1.0) and hist.weights[-1] == pytest.approx(2 * hist.weights[0])


def test_trend_mode_carries_the_observed_trend_10_years_forward(weather):
    annual = SC.site_years(weather)
    years = annual["years"].astype(float)
    # a record with an exact trend: rain falls 4 mm a year, maximum temperature rises 0.03 degC a year
    mean_rain = annual["precip"].sum(axis=1).mean()
    flat = annual["precip"] / annual["precip"].sum(axis=1, keepdims=True)
    made = dict(annual)
    made["precip"] = flat * (mean_rain - 4.0 * (years - years.mean()))[:, None]
    made["tmax"] = annual["tmax"] - annual["tmax"].mean(axis=1, keepdims=True) + (20.0 + 0.03 * (years - 1981))[:, None]
    made["et0"] = annual["et0"] / annual["et0"].sum(axis=1, keepdims=True) * 900.0
    fit = CS.trend_fit(made)
    assert fit["target_year"] == 2035 and fit["rain_slope_per_decade"] == pytest.approx(-40.0)
    assert fit["tmax_slope_per_decade"] == pytest.approx(0.3) and fit["et0_slope_per_decade"] == pytest.approx(0.0, abs=1e-6)
    base = SC.bootstrap(made)
    t = CS.trend(base, made)
    assert t.climate_mode == "trend" and "what-if" in t.note and np.array_equal(t.years, base.years)
    level_2035 = mean_rain - 4.0 * (2035 - years.mean())
    assert np.allclose(t.precip.sum(axis=2), level_2035)               # every year sits at the 2035 trend level
    assert np.allclose(t.tmax.mean(axis=2), 20.0 + 0.03 * (2035 - 1981))
    assert np.allclose(t.et0, base.et0)                                 # no trend in ET0: unchanged
    shift_1981 = t.tmax[base.years == 1981].mean() - base.tmax[base.years == 1981].mean()
    assert shift_1981 == pytest.approx(0.03 * (2035 - 1981))
    # a record with no trend at all is left as it is
    still = dict(made)
    still["precip"], still["tmax"] = flat * mean_rain, made["tmax"] - 0.03 * (years - 1981)[:, None]
    b2 = SC.bootstrap(still)
    t2 = CS.trend(b2, still)
    assert np.allclose(t2.precip, b2.precip) and np.allclose(t2.tmax, b2.tmax)


def test_modes_run_through_simulate_and_are_labeled(site, weather):
    inp = inputs("rain", maize={"yield": 9000.0})
    hist = SIM.simulate(site, inp, ROT)
    for mode in ("recent", "trend"):
        scen = CS.scenarios_for(site, mode)
        assert scen is CS.scenarios_for(site, mode)                     # remembered
        r = SIM.simulate(site, inp, ROT, scen)
        with CS.use(mode):
            inside = SIM.simulate(site, inp, ROT, list(range(41)))      # the optimizer's placeholder scenario list
        assert r.feasible and np.array_equal(r.rel_yield, inside.rel_yield)
        assert not np.array_equal(r.rel_yield, hist.rel_yield)
        assert any("what-if" in n for n in r.notes)
        assert np.abs(r.closure_error_mm).max() < 1e-6
        d = CS.describe(weather, mode)
        assert "not a forecast" in d["text"] and d["what_if"] == CS.WHAT_IF
    assert SIM.current_what_if() == {}
    assert CS.normalize_mode("Continuing trend") == "trend" and CS.normalize_mode(None) == "historical"
    with pytest.raises(ValueError):
        CS.normalize_mode("forecast")
    with pytest.raises(ValueError):
        CS.apply(CS.scenarios_for(site, "trend"), "recent", weather)


def test_what_if_block_changes_rain_heat_and_water_only_inside(site):
    inp = inputs("irrigated", 200.0, 100.0, maize={"yield": 9000.0})
    base = SIM.simulate(site, inp, ROT)
    with SIM.what_if(rain_mult=0.6):
        dry = SIM.simulate(site, inp, ROT)
        with SIM.what_if(water={"mode": "irrigated", "normal_mm": 0.0, "dry_mm": 0.0}):
            drier = SIM.simulate(site, inp, ROT)
            assert SIM.current_what_if()["rain_mult"] == 0.6
    after = SIM.simulate(site, inp, ROT)
    assert np.array_equal(base.rel_yield, after.rel_yield)
    assert np.allclose(dry.rain_mm, 0.6 * base.rain_mm)
    assert (dry.rel_yield <= base.rel_yield + 1e-9).all() and dry.rel_yield.mean() < base.rel_yield.mean()
    assert (drier.irrigation_mm == 0).all() and (drier.rel_yield <= dry.rel_yield + 1e-9).all()
    # the farm's potential yield does not move with the what-if
    assert [s["ym_kg_ha"] for s in dry.seasons] == [s["ym_kg_ha"] for s in base.seasons]
    assert [s["ym_kg_ha"] for s in drier.seasons] == [s["ym_kg_ha"] for s in base.seasons]
    with SIM.what_if(heat_shift_c=3.0):
        hot = SIM.simulate(site, inp, ROT)
    assert (hot.heat_days >= base.heat_days).all() and hot.heat_days.sum() > base.heat_days.sum()
