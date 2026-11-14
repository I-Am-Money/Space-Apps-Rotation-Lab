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
