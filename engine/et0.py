# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""FAO-56 Penman-Monteith reference evapotranspiration (daily).

Reference: Allen, Pereira, Raes, Smith (1998), FAO Irrigation and Drainage
Paper 56, ch. 3 (eq. 6, 7, 8, 12, 13, 19, 21, 23, 24, 37, 39, 40, 47, 50, 52).
Hargreaves fallback is eq. 52 of the same chapter.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

GSC = 0.0820            # solar constant, MJ m-2 min-1
SIGMA = 4.903e-9        # Stefan-Boltzmann, MJ K-4 m-2 day-1
ALBEDO = 0.23           # grass reference surface


def _sat_vp(t):
    """Saturation vapour pressure, kPa (eq. 11)."""
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def extraterrestrial_radiation(lat_deg: float, doy):
    """Ra, MJ m-2 day-1 (eq. 21) and daylight hours N (eq. 34)."""
    doy = np.asarray(doy, dtype=float)
    phi = np.radians(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    delta = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(delta), -1, 1))
    ra = (24 * 60 / np.pi) * GSC * dr * (
        ws * np.sin(phi) * np.sin(delta) + np.cos(phi) * np.cos(delta) * np.sin(ws))
    return ra, 24 * ws / np.pi


def et0_penman_monteith(tmax, tmin, rs, u2, ea, lat_deg, doy, elevation_m):
    """FAO-56 PM daily ET0 (eq. 6), mm/day, with G = 0. All inputs array-like.

    ea: actual vapour pressure, kPa. rs: shortwave MJ m-2 day-1. u2: m/s at 2 m.
    """
    tmax, tmin, rs, u2, ea = (np.asarray(x, dtype=float) for x in (tmax, tmin, rs, u2, ea))
    tmean = (tmax + tmin) / 2
    p = 101.3 * ((293 - 0.0065 * elevation_m) / 293) ** 5.26          # eq. 7
    gamma = 0.000665 * p                                               # eq. 8
    delta = 4098 * _sat_vp(tmean) / (tmean + 237.3) ** 2               # eq. 13
    es = (_sat_vp(tmax) + _sat_vp(tmin)) / 2                           # eq. 12
    ea = np.minimum(ea, es)
    ra, _ = extraterrestrial_radiation(lat_deg, doy)
    rso = (0.75 + 2e-5 * elevation_m) * ra                             # eq. 37
    rns = (1 - ALBEDO) * rs                                            # eq. 38
    ratio = np.clip(rs / np.maximum(rso, 1e-6), 0.3, 1.0)
    rnl = SIGMA * (((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2) \
        * (0.34 - 0.14 * np.sqrt(ea)) * (1.35 * ratio - 0.35)          # eq. 39
    rn = rns - rnl                                                     # eq. 40
    num = 0.408 * delta * rn + gamma * (900 / (tmean + 273)) * u2 * (es - ea)
    den = delta + gamma * (1 + 0.34 * u2)
    return np.maximum(num / den, 0.0)


def et0_hargreaves(tmax, tmin, lat_deg, doy):
    """Hargreaves-Samani ET0, mm/day (FAO-56 eq. 52)."""
    tmax, tmin = np.asarray(tmax, float), np.asarray(tmin, float)
    ra, _ = extraterrestrial_radiation(lat_deg, doy)
    tmean = (tmax + tmin) / 2
    return np.maximum(0.0023 * (tmean + 17.8) * np.sqrt(np.maximum(tmax - tmin, 0)) * 0.408 * ra, 0.0)


def et0_daily(weather: pd.DataFrame, lat: float, elevation_m: float) -> np.ndarray:
    """Daily ET0 (mm/day) for a weather frame (columns tmax,tmin,rh,wind2,srad).

    ea = RH/100 * es (es = mean of saturation vp at tmax and tmin), since POWER
    gives one daily mean RH. Days with a missing/-999 input fall back to
    Hargreaves (needs only tmax/tmin) and the count is logged.
    """
    w = weather
    doy = w.index.day_of_year.to_numpy()
    cols = {c: w[c].to_numpy(dtype=float) for c in ("tmax", "tmin", "rh", "wind2", "srad")}
    bad = np.zeros(len(w), dtype=bool)
    for c, v in cols.items():
        bad |= ~np.isfinite(v) | (v <= -900)
    rh = np.clip(np.where(bad, 50.0, cols["rh"]), 1, 100)
    safe = {c: np.where(bad, 0.0, v) for c, v in cols.items()}
    es = (_sat_vp(safe["tmax"]) + _sat_vp(safe["tmin"])) / 2
    ea = rh / 100 * es
    et = et0_penman_monteith(safe["tmax"], safe["tmin"], safe["srad"], np.maximum(safe["wind2"], 0.5),
                             ea, lat, doy, elevation_m)
    if bad.any():
        tx, tn = cols["tmax"], cols["tmin"]
        tbad = bad & ~(np.isfinite(tx) & np.isfinite(tn) & (tx > -900) & (tn > -900))
        if tbad.any():
            raise ValueError(f"{int(tbad.sum())} days lack tmax/tmin; cannot compute ET0")
        hg = et0_hargreaves(np.where(bad, tx, 0), np.where(bad, tn, 0), lat, doy)
        et = np.where(bad, hg, et)
        log.warning("ET0: Hargreaves fallback used on %d of %d days (missing inputs)", int(bad.sum()), len(w))
    return et
