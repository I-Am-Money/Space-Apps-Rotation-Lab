# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Scenario construction (engine-decision).

A scenario is one plan of 4 consecutive years of REAL weather (Feb 29 dropped):
dict with float arrays ``et0, precip, tmax`` shaped [S, 4, 365] plus ``labels``.

What-if adjustments (rainfall multiplier, +dT, late monsoon) are edits applied to
real years. They are "what-if adjustments to real years, not forecasts".
"""
from __future__ import annotations

from dataclasses import dataclass
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


def load_annual(lat: float | None = None, lon: float | None = None) -> dict:
    from engine.configuration import version
    return _load_annual(lat, lon, version(include_data=True))


@lru_cache(maxsize=4)
def _load_annual(lat, lon, source_version) -> dict:
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
    a["source_version"] = source_version
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
    s["source_version"] = annual.get("source_version", ())
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
    return ScenSet(("hist", int(yrs[0]), int(yrs[-1]), annual.get("source_version", ())), make_scen(annual, idx, labels), "historical 4-year blocks")


def bootstrap_plans(annual: dict, n: int = N_BOOT, seed: int = SEED) -> ScenSet:
    """n plans of 4 years drawn at random (with replacement) from the real record."""
    rng = np.random.default_rng(seed)
    Y = len(annual["years"])
    idx = rng.integers(0, Y, size=(n, PLAN_YEARS))
    yrs = annual["years"]
    labels = ["/".join(str(yrs[i]) for i in r) for r in idx]
    return ScenSet(("boot", n, seed, int(yrs[0]), int(yrs[-1]), annual.get("source_version", ())), make_scen(annual, idx, labels),
                   "bootstrap of real years (seed 42)")


def _stress_tests_v3(annual: dict) -> dict:
    """Named stress tests. Each is ONE real year placed in the stated plan year; the other
    three plan years are the median-monsoon year of the record (documented filler).
    Returns {name: {scen, source_year, plan_year, description}}."""
    yrs = annual["years"]
    mr, tm = monsoon_rain(annual), season_tmax(annual)
    on = np.asarray(annual["onset"]) if annual.get("onset") is not None else np.array([onset_doy(annual["precip"][i]) for i in range(len(yrs))])
    med_year = int(np.argsort(np.abs(mr - np.median(mr)))[0])
    picks = [
        ("driest monsoon in year 2", int(np.argmin(mr)), 2,
         lambda i: f"monsoon (Jun-Sep) rain {mr[i]:.0f} mm in {yrs[i]}, record median {np.median(mr):.0f} mm"),
        ("latest monsoon onset in year 1", int(np.argmax(on)), 1,
         lambda i: f"monsoon onset on day {on[i]} of {yrs[i]} by the rule in engine/monsoon.py, record median day {np.median(on):.0f}; sowing moves with it"),
        ("hottest kharif season in year 3", int(np.argmax(tm)), 3,
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
    out["tmax"] = scen["tmax"] if dT == 0 else scen["tmax"] + float(dT)
    if "onset_doy" in scen and int(shift_days) > 0:
        out["onset_doy"] = np.asarray(scen["onset_doy"]) + int(shift_days)
    out["et0"] = scen["et0"] if dT == 0 else scen["et0"] * (1.0 + et0_per_degc * float(dT))
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


# =====================================================================================================
# v4 (universal, any farm). Feature 2, Person 2. Everything above is the v3 Nalgonda code, kept working.
#
# Scenarios           a set of 4-year plans made of REAL years of the site's own weather record.
# site_years(w)       daily weather frame (Site.weather) -> one row per full calendar year.
# historical(...)     every run of 4 consecutive real years (R7).
# bootstrap(...)      500 plans of 4 real years drawn with replacement, seed 42 (R7).
# stress_tests(...)   named stress tests, each labeled with the real years it is made of (R7).
# build(...)          one call for the three above; default for simulate().
# Scenarios.adjust()  what-if: rainfall multiplier and heat shift applied to real years (not a forecast).
# =====================================================================================================
from dataclasses import field as _field, replace as _replace


@dataclass
class Scenarios:
    kind: str                       # "historical" | "bootstrap" | "stress"
    years: np.ndarray               # [S,4] the real year used in each plan year
    labels: list                    # [S] plain-English label with the real years
    precip: np.ndarray              # [S,4,365] mm/day
    et0: np.ndarray                 # [S,4,365] mm/day
    tmax: np.ndarray                # [S,4,365] degC
    weights: np.ndarray             # [S], sums to 1 (equal unless a climate-shift mode re-weights)
    rain_normal_mm: float           # median yearly rainfall of the whole real record
    rain_dry_mm: float              # yearly rainfall of a dry year (rule dry_year_quantile) of the real record
    record: tuple = (0, 0)          # first and last full year of the weather record
    names: list = _field(default_factory=list)     # stress tests only: the name of each test
    rain_mult: float = 1.0
    heat_shift_c: float = 0.0
    note: str = "real years from NASA POWER"
    seed: int | None = None

    @property
    def n(self) -> int:
        return int(self.precip.shape[0])

    def annual_rain(self) -> np.ndarray:
        """[S,4] rainfall of each plan year (mm), after any what-if multiplier."""
        return self.precip.sum(axis=2)

    def adjust(self, rain_mult: float = 1.0, heat_shift_c: float = 0.0) -> "Scenarios":
        """What-if adjustment of real years (not a forecast): every day's rain times rain_mult, every day's
        maximum temperature plus heat_shift_c. ET0 rises by rule heat_shift_et0_pct_per_c per degree
        (0 by default, so the heat shift changes heat days only until the team verifies a value)."""
        if rain_mult == 1.0 and heat_shift_c == 0.0:
            return self
        from engine.crops import rule
        k = float(rule("heat_shift_et0_pct_per_c")) / 100.0
        return _replace(self, precip=self.precip * float(rain_mult), tmax=self.tmax + float(heat_shift_c),
                        et0=self.et0 * (1.0 + k * float(heat_shift_c)),
                        rain_mult=self.rain_mult * float(rain_mult), heat_shift_c=self.heat_shift_c + float(heat_shift_c),
                        note="what-if adjustments to real years, not forecasts")

    def subset(self, idx) -> "Scenarios":
        idx = np.asarray(idx)
        w = self.weights[idx]
        return _replace(self, years=self.years[idx], labels=[self.labels[int(i)] for i in idx], precip=self.precip[idx],
                        et0=self.et0[idx], tmax=self.tmax[idx], weights=w / w.sum(),
                        names=[self.names[int(i)] for i in idx] if self.names else [])

    def reweighted(self, weights) -> "Scenarios":
        w = np.asarray(weights, float)
        return _replace(self, weights=w / w.sum())


_SITE_YEARS_CACHE: dict = {}


def site_years(weather, lat: float | None = None, elevation_m: float | None = None) -> dict:
    """Daily weather frame -> {"years": [Y], "precip", "et0", "tmax", "tmin": [Y,365]} for full calendar years
    (29 February dropped). Uses the frame's own et0 column; if there is none, ET0 is computed with
    engine.et0 (FAO-56 Penman-Monteith, Hargreaves on days with missing inputs)."""
    key = (id(weather), len(weather), None if lat is None else round(float(lat), 4))
    hit = _SITE_YEARS_CACHE.get(key)
    if hit is not None and hit[0] is weather:
        return hit[1]
    import pandas as pd
    idx = pd.DatetimeIndex(weather.index)
    if "et0" in weather.columns:
        e = weather["et0"].to_numpy(float)
    else:
        from engine import et0 as _et0
        la = float(lat if lat is not None else weather.attrs.get("lat"))
        el = float(elevation_m if elevation_m is not None else weather.attrs.get("elevation_m", 0.0) or 0.0)
        e = _et0.et0_daily(weather, la, el)
    keep = ~((idx.month == 2) & (idx.day == 29))
    yrs = idx.year.to_numpy()[keep]
    cols = {"precip": weather["precip"].to_numpy(float)[keep], "et0": np.asarray(e, float)[keep],
            "tmax": weather["tmax"].to_numpy(float)[keep], "tmin": weather["tmin"].to_numpy(float)[keep]}
    uniq, counts = np.unique(yrs, return_counts=True)
    full = [int(y) for y, c in zip(uniq, counts) if c == DAYS
            and all(np.isfinite(v[yrs == y]).all() and (v[yrs == y] > -900).all() for v in cols.values())]
    if len(full) < PLAN_YEARS:
        raise ValueError(f"the weather record has {len(full)} full years; at least {PLAN_YEARS} are needed")
    out = {"years": np.array(full)}
    for k, v in cols.items():
        out[k] = np.stack([v[yrs == y] for y in full])
    out["precip"] = np.maximum(out["precip"], 0.0)
    out["et0"] = np.maximum(out["et0"], 0.0)
    _SITE_YEARS_CACHE.clear()
    _SITE_YEARS_CACHE[key] = (weather, out)
    return out


def _as_annual(weather_or_annual, lat=None, elevation_m=None) -> dict:
    if isinstance(weather_or_annual, dict) and "years" in weather_or_annual:
        return weather_or_annual
    return site_years(weather_or_annual, lat, elevation_m)


def _make(annual: dict, idx, labels, kind: str, names=None, seed=None) -> Scenarios:
    from engine.crops import rule
    idx = np.asarray(idx, int)
    rain = annual["precip"].sum(axis=1)
    yrs = np.asarray(annual["years"])
    return Scenarios(kind=kind, years=yrs[idx], labels=list(labels), precip=annual["precip"][idx], et0=annual["et0"][idx],
                     tmax=annual["tmax"][idx], weights=np.full(len(idx), 1.0 / len(idx)),
                     rain_normal_mm=float(np.median(rain)),
                     rain_dry_mm=float(np.quantile(rain, float(rule("dry_year_quantile")))),
                     record=(int(yrs[0]), int(yrs[-1])), names=list(names or []), seed=seed)


def historical(weather_or_annual, lat=None, elevation_m=None) -> Scenarios:
    """Every run of 4 consecutive real years in the record (R7)."""
    a = _as_annual(weather_or_annual, lat, elevation_m)
    yrs = a["years"]
    runs = [i for i in range(len(yrs) - PLAN_YEARS + 1) if yrs[i + PLAN_YEARS - 1] - yrs[i] == PLAN_YEARS - 1]
    idx = np.array([[i + j for j in range(PLAN_YEARS)] for i in runs])
    return _make(a, idx, [f"{yrs[r[0]]}-{yrs[r[-1]]}" for r in idx], "historical")


def bootstrap(weather_or_annual, n: int | None = None, seed: int | None = None, lat=None, elevation_m=None) -> Scenarios:
    """n plans (default 500) of 4 real years drawn with replacement from the record, fixed seed (default 42)."""
    from engine.crops import rule
    a = _as_annual(weather_or_annual, lat, elevation_m)
    n = int(rule("n_bootstrap") if n is None else n)
    seed = int(rule("seed") if seed is None else seed)
    idx = np.random.default_rng(seed).integers(0, len(a["years"]), size=(n, PLAN_YEARS))
    yrs = a["years"]
    return _make(a, idx, ["/".join(str(yrs[i]) for i in r) for r in idx], "bootstrap", seed=seed)


def stress_tests(weather_or_annual, lat=None, elevation_m=None):
    """Named stress tests made only of real years; each label names the years (R7).

    Called with a daily weather frame (v4) it returns a Scenarios set. Called with the v3 annual dict (the one
    with an "onset" entry) it keeps the v3 behaviour, so the v3 engine and its tests are unchanged.
    """
    if isinstance(weather_or_annual, dict) and "onset" in weather_or_annual:
        return _stress_tests_v3(weather_or_annual)
    a = _as_annual(weather_or_annual, lat, elevation_m)
    yrs = a["years"]
    rain = a["precip"].sum(axis=1)
    hot = np.sort(a["tmax"], axis=1)[:, -30:].mean(axis=1)                 # mean of the 30 hottest days of each year
    h = historical(a)
    block_rain = h.precip.sum(axis=(1, 2))
    med = int(np.argsort(np.abs(rain - np.median(rain)))[0])
    start = {int(r[0]): i for i, r in enumerate(h.years)}
    first = np.array([list(yrs).index(int(r[0])) for r in h.years])
    rows, names, labels = [], [], []

    def add(name, row, text):
        rows.append(row), names.append(name), labels.append(f"{name}: {text}")

    i = int(np.argmin(block_rain))
    add("Driest four years in a row", [first[i] + j for j in range(PLAN_YEARS)],
        f"{h.labels[i]}, {block_rain[i] / PLAN_YEARS:.0f} mm of rain a year (record median {np.median(rain):.0f} mm)")
    d = int(np.argmin(rain))
    add("Driest single year", [med, d, med, med],
        f"{yrs[d]} ({rain[d]:.0f} mm) as plan year 2, the other years are {yrs[med]} (the median-rain year)")
    two = rain[:-1] + rain[1:]
    ok = np.diff(yrs) == 1
    if ok.any():
        t = int(np.argmin(np.where(ok, two, np.inf)))
        add("Two dry years back to back", [med, t, t + 1, med],
            f"{yrs[t]} and {yrs[t + 1]} ({rain[t]:.0f} and {rain[t + 1]:.0f} mm) as plan years 2 and 3, "
            f"the other years are {yrs[med]}")
    x = int(np.argmax(hot))
    add("Hottest year", [med, x, med, med],
        f"{yrs[x]} (its 30 hottest days averaged {hot[x]:.1f} degC) as plan year 2, the other years are {yrs[med]}")
    wet = int(np.argmax(rain))
    add("Wettest year", [med, wet, med, med],
        f"{yrs[wet]} ({rain[wet]:.0f} mm) as plan year 2, the other years are {yrs[med]}")
    return _make(a, np.array(rows), labels, "stress", names=names)


def build(weather_or_annual, kind: str = "bootstrap", n: int | None = None, seed: int | None = None,
          lat=None, elevation_m=None) -> Scenarios:
    """One entry point: kind = "bootstrap" (default), "historical" or "stress"."""
    if kind == "bootstrap":
        return bootstrap(weather_or_annual, n, seed, lat, elevation_m)
    if kind == "historical":
        return historical(weather_or_annual, lat, elevation_m)
    if kind == "stress":
        return stress_tests(weather_or_annual, lat, elevation_m)
    raise ValueError(f"unknown scenario kind {kind!r}")
