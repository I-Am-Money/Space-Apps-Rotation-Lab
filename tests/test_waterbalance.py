# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
import itertools

import numpy as np

from engine.crops import CROP_IDS, load_crops
from engine.waterbalance import ks_from_depletion, simulate_batch, simulate_plan
from tests.synth import make_scen

AWC = 150.0


def test_mass_closure_all_256_plans():
    scen = make_scen(S=8)
    plans = list(itertools.product(CROP_IDS, repeat=4))
    b = simulate_batch(scen, plans, AWC, 900.0)
    assert np.abs(b["closure_error_mm"]).max() < 1e-6


def test_mass_closure_recomputed_from_outputs_rice_years():
    scen = make_scen(S=10)
    r = simulate_plan(scen, ["rice", "rice", "jowar", "rice"], AWC, 700.0)
    inflow = (r["rain_total_mm"] + r["irrig_total_mm"]).sum(axis=1)
    outflow = (r["eta_total_mm"] + r["drainage_total_mm"] + r["runoff_total_mm"]).sum(axis=1)
    assert np.abs(inflow - outflow - r["storage_change_mm"]).max() < 1e-6
    assert np.abs(r["closure_error_mm"]).max() < 1e-6


def test_depletion_bounds_and_ks_while_below_raw():
    scen = make_scen(S=6)
    r = simulate_plan(scen, ["jowar", "bajra", "pigeonpea", "jowar"], AWC, 0.0, {"record_daily": True})
    dcol = r["dcol_mm"]
    dr, ks = r["daily"]["dr"], r["daily"]["ks"]
    assert dr.min() >= 0 and dr.max() <= dcol + 1e-9
    c = load_crops()["jowar"]
    taw = AWC * c.root_depth_m
    sow, n = c.sowing_doy - 1, c.season_days
    d, k = dr[:, 0, sow:sow + n], ks[:, 0, sow:sow + n]
    below = d <= c.p * taw
    assert below.any() and np.all(k[below] == 1.0)
    assert np.all(k[~below & (d < taw)] < 1.0)
    assert ks_from_depletion(0.0, 100, 0.5) == 1.0 and ks_from_depletion(100, 100, 0.5) == 0.0


def test_dry_down_monotonic_and_eta_declines_past_raw():
    scen = make_scen(S=2)
    scen["precip"][:] = 0.0
    r = simulate_plan(scen, ["jowar", "jowar", "jowar", "jowar"], AWC, 0.0,
                      {"record_daily": True, "hydrology.init_depletion_frac": 0.0})
    c = load_crops()["jowar"]
    raw = c.p * AWC * c.root_depth_m
    sow, n = c.sowing_doy - 1, c.season_days
    dr = r["daily"]["dr"][0, 0, sow:sow + n]
    ks = r["daily"]["ks"][0, 0, sow:sow + n]
    eta = r["daily"]["eta"][0, 0, sow:sow + n]
    assert np.all(np.diff(dr) >= -1e-12)                 # only ever dries
    assert np.all(np.diff(ks) <= 1e-12)
    past = np.where(dr > raw)[0]
    assert len(past) > 5
    kc = c.kc_curve()[:n]
    assert np.all(eta[past] <= kc[past] * 4.0 + 1e-9)
    assert eta[past][-1] < kc[past][-1] * 4.0 - 1e-6     # ETa below ETm once past RAW
    assert eta[-1] <= eta[past[0]] + 1e-9 or eta[-1] < 1.0


def test_rainfall_monotonicity_mean_yield():
    plans = [["rice", "rice", "rice", "rice"], ["rice", "jowar", "rice", "jowar"],
             ["rice", "pigeonpea", "jowar", "rice"], ["bajra"] * 4, ["pigeonpea", "bajra", "jowar", "rice"]]
    means = []
    for m in (0.4, 0.7, 1.0, 1.4):
        b = simulate_batch(make_scen(S=12, rain_mult=m), plans, AWC, 900.0, {"median_season_rain_mm": 600.0})
        means.append(b["yield_kg_ha"].mean(axis=(1, 2)))
    means = np.array(means)
    assert np.all(np.diff(means, axis=0) >= -1e-9)
