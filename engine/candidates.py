# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Which crops are worth considering at a pin (Build Spec v4, R5). Owner: Feature 3.

A crop is a candidate when its growing season fits the local climate AND, for US pins, the county grows it.

Climate fit, per crop, per recent year: a window as long as the crop's season exists, starting in that year,
whose mean daily temperature stays between the crop's limits and, for frost-sensitive crops, with no day whose
minimum is at or below the frost limit. A crop is offered if that holds in at least `min_share_of_years` of
the last `recent_years` years. Windows may run across the new year, so winter crops work.

Season length comes from FAO-56 Table 11 (crops.py once Person 2's catalog has it; the stand-in table in
config/validation/standin_crops.yaml until then). Temperature limits are in config/assumptions/recommend.yaml and are
NOT yet read from FAO EcoCrop: they are marked "team to verify". Crops in the farmer's current plan are always
kept, with a note when the climate check says they are a poor fit.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
RECOMMEND = ROOT / "config" / "assumptions" / "recommend.yaml"
STANDIN = ROOT / "config" / "validation" / "standin_crops.yaml"


@lru_cache(maxsize=1)
def _params() -> dict:
    return yaml.safe_load(RECOMMEND.read_text())["candidates"]


@lru_cache(maxsize=1)
def _standin() -> dict:
    return yaml.safe_load(STANDIN.read_text()).get("crops", {})


def _norm(crop: str) -> str:
    from engine import soil_score
    return soil_score.norm(crop) or str(crop).lower()


def season_days(crop: str) -> int | None:
    """Season length in days: Person 2's crops catalog if it provides one, else the stand-in FAO-56 stage lengths."""
    try:
        from engine import crops as catalog
        fn = getattr(catalog, "season_days", None)
        if fn is not None:
            d = fn(crop)
            if d:
                return int(d)
    except Exception:
        pass
    node = _standin().get(crop)
    return int(sum(node["stages"])) if node else None


def climate_fit(weather: pd.DataFrame, crop: str) -> dict:
    """How many of the recent years this crop's season fits the climate. Returns share, years_ok, years_total and why."""
    p = _params()
    lim = p["crops"].get(crop)
    days = season_days(crop)
    if lim is None or days is None:
        return {"crop": crop, "share": None, "years_ok": 0, "years_total": 0, "fits": None,
                "reason": "no season or temperature data for this crop yet"}
    n_years = int(p["recent_years"]["value"])
    w = weather[["tmean", "tmin"]].dropna()
    last = int(w.index.year.max())
    w = w[w.index.year > last - n_years]
    if len(w) < days + 30:
        return {"crop": crop, "share": None, "years_ok": 0, "years_total": 0, "fits": None,
                "reason": "not enough weather to judge"}
    mean_t = w["tmean"].rolling(days).mean().to_numpy()
    ok = (mean_t >= lim["t_mean_min"]) & (mean_t <= lim["t_mean_max"])
    if lim["frost_sensitive"]:
        ok &= (w["tmin"].rolling(days).min().to_numpy() > float(p["frost_limit_c"]["value"]))
    ok = np.nan_to_num(ok.astype(float)).astype(bool)
    end_idx = np.arange(len(w))
    start_year = w.index.year.to_numpy()[np.maximum(end_idx - days + 1, 0)]
    start_year = np.where(end_idx >= days - 1, start_year, -1)
    years = [y for y in sorted(set(w.index.year)) if y > last - n_years]
    years_ok = sum(bool(ok[start_year == y].any()) for y in years)
    share = years_ok / len(years)
    need = float(p["min_share_of_years"]["value"])
    return {"crop": crop, "share": round(share, 3), "years_ok": years_ok, "years_total": len(years), "fits": share >= need,
            "reason": (f"season fits in {years_ok} of {len(years)} recent years" +
                       ("" if share >= need else f" (needs {need:.0%})"))}


def candidate_report(site, inputs) -> list[dict]:
    """One row per crop considered: fit, share of years, whether the county grows it (US), and why kept or dropped."""
    current = {_norm(c) for y in _years(inputs.current_plan) for c in y}
    county = None
    ud = getattr(site, "us_defaults", None)
    if ud is not None:
        county = {_norm(c) for c in (ud.get("crops") if isinstance(ud, dict) else ud.crops) or []}
    pool = sorted(set(_params()["crops"]) & set(_standin()) | current)
    rows = []
    for crop in pool:
        fit = climate_fit(site.weather, crop)
        in_county = None if county is None else crop in county
        keep = bool(fit["fits"]) and (in_county is not False)
        note = fit["reason"]
        if in_county is False:
            note += "; not grown in this county"
        if crop in current and not keep:
            keep, note = True, note + "; kept because it is in your current plan"
        rows.append({**fit, "in_county": in_county, "candidate": keep, "note": note})
    return rows


def candidates(site, inputs) -> list[str]:
    """Crop ids to build rotations from (R5)."""
    return [r["crop"] for r in candidate_report(site, inputs) if r["candidate"]]


def _years(plan) -> list[list[str]]:
    return [[c] if isinstance(c, str) else list(c) for c in (plan or [])]
