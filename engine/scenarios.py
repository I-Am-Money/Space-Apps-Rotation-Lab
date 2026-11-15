# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
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

    def derive(self, rain_mult: float = 1.0, dT: float = 0.0, shift_days: int = 0,
               upstream_mult: float = 1.0) -> "ScenSet":
        if rain_mult == 1.0 and dT == 0.0 and shift_days == 0 and upstream_mult == 1.0:
            return self
        return ScenSet(self.key + (("wi", round(float(rain_mult), 4), round(float(dT), 4), int(shift_days),
                                    round(float(upstream_mult), 4)),),
                       apply_whatif(self.scen, rain_mult, dT, shift_days, upstream_mult=upstream_mult), WHATIF_LABEL)

    def subset(self, n: int) -> "ScenSet":
        n = min(n, self.n)
        s = {k: (v[:n] if isinstance(v, (np.ndarray, list)) else v) for k, v in self.scen.items()}
        return ScenSet(self.key + (("first", n),), s, self.note)


# ---------------------------------------------------------------- annual data
def annual_from_arrays(years, et0, precip, tmax, upstream=None) -> dict:
    """upstream = Jun-Oct season rain (mm) upstream of Nagarjuna Sagar per year, or None if not available.
    Adds the monsoon onset day of every year (engine.monsoon, v3 section 6.2) and the record's median onset."""
    from engine import monsoon
    precip = np.asarray(precip, float)
    onset = monsoon.onset_doy_years(precip)
    return {"years": np.asarray(years), "et0": np.asarray(et0, float),
            "precip": precip, "tmax": np.asarray(tmax, float),
            "upstream": None if upstream is None else np.asarray(upstream, float),
            "onset": onset, "onset_median": float(np.median(onset))}


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


def load_upstream_for(years):
    """Upstream (upper Krishna basin) season rain aligned to `years`, from engine.fetch_upstream.
    Returns (array [Y] or None, note)."""
    try:
        from engine import fetch_upstream
        df = fetch_upstream.load_upstream_season_rain()
    except Exception as e:      # module absent or data not cached yet
        return None, f"upstream rain unavailable ({type(e).__name__}: {e})"
    d = df.set_index("year")["mean_season_rain_mm"] if "year" in df.columns else df["mean_season_rain_mm"]
    missing = [int(y) for y in years if int(y) not in d.index]
    if missing:
        return None, f"upstream rain missing for years {missing[:5]}..."
    return np.array([float(d.loc[int(y)]) for y in years]), "NASA POWER upstream points (engine.fetch_upstream)"


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
    a = annual_from_daily(w, et0.et0_daily(w, lat, elev))
    a["upstream"], a["upstream_note"] = load_upstream_for(a["years"])
    return a


# ------------------------------------------------------------ seasonal stats
def monsoon_rain(annual: dict) -> np.ndarray:
    return annual["precip"][:, JUN1:OCT1].sum(1)


GROWING = (JUN1, 304)           # June to October: the kharif growing season


def season_tmax(annual: dict) -> np.ndarray:
    """Mean daily maximum temperature over the growing season (June to October) of each year."""
    return annual["tmax"][:, GROWING[0]:GROWING[1]].mean(1)


def onset_doy(precip_year: np.ndarray) -> int:
    """Monsoon onset day-of-year (1-based) by the documented rule in engine/monsoon.py (v3 section 6.2)."""
    from engine import monsoon
    return monsoon.onset_doy(precip_year)


def _take(annual, idx) -> dict:
    idx = np.asarray(idx)
    return {k: annual[k][idx] for k in ("et0", "precip", "tmax")}


def make_scen(annual: dict, idx: np.ndarray, labels: list[str]) -> dict:
    s = _take(annual, idx)
    if annual.get("upstream") is not None:
        s["upstream_season_rain"] = np.asarray(annual["upstream"])[np.asarray(idx)]      # [S,4] mm
    s["labels"] = list(labels)
    s["year_idx"] = np.asarray(idx)
    if annual.get("onset") is not None:
        s["onset_doy"] = np.asarray(annual["onset"])[np.asarray(idx)]                   # [S,4] day-of-year, 1-based
        s["onset_median"] = float(annual["onset_median"])
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
    mr, tm = monsoon_rain(annual), season_tmax(annual)
    on = np.asarray(annual["onset"]) if annual.get("onset") is not None else np.array([onset_doy(annual["precip"][i]) for i in range(len(yrs))])
    med_year = int(np.argsort(np.abs(mr - np.median(mr)))[0])
    picks = [
        ("weakest monsoon in year 2", int(np.argmin(mr)), 2,
         lambda i: f"monsoon (Jun-Sep) rain {mr[i]:.0f} mm in {yrs[i]}, record median {np.median(mr):.0f} mm"),
        ("latest monsoon onset in year 1", int(np.argmax(on)), 1,
         lambda i: f"monsoon onset on day {on[i]} of {yrs[i]} by the rule in engine/monsoon.py, record median day {np.median(on):.0f}; sowing moves with it"),
        ("hottest season in year 3", int(np.argmax(tm)), 3,
         lambda i: f"June-October mean daily maximum {tm[i]:.1f} degC in {yrs[i]}, record median {np.median(tm):.1f} degC"),
    ]
    if annual.get("upstream") is not None:
        up = annual["upstream"]
        picks.append(("low canal release year", int(np.argmin(up)), 2,
                      lambda i: f"lowest upstream (upper Krishna basin) Jun-Oct rain {up[i]:.0f} mm in {yrs[i]}, record median {np.median(up):.0f} mm; "
                                f"proxy for canal releases, actual releases depend on reservoir operations"))
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
def delay_onset(precip: np.ndarray, onset_doy, n_days: int) -> np.ndarray:
    """Later monsoon onset what-if: the monsoon starts n_days later than it really did in each year, and the
    rain of those first n_days after the real onset does NOT arrive (it is lost, not moved). Rain before the
    real onset (pre-monsoon showers) and after the delayed onset is unchanged.
    precip [..., 365]; onset_doy [...] 1-based day-of-year of the real onset in each year."""
    n = int(n_days)
    if n <= 0:
        return precip
    day = np.arange(precip.shape[-1])
    on0 = np.asarray(onset_doy)[..., None] - 1                    # 0-based index of the real onset day
    lost = (day >= on0) & (day < on0 + n)
    return np.where(lost, 0.0, precip)


def shift_june_july(precip: np.ndarray, n_days: int) -> np.ndarray:
    """Fallback when the scenario carries no onset days: June-July rain of the first n_days is removed."""
    n = int(n_days)
    if n <= 0:
        return precip
    out = precip.copy()
    out[..., JUN1:min(JUN1 + n, DAYS)] = 0.0
    return out


def apply_whatif(scen: dict, rain_mult: float = 1.0, dT: float = 0.0, shift_days: int = 0,
                 et0_per_degc: float = ET0_PER_DEGC, upstream_mult: float = 1.0) -> dict:
    """Return a copy with rain scaled, temperature raised by dT, ET0 scaled by (1+k*dT),
    and the monsoon onset delayed by shift_days: the rain of the first shift_days after the real onset is lost
    and the onset day moves later by shift_days, so sowing moves too (v3 section 6.2).
    Labelled as what-if, not forecast."""
    out = dict(scen)
    if "onset_doy" in scen:
        p = delay_onset(scen["precip"], scen["onset_doy"], shift_days) * float(rain_mult)
    else:
        p = shift_june_july(scen["precip"], shift_days) * float(rain_mult)
    out["precip"] = p
    out["tmax"] = scen["tmax"] + float(dT)
    if "onset_doy" in scen and int(shift_days) > 0:
        out["onset_doy"] = np.asarray(scen["onset_doy"]) + int(shift_days)
    out["et0"] = scen["et0"] * (1.0 + et0_per_degc * float(dT))
    if "upstream_season_rain" in scen:      # independent of the local multiplier
        out["upstream_season_rain"] = np.asarray(scen["upstream_season_rain"]) * float(upstream_mult)
    out["whatif"] = {"rain_mult": float(rain_mult), "upstream_mult": float(upstream_mult), "dT": float(dT), "shift_days": int(shift_days),
                     "label": WHATIF_LABEL, "et0_scaling": ET0_PER_DEGC_NOTE}
    return out


def upstream_median(scen: dict):
    u = scen.get("upstream_season_rain")
    return None if u is None else float(np.median(u))


def median_year_scenario(annual: dict) -> ScenSet:
    """One scenario: the median-monsoon real year repeated for all 4 plan years (base for the canal what-if)."""
    mr = monsoon_rain(annual)
    i = int(np.argsort(np.abs(mr - np.median(mr)))[0])
    return ScenSet(("medyear", int(annual["years"][i])), make_scen(annual, np.array([[i] * PLAN_YEARS]),
                   [f"median-monsoon year {int(annual['years'][i])} x4"]), "median real year repeated")


CANAL_LOW_RELEASE_FACTOR = 0.5   # what-if multiplier on available irrigation; assumption, team to verify; NOT release data
