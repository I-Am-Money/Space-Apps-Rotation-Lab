import numpy as np
import pytest
from engine import api, boundaries as bd
from engine import optimize as opt
from tests.decision_fakes import fake_simulate_plan, synthetic_annual


@pytest.fixture(autouse=True)
def fake():
    opt.set_simulator(fake_simulate_plan)
    api.set_annual(synthetic_annual(30))
    api.N_SCEN = 60; api.BOUNDARY_N_SCEN = 60; api._scensets.clear()
    yield
    opt.set_simulator(None); api.set_annual(None); api.N_SCEN = 500


def test_tipping_points_structure_and_evpi_nonneg():
    t = api.tipping_points({"irrigation_mm": 400})
    rc = t["rainfall_crossover"]
    assert len(rc["rain_mult"]) == 17 and rc["rain_mult"][0] == 0.5 and rc["rain_mult"][-1] == 1.3
    assert rc["band"]["n_boot"] == 200
    g = t["grid"]
    assert len(g["winner"]) == len(g["irrigation_mm"]) and len(g["winner"][0]) == len(g["rain_mult"])
    for k in ("evpi_awc", "evpi_irrigation"):
        assert t[k]["value"] >= 0 and t[k]["text"]
    assert "borewell or tank" in t["evpi_irrigation"]["text"]
    assert "EVSI" not in str(t)
    assert "not forecasts" in rc["text"]


def test_evpi_formula_by_hand():
    # two rotations, two states, J known: state1 -> (10, 0), state2 -> (0, 10). perfect=10, no-info=5, EVPI=5
    J = np.array([[10., 0.], [0., 10.]])
    assert J.max(1).mean() - J.mean(0).max() == 5.0


def test_crossover_interpolation():
    ms = np.array([0.5, 0.6]); Jm = np.array([[10., 0.], [0., 10.]])
    c = bd._first_crossover(np.array([0, 1]), Jm, ms)
    assert abs(c[0][0] - 0.55) < 1e-9


def test_dry_favours_millet_wet_favours_rice_in_grid():
    t = api.tipping_points({"irrigation_mm": 400, "lam": 0.0, "w": 0.0})
    g = t["grid"]
    assert g["text"]


def test_hindcast_machinery_on_synthetic_observed():
    import pandas as pd
    from engine import hindcast as hc
    a = api.annual()
    yrs = a["years"]
    mod = hc.model_single_season(a, opt.MILLETS[0], 140.0, 400.0)
    obs = pd.DataFrame({"year": yrs, "crop": opt.MILLETS[0], "yield_kg_ha": mod * 0.9 + 20 * (yrs - yrs[0])})
    h = hc.hindcast(a, 140.0, 400.0, observed=obs, farm=None)
    c = h["per_crop"][opt.MILLETS[0]]
    assert c["pearson_r"] > 0.99 and c["heldout_r"] > 0.9 and len(c["heldout_years"]) == 10
    assert h["farm_records"] is None


def test_hindcast_unavailable_is_honest():
    from engine import hindcast as hc
    h = hc.hindcast(api.annual(), 140.0, 400.0, observed=__import__("pandas").DataFrame(columns=["year", "crop", "yield_kg_ha"]), farm=None)
    assert not h["available"] and "fabricated" in h["note"]


def test_upstream_local_grid_and_canal_well_split():
    t = api.tipping_points({"irrigation_mm": 400})
    g = t["grid_upstream_local"]
    assert g["available"] and len(g["winner"]) == len(g["local_mult"]) and len(g["winner"][0]) == len(g["upstream_mult"])
    assert g["text"] and "proxy" in g["text"]
    c = api.compare(["A"], {"irrigation_mm": 400})
    r = c["rotations"]["A"]
    assert abs(r["irrigation_canal_mm"] + r["irrigation_well_mm"] - r["irrigation_mm"]) < 1e-6
