# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
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
    t = st["weakest monsoon in year 2"]
    assert t["source_year"] == int(a["years"][np.argmin(sc.monsoon_rain(a))])
    assert str(t["source_year"]) in t["label"]
    assert np.allclose(t["scen"]["precip"][0, 1], a["precip"][np.argmin(sc.monsoon_rain(a))])
    # names exactly as in Build Spec v3 section 6.1
    assert set(st) == {"weakest monsoon in year 2", "hottest season in year 3", "latest monsoon onset in year 1", "low canal release year"}
    h = st["hottest season in year 3"]
    assert h["source_year"] == int(a["years"][np.argmax(sc.season_tmax(a))]) and h["plan_year"] == 3
    lt = st["latest monsoon onset in year 1"]
    assert lt["source_year"] == int(a["years"][np.argmax(a["onset"])]) and lt["plan_year"] == 1
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


def test_late_onset_loses_early_monsoon_rain_and_moves_onset():
    a = synthetic_annual(10)
    s = sc.historical_blocks(a).scen
    w = sc.apply_whatif(s, shift_days=20)
    assert np.all(w["precip"] <= s["precip"])                         # rain is lost, never added or moved
    assert np.all(w["onset_doy"] == s["onset_doy"] + 20)              # onset (and so sowing) is 20 days later
    on = s["onset_doy"]
    for i in range(on.shape[0]):
        for y in range(4):
            o = int(on[i, y]) - 1
            assert np.allclose(w["precip"][i, y, :o], s["precip"][i, y, :o])            # before the real onset: unchanged
            assert np.all(w["precip"][i, y, o:o + 20] == 0)                              # the first 20 monsoon days: lost
            assert np.allclose(w["precip"][i, y, o + 20:], s["precip"][i, y, o + 20:])  # after the delayed onset: unchanged
    assert np.array_equal(sc.apply_whatif(s, shift_days=0)["precip"], s["precip"])


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
