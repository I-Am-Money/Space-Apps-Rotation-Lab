"""Hindcast (engine-decision): single-season model yield vs ICRISAT district yield, per crop.

Model yield for year Y = first-year yield of plan [crop]*4 under a scenario that repeats year Y four times
(no prior-crop effect in year 1). Observed and modeled are linearly detrended before Pearson r.
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
    for name, row in (("recommended", d_rec.sort_values("J", ascending=False).iloc[0]),
                      ("always rice (A)", df[df.id == opt.plan_id(opt.REF["A"])].iloc[0]),
                      ("mean-profit only (lam=0)", d_mean.sort_values("J", ascending=False).iloc[0])):
        rows.append({"strategy": name, "id": row["id"], "mean_profit": float(row.mean_profit),
                     "worst10_profit": float(row.worst10_profit), "water_stress_mm": float(row.water_stress_mm),
                     "irrigation_mm": float(row.irrigation_mm)})
    return rows
