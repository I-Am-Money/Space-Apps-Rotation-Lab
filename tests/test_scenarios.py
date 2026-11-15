import numpy as np
from engine import scenarios as sc
from tests.decision_fakes import synthetic_annual


def test_blocks_count_derived():
    a = synthetic_annual(30)
    h = sc.historical_blocks(a)
    assert h.n == 30 - 3 and h.scen["precip"].shape == (27, 4, 365)
    assert h.scen["labels"][0] == "1990-1993"


def test_bootstrap_seeded_identical_and_shape():
    a = synthetic_annual(30)
    b1, b2 = sc.bootstrap_plans(a), sc.bootstrap_plans(a)
    assert b1.scen["precip"].shape == (500, 4, 365)
    assert np.array_equal(b1.scen["year_idx"], b2.scen["year_idx"])
    assert b1.scen["labels"] == b2.scen["labels"]


def test_stress_tests_use_actual_years():
    a = synthetic_annual(30)
    st = sc.stress_tests(a)
    t = st["driest monsoon in year 2"]
    assert t["source_year"] == int(a["years"][np.argmin(sc.monsoon_rain(a))])
    assert str(t["source_year"]) in t["label"]
    assert np.allclose(t["scen"]["precip"][0, 1], a["precip"][np.argmin(sc.monsoon_rain(a))])
    assert set(st) == {"driest monsoon in year 2", "hottest kharif season in year 3", "latest monsoon onset in year 1", "low canal release year"}
    c = st["low canal release year"]
    assert c["source_year"] == int(a["years"][np.argmin(a["upstream"])]) and str(c["source_year"]) in c["label"]


def test_whatif_rain_and_temperature():
    a = synthetic_annual(10)
    s = sc.historical_blocks(a).scen
    w = sc.apply_whatif(s, rain_mult=0.5, dT=2.0)
    assert np.allclose(w["precip"], 0.5 * s["precip"])
    assert np.allclose(w["tmax"], s["tmax"] + 2)
    assert np.all(w["et0"] > s["et0"])
    assert "not forecasts" in w["whatif"]["label"]


def test_late_monsoon_conserves_total_and_delays():
    a = synthetic_annual(10)
    s = sc.historical_blocks(a).scen
    w = sc.apply_whatif(s, shift_days=20)
    assert np.allclose(w["precip"].sum(-1), s["precip"].sum(-1))
    cum0 = s["precip"][..., 151:273].cumsum(-1); cum1 = w["precip"][..., 151:273].cumsum(-1)
    assert np.all(cum1 <= cum0 + 1e-9)


def test_upstream_aligned_and_independent_multipliers():
    a = synthetic_annual(30)
    h = sc.historical_blocks(a)
    up = h.scen["upstream_season_rain"]
    assert up.shape == (h.n, 4)
    assert np.allclose(up[0], a["upstream"][:4])
    w = sc.apply_whatif(h.scen, rain_mult=0.5, upstream_mult=1.0)
    assert np.allclose(w["upstream_season_rain"], up) and np.allclose(w["precip"], 0.5 * h.scen["precip"])
    w2 = sc.apply_whatif(h.scen, rain_mult=1.0, upstream_mult=0.6)
    assert np.allclose(w2["upstream_season_rain"], 0.6 * up) and np.allclose(w2["precip"], h.scen["precip"])
