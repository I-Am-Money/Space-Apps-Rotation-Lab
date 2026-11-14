"""Synthetic stand-ins for the decision tests (NOT model results)."""
import numpy as np
from engine import scenarios as sc

YM = {"rice": 5000., "jowar": 3000., "bajra": 2200., "pigeonpea": 1200.}
NEED = {"rice": 900., "jowar": 450., "bajra": 400., "pigeonpea": 500.}
KY = {"rice": 1.1, "jowar": 0.9, "bajra": 0.8, "pigeonpea": 0.8}


def synthetic_annual(n_years=30, seed=1):
    rng = np.random.default_rng(seed)
    days = np.arange(365)
    shape = np.where((days >= 151) & (days < 273), 6.0, 0.4)
    wet = rng.lognormal(0, 0.3, size=(n_years, 1))
    scale = (shape[None, :] * wet) / 0.6
    p = rng.gamma(0.6, scale, size=(n_years, 365)) * (rng.random((n_years, 365)) < 0.5) * 2
    et0 = np.full((n_years, 365), 4.0) + rng.normal(0, 0.2, (n_years, 365))
    tmax = 33 + 4 * np.sin((days - 80) / 365 * 2 * np.pi) + rng.normal(0, 1, (n_years, 365))
    up = 900 * rng.lognormal(0, 0.25, n_years)
    return sc.annual_from_arrays(np.arange(1990, 1990 + n_years), et0, p, tmax, upstream=up)


def fake_simulate_plan(scen, plan, awc, irrigation_mm, params=None):
    P = scen["precip"]
    S = P.shape[0]
    rain = P[:, :, 151:273].sum(-1)
    med = np.median(rain)
    y = np.zeros((S, 4)); eta = np.zeros((S, 4)); etm = np.zeros((S, 4)); irr = np.zeros((S, 4)); need_i = np.zeros((S, 4)); irr_c = np.zeros((S, 4)); irr_w = np.zeros((S, 4))
    for t, c in enumerate(plan):
        etm[:, t] = NEED[c]
        eff = 0.8 * rain[:, t]
        if c == "rice":
            need = np.maximum(0, NEED[c] - eff)
            if "upstream_season_rain" in scen:
                canal = 0.6 * irrigation_mm * (scen["upstream_season_rain"][:, t] / np.median(scen["upstream_season_rain"])) ** 0.7
                well = 0.4 * irrigation_mm * (rain[:, t] / med) ** 0.5
                ic = np.minimum(need, canal); iw = np.minimum(need - ic, well)
                irr_c[:, t], irr_w[:, t] = ic, iw
                avail = canal + well
            else:
                avail = irrigation_mm * (rain[:, t] / med) ** 0.5
            irr[:, t] = np.minimum(need, avail); need_i[:, t] = need
        eta[:, t] = np.minimum(NEED[c], eff + irr[:, t] + 0.2 * awc)
        pen = 0.95 if (t > 0 and plan[t - 1] == c) else 1.0
        y[:, t] = YM[c] * np.clip(1 - KY[c] * (1 - eta[:, t] / etm[:, t]), 0, 1) * pen
    return {"yield_kg_ha": y, "eta_mm": eta, "etm_mm": etm, "rain_mm": np.repeat(rain[:, :1] * 0 + rain, 1, axis=1),
            "irrig_mm": irr, "irrig_canal_mm": irr_c, "irrig_well_mm": irr_w, "irrig_needed_mm": need_i, "runoff_mm": np.zeros((S, 4)), "drainage_mm": np.zeros((S, 4)),
            "storage_change_mm": np.zeros(S), "closure_error_mm": np.zeros(S)}
