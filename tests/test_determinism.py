import numpy as np
from engine import api
from engine import optimize as opt
from tests.decision_fakes import fake_simulate_plan, synthetic_annual


def _run():
    opt.set_simulator(fake_simulate_plan)
    api.set_annual(synthetic_annual(30))
    api.N_SCEN = 60; api.BOUNDARY_N_SCEN = 60; api._scensets.clear()
    r = api.recommend({"irrigation_mm": 400}); t = api.tipping_points({"irrigation_mm": 400})
    return r, t


def test_two_runs_identical():
    r1, t1 = _run(); r2, t2 = _run()
    assert np.array_equal(r1["metrics"].J.values, r2["metrics"].J.values)
    assert t1["rainfall_crossover"]["band"] == t2["rainfall_crossover"]["band"]
    assert t1["evpi_awc"]["value"] == t2["evpi_awc"]["value"]
    assert t1["grid"]["winner"] == t2["grid"]["winner"]
    opt.set_simulator(None); api.set_annual(None); api.N_SCEN = 500
