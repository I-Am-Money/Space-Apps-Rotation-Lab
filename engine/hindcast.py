# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
# TODO (partial): uses a stand-in yield model until Person 2's engine.yieldmodel.season_relative_yield is on main;
# real numbers need NASS county yields cached (python -m engine.fetch_nass --precache-validation, needs NASS_API_KEY).
"""Hindcast (engine-decision): single-season model yield vs ICRISAT district yield, per crop.

Model yield for year Y = first-year yield of plan [crop]*4 under a scenario that repeats year Y four times
(year 1 follows the configured previous crop, rice on this farm). Observed and modeled are linearly detrended before Pearson r.
Held-out: the most recent eight overlap years are excluded from potential-yield and trend estimation.
Rice note: district rice yields mix irrigated and rainfed fields, so weak r is expected.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from engine import optimize as opt
from engine import scenarios as sc

ROOT = Path(__file__).resolve().parent.parent
HELD_OUT_YEARS = 8
CROP_MAP = {"rice": "rice", "paddy": "rice", "sorghum": "jowar", "jowar": "jowar", "pearl millet": "bajra",
            "pearl_millet": "bajra", "bajra": "bajra", "pigeonpea": "pigeonpea", "pigeon pea": "pigeonpea",
            "pigeon_pea": "pigeonpea", "tur": "pigeonpea"}
WEAK_R = 0.3


def load_observed() -> pd.DataFrame | None:
    """DataFrame [year, crop, yield_kg_ha] from india-data's loader, or None if unavailable."""
    df = None
    try:
        from engine import fetch_icrisat
        for fn in ("load_district_yields", "load_yields"):
            if hasattr(fetch_icrisat, fn):
                df = getattr(fetch_icrisat, fn)()
                break
    except Exception:
        df = None
    if df is None:
        return None
    df = df.copy()
    df["crop"] = df["crop"].astype(str).str.lower().map(lambda c: CROP_MAP.get(c, c))
    return df[df.crop.isin(opt.CROPS)][["year", "crop", "yield_kg_ha"]].dropna()


def load_farm_records() -> pd.DataFrame | None:
    p = ROOT / "data" / "raw" / "farm_records.csv"
    if not p.exists():
        return None
    from engine.records import validate_records
    return validate_records(pd.read_csv(p))


def detrend(years, y, fit_mask=None):
    years, y = np.asarray(years, float), np.asarray(y, float)
    m = np.ones(len(y), bool) if fit_mask is None else fit_mask
    b, a = np.polyfit(years[m], y[m], 1)
    return y - (a + b * years)


def pearson(a, b):
    if len(a) < 4 or np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def model_single_season(annual, crop, awc, irr, ym_override=None) -> np.ndarray:
    n = len(annual["years"])
    idx = np.repeat(np.arange(n)[:, None], 4, axis=1)
    scen = sc.make_scen(annual, idx, [str(y) for y in annual["years"]])
    ss = sc.ScenSet(("single", n, int(annual["years"][0])), scen)
    if ym_override is None:
        sim = opt.sim_plan([crop] * 4, ss, awc, irr)
    else:
        with opt.simulation_overrides(**{f"ym_kg_ha.{crop}": float(ym_override)}):
            sim = opt.sim_plan([crop] * 4, ss, awc, irr)
    return np.asarray(sim["yield_kg_ha"])[:, 0]


def hindcast(annual, awc, irr, observed=None, farm=None) -> dict:
    observed = load_observed() if observed is None else observed
    farm = load_farm_records() if farm is None else farm
    out = {"per_crop": {}, "farm_records": None, "badge_observed": "observed", "badge_modeled": "modeled",
           "available": observed is not None and len(observed) > 0}
    if farm is not None:
        out["farm_records"] = {"badge": "local", "rows": farm.to_dict("records")}
    if not out["available"]:
        out["note"] = "No district yield data found; hindcast skipped (nothing fabricated)."
        return out
    yrs_all = np.asarray(annual["years"])
    for crop in opt.CROPS:
        d = observed[observed.crop == crop].groupby("year").yield_kg_ha.mean()
        years = np.array(sorted(set(d.index.astype(int)) & set(yrs_all.tolist())))
        if len(d) == 0:
            out["per_crop"][crop] = {"years": [], "no_data": True, "status": "no validation data", "note": "no validation data: no Nalgonda yield series for this crop in the available ICRISAT files"}
            continue
        if len(years) < 8:
            out["per_crop"][crop] = {"years": years.tolist(), "no_data": False, "status": "no validation data", "note": "no validation data: fewer than 8 overlapping years"}
            continue
        obs = d.loc[years].to_numpy(float)
        h = min(HELD_OUT_YEARS, len(years) // 2)
        fit = np.arange(len(years)) < len(years) - h
        from engine.fetch_icrisat import detrend as detrend_levels
        ym_train = float(np.percentile(detrend_levels(years[fit], obs[fit]), 90))
        mod_all = model_single_season(annual, crop, awc, irr, ym_override=ym_train)
        mod = mod_all[np.searchsorted(yrs_all, years)]
        a_obs, a_mod = detrend(years, obs), detrend(years, mod)
        r = pearson(a_obs, a_mod)
        mae = float(np.mean(np.abs(obs - mod)))
        mae_anom = float(np.mean(np.abs(a_obs - a_mod)))
        ho_obs, ho_mod = detrend(years, obs, fit)[~fit], detrend(years, mod, fit)[~fit]
        r_ho = pearson(ho_obs, ho_mod)
        reasons = []
        if r is None or r < WEAK_R:
            reasons.append("weak agreement after detrending")
            if crop == "rice":
                reasons.append("district rice yields mix irrigated and rainfed fields while the model treats rice as irrigated paddy with a limited water budget")
            reasons.append("district yields reflect management, pests, varieties and area mix that a water-balance model does not capture; weather is a ~0.5 degree grid")
        out["per_crop"][crop] = {
            "status": "validated against district yields", "years": years.tolist(), "observed": obs.tolist(), "modeled": mod.tolist(),
            "observed_anomaly": a_obs.tolist(), "modeled_anomaly": a_mod.tolist(),
            "pearson_r": r, "mae_kg_ha": mae, "mae_anomaly_kg_ha": mae_anom,
            "heldout_years": years[~fit].tolist(), "heldout_r": r_ho, "n_years": int(len(years)),
            "bias_kg_ha": float(np.mean(mod - obs)),
            "ym_training_kg_ha": ym_train, "training_years": years[fit].tolist(),
            "heldout_mae_kg_ha": float(np.mean(np.abs(obs[~fit] - mod[~fit]))),
            "level_note": "Validation potential yield and trend lines are estimated from training years only; the latest eight overlap years are held out. Operational recommendations use the full published yield series.",
            "weak": bool(r is None or r < WEAK_R), "weak_reason": "; ".join(reasons) or None,
            "text": (f"{crop}: r = {r:.2f} on {len(years)} years" if r is not None else f"{crop}: r not computable")
                    + (f"; held-out last {h} years r = {r_ho:.2f}" if r_ho is not None else "; held-out r not computable")
                    + f"; MAE {mae:.0f} kg/ha (modeled minus observed mean {np.mean(mod-obs):+.0f} kg/ha)."}
    if farm is not None:
        out["farm_records"] = {"badge": "local", "rows": farm.to_dict("records")}
    return out


def baseline_table(df, scenset, awc, irr, params, price_mult=1.0) -> list[dict]:
    """Recommended vs always-rice vs mean-profit-only (lam=0, w=0) picks; mean and worst-10% profit."""
    d_rec = opt.rescore(df, params["lam"], params["w"], df.attrs.get("scale"))
    d_mean = opt.rescore(df, 0.0, 0.0, df.attrs.get("scale"))
    rows = []
    for name, row in (("Picked for your priorities", opt.offered(d_rec).sort_values("J", ascending=False).iloc[0]),
                      ("Rice every year (our farm today)", df[df.id == opt.plan_id(opt.REF["A"])].iloc[0]),
                      ("Picked on average profit alone", opt.offered(d_mean).sort_values("J", ascending=False).iloc[0])):
        rows.append({"strategy": name, "id": row["id"], "mean_profit": float(row.mean_profit),
                     "worst10_profit": float(row.worst10_profit),
                     "irrigation_mm": float(row.irrigation_mm)})
    return rows


# =====================================================================================================
# Build Spec v4 (US) hindcast, R20. Owner: Person 3.
#
# For each validation county and crop: a single-season model yield per year (no rotation effects), both the
# NASS county yield and the modeled yield detrended with a line fitted on TRAINING years only, then Pearson r
# and MAE. The latest `holdout` years are held out (never used to fit Ym, trend lines or the correction) and
# reported separately. The India functions above stay for the v3 app until api.py moves to v4.
#
# Yield function: Person 2's engine.yieldmodel.season_relative_yield(weather, crop, year, lat, awc_mm_per_m)
# -> Ya/Ym, when it exists. Until then a STAND-IN (FAO-56 single Kc daily bucket + FAO-33 Ky) with settings in
# config/validation/standin_crops.yaml is used and every row is badged as stand-in.
# =====================================================================================================
import os
from dataclasses import dataclass, field as _field
from functools import lru_cache as _lru_cache

import yaml as _yaml

VALIDATION_DIR = ROOT / "config" / "validation"
SITES_PATH = VALIDATION_DIR / "sites.yaml"
STANDIN_PATH = VALIDATION_DIR / "standin_crops.yaml"
RESULTS_PATH = VALIDATION_DIR / "results.csv"
INDIA_PATH = VALIDATION_DIR / "india.yaml"
US_HOLDOUT_YEARS = 8


@_lru_cache(maxsize=4)
def _read_yaml(path_str: str, version) -> dict:
    return _yaml.safe_load(Path(path_str).read_text()) or {}


def load_yaml(path: Path) -> dict:
    return _read_yaml(str(path), path.stat().st_mtime_ns)


def validation_sites() -> list[dict]:
    return list(load_yaml(SITES_PATH)["sites"])


def india_sites() -> list[dict]:
    """India validation pack (config/validation/india.yaml), only when its ICRISAT loader works."""
    if not INDIA_PATH.exists():
        return []
    cfg = load_yaml(INDIA_PATH)
    if not cfg.get("enabled") or load_observed() is None:
        return []
    return list(cfg.get("sites") or [])


def all_validation_sites() -> list[dict]:
    return validation_sites() + india_sites()


def crop_settings(crop: str) -> dict:
    """Stand-in season settings: US crops from standin_crops.yaml; India crops (jowar, bajra, pigeonpea) from
    the shared config/assumptions.yaml (crops.<id>, heat.tmax_c.<id>), same keys."""
    us = load_yaml(STANDIN_PATH)["crops"]
    if crop in us:
        return us[crop]
    shared = load_yaml(ROOT / "config" / "assumptions.yaml")
    c = shared["crops"][crop]
    v = lambda k: c[k]["value"] if isinstance(c[k], dict) else c[k]
    heat = shared.get("heat", {}).get("tmax_c", {}).get(crop, {})
    return {"plant_doy": int(v("sowing_doy")), "stages": list(v("stages_days")),
            "kc": [v("kc_ini"), v("kc_mid"), v("kc_end")], "ky": v("ky"), "root_m": v("root_depth_m"),
            "p": v("p"), "heat_c": heat["value"] if isinstance(heat, dict) else heat}


def load_icrisat_yields(crop: str) -> pd.DataFrame | None:
    """[year, yield_kg_ha] district yields from the ICRISAT loader (India pack), or None."""
    df = load_observed()
    if df is None:
        return None
    df = df[df["crop"] == crop][["year", "yield_kg_ha"]].dropna()
    df = df[df["yield_kg_ha"] > 0]          # zero / missing records are not yields
    return df if len(df) else None


def load_site_yields(site: dict, crop: str) -> pd.DataFrame | None:
    if site.get("yield_source") == "icrisat":
        return load_icrisat_yields(crop)
    return load_county_yields(str(site.get("fips")), crop, site.get("nass_practice"))


# ---------------------------------------------------------------- season window and features

def season_window(crop: str, year: int) -> tuple[pd.Timestamp, pd.Timestamp, dict]:
    """(first day, last day, crop settings) of the season harvested in `year` (stand-in calendar).
    A plant_doy later than the season length allows (winter wheat) starts in the previous year."""
    c = crop_settings(crop)
    length = int(sum(c["stages"]))
    start = pd.Timestamp(year, 1, 1) + pd.Timedelta(days=int(c["plant_doy"]) - 1)
    if int(c["plant_doy"]) + length > 366:
        start = pd.Timestamp(year - 1, 1, 1) + pd.Timedelta(days=int(c["plant_doy"]) - 1)
    return start, start + pd.Timedelta(days=length - 1), c


def season_features(weather: pd.DataFrame, crop: str, year: int) -> dict:
    """Season rain (mm) and heat days (Tmax >= crop heat_c) in the crop's season window."""
    start, end, c = season_window(crop, year)
    w = weather.loc[start:end]
    if len(w) < (end - start).days + 1:
        return {"season_rain_mm": None, "heat_days": None}
    return {"season_rain_mm": float(w["precip"].sum()), "heat_days": int((w["tmax"] >= c["heat_c"]).sum())}


def _kc_curve(stages, kc) -> np.ndarray:
    """FAO-56 single crop coefficient curve, daily: flat ini, linear to mid, flat mid, linear to end."""
    ini, dev, mid, late = (int(s) for s in stages)
    k_ini, k_mid, k_end = kc
    return np.concatenate([np.full(ini, k_ini), np.linspace(k_ini, k_mid, dev, endpoint=False),
                           np.full(mid, k_mid), np.linspace(k_mid, k_end, late)])


def standin_relative_yield(weather: pd.DataFrame, crop: str, year: int, lat: float,
                           awc_mm_per_m: float | None = None) -> float | None:
    """STAND-IN Ya/Ym: FAO-56 single-Kc daily root-zone bucket (Hargreaves ET0, root zone full at planting,
    no runoff, deep drainage above field capacity) and FAO-33 1 - Ya/Ym = Ky (1 - ETa/ETm)."""
    from engine.et0 import et0_hargreaves

    start, end, c = season_window(crop, year)
    w = weather.loc[start:end]
    n = (end - start).days + 1
    if len(w) < n:
        return None
    awc = float(awc_mm_per_m if awc_mm_per_m is not None else load_yaml(STANDIN_PATH)["awc_mm_per_m"]["value"])
    taw = awc * float(c["root_m"])
    raw_ = float(c["p"]) * taw
    et0 = et0_hargreaves(w["tmax"].to_numpy(float), w["tmin"].to_numpy(float), lat, w.index.day_of_year.to_numpy())
    kc = _kc_curve(c["stages"], c["kc"])
    rain = w["precip"].to_numpy(float)
    dr, eta, etm = 0.0, 0.0, 0.0
    for i in range(n):
        etc = kc[i] * et0[i]
        ks = 1.0 if dr <= raw_ else max((taw - dr) / max(taw - raw_, 1e-9), 0.0)
        dr = min(max(dr - rain[i] + ks * etc, 0.0), taw)
        eta += ks * etc
        etm += etc
    return float(max(1.0 - float(c["ky"]) * (1.0 - min(eta / max(etm, 1e-9), 1.0)), 0.0))


def yield_function():
    """(callable, badge). Person 2's season_relative_yield if present, else the stand-in."""
    try:
        from engine import yieldmodel
        fn = getattr(yieldmodel, "season_relative_yield", None)
        if callable(fn):
            return fn, "Estimated"
    except Exception:
        pass
    return standin_relative_yield, "Estimated (stand-in model)"


# ---------------------------------------------------------------- statistics

def fit_line(years, y, mask=None) -> tuple[float, float]:
    """(intercept, slope) of a least-squares line through (years[mask], y[mask])."""
    years, y = np.asarray(years, float), np.asarray(y, float)
    m = np.ones(len(y), bool) if mask is None else np.asarray(mask, bool)
    slope, intercept = np.polyfit(years[m], y[m], 1)
    return float(intercept), float(slope)


def detrend_on(years, y, train_mask) -> np.ndarray:
    """y minus the line fitted on training years only (extrapolated over held-out years)."""
    a, b = fit_line(years, y, train_mask)
    return np.asarray(y, float) - (a + b * np.asarray(years, float))


def pearson_r(a, b) -> float | None:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3 or np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def mae(a, b) -> float | None:
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(np.mean(np.abs(a - b))) if len(a) else None


def split_years(years, holdout: int = US_HOLDOUT_YEARS) -> np.ndarray:
    """Boolean training mask: everything except the latest `holdout` years."""
    years = np.asarray(years)
    order = np.argsort(years)
    train = np.ones(len(years), bool)
    if holdout > 0:
        train[order[len(years) - holdout:]] = False
    return train


@dataclass
class CountyHindcast:
    site: str
    crop: str
    years: list
    actual: list                 # kg/ha, NASS
    modeled: list                # kg/ha, Ym * Ya/Ym
    train_mask: list
    season_rain_mm: list
    heat_days: list
    ym_kg_ha: float | None
    r_train: float | None
    r_test: float | None
    mae_train: float | None
    mae_test: float | None
    mae_anom_test: float | None
    badge: str
    status: str = "ok"
    notes: list = _field(default_factory=list)

    @property
    def test_years(self):
        return [y for y, t in zip(self.years, self.train_mask) if not t]


def hindcast_series(site: str, crop: str, years, actual, rel_yield, season_rain=None, heat_days=None,
                    holdout: int = US_HOLDOUT_YEARS, badge: str = "Estimated", min_years: int = 10) -> CountyHindcast:
    """Core hindcast arithmetic, separated from data loading so it can be hand-checked.

    rel_yield: modeled Ya/Ym per year. Ym = training-trend level at the last training year + the 90th
    percentile of detrended training yields (Person 2's rule: NASS P90 of detrended yields), from training
    years only. Modeled kg/ha = Ym * rel_yield.
    """
    years = np.asarray(years, int)
    actual = np.asarray(actual, float)
    rel = np.asarray(rel_yield, float)
    ok = np.isfinite(actual) & np.isfinite(rel)
    years, actual, rel = years[ok], actual[ok], rel[ok]
    rain = None if season_rain is None else np.asarray(season_rain, float)[ok]
    heat = None if heat_days is None else np.asarray(heat_days, float)[ok]
    empty = dict(years=years.tolist(), actual=actual.tolist(), modeled=[], train_mask=[],
                 season_rain_mm=[] if rain is None else rain.tolist(), heat_days=[] if heat is None else heat.tolist(),
                 ym_kg_ha=None, r_train=None, r_test=None, mae_train=None, mae_test=None, mae_anom_test=None)
    if len(years) < max(min_years, holdout + 3):
        return CountyHindcast(site, crop, badge=badge, status="not enough data",
                              notes=[f"{len(years)} overlapping years; need {max(min_years, holdout + 3)}"], **empty)
    train = split_years(years, holdout)
    a, b = fit_line(years, actual, train)
    last_train = years[train].max()
    resid_train = actual[train] - (a + b * years[train])
    ym = float(a + b * last_train + np.percentile(resid_train, 90))
    modeled = ym * rel
    act_anom = detrend_on(years, actual, train)
    mod_anom = detrend_on(years, modeled, train)
    return CountyHindcast(
        site=site, crop=crop, years=years.tolist(), actual=actual.tolist(), modeled=modeled.tolist(),
        train_mask=train.tolist(), season_rain_mm=[] if rain is None else rain.tolist(),
        heat_days=[] if heat is None else heat.tolist(), ym_kg_ha=ym,
        r_train=pearson_r(act_anom[train], mod_anom[train]), r_test=pearson_r(act_anom[~train], mod_anom[~train]),
        mae_train=mae(actual[train], modeled[train]), mae_test=mae(actual[~train], modeled[~train]),
        mae_anom_test=mae(act_anom[~train], mod_anom[~train]), badge=badge)


# ---------------------------------------------------------------- data loading (Person 2's loaders)

def load_county_yields(fips: str, crop: str, practice: str | None = None) -> pd.DataFrame | None:
    """DataFrame [year, yield_kg_ha] of NASS COUNTY yields (engine.fetch_nass), or None.
    County only: a suppressed county is reported as "no NASS data", never validated against a state number.
    Never invents yields: no key and no cached copy -> None."""
    try:
        from engine import fetch_nass
        df = fetch_nass.county_yields(fips, crop, practice=practice)
    except Exception:
        return None
    if df is None or len(df) == 0:
        return None
    return df[["year", "yield_kg_ha"]].dropna()


def load_site_weather(site: dict) -> pd.DataFrame | None:
    """Daily NASA POWER weather for a site: the v4 loader (load_site_weather, cached) if present, else v3."""
    try:
        from engine import fetch_power
    except Exception:
        return None
    for name, kw in (("load_site_weather", {"refresh": "never"}), ("load_weather", {})):
        fn = getattr(fetch_power, name, None)
        if callable(fn):
            try:
                return fn(float(site["lat"]), float(site["lon"]), **kw)
            except Exception:
                continue
    return None


def validation_summary(recompute: bool = False):
    """A5 validation_summary() for api.py: hindcast + correction table (see engine.correction)."""
    from engine import correction
    return correction.validation_summary(recompute=recompute)


def hindcast_county(site: dict, crop: str, weather: pd.DataFrame | None = None,
                    yields: pd.DataFrame | None = None, yield_fn=None, awc_mm_per_m=None,
                    holdout: int | None = None, min_years: int | None = None) -> CountyHindcast:
    cfg = load_yaml(SITES_PATH)
    holdout = int(cfg.get("holdout_years", US_HOLDOUT_YEARS) if holdout is None else holdout)
    min_years = int(cfg.get("min_years", 20) if min_years is None else min_years)
    sid = site.get("id", site.get("fips", "site"))
    if yield_fn is None:
        yield_fn, badge = yield_function()
    else:
        badge = "Estimated"
    weather = load_site_weather(site) if weather is None else weather
    yields = load_site_yields(site, crop) if yields is None else yields
    empty = dict(years=[], actual=[], modeled=[], train_mask=[], season_rain_mm=[], heat_days=[], ym_kg_ha=None,
                 r_train=None, r_test=None, mae_train=None, mae_test=None, mae_anom_test=None)
    if weather is None:
        return CountyHindcast(sid, crop, badge=badge, status="no weather", notes=["NASA POWER weather not cached"], **empty)
    if yields is None or len(yields) == 0:
        return CountyHindcast(sid, crop, badge=badge, status="no NASS data",
                              notes=["No NASS county yields (NASS_API_KEY not set and nothing cached, or county data withheld)"], **empty)
    y = yields.groupby("year")["yield_kg_ha"].mean()
    w_years = set(weather.index.year)
    years = [int(t) for t in sorted(y.index) if int(t) in w_years]
    rel, rain, heat = [], [], []
    for t in years:
        f = season_features(weather, crop, t)
        rr = yield_fn(weather, crop, t, float(site["lat"]), awc_mm_per_m)
        rel.append(np.nan if rr is None or f["season_rain_mm"] is None else rr)
        rain.append(np.nan if f["season_rain_mm"] is None else f["season_rain_mm"])
        heat.append(np.nan if f["heat_days"] is None else f["heat_days"])
    h = hindcast_series(sid, crop, years, y.loc[years].to_numpy(float), rel, rain, heat,
                        holdout=holdout, badge=badge, min_years=min_years)
    if site.get("water") == "irrigated":
        h.notes.append("Mostly irrigated county: a water-limited model is expected to agree less here.")
    return h
