# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Feature 2: the climate shift setting (Build Spec v4 R8). Every mode is a what-if, not a forecast.

    historical   the site's real weather years, every year counted once. The scenario set is returned unchanged.
    recent       the last 20 years of the record count twice (rules recent_years, recent_weight). Bootstrap plans
                 are drawn again with those years twice as likely, so every plan still counts equally and any
                 plain average over the plans already reflects the setting. Historical 4-year blocks and stress
                 tests cannot be drawn again, so they are re-weighted instead (see Scenarios.weights).
    trend        the straight-line trend observed in the record (yearly rainfall, yearly mean daily maximum
                 temperature, yearly reference evapotranspiration) is carried 10 years past the end of the record
                 (rule trend_years_forward) and every real year is moved to that level: its daily rain and ET0 are
                 scaled, its daily maximum temperature is shifted. Day-to-day weather stays the real year's.

    apply(scenarios, mode, weather)        -> Scenarios        (the general call)
    scenarios_for(site, mode, kind)        -> Scenarios        (remembered per site; what simulate() uses)
    describe(weather, mode)                -> dict             (plain words and numbers for the screen)
    use(mode)                              context manager: simulate() calls inside it use that mode when the
                                           caller passes no scenario set (for api.recommend and the optimizer)

All settings are in config/assumptions/simulation.yaml (rules section), each with its source note.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace

import numpy as np

from engine import scenarios as SC

MODES = ("historical", "recent", "trend")
LABELS = {"historical": "Historical", "recent": "Recent (last 20 years count double)",
          "trend": "Continuing trend (10 years ahead)"}
WHAT_IF = "what-if, not a forecast"
_ALIASES = {"": "historical", "none": "historical", "hist": "historical", "continuing_trend": "trend",
            "continuing trend": "trend", "trend_10": "trend", "recent_2x": "recent"}


def normalize_mode(mode) -> str:
    """'Historical', None, 'Continuing trend' ... -> one of MODES. Unknown names raise ValueError."""
    key = str(mode or "").strip().lower()
    key = _ALIASES.get(key, key.split(" (")[0].strip())
    key = _ALIASES.get(key, key)
    if key not in MODES:
        raise ValueError(f"unknown climate shift mode {mode!r}; use one of {', '.join(MODES)}")
    return key


def _rule(name):
    from engine.crops import rule
    return rule(name)


def year_weights(years, recent_years: int | None = None, recent_weight: float | None = None) -> np.ndarray:
    """One weight per record year: recent_weight (default 2) for the last recent_years (default 20) calendar
    years of the record, 1 for the earlier years."""
    years = np.asarray(years, int)
    n = int(_rule("recent_years") if recent_years is None else recent_years)
    w = float(_rule("recent_weight") if recent_weight is None else recent_weight)
    return np.where(years > years.max() - n, w, 1.0)


def trend_fit(annual: dict, years_forward: int | None = None) -> dict:
    """Straight-line (least squares) trends of the record and what moving each real year to the level of
    `last year + years_forward` means for that year.

    Returns years, target_year, per-year rain_mult / et0_mult / tmax_shift_c, and for the screen: slopes per
    decade, the fitted level at the end of the record and at the target year.
    """
    years = np.asarray(annual["years"], float)
    fwd = int(_rule("trend_years_forward") if years_forward is None else years_forward)
    lo, hi = (float(v) for v in _rule("trend_rain_mult_limits"))
    elo, ehi = (float(v) for v in _rule("trend_et0_mult_limits"))
    target = float(years.max()) + fwd
    series = {"rain": annual["precip"].sum(axis=1), "et0": annual["et0"].sum(axis=1),
              "tmax": annual["tmax"].mean(axis=1)}
    out = {"years": years.astype(int), "target_year": int(target), "years_forward": fwd, "record": (int(years.min()), int(years.max()))}
    for name, v in series.items():
        slope, icpt = np.polyfit(years, v, 1) if len(years) >= 3 and np.ptp(years) > 0 else (0.0, float(np.mean(v)))
        fit_y, fit_t, fit_end = slope * years + icpt, slope * target + icpt, slope * years.max() + icpt
        out[f"{name}_slope_per_decade"] = float(slope * 10.0)
        out[f"{name}_level_end"] = float(fit_end)
        out[f"{name}_level_target"] = float(fit_t)
        if name == "tmax":
            out["tmax_shift_c"] = fit_t - fit_y
        else:
            floor = 0.05 * float(np.mean(v)) + 1e-9          # a fitted level never goes to zero or below
            mult = max(fit_t, floor) / np.maximum(fit_y, floor)
            out[f"{name}_mult"] = np.clip(mult, lo, hi) if name == "rain" else np.clip(mult, elo, ehi)
    return out


def _annual(scenarios: SC.Scenarios, weather, lat=None, elevation_m=None) -> dict:
    if weather is None:
        raise ValueError("this climate shift mode needs the site's weather record (pass weather=site.weather)")
    return SC._as_annual(weather, lat, elevation_m)


def recent(scenarios: SC.Scenarios, annual: dict, recent_years: int | None = None,
           recent_weight: float | None = None) -> SC.Scenarios:
    """'Recent' mode. Bootstrap sets are drawn again (same size, same seed) with the recent years more likely;
    other sets are re-weighted by the average weight of their four years."""
    w = year_weights(annual["years"], recent_years, recent_weight)
    n = int(_rule("recent_years") if recent_years is None else recent_years)
    info = {"mode": "recent", "recent_years": n, "recent_weight": float(w.max()),
            "first_recent_year": int(np.asarray(annual["years"])[w > 1.0].min()) if (w > 1.0).any() else None,
            "record": (int(annual["years"][0]), int(annual["years"][-1]))}
    note = (f"real years from NASA POWER; the last {n} years count {w.max():g}x ({WHAT_IF})")
    if scenarios.kind == "bootstrap":
        out = SC.bootstrap(annual, n=scenarios.n, seed=scenarios.seed, year_weights=w)
        info["method"] = "plans drawn again with recent years more likely; every plan counts equally"
        out = replace(out, climate_mode="recent", climate_info=info, note=note)
        if scenarios.rain_mult != 1.0 or scenarios.heat_shift_c != 0.0:
            out = out.adjust(scenarios.rain_mult, scenarios.heat_shift_c)
        return out
    lookup = dict(zip((int(y) for y in annual["years"]), w))
    plan_w = np.array([[lookup.get(int(y), 1.0) for y in row] for row in scenarios.years]).mean(axis=1)
    info["method"] = "plans re-weighted by the average weight of their four years"
    out = scenarios.reweighted(scenarios.weights * plan_w)
    return replace(out, climate_mode="recent", climate_info=info, note=note)


def trend(scenarios: SC.Scenarios, annual: dict, years_forward: int | None = None) -> SC.Scenarios:
    """'Continuing trend' mode: every real year moved to the trend level years_forward (default 10) years after
    the record ends."""
    fit = trend_fit(annual, years_forward)
    pos = {int(y): i for i, y in enumerate(fit["years"])}
    idx = np.array([[pos[int(y)] for y in row] for row in scenarios.years])
    info = {k: (v if np.isscalar(v) or isinstance(v, tuple) else None) for k, v in fit.items()}
    info = {k: v for k, v in info.items() if v is not None}
    info["mode"] = "trend"
    return replace(scenarios, precip=scenarios.precip * fit["rain_mult"][idx][:, :, None],
                   et0=scenarios.et0 * fit["et0_mult"][idx][:, :, None],
                   tmax=scenarios.tmax + fit["tmax_shift_c"][idx][:, :, None],
                   climate_mode="trend", climate_info=info,
                   note=(f"real years from NASA POWER moved to the level of {fit['target_year']} on the record's own "
                         f"straight-line trend ({WHAT_IF})"))


def apply(scenarios: SC.Scenarios, mode="historical", weather=None, lat=None, elevation_m=None) -> SC.Scenarios:
    """The scenario set under a climate shift mode. 'historical' returns the same set, untouched."""
    mode = normalize_mode(mode)
    if mode == "historical":
        return scenarios
    if scenarios.climate_mode != "historical":
        raise ValueError(f"this scenario set already has climate mode {scenarios.climate_mode!r}; start from the historical set")
    annual = _annual(scenarios, weather, lat, elevation_m)
    return recent(scenarios, annual) if mode == "recent" else trend(scenarios, annual)


_CACHE: dict = {}


def scenarios_for(site, mode="historical", kind: str = "bootstrap") -> SC.Scenarios:
    """The site's scenario set under a climate shift mode (remembered per weather record and settings file)."""
    from engine import simulate as SIM
    from engine.crops import SIM_PATH
    mode = normalize_mode(mode)
    base = SIM.default_scenarios(site, kind)
    if mode == "historical":
        return base
    p = SIM._site_parts(site)
    key = (id(p["weather"]), mode, kind, SIM_PATH.stat().st_mtime_ns)
    hit = _CACHE.get(key)
    if hit is not None and hit[0] is p["weather"]:
        return hit[1]
    out = apply(base, mode, p["weather"], p["lat"], p["elevation_m"])
    if len(_CACHE) > 12:
        _CACHE.clear()
    _CACHE[key] = (p["weather"], out)
    return out


@contextmanager
def use(mode):
    """Inside this block, simulate() calls that are given no scenario set use this climate shift mode:

        with climate_shift.use(sliders.climate_shift):
            result = optimize.recommend_picks(site, inputs, sliders)
    """
    from engine import simulate as SIM
    with SIM.what_if(climate_shift=normalize_mode(mode)):
        yield


def describe(weather, mode="historical", lat=None, elevation_m=None) -> dict:
    """Plain words and the numbers behind a mode, for the screen. Everything here is computed from the record."""
    mode = normalize_mode(mode)
    annual = SC._as_annual(weather, lat, elevation_m)
    first, last = int(annual["years"][0]), int(annual["years"][-1])
    out = {"mode": mode, "label": LABELS[mode], "what_if": WHAT_IF, "record": (first, last), "badge": "observed"}
    if mode == "historical":
        out["text"] = f"Every real weather year from {first} to {last} counts once."
    elif mode == "recent":
        w = year_weights(annual["years"])
        start = int(np.asarray(annual["years"])[w > 1.0].min())
        out.update(first_recent_year=start, recent_weight=float(w.max()), badge="assumption")
        out["text"] = (f"The years {start} to {last} count {w.max():g} times, earlier years once. "
                       f"A what-if that leans on recent weather, not a forecast.")
    else:
        f = trend_fit(annual)
        out.update({k: v for k, v in f.items() if np.isscalar(v)}, badge="assumption")
        out["text"] = (
            f"Every real year is moved to where the record's own straight-line trend points for {f['target_year']}: "
            f"yearly rain {f['rain_slope_per_decade']:+.0f} mm per decade, "
            f"daily maximum temperature {f['tmax_slope_per_decade']:+.2f} degC per decade, "
            f"reference evapotranspiration {f['et0_slope_per_decade']:+.0f} mm per decade "
            f"({first} to {last}). A what-if that assumes the trend simply continues, not a forecast.")
    return out
