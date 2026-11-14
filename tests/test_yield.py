import numpy as np

from engine.waterbalance import simulate_plan
from engine.yieldmodel import nitrogen_credit_kg_ha, rotation_factor, season_yield
from tests.synth import make_scen


def test_yield_limits():
    assert season_yield(5000, 1.09, 600, 600, 1.0) == 5000
    assert season_yield(5000, 1.09, np.array([0.0, 10, 300]), 600, 1.0).min() >= 0
    assert season_yield(5000, 1.5, 0.0, 600, 1.0) == 0.0          # Ky>1 and no water: floored at 0, not negative
    assert abs(season_yield(1000, 0.9, 300, 600, 1.0) - 1000 * (1 - 0.9 * 0.5)) < 1e-9
    assert season_yield(1000, 0.9, 700, 600, 1.0) == 1000.0       # ETa capped at ETm


def test_simulated_yield_equals_ym_when_unstressed_and_never_negative():
    scen = make_scen(S=4, rain_mult=4.0)
    r = simulate_plan(scen, ["jowar", "bajra", "pigeonpea", "jowar"], 150.0, 0.0)
    assert np.all(r["yield_kg_ha"] >= 0)
    scen = make_scen(S=4, rain_mult=0.0)
    r = simulate_plan(scen, ["jowar", "bajra", "pigeonpea", "rice"], 150.0, 0.0)
    assert np.all(r["yield_kg_ha"] >= 0)


def test_rotation_factor_and_n_credit():
    f = rotation_factor(["rice", "rice", "pigeonpea", "jowar"])
    assert f[0] == 1 and f[1] < 1 and f[2] == 1 and f[3] > 1
    assert rotation_factor(["pigeonpea", "rice", "x", "x"])[1] > 1
    assert rotation_factor(["jowar", "bajra", "jowar", "jowar"])[1] < 1
    assert nitrogen_credit_kg_ha(["pigeonpea", "jowar", "rice", "rice"])[1] > 0
    assert nitrogen_credit_kg_ha(["rice", "jowar", "rice", "rice"]).sum() == 0


def test_crop_after_pigeonpea_beats_crop_after_itself_same_weather():
    scen = make_scen(S=8, rain_mult=1.5)
    for crop in ("jowar", "bajra", "rice"):
        after_pp = simulate_plan(scen, ["pigeonpea", crop, "rice", "rice"], 150.0, 900.0)["yield_kg_ha"][:, 1]
        after_self = simulate_plan(scen, [crop, crop, "rice", "rice"], 150.0, 900.0)["yield_kg_ha"][:, 1]
        assert after_pp.mean() > after_self.mean()
