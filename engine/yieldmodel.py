# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""FAO-33 yield response (Doorenbos & Kassam 1979): 1 - Ya/Ym = Ky (1 - ETa/ETm), plus rotation effects."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Sequence

import numpy as np

from engine.crops import A, MILLETS


def season_yield(ym_kg_ha: float, ky: float, eta, etm, rotation_factor=1.0):
    """Ya in kg/ha. eta, etm: season sums (mm), any shape. Ya floored at 0; ETa capped at ETm."""
    eta, etm = np.asarray(eta, float), np.asarray(etm, float)
    ratio = np.clip(eta / np.maximum(etm, 1e-9), 0.0, 1.0)
    rel = np.maximum(1.0 - ky * (1.0 - ratio), 0.0)
    return ym_kg_ha * rel * rotation_factor


def _farm_current_crop():
    path = Path(__file__).resolve().parents[1] / "config" / "farm.yaml"
    return _read_farm_crop(path.stat().st_mtime_ns if path.exists() else None)


@lru_cache(maxsize=2)
def _read_farm_crop(version):
    try:
        import yaml
        doc = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "farm.yaml").read_text()) or {}
        return (doc.get("farm") or {}).get("current_crop")
    except Exception:
        return None


def previous_crop(params: dict | None = None):
    """The crop grown the year before the plan starts: farm.current_crop in config/farm.yaml (a farm fact, Local
    input), unless params["previous_crop"] says otherwise. The farm grows rice every year today, so a plan that
    starts with rice starts with rice after rice. None means year 1 has no predecessor."""
    if params and "previous_crop" in params:
        return params["previous_crop"]
    return _farm_current_crop()


def _pair_factor(prev, cur, params) -> float:
    if prev == "pigeonpea":
        if cur == "rice":
            return A(params, "rotation.rice_after_pigeonpea")
        if cur in MILLETS:
            return A(params, "rotation.millet_after_pigeonpea")
        if cur == "pigeonpea":
            return A(params, "rotation.pigeonpea_after_pigeonpea")
    elif prev == "rice" and cur == "rice":
        return A(params, "rotation.rice_after_rice")
    elif prev in MILLETS and cur in MILLETS:
        return A(params, "rotation.millet_after_millet")
    return 1.0


def rotation_factor(plan: Sequence[str], params: dict | None = None) -> np.ndarray:
    """Per-year yield multiplier from the previous year's crop. Year 1 follows previous_crop() (rice on this farm)."""
    seq = [previous_crop(params)] + list(plan)
    return np.array([_pair_factor(seq[i], seq[i + 1], params) for i in range(len(plan))], float)


def nitrogen_credit_kg_ha(plan: Sequence[str], params: dict | None = None) -> np.ndarray:
    """Nitrogen credit (kg N/ha) to rice or millet following pigeon pea (year 1 follows previous_crop())."""
    seq = [previous_crop(params)] + list(plan)
    n = np.zeros(len(plan))
    for i in range(len(plan)):
        if seq[i] == "pigeonpea" and (seq[i + 1] == "rice" or seq[i + 1] in MILLETS):
            n[i] = A(params, "rotation.n_credit_after_pigeonpea")
    return n


# =====================================================================================================
# v4 (universal, any farm). Feature 2, Person 2. Everything above is the v3 code, kept working.
#
# relative_yield(...)          FAO-33: Ya/Ym = 1 - Ky (1 - ETa/ETm), times the optional heat penalty.
# heat_factor(...)             1 - (penalty per hot day) x (hot days in the flowering window); toggle in settings.
# ym_from_yield_series(...)    potential yield = 90th percentile of detrended county yields (NASS).
# potential_yield(...)         potential yield of a crop from the farmer's typical yield or the county numbers.
# season_relative_yield(...)   ONE season's Ya/Ym at a site in a real year: the function Person 3's hindcast calls.
# =====================================================================================================
def heat_factor(heat_days, enabled: bool | None = None):
    """Yield multiplier for heat at flowering. heat_days: hot days counted in the flowering window."""
    from engine.crops import rule
    on = bool(rule("heat_enabled")) if enabled is None else bool(enabled)
    h = np.asarray(heat_days, float)
    if not on:
        return np.ones_like(h)
    return np.clip(1.0 - float(rule("heat_pen_per_day")) * h, 0.0, 1.0)


def relative_yield(ky: float, eta, etm, heat_days=None, heat: bool | None = None):
    """Ya/Ym by FAO-33 (Doorenbos and Kassam 1979): 1 - Ky (1 - ETa/ETm), floored at 0, ETa capped at ETm.
    With heat_days given, multiplied by the heat factor (heat=False switches the heat penalty off)."""
    eta, etm = np.asarray(eta, float), np.asarray(etm, float)
    ratio = np.clip(eta / np.maximum(etm, 1e-9), 0.0, 1.0)
    rel = np.maximum(1.0 - float(ky) * (1.0 - ratio), 0.0)
    return rel if heat_days is None else rel * heat_factor(heat_days, heat)


def ym_from_yield_series(years, yields, quantile: float | None = None) -> float | None:
    """Potential yield Ym from a county yield history: fit a straight-line trend, then
    Ym = trend value in the last year + the 90th percentile of the departures from the trend.
    Returns None with fewer than 8 years (too few to detrend)."""
    from engine.crops import rule
    q = float(rule("ym_nass_quantile") if quantile is None else quantile)
    t, v = np.asarray(years, float), np.asarray(yields, float)
    ok = np.isfinite(t) & np.isfinite(v)
    t, v = t[ok], v[ok]
    if len(v) < 8:
        return None
    slope, icpt = np.polyfit(t, v, 1)
    resid = v - (icpt + slope * t)
    return float(icpt + slope * t.max() + np.quantile(resid, q))


def _get(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def potential_yield(crop: str, site=None, inputs=None, reference_rel: float | None = None):
    """(Ym in kg/ha or None, where it came from).

    1. the farmer's own potential yield (crop_overrides[crop]["ym"]) if given;
    2. the farmer's typical yield (crop_overrides[crop]["yield"]) divided by the model's median relative yield
       for this crop at this site (reference_rel), so a typical year reproduces the typical yield;
    3. the county potential yield (us_defaults["ym"][crop], NASS 90th percentile of detrended yields);
    4. the county typical yield (us_defaults["yields"][crop]) treated like 2;
    otherwise None: yields are then reported as a share of potential only.
    """
    from engine.crops import crop_id, rule
    cid = crop_id(crop)
    floor = float(rule("ym_min_reference_rel"))
    ref = None if reference_rel is None or not np.isfinite(reference_rel) else max(float(reference_rel), floor)

    def pick(table, *keys):
        table = table or {}
        for k in list(table):
            if crop_id(k) == cid:
                node = table[k]
                for key in keys:
                    v = _get(node, key) if not isinstance(node, (int, float)) else (node if key == "yield" else None)
                    if v is not None and np.isfinite(float(v)) and float(v) > 0:
                        return float(v)
        return None

    ov = _get(inputs, "crop_overrides")
    v = pick(ov, "ym")
    if v:
        return v, "farmer's potential yield"
    v = pick(ov, "yield")
    if v:
        return (v / ref if ref else v), "farmer's typical yield" + (" scaled to potential" if ref else "")
    us = _get(site, "us_defaults")
    v = pick(_get(us, "ym"), "yield")
    if v:
        return v, "county potential yield (NASS 90th percentile of detrended yields)"
    v = pick(_get(us, "yields"), "yield")
    if v:
        return (v / ref if ref else v), "county typical yield" + (" scaled to potential" if ref else "")
    return None, "no yield number for this crop: shown as a share of potential"


_SEASON_CACHE: dict = {}


def season_relative_yields(weather, crop: str, lat: float | None = None, awc_mm_per_m: float | None = None,
                           irrigated: bool | None = None, heat: bool | None = None) -> dict:
    """{year: Ya/Ym} for every full year of the weather record, the crop grown every year at this site.

    The season harvested in year t uses the real weather of year t (and of the fall before for winter crops),
    after three real lead-in years so the soil water start is realistic. Rain-fed unless irrigated=True
    (crops marked irrigated-only, like rice, are always fully irrigated). Empty dict when the crop does not
    fit this climate.
    """
    from engine import crops as C, scenarios as SC, waterbalance as WB
    cid = C.crop_id(crop)
    c = C.get_crop(cid)
    irr = bool(c.irrigated_only) if irrigated is None else bool(irrigated)
    awc = float(C.rule("default_awc_mm_per_m") if awc_mm_per_m is None else awc_mm_per_m)
    key = (id(weather), len(weather), cid, round(awc, 3), irr, heat)
    hit = _SEASON_CACHE.get(key)
    if hit is not None and hit[0] is weather:
        return hit[1]
    annual = SC.site_years(weather, lat)
    clim = C.climatology(weather, lat)
    tl = WB.build_timeline([cid], clim, irrigated=True)
    out = {}
    if tl.feasible:
        Y = len(annual["years"])
        idx = np.clip(np.arange(Y)[:, None] + np.arange(-3, 1)[None, :], 0, None)
        sc = SC._make(annual, idx, [str(y) for y in annual["years"]], "historical")
        supply = np.full((sc.n, 4), np.inf if irr else 0.0)
        bal = WB.run_balance([tl], sc, supply, awc)
        seg = [s for s in tl.cash if s.plan_year == 3][0]
        k = tl.cash.index(seg)
        win = (seg.start + seg.flower_start + np.arange(seg.flower_days)) % WB.D4
        hot = (sc.tmax.reshape(sc.n, -1)[:, win] >= seg.heat_tmax_c).sum(axis=1)
        rel = relative_yield(seg.ky, bal["eta"][0, :, k], bal["etm"][0, :, k], hot, heat)
        out = {int(y): float(r) for y, r in zip(annual["years"], rel)}
    if len(_SEASON_CACHE) > 64:
        _SEASON_CACHE.clear()
    _SEASON_CACHE[key] = (weather, out)
    return out


def season_relative_yield(weather, crop: str, year: int, lat: float | None = None,
                          awc_mm_per_m: float | None = None, irrigated: bool | None = None,
                          heat: bool | None = None):
    """Ya/Ym (0 to 1) of ONE crop season harvested in `year` at this site, or None when the crop does not fit
    the climate or the year is not a full year of the record. This is the single-season function the
    hindcast uses. All years of a site are computed once and remembered, so calling it per year is cheap."""
    return season_relative_yields(weather, crop, lat, awc_mm_per_m, irrigated, heat).get(int(year))
