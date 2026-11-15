# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
# TODO (Person 2 handoff, 2026-11-15 12:56 PM): the v4 section at the bottom (crop_library, climatology, crop_calendar,
# climate_fit) runs and was smoke-tested on one site, but has NO unit tests yet and the planting rules are unreviewed.
# Calories are filled only for crops already read from USDA FoodData Central; the rest are null (not counted).
"""Crop parameters and assumption lookup. Reads config/assumptions.yaml (nothing hard-coded here)."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
ASSUMPTIONS_PATH = ROOT / "config" / "assumptions.yaml"
PRICES_PATH = ROOT / "config" / "prices_india.yaml"
CROP_IDS = ("rice", "jowar", "bajra", "ragi", "pigeonpea")
MILLETS = ("jowar", "bajra", "ragi")


def load_assumptions() -> dict:
    return _read_assumptions(ASSUMPTIONS_PATH.stat().st_mtime_ns)


@lru_cache(maxsize=2)
def _read_assumptions(version) -> dict:
    """Flat dict: dotted name -> leaf dict(value, range, unit, source, badge)."""
    raw = yaml.safe_load(ASSUMPTIONS_PATH.read_text())
    flat = {}

    def walk(node, prefix):
        for k, v in node.items():
            name = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict) and "value" in v:
                flat[name] = v
            elif isinstance(v, dict):
                walk(v, name)

    walk(raw, "")
    return flat


def A(params: dict | None, name: str):
    """Assumption value with optional override: params[dotted name] wins, then params[leaf name]."""
    if params:
        if name in params:
            return params[name]
        leaf = name.rsplit(".", 1)[-1]
        if leaf in params and not name.startswith(("crops.", "heat.tmax_c.", "heat.flowering_days.", "soil_cover.score.")):
            return params[leaf]
    return load_assumptions()[name]["value"]


@dataclass
class CropParams:
    id: str
    kc_ini: float
    kc_mid: float
    kc_end: float
    stages_days: tuple
    root_depth_m: float
    p: float
    ky: float
    sowing_doy: int
    ym_kg_ha: float
    badges: dict = field(default_factory=dict)

    @property
    def season_days(self) -> int:
        return int(sum(self.stages_days))

    def kc_curve(self) -> np.ndarray:
        """FAO-56 piecewise Kc over the season (ch.6 Fig. 34): flat ini, linear dev, flat mid, linear late."""
        ini, dev, mid, late = self.stages_days
        kc = np.empty(self.season_days)
        kc[:ini] = self.kc_ini
        kc[ini:ini + dev] = np.linspace(self.kc_ini, self.kc_mid, dev + 1)[1:]
        kc[ini + dev:ini + dev + mid] = self.kc_mid
        kc[ini + dev + mid:] = np.linspace(self.kc_mid, self.kc_end, late + 1)[1:]
        return kc


@lru_cache(maxsize=1)
def _prices_yaml() -> dict:
    return (yaml.safe_load(PRICES_PATH.read_text()) or {}) if PRICES_PATH.exists() else {}


def _ym_from_prices(crop: str):
    if not PRICES_PATH.exists():
        return None, None
    d = _prices_data(PRICES_PATH.stat().st_mtime_ns)
    y = d.get("potential_yield_kg_ha")
    if not isinstance(y, dict) or crop not in y:
        return None, None
    v = y[crop]
    badge = "observed"
    if isinstance(v, dict):
        badge = v.get("badge", "observed")
        v = v.get("value")
    return (None, None) if v is None else (float(v), badge)


@lru_cache(maxsize=2)
def _prices_data(version):
    return yaml.safe_load(PRICES_PATH.read_text()) or {}


def load_crops(params: dict | None = None) -> dict[str, CropParams]:
    out = {}
    for c in CROP_IDS:
        g = lambda k: A(params, f"crops.{c}.{k}")
        ym, ym_badge = _ym_from_prices(c)
        meta = (_prices_data(PRICES_PATH.stat().st_mtime_ns).get("potential_yield_kg_ha") or {}).get(c, {})
        ym_badge = meta.get("badge", "modeled") if isinstance(meta, dict) else "modeled"
        if ym is None:
            ym, ym_badge = float(A(params, f"ym_kg_ha.{c}")), "placeholder"
        if params and f"ym_kg_ha.{c}" in params:
            ym = float(params[f"ym_kg_ha.{c}"])
        badges = {k: load_assumptions()[f"crops.{c}.{k}"]["badge"] for k in
                  ("kc_ini", "kc_mid", "kc_end", "stages_days", "root_depth_m", "p", "ky", "sowing_doy")}
        badges["ym_kg_ha"] = ym_badge
        out[c] = CropParams(c, float(g("kc_ini")), float(g("kc_mid")), float(g("kc_end")),
                            tuple(int(x) for x in g("stages_days")), float(g("root_depth_m")),
                            float(g("p")), float(g("ky")), int(g("sowing_doy")), ym, badges)
        item = out[c]
        if len(item.stages_days) != 4 or any(n <= 0 for n in item.stages_days) or item.season_days > 365:
            raise ValueError(f"{c}: use four positive crop-stage lengths totaling at most 365 days")
        values = [item.kc_ini, item.kc_mid, item.kc_end, item.root_depth_m, item.p, item.ky, item.ym_kg_ha]
        if not np.isfinite(values).all() or min(values) < 0 or item.root_depth_m <= 0 or not 0 < item.p < 1 or not 1 <= item.sowing_doy <= 365:
            raise ValueError(f"{c}: invalid crop coefficients, root depth, depletion fraction or calendar")
    return out


# =====================================================================================================
# Build Spec v4 crop library (Person 2, task 4) and climate-fit calendar (R5).
#
# crop_library()      every annual crop with FAO-56 Kc, stage lengths, root depth, p, FAO-33 Ky, calories per kg
#                     and harvest index, read from the crop_library section of config/assumptions.yaml.
# cover_crops()       cover crops (ids match Person 3's soil score).
# climatology(w)      day-of-year normals from a daily weather frame (Site.weather).
# crop_calendar(...)  when a crop would be planted and harvested at this location, and whether it fits at all.
# climate_fit(...)    the calendar of every crop: the climate filter behind api.get_candidates().
#
# Day numbers here are 0-based day-of-year indexes (0 = 1 January) on a 365-day year (29 February dropped).
# Nothing is hard-coded: every number comes from assumptions.yaml with its source and badge.
# =====================================================================================================
import pandas as _pd

NDOY = 365
ALIASES = {"corn": "maize", "soybeans": "soybean", "wheat": "wheat_winter", "winter_wheat": "wheat_winter",
           "spring_wheat": "wheat_spring", "peanuts": "peanut", "groundnut": "peanut", "jowar": "sorghum",
           "bajra": "pearl_millet", "millet": "pearl_millet", "beans": "dry_bean", "dry_beans": "dry_bean",
           "peas": "pea", "lentils": "lentil", "chickpeas": "chickpea", "rapeseed": "canola",
           "potatoes": "potato", "sugar_beet": "sugarbeet", "sugarbeets": "sugarbeet", "pigeon_pea": "pigeonpea",
           "paddy": "rice", "sunflowers": "sunflower"}


def crop_id(name: str) -> str:
    """Canonical v4 crop id for a name ('Corn' -> 'maize')."""
    key = str(name).strip().lower().replace(" ", "_").replace("-", "_")
    return ALIASES.get(key, key)


@dataclass(frozen=True)
class Crop:
    id: str
    name: str
    legume: bool
    season_type: str            # warm | cool | winter
    kc_ini: float
    kc_mid: float
    kc_end: float
    stages_days: tuple          # FAO-56 Table 11: initial, development, mid-season, late
    root_depth_m: float
    p: float
    ky: float
    t_plant_c: float
    t_min_grow_c: float
    t_max_grow_c: float
    heat_tmax_c: float
    flowering_days: int
    harvest_index: float
    kcal_per_kg: float | None   # None = not read from the food composition source yet (not counted)
    edible_fraction: float = 1.0
    irrigated_only: bool = False
    kc_ini_frozen: float | None = None
    stages_days_short: tuple | None = None
    badges: dict = field(default_factory=dict, compare=False, hash=False)
    sources: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def season_days(self) -> int:
        return int(sum(self.stages_days))

    @property
    def unverified(self) -> list:
        """Names of the values still marked 'team to verify' or placeholder."""
        return sorted(k for k, s in self.sources.items()
                      if "team to verify" in str(s).lower() or self.badges.get(k) == "placeholder")

    def kc_curve(self, stages=None, kc_ini=None) -> np.ndarray:
        return kc_curve(stages or self.stages_days, self.kc_ini if kc_ini is None else kc_ini, self.kc_mid, self.kc_end)


@dataclass(frozen=True)
class CoverCrop:
    id: str
    name: str
    legume: bool
    max_days: int
    kc_full: float
    root_depth_m: float
    p: float
    badges: dict = field(default_factory=dict, compare=False, hash=False)
    sources: dict = field(default_factory=dict, compare=False, hash=False)


def kc_curve(stages, kc_ini, kc_mid, kc_end) -> np.ndarray:
    """FAO-56 single crop coefficient curve (ch.6, Fig. 34): flat ini, linear dev, flat mid, linear late."""
    ini, dev, mid, late = (int(x) for x in stages)
    kc = np.empty(ini + dev + mid + late)
    kc[:ini] = kc_ini
    kc[ini:ini + dev] = np.linspace(kc_ini, kc_mid, dev + 1)[1:]
    kc[ini + dev:ini + dev + mid] = kc_mid
    kc[ini + dev + mid:] = np.linspace(kc_mid, kc_end, late + 1)[1:]
    return kc


def _library_raw() -> dict:
    return _read_library(ASSUMPTIONS_PATH.stat().st_mtime_ns)


@lru_cache(maxsize=2)
def _read_library(version) -> dict:
    return (yaml.safe_load(ASSUMPTIONS_PATH.read_text()) or {}).get("crop_library") or {}


def rule(name: str):
    """A value from crop_library.rules (turnaround_days, heat_pen_per_day, ...)."""
    return _library_raw()["rules"][name]["value"]


@lru_cache(maxsize=2)
def _build_library(version) -> tuple:
    raw = _read_library(version)
    crops, covers = {}, {}
    for cid, node in (raw.get("crops") or {}).items():
        v = {k: leaf["value"] for k, leaf in node.items()}
        crops[cid] = Crop(
            id=cid, name=str(v["name"]), legume=bool(v["legume"]), season_type=str(v["season_type"]),
            kc_ini=float(v["kc_ini"]), kc_mid=float(v["kc_mid"]), kc_end=float(v["kc_end"]),
            stages_days=tuple(int(x) for x in v["stages_days"]), root_depth_m=float(v["root_depth_m"]),
            p=float(v["p"]), ky=float(v["ky"]), t_plant_c=float(v["t_plant_c"]),
            t_min_grow_c=float(v["t_min_grow_c"]), t_max_grow_c=float(v["t_max_grow_c"]),
            heat_tmax_c=float(v["heat_tmax_c"]), flowering_days=int(v["flowering_days"]),
            harvest_index=float(v["harvest_index"]),
            kcal_per_kg=None if v.get("kcal_per_kg") is None else float(v["kcal_per_kg"]),
            edible_fraction=float(v.get("edible_fraction", 1.0)), irrigated_only=bool(v.get("irrigated_only", False)),
            kc_ini_frozen=None if v.get("kc_ini_frozen") is None else float(v["kc_ini_frozen"]),
            stages_days_short=None if v.get("stages_days_short") is None else tuple(int(x) for x in v["stages_days_short"]),
            badges={k: leaf.get("badge") for k, leaf in node.items()},
            sources={k: leaf.get("source") for k, leaf in node.items()})
        c = crops[cid]
        nums = [c.kc_ini, c.kc_mid, c.kc_end, c.root_depth_m, c.p, c.ky]
        if (len(c.stages_days) != 4 or min(c.stages_days) <= 0 or not np.isfinite(nums).all() or min(nums) <= 0
                or not 0 < c.p < 1 or c.season_type not in ("warm", "cool", "winter")):
            raise ValueError(f"crop_library.{cid}: invalid crop parameters in config/assumptions.yaml")
    for cid, node in (raw.get("cover_crops") or {}).items():
        v = {k: leaf["value"] for k, leaf in node.items()}
        covers[cid] = CoverCrop(cid, str(v["name"]), bool(v["legume"]), int(v["max_days"]), float(v["kc_full"]),
                                float(v["root_depth_m"]), float(v["p"]),
                                badges={k: leaf.get("badge") for k, leaf in node.items()},
                                sources={k: leaf.get("source") for k, leaf in node.items()})
    return crops, covers


def crop_library() -> dict[str, Crop]:
    """All v4 annual crops, keyed by id."""
    return dict(_build_library(ASSUMPTIONS_PATH.stat().st_mtime_ns)[0])


def cover_crops() -> dict[str, CoverCrop]:
    return dict(_build_library(ASSUMPTIONS_PATH.stat().st_mtime_ns)[1])


def get_crop(name: str) -> Crop:
    lib = crop_library()
    cid = crop_id(name)
    if cid not in lib:
        raise KeyError(f"unknown crop {name!r}; known crops: {', '.join(sorted(lib))}")
    return lib[cid]


def calories_kcal_per_ha(crop: str, yield_kg_ha):
    """Food calories per hectare from a yield (kg/ha). None when the crop's calorie value is not verified yet."""
    c = get_crop(crop)
    if c.kcal_per_kg is None:
        return None
    return np.asarray(yield_kg_ha, float) * c.kcal_per_kg * c.edible_fraction


def residue_kg_ha(crop: str, yield_kg_ha):
    """Above-ground residue (kg/ha, same moisture basis as the yield) from the harvest index: Y * (1 - HI) / HI."""
    hi = get_crop(crop).harvest_index
    return np.asarray(yield_kg_ha, float) * (1.0 - hi) / hi


# ---------------------------------------------------------------- climatology and calendar

def _smooth(x: np.ndarray, window: int) -> np.ndarray:
    """Circular running mean over the year."""
    window = max(int(window) | 1, 1)
    h = window // 2
    ext = np.concatenate([x[-h:], x, x[:h]]) if h else x
    return np.convolve(ext, np.ones(window) / window, mode="valid")


def climatology(weather: _pd.DataFrame, lat: float | None = None, years: tuple | None = None) -> dict:
    """Day-of-year normals (365 values each) from a daily weather frame with columns tmax, tmin, precip.

    Returns tmean, tmin, tmax (smoothed running means), precip (mean mm per day, smoothed), lat and the
    index of the coldest and hottest day of the smoothed year. years=(first, last) limits the period.
    """
    w = weather
    if years is not None:
        w = w[(w.index.year >= years[0]) & (w.index.year <= years[1])]
    w = w[~((w.index.month == 2) & (w.index.day == 29))]
    doy = np.where(w.index.is_leap_year & (w.index.month > 2), w.index.day_of_year - 1, w.index.day_of_year) - 1
    win = int(rule("climate_smoothing_days"))
    out = {}
    tm = w["tmean"].to_numpy(float) if "tmean" in w else (w["tmax"].to_numpy(float) + w["tmin"].to_numpy(float)) / 2
    for name, vals in (("tmean", tm), ("tmin", w["tmin"].to_numpy(float)), ("tmax", w["tmax"].to_numpy(float)),
                       ("precip", w["precip"].to_numpy(float))):
        total = np.bincount(doy, weights=vals, minlength=NDOY)[:NDOY]
        count = np.maximum(np.bincount(doy, minlength=NDOY)[:NDOY], 1)
        out[name] = _smooth(total / count, win)
    out["lat"] = float(weather.attrs.get("lat", 0.0) if lat is None else lat)
    out["coldest_doy"] = int(np.argmin(out["tmean"]))
    out["hottest_doy"] = int(np.argmax(out["tmean"]))
    return out


@dataclass(frozen=True)
class Calendar:
    crop: str
    feasible: bool
    reason: str                 # plain words: why it fits, or why not
    plant_doy: int = -1         # 0-based day of year
    harvest_doy: int = -1       # 0-based day of year of the last growing day (may be in the next year)
    stages_days: tuple = ()
    kc_ini: float = 0.0
    shifted: bool = False       # True when planted later than its own preferred day (double cropping)

    @property
    def season_days(self) -> int:
        return int(sum(self.stages_days))

    @property
    def crosses_new_year(self) -> bool:
        return self.feasible and self.plant_doy + self.season_days > NDOY


def _roll(x: np.ndarray, start: int, n: int) -> np.ndarray:
    idx = (start + np.arange(n)) % NDOY
    return x[idx]


def _season_ok(crop: Crop, t: np.ndarray, d: int, stages) -> tuple[bool, str]:
    ini, dev, mid, late = stages
    grow = _roll(t, d, ini + dev + mid)
    if t[d % NDOY] < crop.t_plant_c - 1e-9:
        return False, f"too cold to plant ({t[d % NDOY]:.1f} degC, needs {crop.t_plant_c:g})"
    if grow.min() < crop.t_min_grow_c:
        return False, f"season turns too cold before the crop finishes ({grow.min():.1f} degC, needs {crop.t_min_grow_c:g})"
    mid_mean = float(_roll(t, d + ini + dev, mid).mean())
    if mid_mean > crop.t_max_grow_c:
        return False, f"mid-season is too hot (mean {mid_mean:.1f} degC, limit {crop.t_max_grow_c:g})"
    return True, "fits"


def _first_after(mask: np.ndarray, start: int, limit: int = NDOY) -> int | None:
    for k in range(limit):
        if mask[(start + k) % NDOY]:
            return (start + k) % NDOY
    return None


def _winter_calendar(crop: Crop, clim: dict, earliest: int | None) -> Calendar:
    t = clim["tmean"]
    cold, hot = clim["coldest_doy"], clim["hottest_doy"]
    if t[cold] > float(rule("winter_wheat_vernalization_max_c")):
        return Calendar(crop.id, False, f"winters are too warm for a fall-planted crop (coldest period {t[cold]:.1f} degC)")
    if t[cold] < crop.t_min_grow_c:
        return Calendar(crop.id, False, f"winters are too cold for it to survive (coldest period {t[cold]:.1f} degC)")
    days_to_cold = (cold - hot) % NDOY
    plant = _first_after(t <= crop.t_plant_c, hot, max(days_to_cold, 1))
    if plant is None:
        return Calendar(crop.id, False, "it never cools enough in fall to plant")
    shifted = False
    if earliest is not None and (earliest - hot) % NDOY > (plant - hot) % NDOY:
        if (earliest - hot) % NDOY >= days_to_cold:
            return Calendar(crop.id, False, "the field is not free before winter")
        plant, shifted = earliest % NDOY, True
    mature = _first_after(t >= float(rule("winter_wheat_maturity_c")), cold, (hot - cold) % NDOY)
    mature = hot if mature is None else mature
    lo, hi = (int(x) for x in rule("winter_wheat_season_days"))
    length = int(np.clip((mature - plant) % NDOY, lo, hi))
    long_, short = np.array(crop.stages_days, float), np.array(crop.stages_days_short or crop.stages_days, float)
    f = (length - short.sum()) / max(long_.sum() - short.sum(), 1e-9)
    st = np.maximum(np.round(short + np.clip(f, 0, 1) * (long_ - short)).astype(int), 1)
    st[0] += length - int(st.sum())                       # rounding goes to the initial (dormant) stage
    if st[0] < 1:
        st[0] = 1
    kc_ini = crop.kc_ini_frozen if (crop.kc_ini_frozen is not None and t[cold] < 0.0) else crop.kc_ini
    return Calendar(crop.id, True, "fall-planted, overwinters", int(plant), int((plant + st.sum() - 1) % NDOY),
                    tuple(int(x) for x in st), float(kc_ini), shifted)


def crop_calendar(crop, clim: dict, earliest: int | None = None, irrigated: bool = True) -> Calendar:
    """Planting day, harvest day and stage lengths of a crop at this location, or feasible=False with the reason.

    Rules (team rules of thumb on the smoothed temperature normals; every threshold is in assumptions.yaml):
    - warm and cool crops where there is a cold season: plant on the first day after the coldest day when the
      mean temperature reaches t_plant_c, if the season then stays warm enough (t_min_grow_c) and the
      mid-season is not too hot (t_max_grow_c).
    - warm crops with no cold season (tropics): plant at the start of the wettest season-length window.
    - cool crops with no cold season: plant in the cool season, on the first workable day after the hottest day.
    - winter crops: plant in fall when it cools to t_plant_c; mature when spring reaches the maturity
      temperature; the FAO-56 Idaho (335 d) and California (180 d) rows are interpolated to that length.
    earliest: the field is busy until this day of year (double cropping); the crop is planted on or after it.
    irrigated=False rejects crops marked irrigated_only (rice).
    """
    c = get_crop(crop) if isinstance(crop, str) else crop
    if c.irrigated_only and not irrigated:
        return Calendar(c.id, False, "needs irrigation")
    if c.season_type == "winter":
        return _winter_calendar(c, clim, earliest)
    t = clim["tmean"]
    st = c.stages_days
    cold, hot = clim["coldest_doy"], clim["hottest_doy"]
    ok = np.zeros(NDOY, bool)
    why = {}
    for d in range(NDOY):
        ok[d], why[d] = _season_ok(c, t, d, st)
    if not ok.any():
        reasons = _pd.Series(list(why.values())).str.split(" (", regex=False).str[0].value_counts()
        return Calendar(c.id, False, reasons.index[0])
    cold_limited = t[cold] < c.t_plant_c
    if cold_limited:
        start = cold
    elif c.season_type == "cool":
        start = hot
    else:                                                 # warm crop, no cold season: follow the rains
        rain = np.array([_roll(clim["precip"], d, c.season_days).sum() for d in range(NDOY)])
        rain[~ok] = -1.0
        start = int(np.argmax(rain))
    plant = _first_after(ok, start)
    shifted = False
    if earliest is not None:
        e = earliest % NDOY
        if (e - start) % NDOY > (plant - start) % NDOY:   # field still busy on the preferred day
            later = _first_after(ok, e, (start - e) % NDOY or NDOY)
            if later is None:
                return Calendar(c.id, False, "not enough season left after the previous crop")
            plant, shifted = later, True
    return Calendar(c.id, True, "fits the temperature and season length", int(plant),
                    int((plant + c.season_days - 1) % NDOY), tuple(st), float(c.kc_ini), shifted)


def climate_fit(clim_or_weather, crops=None, irrigated: bool = True) -> dict[str, Calendar]:
    """Calendar of every crop at this location (R5 climate filter). Pass Site.weather or a climatology dict."""
    clim = clim_or_weather if isinstance(clim_or_weather, dict) else climatology(clim_or_weather)
    lib = crop_library()
    ids = [crop_id(c) for c in crops] if crops is not None else list(lib)
    return {cid: crop_calendar(lib[cid], clim, irrigated=irrigated) for cid in ids}


def candidate_crops(clim_or_weather, irrigated: bool = True, county_crops=None) -> list[str]:
    """Crop ids that fit the climate and, when county_crops is given (US), that the county grows (R5)."""
    fit = climate_fit(clim_or_weather, irrigated=irrigated)
    keep = [c for c, cal in fit.items() if cal.feasible]
    if county_crops:
        grown = {crop_id(c) for c in county_crops}
        keep = [c for c in keep if c in grown]
    return keep
