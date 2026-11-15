# AI use: this file was written by Claude Code (Anthropic) under the team's direction, then reviewed by the team. See AI_USE.md.
# TODO (partial): works and is tested; config/validation/results.csv is not generated yet because NASS county yields
# need NASS_API_KEY. Then run: python -m engine.fetch_nass --precache-validation && python -m engine.correction
"""Hybrid bias correction (Build Spec v4, R12) and validation_summary() for api.py. Owner: Person 3.

In counties with enough NASS history, a numpy linear regression of (actual - modeled yield) on season rain,
heat days and year, fitted on TRAINING years only:

    actual - modeled = b0 + b1 * rain_mm + b2 * heat_days + b3 * (year - first training year)
    corrected = modeled + prediction

r and MAE are reported on held-out years with and without the correction. The held-out years never enter
the fit (fit() only ever receives the rows of the training mask).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from engine import hindcast as hc

MIN_TRAIN_YEARS = 10     # 4 coefficients; fewer training years than this -> no correction (reported)
FEATURES = ("intercept", "season_rain_mm", "heat_days", "year")


@dataclass
class Correction:
    coef: np.ndarray          # b0..b3 in FEATURES order
    year0: int
    train_years: list
    rmse_train: float

    def predict(self, rain_mm, heat_days, year) -> np.ndarray:
        return design(rain_mm, heat_days, year, self.year0) @ self.coef

    def apply(self, modeled, rain_mm, heat_days, year) -> np.ndarray:
        return np.asarray(modeled, float) + self.predict(rain_mm, heat_days, year)


def design(rain_mm, heat_days, year, year0: int) -> np.ndarray:
    rain = np.atleast_1d(np.asarray(rain_mm, float))
    heat = np.atleast_1d(np.asarray(heat_days, float))
    yr = np.atleast_1d(np.asarray(year, float)) - year0
    return np.column_stack([np.ones_like(rain), rain, heat, yr])


def fit(actual, modeled, rain_mm, heat_days, year) -> Correction:
    """Least squares on the rows given (callers pass training rows only)."""
    actual, modeled = np.asarray(actual, float), np.asarray(modeled, float)
    year = np.asarray(year, int)
    if len(actual) < MIN_TRAIN_YEARS:
        raise ValueError(f"need at least {MIN_TRAIN_YEARS} training years, got {len(actual)}")
    year0 = int(year.min())
    X = design(rain_mm, heat_days, year, year0)
    resid = actual - modeled
    coef, *_ = np.linalg.lstsq(X, resid, rcond=None)
    rmse = float(np.sqrt(np.mean((X @ coef - resid) ** 2)))
    return Correction(coef=coef, year0=year0, train_years=year.tolist(), rmse_train=rmse)


def fit_training(h: hc.CountyHindcast) -> Correction:
    """Fit on the training years of a hindcast (held-out rows are dropped before fit is called)."""
    m = np.asarray(h.train_mask, bool)
    sel = lambda v: np.asarray(v, float)[m]
    return fit(sel(h.actual), sel(h.modeled), sel(h.season_rain_mm), sel(h.heat_days), np.asarray(h.years)[m])


@dataclass
class CorrectedResult:
    site: str
    crop: str
    n_train: int
    n_test: int
    r: float | None                 # held-out, model only (detrended)
    mae: float | None               # held-out, model only (kg/ha)
    r_corrected: float | None       # held-out, model + correction (detrended)
    mae_corrected: float | None     # held-out, model + correction (kg/ha)
    r_train: float | None
    mae_train: float | None
    corrected_used: bool
    badge: str
    status: str
    notes: list = field(default_factory=list)
    coef: list | None = None


def evaluate(h: hc.CountyHindcast) -> CorrectedResult:
    base = dict(site=h.site, crop=h.crop, r_train=h.r_train, mae_train=h.mae_train, badge=h.badge,
                notes=list(h.notes))
    if h.status != "ok":
        return CorrectedResult(n_train=0, n_test=0, r=None, mae=None, r_corrected=None, mae_corrected=None,
                               corrected_used=False, status=h.status, **base)
    m = np.asarray(h.train_mask, bool)
    years = np.asarray(h.years, int)
    actual, modeled = np.asarray(h.actual, float), np.asarray(h.modeled, float)
    rain, heat = np.asarray(h.season_rain_mm, float), np.asarray(h.heat_days, float)
    out = CorrectedResult(n_train=int(m.sum()), n_test=int((~m).sum()), r=h.r_test, mae=h.mae_test,
                          r_corrected=None, mae_corrected=None, corrected_used=False, status="ok", **base)
    if m.sum() < MIN_TRAIN_YEARS:
        out.notes.append(f"Correction not fitted: {int(m.sum())} training years, needs {MIN_TRAIN_YEARS}.")
        return out
    corr = fit_training(h)
    corrected = corr.apply(modeled, rain, heat, years)
    a_anom = hc.detrend_on(years, actual, m)
    c_anom = hc.detrend_on(years, corrected, m)
    out.r_corrected = hc.pearson_r(a_anom[~m], c_anom[~m])
    out.mae_corrected = hc.mae(actual[~m], corrected[~m])
    out.corrected_used = True
    out.coef = corr.coef.tolist()
    return out


# ---------------------------------------------------------------- validation summary (api.validation_summary)

COLUMNS = ["site", "crop", "r", "mae", "r_corrected", "mae_corrected", "n_train", "n_test", "r_train",
           "mae_train", "region", "ers_region", "state", "county", "fips", "lat", "lon", "water", "badge", "status", "notes"]


@dataclass
class _ValidationSummary:              # local stand-in for api.ValidationSummary (A5) until api.py has it
    table: pd.DataFrame
    sites: list


def _summary_cls():
    try:
        from engine import api
        cls = getattr(api, "ValidationSummary", None)
        if cls is not None:
            return cls
    except Exception:
        pass
    return _ValidationSummary


def run_validation(sites: list[dict] | None = None, weather_loader=None, yield_loader=None) -> pd.DataFrame:
    """Hindcast + correction for every site and crop in config/validation/sites.yaml. One row per site and crop."""
    sites = hc.all_validation_sites() if sites is None else sites
    weather_loader = weather_loader or hc.load_site_weather
    rows = []
    for s in sites:
        ys = {crop: (hc.load_site_yields(s, crop) if yield_loader is None else yield_loader(str(s.get("fips")), crop))
              for crop in s["crops"]}
        # weather is only loaded when there is at least one yield series to compare with
        w = weather_loader(s) if any(y is not None and len(y) for y in ys.values()) else None
        for crop in s["crops"]:
            y = ys[crop]
            if y is None or len(y) == 0:
                e = CorrectedResult(s["id"], crop, 0, 0, None, None, None, None, None, None, False,
                                    hc.yield_function()[1], "no NASS data" if s.get("yield_source") != "icrisat"
                                    else "no yield data",
                                    ["No yield records loaded (NASS_API_KEY not set and nothing cached, or withheld)"])
            elif w is None:
                e = CorrectedResult(s["id"], crop, 0, 0, None, None, None, None, None, None, False,
                                    hc.yield_function()[1], "no weather", ["NASA POWER weather not cached"])
            else:
                e = evaluate(hc.hindcast_county(s, crop, weather=w, yields=y))
            rows.append({"site": s["id"], "crop": crop, "r": e.r, "mae": e.mae, "r_corrected": e.r_corrected,
                         "mae_corrected": e.mae_corrected, "n_train": e.n_train, "n_test": e.n_test,
                         "r_train": e.r_train, "mae_train": e.mae_train, "region": s.get("region"),
                         "ers_region": s.get("ers_region"), "state": s.get("state"), "county": s.get("county"), "fips": s.get("fips"),
                         "lat": s.get("lat"), "lon": s.get("lon"), "water": s.get("water"), "badge": e.badge,
                         "status": e.status, "notes": "; ".join(e.notes)})
    return pd.DataFrame(rows, columns=COLUMNS)


def validation_summary(recompute: bool = False):
    """A5 ValidationSummary(table, sites). Reads config/validation/results.csv (written by
    `python -m engine.correction`) so the deployed app needs no API keys; recompute=True reruns everything."""
    cls = _summary_cls()
    sites = hc.all_validation_sites()
    if recompute:
        table = run_validation(sites)
    elif hc.RESULTS_PATH.exists():
        table = pd.read_csv(hc.RESULTS_PATH, dtype={"fips": str})
    else:      # never fetch inside the app: show every site as not run yet
        table = pd.DataFrame([{"site": s["id"], "crop": c, "region": s.get("region"), "ers_region": s.get("ers_region"),
                               "state": s.get("state"), "county": s.get("county"), "fips": s.get("fips"), "lat": s.get("lat"),
                               "lon": s.get("lon"), "water": s.get("water"), "status": "validation not run yet",
                               "notes": "Run python -m engine.correction after NASS yields are cached."}
                              for s in sites for c in s["crops"]])
    table = table.reindex(columns=COLUMNS)
    try:
        return cls(table=table, sites=sites)
    except TypeError:
        return cls(table, sites)


def main():
    table = run_validation()
    hc.RESULTS_PATH.write_text(table.to_csv(index=False))
    ok = table[table.status == "ok"]
    print(f"wrote {hc.RESULTS_PATH} ({len(table)} rows, {len(ok)} with results)")
    print(table[["site", "crop", "r", "mae", "r_corrected", "mae_corrected", "status"]].to_string(index=False))


if __name__ == "__main__":
    main()
