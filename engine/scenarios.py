"""Scenario construction (engine-decision).

A scenario is one plan of 4 consecutive years of REAL weather (Feb 29 dropped):
dict with float arrays ``et0, precip, tmax`` shaped [S, 4, 365] plus ``labels``.

What-if adjustments (rainfall multiplier, +dT, late monsoon) are edits applied to
real years. They are "what-if adjustments to real years, not forecasts".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SEED = 42
N_BOOT = 500
PLAN_YEARS = 4
DAYS = 365
# 0-based day-of-year indices in a 365-day (non-leap) year
MAR1, MAY15, JUN1, AUG1, OCT1 = 59, 134, 151, 212, 273
JUN_JUL = (JUN1, AUG1)
MONSOON = (JUN1, OCT1)          # Jun-Sep
PRE_MONSOON = (MAR1, JUN1)      # Mar-May

# ET0 response to warming used when we scale instead of recomputing the full
# Penman-Monteith chain: ~ +4 % ET0 per degC. Assumption, literature range
# roughly 2-5 % per degC, team to verify.
ET0_PER_DEGC = 0.04
ET0_PER_DEGC_NOTE = "documented scaling: ET0 rises 4% per degC (assumption, literature range 2-5%, team to verify)"
WHATIF_LABEL = "what-if adjustments to real years, not forecasts"


@dataclass
class ScenSet:
    """A scenario array dict plus a hashable key used for caching."""
    key: tuple
    scen: dict
    note: str = ""

    @property
    def n(self) -> int:
        return self.scen["precip"].shape[0]

    def derive(self, rain_mult: float = 1.0, dT: float = 0.0, shift_days: int = 0) -> "ScenSet":
        if rain_mult == 1.0 and dT == 0.0 and shift_days == 0:
            return self
        return ScenSet(self.key + (("wi", round(float(rain_mult), 4), round(float(dT), 4), int(shift_days)),),
                       apply_whatif(self.scen, rain_mult, dT, shift_days), WHATIF_LABEL)

    def subset(self, n: int) -> "ScenSet":
        n = min(n, self.n)
        s = {k: (v[:n] if isinstance(v, np.ndarray) else v[:n]) for k, v in self.scen.items()}
        return ScenSet(self.key + (("first", n),), s, self.note)


# ---------------------------------------------------------------- annual data
def annual_from_arrays(years, et0, precip, tmax) -> dict:
    return {"years": np.asarray(years), "et0": np.asarray(et0, float),
            "precip": np.asarray(precip, float), "tmax": np.asarray(tmax, float)}


def annual_from_daily(weather, et0_daily_arr) -> dict:
    """Split a daily frame (index = dates) + daily ET0 into [Y,365] arrays, dropping Feb 29."""
    import pandas as pd
    idx = pd.DatetimeIndex(weather.index)
    keep = ~((idx.month == 2) & (idx.day == 29))
    yrs = idx[keep].year
    uniq = np.unique(yrs)
    full = [y for y in uniq if (yrs == y).sum() == DAYS]
    def mat(a):
        a = np.asarray(a, float)[keep]
        return np.stack([a[yrs == y] for y in full])
    return annual_from_arrays(full, mat(et0_daily_arr), mat(weather["precip"].to_numpy()),
                              mat(weather["tmax"].to_numpy()))


@lru_cache(maxsize=4)
def load_annual(lat: float | None = None, lon: float | None = None) -> dict:
    """Real weather -> annual arrays. Needs engine.fetch_power and engine.et0 (other agents)."""
    import yaml
    from engine import fetch_power, et0
    reg = yaml.safe_load(open(ROOT / "config" / "region.yaml")) or {}
    lat = float(lat if lat is not None else reg.get("lat", 17.5))
    lon = float(lon if lon is not None else reg.get("lon", 78.5))
    elev = float(reg.get("elevation_m", 0.0) or 0.0)
    w = fetch_power.load_weather(lat, lon)
    return annual_from_daily(w, et0.et0_daily(w, lat, elev))


# ------------------------------------------------------------ seasonal stats
def monsoon_rain(annual: dict) -> np.ndarray:
    return annual["precip"][:, JUN1:OCT1].sum(1)


def summer_tmax(annual: dict) -> np.ndarray:
    return annual["tmax"][:, MAR1:JUN1].mean(1)


def onset_doy(precip_year: np.ndarray, window: int = 7, thresh_mm: float = 50.0) -> int:
    """First day from 15 May where the trailing 7-day rain >= 50 mm (a documented
    onset proxy). Returns OCT1 (273) if it never happens."""
    c = np.concatenate([[0.0], np.cumsum(precip_year)])
    for d in range(MAY15, OCT1):
        lo = max(0, d - window + 1)
        if c[d + 1] - c[lo] >= thresh_mm:
            return d
    return OCT1


def _take(annual, idx) -> dict:
    idx = np.asarray(idx)
    return {k: annual[k][idx] for k in ("et0", "precip", "tmax")}


def make_scen(annual: dict, idx: np.ndarray, labels: list[str]) -> dict:
    s = _take(annual, idx)
    s["labels"] = list(labels)
    s["year_idx"] = np.asarray(idx)
    return s


def historical_blocks(annual: dict) -> ScenSet:
    """Every run of 4 consecutive years (count derived from the weather record length)."""
    Y = len(annual["years"])
    idx = np.array([[i + j for j in range(PLAN_YEARS)] for i in range(Y - PLAN_YEARS + 1)])
    yrs = annual["years"]
    labels = [f"{yrs[r[0]]}-{yrs[r[-1]]}" for r in idx]
    return ScenSet(("hist", int(yrs[0]), int(yrs[-1])), make_scen(annual, idx, labels), "historical 4-year blocks")


def bootstrap_plans(annual: dict, n: int = N_BOOT, seed: int = SEED) -> ScenSet:
    """n plans of 4 years drawn at random (with replacement) from the real record."""
    rng = np.random.default_rng(seed)
    Y = len(annual["years"])
    idx = rng.integers(0, Y, size=(n, PLAN_YEARS))
    yrs = annual["years"]
    labels = ["/".join(str(yrs[i]) for i in r) for r in idx]
    return ScenSet(("boot", n, seed, int(yrs[0]), int(yrs[-1])), make_scen(annual, idx, labels),
                   "bootstrap of real years (seed 42)")


def stress_tests(annual: dict) -> dict:
    """Named stress tests. Each is ONE real year placed in the stated plan year; the other
    three plan years are the median-monsoon year of the record (documented filler).
    Returns {name: {scen, source_year, plan_year, description}}."""
    yrs = annual["years"]
    mr, tm = monsoon_rain(annual), summer_tmax(annual)
    on = np.array([onset_doy(annual["precip"][i]) for i in range(len(yrs))])
    med_year = int(np.argsort(np.abs(mr - np.median(mr)))[0])
    picks = [
        ("driest monsoon in year 2", int(np.argmin(mr)), 2,
         lambda i: f"monsoon (Jun-Sep) rain {mr[i]:.0f} mm in {yrs[i]}, record median {np.median(mr):.0f} mm"),
        ("hottest summer in year 3", int(np.argmax(tm)), 3,
         lambda i: f"Mar-May mean Tmax {tm[i]:.1f} degC in {yrs[i]}, record median {np.median(tm):.1f} degC"),
        ("latest monsoon onset in year 1", int(np.argmax(on)), 1,
         lambda i: f"onset proxy on day {on[i]+1} of {yrs[i]} (first 7-day rain >= 50 mm after 15 May), median day {int(np.median(on))+1}"),
    ]
    out = {}
    for name, i, py, desc in picks:
        row = [med_year] * PLAN_YEARS
        row[py - 1] = i
        label = f"{name} (source year {yrs[i]})"
        out[name] = {"scen": make_scen(annual, np.array([row]), [label]), "source_year": int(yrs[i]),
                     "plan_year": py, "filler_year": int(yrs[med_year]), "description": desc(i),
                     "label": label, "key": ("stress", name, int(yrs[i]))}
    return out


# ----------------------------------------------------------------- what-ifs
def shift_june_july(precip: np.ndarray, n_days: int) -> np.ndarray:
    """Move Jun-Jul rain n_days later, conserving the total (rain lands in Aug if shifted past Jul)."""
    n = int(n_days)
    if n <= 0:
        return precip
    out = precip.copy()
    lo, hi = JUN_JUL
    window = precip[..., lo:hi].copy()
    out[..., lo:hi] = 0.0
    n = min(n, DAYS - hi)
    out[..., lo + n:hi + n] += window
    return out


def apply_whatif(scen: dict, rain_mult: float = 1.0, dT: float = 0.0, shift_days: int = 0,
                 et0_per_degc: float = ET0_PER_DEGC) -> dict:
    """Return a copy with rain scaled, temperature raised by dT, ET0 scaled by (1+k*dT),
    and Jun-Jul rain shifted later. Labelled as what-if, not forecast."""
    out = dict(scen)
    p = shift_june_july(scen["precip"], shift_days) * float(rain_mult)
    out["precip"] = p
    out["tmax"] = scen["tmax"] + float(dT)
    out["et0"] = scen["et0"] * (1.0 + et0_per_degc * float(dT))
    out["whatif"] = {"rain_mult": float(rain_mult), "dT": float(dT), "shift_days": int(shift_days),
                     "label": WHATIF_LABEL, "et0_scaling": ET0_PER_DEGC_NOTE}
    return out
