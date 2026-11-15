# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Feature 2: simulate a 4-year rotation on a farm across many weather scenarios.

    simulate(site, inputs, rotation, scenarios=None) -> SimResult
    simulate_many(site, inputs, rotations, scenarios=None) -> [SimResult, ...]   (one batch, for the optimizer)

site      Site from engine/api.py (or a dict): weather (daily frame), lat, soil (awc_mm_per_m, optional
          hydrologic_group), elevation_m, us_defaults.
inputs    UserInputs (or a dict): water (mode, normal_mm, dry_mm), crop_overrides {crop: {yield, ...}}.
rotation  4 crop names; a year may be a list (double crop) or "fallow"; or an object/dict with crops and
          cover_crops. Shorter plans repeat to 4 years.
scenarios engine.scenarios.Scenarios (bootstrap, historical or stress; optionally .adjust()-ed or
          changed by engine.climate_shift). Default: 500 bootstrap plans, seed 42.

    what_if(rain_mult=, heat_shift_c=, water=, scenarios=, climate_shift=)   context manager
          Every simulate() call inside the block runs under that what-if, whoever makes the call. This is how
          engine/tipping.py asks api.recommend() "what would win with 30% less rain" without changing any
          signature. Potential yields and planting dates stay those of the real farm.

Units are metric: mm of water, kg/ha, degC. Every array's first axis is the scenario.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

import numpy as np

from engine import crops as C
from engine import scenarios as SC
from engine import waterbalance as WB
from engine import yieldmodel as YM


@dataclass
class SimResult:
    feasible: bool
    reason: str = ""
    crops: list = field(default_factory=list)          # 4 lists of crop ids (normalized rotation)
    cover_crops: list = field(default_factory=list)
    seasons: list = field(default_factory=list)        # one dict per cash-crop season: crop, plan_year, timing, ym, ...
    cover_seasons: list = field(default_factory=list)  # timing of the cover crops actually grown
    labels: list = field(default_factory=list)         # [S] scenario labels (real years)
    weights: np.ndarray = None                         # [S]
    rel_yield: np.ndarray = None                       # [S,K] Ya/Ym per season
    yield_kg_ha: np.ndarray = None                     # [S,K] (NaN where no potential yield is known)
    heat_days: np.ndarray = None                       # [S,K] hot days in the flowering window
    eta_mm: np.ndarray = None                          # [S,K] crop water use (actual ET) per season
    etm_mm: np.ndarray = None                          # [S,K] water use with no stress per season
    irrigation_season_mm: np.ndarray = None            # [S,K]
    irrigation_mm: np.ndarray = None                   # [S,4] per plan year
    supply_mm: np.ndarray = None                       # [S,4] irrigation water available per plan year
    rain_mm: np.ndarray = None                         # [S,4]
    total_water_mm: np.ndarray = None                  # [S,4] ET of the whole year (crop, cover and bare soil)
    runoff_mm: np.ndarray = None                       # [S,4]
    drainage_mm: np.ndarray = None                     # [S,4]
    closure_error_mm: np.ndarray = None                # [S] water in - water out - storage change (about 0)
    badges: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    def __getitem__(self, key):
        return getattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)

    @property
    def n_scenarios(self) -> int:
        return 0 if self.rel_yield is None else int(self.rel_yield.shape[0])

    @property
    def yields_kg_ha(self) -> np.ndarray:
        """[S,4] yield of the (first) cash crop of each plan year, the shape Feature 3's optimizer reads.
        0 in a fallow year and for a rotation that cannot be grown here; NaN where the crop has no yield number
        (see missing_yield)."""
        out = np.zeros((len(self.labels), 4))
        if self.feasible:
            for y in range(4):
                ks = self.season_index(y + 1)
                if ks:
                    out[:, y] = self.yield_kg_ha[:, ks[0]]
        return out

    @property
    def rel_yields(self) -> np.ndarray:
        """[S,4] share of potential yield of the (first) cash crop of each plan year (0 in a fallow year)."""
        out = np.zeros((len(self.labels), 4))
        if self.feasible:
            for y in range(4):
                ks = self.season_index(y + 1)
                if ks:
                    out[:, y] = self.rel_yield[:, ks[0]]
        return out

    @property
    def missing_yield(self) -> list:
        """Crops of this rotation with no yield number (farmer's or county): their yields are NaN."""
        return sorted({s["crop"] for s in self.seasons if s.get("ym_kg_ha") is None})

    def season_index(self, plan_year: int) -> list:
        """Indexes (into the K axis) of the seasons of a plan year (1 to 4)."""
        return [k for k, s in enumerate(self.seasons) if s["plan_year"] == plan_year]

    def yields_by_year(self) -> list:
        """4 lists (one per plan year) of {crop, yield_kg_ha [S], rel_yield [S]}."""
        return [[{"crop": self.seasons[k]["crop"], "yield_kg_ha": self.yield_kg_ha[:, k],
                  "rel_yield": self.rel_yield[:, k]} for k in self.season_index(y)] for y in range(1, 5)]

    def mean(self, name: str):
        """Scenario-weighted mean of any [S,...] array of this result."""
        a = getattr(self, name)
        return np.tensordot(self.weights, a, axes=(0, 0))

    def summary(self) -> dict:
        """Plain numbers for a quick look: weighted means per season and per year."""
        if not self.feasible:
            return {"feasible": False, "reason": self.reason}
        return {"feasible": True,
                "seasons": [{**s, "mean_rel_yield": float(self.mean("rel_yield")[k]),
                             "mean_yield_kg_ha": float(self.mean("yield_kg_ha")[k]),
                             "mean_irrigation_mm": float(self.mean("irrigation_season_mm")[k])}
                            for k, s in enumerate(self.seasons)],
                "mean_irrigation_mm_per_year": float(self.mean("irrigation_mm").mean()),
                "mean_total_water_mm_per_year": float(self.mean("total_water_mm").mean())}


def _get(obj, key, default=None):
    if obj is None:
        return default
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _site_parts(site) -> dict:
    weather = _get(site, "weather")
    if weather is None:
        raise ValueError("site.weather is missing: simulate() needs the site's daily weather")
    soil = _get(site, "soil")
    awc = _get(soil, "awc_mm_per_m")
    if awc is None:
        raise ValueError("site.soil.awc_mm_per_m is missing: simulate() needs the soil's water capacity")
    return {"weather": weather, "lat": _get(site, "lat", weather.attrs.get("lat")),
            "elevation_m": _get(site, "elevation_m", weather.attrs.get("elevation_m")),
            "awc": float(awc), "group": _get(soil, "hydrologic_group")}


_CLIM_CACHE: dict = {}


def site_climate(site) -> dict:
    """Day-of-year climate normals of the site (remembered per weather frame)."""
    w = _get(site, "weather")
    hit = _CLIM_CACHE.get(id(w))
    if hit is not None and hit[0] is w:
        return hit[1]
    clim = C.climatology(w, _get(site, "lat", w.attrs.get("lat")))
    _CLIM_CACHE.clear()
    _CLIM_CACHE[id(w)] = (w, clim)
    return clim


_SCEN_CACHE: dict = {}


def default_scenarios(site, kind: str = "bootstrap") -> SC.Scenarios:
    """The site's scenario set (remembered per weather frame): 500 bootstrap plans with seed 42 by default."""
    p = _site_parts(site)
    key = (id(p["weather"]), kind, C.SIM_PATH.stat().st_mtime_ns)
    hit = _SCEN_CACHE.get(key)
    if hit is not None and hit[0] is p["weather"]:
        return hit[1]
    scen = SC.build(p["weather"], kind, lat=p["lat"], elevation_m=p["elevation_m"])
    if len(_SCEN_CACHE) > 12:
        _SCEN_CACHE.clear()
    _SCEN_CACHE[key] = (p["weather"], scen)
    return scen


_WHAT_IF: ContextVar = ContextVar("rotationlab_what_if", default=None)


@contextmanager
def what_if(rain_mult: float | None = None, heat_shift_c: float | None = None, water=None, scenarios=None,
            climate_shift: str | None = None):
    """Run every simulate() call inside the block under a what-if (not a forecast):

    rain_mult      every day's rain times this            heat_shift_c   every day's maximum temperature plus this
    water          a water answer (mode, normal_mm, dry_mm) used for the irrigation supply instead of the farm's
    scenarios      a Scenarios set used instead of whatever the caller passes (before rain and heat are applied)
    climate_shift  "historical" | "recent" | "trend": used when the caller passes no Scenarios set

    The farm's own answers still set the potential yields (a typical yield was achieved with the farm's real
    water and weather) and the planting dates. Blocks can be nested; an inner block keeps the outer settings it
    does not name.
    """
    new = dict(_WHAT_IF.get() or {})
    for k, v in (("rain_mult", rain_mult), ("heat_shift_c", heat_shift_c), ("water", water),
                 ("scenarios", scenarios), ("climate_shift", climate_shift)):
        if v is not None:
            new[k] = v
    token = _WHAT_IF.set(new)
    try:
        yield new
    finally:
        _WHAT_IF.reset(token)


def current_what_if() -> dict:
    """The what-if settings in force right now ({} outside a what_if block)."""
    return dict(_WHAT_IF.get() or {})


def _scenarios_in_force(site, scenarios) -> SC.Scenarios:
    wi = _WHAT_IF.get() or {}
    if wi.get("scenarios") is not None:
        scen = wi["scenarios"]
    elif isinstance(scenarios, SC.Scenarios):
        scen = scenarios
    else:                    # anything that is not a Scenarios set (None, a count, a placeholder list) = the default set
        mode = wi.get("climate_shift") or "historical"
        if mode != "historical":
            from engine import climate_shift as CS
            scen = CS.scenarios_for(site, mode)
        else:
            scen = default_scenarios(site)
    if wi.get("rain_mult") is not None or wi.get("heat_shift_c") is not None:
        scen = scen.adjust(1.0 if wi.get("rain_mult") is None else float(wi["rain_mult"]),
                           0.0 if wi.get("heat_shift_c") is None else float(wi["heat_shift_c"]))
    return scen


def _is_irrigated(inputs) -> bool:
    mode = _get(_get(inputs, "water"), "mode")
    return bool(mode) and not str(mode).lower().startswith("rain")


_REF_CACHE: dict = {}


def reference_relative_yields(site, inputs, crop_ids) -> dict:
    """{crop: median Ya/Ym} with the crop grown every year on this farm (its soil and water supply) over every
    4-year run of the real record. Used to turn a typical yield into a potential yield."""
    p = _site_parts(site)
    water = _get(inputs, "water")
    wkey = (str(_get(water, "mode")), _get(water, "normal_mm"), _get(water, "dry_mm"))
    out, todo = {}, []
    for cid in crop_ids:
        key = (id(p["weather"]), len(p["weather"]), cid, round(p["awc"], 3), p["group"], wkey)
        hit = _REF_CACHE.get(key)
        if hit is not None and hit[0] is p["weather"]:
            out[cid] = hit[1]
        else:
            todo.append((cid, key))
    if todo:
        clim = site_climate(site)
        hist = default_scenarios(site, "historical")
        tls = [(cid, key, WB.build_timeline([cid], clim, irrigated=_is_irrigated(inputs))) for cid, key in todo]
        ok = [t for t in tls if t[2].feasible]
        if ok:
            bal = WB.run_balance([t[2] for t in ok], hist, WB.yearly_supply(water, hist), p["awc"], p["group"])
            for r, (cid, key, tl) in enumerate(ok):
                rel = _rel_and_heat(tl, hist, bal, r)[0]
                out[cid] = float(np.nanmedian(rel))
        for cid, key, tl in tls:
            out.setdefault(cid, float("nan"))
            if len(_REF_CACHE) > 256:
                _REF_CACHE.clear()
            _REF_CACHE[key] = (p["weather"], out[cid])
    return out


def _rel_and_heat(tl, scen, bal, r):
    tmax = scen.tmax.reshape(scen.n, WB.D4)
    cash = tl.cash
    rel = np.empty((scen.n, len(cash)))
    hot = np.zeros((scen.n, len(cash)))
    for k, s in enumerate(cash):
        if s.flower_days > 0:
            win = (s.start + s.flower_start + np.arange(s.flower_days)) % WB.D4
            hot[:, k] = (tmax[:, win] >= s.heat_tmax_c).sum(axis=1)
        rel[:, k] = YM.relative_yield(s.ky, bal["eta"][r, :, k], bal["etm"][r, :, k], hot[:, k])
    return rel, hot


def simulate_many(site, inputs, rotations, scenarios=None) -> list:
    """simulate() for many rotations in one batch (same site, inputs and scenarios). Same order as given."""
    p = _site_parts(site)
    scen = _scenarios_in_force(site, scenarios)
    clim = site_climate(site)
    irrigated = _is_irrigated(inputs)
    water = (_WHAT_IF.get() or {}).get("water")
    what_if_water = water is not None
    if not what_if_water:
        water = _get(inputs, "water")
    tls = [WB.build_timeline(rot, clim, irrigated=irrigated) for rot in rotations]
    zero = np.zeros((scen.n, WB.PLAN_YEARS_V4))
    results = [None if t.feasible else
               SimResult(False, t.reason, t.crops, t.cover_crops, labels=list(scen.labels),
                         weights=np.asarray(scen.weights, float), irrigation_mm=zero, total_water_mm=zero,
                         rain_mm=scen.annual_rain(), notes=["This rotation cannot be grown at this site: " + t.reason
                                                            + ". Its yields are reported as zero."])
               for t in tls]
    ok = [i for i, t in enumerate(tls) if t.feasible]
    if not ok:
        return results
    supply = WB.yearly_supply(water, scen)
    bal = WB.run_balance([tls[i] for i in ok], scen, supply, p["awc"], p["group"])
    crop_ids = sorted({s.crop for i in ok for s in tls[i].cash})
    ref = reference_relative_yields(site, inputs, crop_ids)
    ym = {cid: YM.potential_yield(cid, site, inputs, ref.get(cid)) for cid in crop_ids}
    lib = C.crop_library()
    notes = ["Seasons (planting and harvest days) are the same in every scenario; they come from the site's "
             "long-term temperature record.", scen.note]
    if not np.isfinite(supply).all():
        notes.append("Irrigated with no amount given: water supply treated as unlimited.")
    if what_if_water:
        notes.append("What-if water supply used instead of the farm's own answer (not a forecast).")
    for r, i in enumerate(ok):
        tl = tls[i]
        cash = tl.cash
        K = len(cash)
        rel, hot = _rel_and_heat(tl, scen, bal, r)
        ymv = np.array([np.nan if ym[s.crop][0] is None else ym[s.crop][0] for s in cash])
        seasons = [{**s.timing(), "ym_kg_ha": None if ym[s.crop][0] is None else float(ym[s.crop][0]),
                    "ym_source": ym[s.crop][1], "unverified": lib[s.crop].unverified} for s in cash]
        results[i] = SimResult(
            True, "", tl.crops, tl.cover_crops, seasons, [s.timing() for s in tl.segments if s.kind == "cover"],
            list(scen.labels), np.asarray(scen.weights, float), rel, rel * ymv[None, :], hot,
            bal["eta"][r, :, :K], bal["etm"][r, :, :K], bal["irr_season"][r, :, :K], bal["irrigation"][r],
            np.array(supply), np.array(bal["rain"][r]), bal["eta_year"][r], bal["runoff"][r], bal["drainage"][r],
            bal["closure_error"][r],
            badges={"weather": "Observed (NASA POWER real years)", "water_balance": "Estimated (FAO-56)",
                    "yield": "Estimated (FAO-33)", "calendar": "Estimated (team planting rules, team to verify)"},
            notes=list(notes))
    return results


def simulate(site, inputs, rotation, scenarios=None) -> SimResult:
    """Yields, water use and season timing of one 4-year rotation in every scenario. See the module docstring."""
    return simulate_many(site, inputs, [rotation], scenarios)[0]
