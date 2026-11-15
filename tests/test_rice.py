# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
import numpy as np

from engine.waterbalance import simulate_plan
from tests.synth import make_scen

AWC = 150.0
A4 = ["rice"] * 4


def test_irrigation_need_never_negative():
    for m in (0.0, 0.5, 1.0, 3.0):
        r = simulate_plan(make_scen(S=6, rain_mult=m), A4, AWC, 900.0, {"record_daily": True})
        assert r["daily"]["need"].min() >= 0 and r["irrig_needed_mm"].min() >= 0 and r["irrig_mm"].min() >= 0


def test_need_near_zero_in_sustained_heavy_rain():
    scen = make_scen(S=3)
    scen["precip"][:] = 40.0
    r = simulate_plan(scen, A4, AWC, 900.0, {"rice_irrigation.puddling_water_mm": 0.0, "record_daily": True})
    assert (r["irrig_needed_mm"] - r["puddle_mm"]).max() < 1.0
    assert r["irrig_needed_mm"].max() < 1.0
    assert np.abs(r["closure_error_mm"]).max() < 1e-6


def test_cutting_available_irrigation_never_raises_rice_yield():
    scen = make_scen(S=10)
    prev = None
    for avail in (2000, 1500, 1000, 600, 300, 0):
        y = simulate_plan(scen, A4, AWC, avail, {"median_season_rain_mm": 600.0})["yield_kg_ha"]
        if prev is not None:
            assert np.all(y <= prev + 1e-9)
        prev = y
    assert prev.max() < simulate_plan(scen, A4, AWC, 2000, {"median_season_rain_mm": 600.0})["yield_kg_ha"].max()


def test_more_millet_uses_less_irrigation():
    scen = make_scen(S=10)
    irr = lambda plan: simulate_plan(scen, plan, AWC, 900.0)["irrig_mm"].sum(axis=1).mean()
    a = irr(A4)
    b = irr(["rice", "jowar", "rice", "jowar"])
    c = irr(["rice", "pigeonpea", "jowar", "rice"])
    d = irr(["rice", "jowar", "bajra", "jowar"])
    assert a > b and a > c and b > d and c > d


def test_rice_closure_with_irrigation_and_shortage():
    for avail in (0, 300, 900, 2000):
        r = simulate_plan(make_scen(S=8), A4, AWC, avail)
        assert np.abs(r["closure_error_mm"]).max() < 1e-6
        assert np.all(r["eta_mm"] <= r["etm_mm"] + 1e-9)


def test_canal_mode_monotone_in_release_factor():
    scen = make_scen(S=10)
    prev = None
    for cf in (1.5, 1.0, 0.6, 0.3, 0.0):
        y = simulate_plan(scen, A4, AWC, 1000, {"water_source": "canal", "canal_release_factor": cf})["yield_kg_ha"]
        if prev is not None:
            assert np.all(y <= prev + 1e-9)
        prev = y
    assert prev.max() < simulate_plan(scen, A4, AWC, 1000, {"water_source": "canal"})["yield_kg_ha"].max()


def test_canal_irrigation_independent_of_local_rain():
    # same canal supply -> same water available; local rain changes yield only through rain itself,
    # and the supply cap (irrig_mm) can never exceed the same fixed canal budget.
    base = 700.0
    for m in (0.5, 1.0, 2.0):
        r = simulate_plan(make_scen(S=6, rain_mult=m), A4, AWC, base, {"water_source": "canal"})
        assert np.all(r["irrig_mm"] <= base + 1e-9)
    dry = make_scen(S=6, rain_mult=0.0)
    wet = make_scen(S=6, rain_mult=3.0)
    a = simulate_plan(dry, A4, AWC, base, {"water_source": "canal"})["irrig_mm"]
    b = simulate_plan(wet, A4, AWC, base, {"water_source": "canal"})["irrig_mm"]
    assert np.allclose(a, base)                 # dry year: full canal budget used, no rain scaling
    # rain-linked mode scales the same budget down in a dry year; canal mode does not
    d_loc = simulate_plan(dry, A4, AWC, base, {"water_source": "borewell", "median_season_rain_mm": 600.0})["irrig_mm"]
    assert d_loc.max() < a.max()
    assert b.max() <= base + 1e-9


def test_water_source_modes_validate_and_unset_equals_borewell():
    scen = make_scen(S=4)
    u = simulate_plan(scen, A4, AWC, 800, {"water_source": "unset"})["yield_kg_ha"]
    t = simulate_plan(scen, A4, AWC, 800, {"water_source": "tank"})["yield_kg_ha"]
    assert np.allclose(u, t)
    try:
        simulate_plan(scen, A4, AWC, 800, {"water_source": "pond"})
        assert False
    except ValueError:
        pass


def test_ragi_and_any_crop_subset_close_balance():
    from engine.waterbalance import simulate_batch
    scen = make_scen(S=6)
    plans = [["ragi"] * 4, ["rice", "ragi", "pigeonpea", "rice"], ["ragi", "jowar", "bajra", "ragi"]]
    b = simulate_batch(scen, plans, AWC, 800, {"water_source": "canal"})
    assert np.abs(b["closure_error_mm"]).max() < 1e-6
    assert np.all(b["yield_kg_ha"] >= 0) and b["yield_kg_ha"][0].max() > 0
    assert np.all(b["irrig_mm"][0] == 0)


# ---- canal_and_well (iteration 3) ----
import pytest

from engine.waterbalance import simulate_batch


def _cw_scen(S=10, up_mult=1.0, loc_mult=1.0):
    s = make_scen(S=S, rain_mult=loc_mult)
    s["upstream_season_rain"] = np.tile(np.linspace(300, 900, S)[:, None], (1, 4)) * up_mult
    return s


CW = {"water_source": "canal_and_well", "median_upstream_rain": 600.0, "median_local_rain": 600.0}


def test_cw_supplies_nonnegative_well_capped_and_total_within_S():
    from engine.crops import A
    for um, lm in ((1.0, 1.0), (0.2, 0.3), (2.0, 3.0), (0.0, 0.0)):
        r = simulate_plan(_cw_scen(up_mult=um, loc_mult=lm), A4, AWC, 0, CW)
        assert r["supply_canal_mm"].min() >= 0 and r["supply_well_mm"].min() >= 0
        assert r["supply_well_mm"].max() <= A(None, "rice_irrigation.max_well") + 1e-9
        assert np.all(r["irrig_mm"] <= r["supply_canal_mm"] + r["supply_well_mm"] + 1e-9)
        assert np.all(r["irrig_canal_mm"] <= r["supply_canal_mm"] + 1e-9)
        assert np.allclose(r["irrig_mm"], r["irrig_canal_mm"] + r["irrig_well_mm"])


def test_cw_wells_only_when_canal_falls_short():
    r = simulate_plan(_cw_scen(), A4, AWC, 0, CW)
    wells = r["irrig_well_mm"] > 1e-9
    assert wells.any()
    assert np.all(r["irrig_canal_mm"][wells] >= r["supply_canal_mm"][wells] - 1e-6)   # canal exhausted first
    big = simulate_plan(_cw_scen(), A4, AWC, 0, {**CW, "canal_supply_mm": 5000.0})
    assert big["irrig_well_mm"].max() < 1e-9


def test_cw_less_upstream_or_local_rain_never_raises_yield():
    prev = None
    for um in (1.5, 1.0, 0.6, 0.3, 0.0):
        y = simulate_plan(_cw_scen(up_mult=um), A4, AWC, 0, CW)["yield_kg_ha"]
        if prev is not None:
            assert np.all(y <= prev + 1e-9)
        prev = y
    prev = None
    for lm in (1.5, 1.0, 0.6, 0.3, 0.0):
        y = simulate_plan(_cw_scen(loc_mult=lm), A4, AWC, 0, CW)["yield_kg_ha"]
        if prev is not None:
            assert np.all(y <= prev + 1e-9)
        prev = y


def test_cw_overrides_missing_upstream_and_old_modes_and_closure():
    r = simulate_plan(make_scen(S=4), A4, AWC, 0, {"water_source": "canal_and_well", "canal_supply_mm": 300,
                                                   "well_supply_mm": 200})
    assert np.allclose(r["supply_canal_mm"], 300) and np.allclose(r["supply_well_mm"], 200)
    assert np.all(r["irrig_mm"] <= 500 + 1e-9)
    with pytest.raises(KeyError):
        simulate_plan(make_scen(S=4), A4, AWC, 0, {"water_source": "canal_and_well"})
    import itertools
    from engine.crops import CROP_IDS
    plans = list(itertools.product(CROP_IDS, repeat=4))
    b = simulate_batch(_cw_scen(S=8), plans, AWC, 0, CW)
    assert np.abs(b["closure_error_mm"]).max() < 1e-6


def test_lower_percolation_never_raises_need_nor_lowers_yield():
    scen = make_scen(S=10)
    prev_need = prev_y = None
    for perc in (8.0, 5.0, 3.0, 2.0, 1.0):
        r = simulate_plan(scen, A4, AWC, 700.0, {"rice_irrigation.percolation_seepage_mm_day": perc,
                                                  "median_season_rain_mm": 600.0})
        if prev_need is not None:
            assert np.all(r["irrig_needed_mm"] <= prev_need + 1e-9)
            assert np.all(r["yield_kg_ha"] >= prev_y - 1e-9)
        prev_need, prev_y = r["irrig_needed_mm"], r["yield_kg_ha"]
