# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Feature 2 (Person 2): v4 water balance, yield model, scenarios and simulate(). Offline: synthetic weather."""
import numpy as np
import pandas as pd
import pytest

from engine import crops as C
from engine import scenarios as SC
from engine import simulate as SIM
from engine import waterbalance as WB
from engine import yieldmodel as YM


def make_weather(first=1995, last=2012, seed=7, lat=41.0, rain_scale=1.0):
    """A mid-latitude continental climate (cold winter, warm wet summer) with random daily rain."""
    idx = pd.date_range(f"{first}-01-01", f"{last}-12-31")
    rng = np.random.default_rng(seed)
    season = np.sin((idx.dayofyear.to_numpy() - 105) / 365.0 * 2 * np.pi)
    tmean = 10.0 + 14.0 * season + rng.normal(0, 3.0, len(idx))
    wet = rng.random(len(idx)) < 0.28
    rain = np.where(wet, rng.gamma(0.8, 9.0, len(idx)), 0.0) * (0.8 + 0.4 * (season > 0)) * rain_scale
    year_factor = dict(zip(range(first, last + 1), rng.uniform(0.55, 1.35, last - first + 1)))
    rain = rain * np.array([year_factor[y] for y in idx.year])
    w = pd.DataFrame({"tmax": tmean + 6.0, "tmin": tmean - 6.0, "tmean": tmean, "precip": rain,
                      "et0": np.maximum(0.3, 2.6 + 2.4 * season + rng.normal(0, 0.4, len(idx)))}, index=idx)
    w.attrs.update(lat=lat, elevation_m=300.0)
    return w


@pytest.fixture(scope="module")
def weather():
    return make_weather()


@pytest.fixture(scope="module")
def site(weather):
    return {"weather": weather, "lat": 41.0, "elevation_m": 300.0,
            "soil": {"awc_mm_per_m": 140.0, "hydrologic_group": "B"}}


def inputs(mode="rain", normal=None, dry=None, **over):
    return {"water": {"mode": mode, "normal_mm": normal, "dry_mm": dry}, "crop_overrides": over}


ROT = ["maize", "soybean", "wheat_winter", "sorghum"]


def test_crop_library_has_sources_for_every_number():
    lib = C.crop_library()
    assert len(lib) >= 20
    for c in lib.values():
        for key in ("kc_ini", "kc_mid", "kc_end", "stages_days", "root_depth_m", "p", "ky", "harvest_index"):
            assert c.sources.get(key), f"{c.id}.{key} has no source note"
        assert not c.kcal_per_kg or "FoodData Central" in c.sources["kcal_per_kg"]
        assert "FAO-56" in c.sources["kc_mid"] and "FAO" in c.sources["ky"]


def test_scenarios_real_years_and_seed_42(weather):
    b1, b2 = SC.bootstrap(weather), SC.bootstrap(weather)
    assert b1.n == 500 and b1.seed == 42
    assert np.array_equal(b1.years, b2.years) and np.array_equal(b1.precip, b2.precip)
    assert set(np.unique(b1.years)) <= set(range(1995, 2013))
    h = SC.historical(weather)
    assert h.n == 18 - 3 and h.labels[0] == "1995-1998" and np.allclose(h.weights.sum(), 1.0)
    assert (np.diff(h.years, axis=1) == 1).all()
    s = SC.stress_tests(weather)
    assert s.n >= 4 and all(any(str(y) in lab for y in row) for lab, row in zip(s.labels, s.years))
    assert not np.array_equal(SC.bootstrap(weather, seed=1).years, b1.years)


def test_timeline_places_winter_wheat_across_new_year(weather):
    tl = WB.build_timeline(ROT, weather)
    assert tl.feasible, tl.reason
    wheat = [s for s in tl.cash if s.crop == "wheat_winter"][0]
    assert wheat.plan_year == 2 and wheat.start < 2 * 365 and wheat.end >= 2 * 365
    days = np.concatenate([s.idx() for s in tl.segments])
    assert len(days) == len(set(days.tolist())), "two crops on the field on the same day"
    assert not WB.build_timeline(["not_a_crop"], weather).feasible
    assert WB.normalize_rotation(["corn", "soybeans"])[0] == [["maize"], ["soybean"], ["maize"], ["soybean"]]


def test_mass_balance_closes_and_depletion_stays_in_bounds(weather):
    scen = SC.historical(weather)
    tls = [WB.build_timeline(ROT, weather), WB.build_timeline({"crops": ["maize", "soybean"], "cover_crops": ["cereal_rye"]}, weather)]
    assert all(t.feasible for t in tls)
    for supply in (0.0, 150.0, np.inf):
        bal = WB.run_balance(tls, scen, np.full((scen.n, 4), supply), 140.0, "C", keep_daily=True)
        assert np.abs(bal["closure_error"]).max() < 1e-6
        dep, cap = bal["depletion"], bal["root_zone_capacity"][:, None, :]
        assert dep.min() >= 0.0 and (dep <= cap + 1e-9).all()
        assert bal["irrigation_daily"].min() >= 0.0
        if np.isfinite(supply):
            assert (bal["irrigation"] <= supply + 1e-9).all()
        assert (bal["eta"] <= bal["etm"] + 1e-9).all()


def test_irrigation_never_negative_or_above_supply(site):
    r = SIM.simulate(site, inputs("irrigated", 200.0, 80.0), ROT)
    assert r.irrigation_mm.min() >= 0.0
    assert (r.irrigation_mm <= r.supply_mm + 1e-9).all()
    assert r.supply_mm.max() <= 200.0 + 1e-9 and r.supply_mm.min() >= 80.0 - 1e-9
    dry_years = r.rain_mm <= SIM.default_scenarios(site).rain_dry_mm
    assert dry_years.any() and np.allclose(r.supply_mm[dry_years], 80.0)


def test_less_water_never_raises_yield(site):
    scen = SIM.default_scenarios(site).subset(np.arange(120))
    prev = None
    for normal in (0.0, 40.0, 120.0, 250.0, 600.0):
        r = SIM.simulate(site, inputs("irrigated", normal, normal * 0.5), ROT, scen)
        if prev is not None:
            assert (r.rel_yield >= prev - 1e-9).all()
        prev = r.rel_yield
    full = SIM.simulate(site, inputs("irrigated"), ROT, scen)        # no amount given = unlimited
    assert (full.rel_yield >= prev - 1e-9).all()


def test_less_rain_never_raises_yield(site):
    scen = SIM.default_scenarios(site).subset(np.arange(120))
    for inp in (inputs("rain"), inputs("irrigated", 150.0, 60.0)):
        prev = None
        for mult in (0.5, 0.7, 0.9, 1.0, 1.15, 1.3):
            r = SIM.simulate(site, inp, ROT, scen.adjust(rain_mult=mult))
            if prev is not None:
                assert (r.rel_yield >= prev - 1e-9).all()
            prev = r.rel_yield


def test_full_water_gives_full_yield(site):
    assert YM.relative_yield(1.25, 400.0, 400.0) == 1.0
    assert float(YM.relative_yield(1.25, 300.0, 400.0)) == pytest.approx(1 - 1.25 * 0.25)
    assert float(YM.relative_yield(1.25, 0.0, 400.0)) == 0.0
    r = SIM.simulate(site, inputs("irrigated", maize={"ym": 12000.0}), ["maize"])
    assert np.allclose(r.eta_mm, r.etm_mm)                            # unlimited water: ETa = ETm
    no_heat = r.heat_days == 0
    assert no_heat.any() and np.allclose(r.rel_yield[no_heat], 1.0) and np.allclose(r.yield_kg_ha[no_heat], 12000.0)


def test_heat_penalty_toggle():
    assert float(YM.heat_factor(0)) == 1.0
    assert float(YM.heat_factor(5, enabled=True)) == pytest.approx(1 - 5 * C.rule("heat_pen_per_day"))
    assert float(YM.heat_factor(5, enabled=False)) == 1.0
    assert float(YM.relative_yield(1.0, 100, 100, heat_days=3, heat=False)) == 1.0


def test_simulate_is_deterministic_and_reports_timing(site):
    a = SIM.simulate(site, inputs("rain", maize={"yield": 9000.0}), ROT)
    b = SIM.simulate(site, inputs("rain", maize={"yield": 9000.0}), ROT)
    assert a.feasible and a.n_scenarios == 500
    for name in ("rel_yield", "yield_kg_ha", "irrigation_mm", "total_water_mm", "eta_mm"):
        assert np.array_equal(getattr(a, name), getattr(b, name), equal_nan=True)
    assert [s["crop"] for s in a.seasons] == ["maize", "soybean", "wheat_winter", "sorghum"] or \
        sorted(s["crop"] for s in a.seasons) == sorted(ROT)
    for s in a.seasons:
        assert 1 <= s["plant_day_of_year"] <= 365 and 1 <= s["harvest_day_of_year"] <= 365 and s["season_days"] > 60
    assert np.abs(a.closure_error_mm).max() < 1e-6
    k = [i for i, s in enumerate(a.seasons) if s["crop"] == "maize"][0]
    assert np.isfinite(a.yield_kg_ha[:, k]).all() and np.isnan(a.yield_kg_ha[:, 1 if k != 1 else 0]).all()
    many = SIM.simulate_many(site, inputs("rain", maize={"yield": 9000.0}), [ROT, ["rice"], ["soybean", "maize"]])
    assert np.array_equal(many[0].rel_yield, a.rel_yield)
    assert not many[1].feasible and "irrigation" in many[1].reason
    assert many[2].feasible


def test_single_season_function_for_hindcasts(weather):
    v = YM.season_relative_yield(weather, "maize", 2005, 41.0, 140.0)
    assert v is not None and 0.0 <= v <= 1.0
    assert YM.season_relative_yield(weather, "corn", 2005, 41.0, 140.0) == v
    assert YM.season_relative_yield(weather, "maize", 1890, 41.0, 140.0) is None
    wet = YM.season_relative_yield(weather, "maize", 2005, 41.0, 140.0, irrigated=True)
    assert wet >= v
    allyears = YM.season_relative_yields(weather, "maize", 41.0, 140.0)
    assert set(allyears) == set(range(1995, 2013)) and min(allyears.values()) < max(allyears.values())


def test_potential_yield_from_county_series():
    years = np.arange(2000, 2020)
    y = 8000 + 100 * (years - 2000) + np.tile([-600, 0, 300, 600], 5)
    ym = YM.ym_from_yield_series(years, y)
    assert 8000 + 100 * 19 < ym < 8000 + 100 * 19 + 800
    assert YM.ym_from_yield_series(years[:5], y[:5]) is None
    assert YM.potential_yield("corn", {"us_defaults": {"ym": {"maize": 13000.0}}}, None)[0] == 13000.0
    assert YM.potential_yield("maize", None, None)[0] is None


def test_result_fits_feature_3_optimizer(site):
    """Person 1's optimizer reads yields_kg_ha, irrigation_mm, total_water_mm as [S,4], passes cover crops as
    True/False and may pass a placeholder instead of a scenario set."""
    inp = inputs("rain", maize={"yield": 9000.0}, soybean={"yield": 3000.0})
    rot = {"crops": [["maize"], ["soybean"], ["maize"], ["soybean"]], "cover_crops": [False, True, True, True]}
    r = SIM.simulate(site, inp, rot, list(range(41)))
    for key in ("yields_kg_ha", "irrigation_mm", "total_water_mm"):
        assert np.asarray(r[key]).shape == (500, 4) and np.isfinite(r[key]).all()
    assert r.missing_yield == [] and {c["crop"] for c in r.cover_seasons} == {"cereal_rye"}
    bad = SIM.simulate(site, inp, {"crops": [["rice"]] * 4, "cover_crops": [False] * 4}, 41)
    assert not bad.feasible and bad.yields_kg_ha.shape == (500, 4) and (bad.yields_kg_ha == 0).all()
    assert C.calories_per_kg("rice") == pytest.approx(3650 * 0.66) and C.calories_per_kg("sunflower") is None
