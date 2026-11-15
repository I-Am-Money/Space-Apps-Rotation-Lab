# Explicit frozen example-provider fixture. Never imported by production code.
# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""The contract between the four parts of RotationLab (Build Spec v4, section A5).

Everyone talks to everyone else ONLY through this file. Nobody changes a signature without telling
the engine lead (Person 1).

STATUS: every function below is a STUB that returns realistic-looking EXAMPLE data. Each returned
object has `example=True`, and every badge value in its `badges` dict is "example". The UI must show
a red EXAMPLE DATA badge wherever `example` is True. Stubs are replaced by real code one at a time;
when a function is real its results carry `example=False`. Nothing returned by a stub is real data.

Units inside the engine are METRIC: millimetres, kg/ha, currency per hectare. The UI converts for
display. Exceptions fixed by the spec: `QuestionValue.evpi_per_acre` and `Zone.area_acres` carry
acres because the spec names them that way.

Per-year conventions (one rule for the whole contract so deltas make sense):
  * `mean_profit`, `worst10_profit`, `calories`, `irrigation_mm`, `total_water_mm` are AVERAGES PER PLAN
    YEAR (profit in currency/ha/year, calories in kcal/ha/year, water in mm/year), averaged over the
    4-year plan and over the scenarios (worst10_profit: mean of the worst 10% of scenarios).
  * `crops` is one entry per plan year, each a list of 1 or 2 crop ids (one or two seasons per year).
  * `cover_crops` is one bool per plan year (a cover crop sits in the off-season before the next year).
  * `deltas_vs_current` is the difference (this pick minus the current plan) for the same keys.
Badge values: "observed", "estimated", "your_input", "assumption", "example".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

SEED = 42
YEARS_IN_PLAN = 4
BADGES = ("observed", "estimated", "your_input", "assumption", "example")
CLIMATE_SHIFTS = ("historical", "recent", "trend")
DELTA_KEYS = ("mean_profit", "worst10_profit", "calories", "irrigation_mm", "total_water_mm", "soil_score")
EXAMPLE_NOTE = "EXAMPLE DATA: stub values, not computed from this site."


# --------------------------------------------------------------------------------------- data classes

@dataclass
class SoilInfo:
    texture: str
    awc_mm_per_m: float                # available water capacity, mm of water per metre of soil
    organic_matter_pct: float
    source: str
    badge: str


@dataclass
class ClimateTrend:
    """R17: 1981-2000 vs the last 20 years at this site. Each pair is (early, late)."""
    early_years: tuple
    late_years: tuple
    season_rain_mm: tuple
    rain_variability_cv: tuple         # coefficient of variation of season rain across years
    heat_days: tuple                   # mean days per year with Tmax above the heat threshold
    rainy_season_start_doy: tuple      # day of year the rainy season starts
    heat_threshold_c: float = 35.0
    note: str = "what changed at this spot in NASA data, not a forecast"
    badges: dict = field(default_factory=dict)
    example: bool = True


@dataclass
class USDefaults:
    crops: list                        # crops grown in the county
    yields: dict                       # crop -> kg/ha (county, or state average if suppressed)
    prices: dict                       # crop -> currency per tonne
    costs: dict                        # crop -> currency per ha
    irrigated_share: float             # 0..1, share of county cropland irrigated
    level: str = "county"              # "county" or "state" (suppressed county data falls back, labelled)
    badges: dict = field(default_factory=dict)


@dataclass
class Site:
    lat: float
    lon: float
    country: str
    us_state: Optional[str]
    us_county_fips: Optional[str]
    weather: pd.DataFrame              # daily; columns tmax, tmin, tmean, rh, wind2, precip, srad; DatetimeIndex
    soil: SoilInfo
    elevation_m: float
    climate_trend: ClimateTrend
    us_defaults: Optional[USDefaults]
    data_as_of: str                    # ISO date the data was fetched
    badges: dict = field(default_factory=dict)
    example: bool = True


@dataclass
class WaterInput:
    mode: str                          # "rain" or "irrigated"
    source: Optional[str] = None       # e.g. "canal", "well", "tank", "river"
    normal_mm: Optional[float] = None  # supply in a normal year (mm over the season)
    dry_mm: Optional[float] = None     # supply in a dry year


@dataclass
class UserInputs:
    current_plan: list                 # the baseline: list of crop ids, one per plan year (or per season)
    water: WaterInput
    farm_acres: float
    soil_test: Optional[dict] = None   # {"organic_matter_pct":, "ph":, "texture":}
    history: Optional[dict] = None     # {"tillage":, "cover_crops":, "erosion":, "waterlogging":, "salinity":}
    crop_overrides: dict = field(default_factory=dict)   # crop -> {"yield": kg/ha, "price": per t, "cost": per ha}


@dataclass
class Sliders:
    bad_year: float = 0.3              # 0 = plan for an average year, 1 = protect me in bad years
    water: float = 0.0                 # 0..1, how much water saving matters
    soil: float = 0.5                  # 0..1, how much soil health matters
    profit_tolerance_pct: float = 0.0  # how far below the current plan's mean profit a pick may fall
    climate_shift: str = "historical"  # "historical" | "recent" | "trend"


@dataclass
class RotationResult:
    crops: list                        # [[crop, ...] x 4]
    cover_crops: list                  # [bool x 4]
    mean_profit: float
    worst10_profit: float
    calories: float
    irrigation_mm: float
    total_water_mm: float
    soil_score: float                  # 0..100, "rule-based score, not a soil test"
    yields_by_year: list               # [{crop: kg/ha} x 4]
    deltas_vs_current: dict
    badges: dict
    example: bool = True


@dataclass
class Recommendations:
    headline: Optional[RotationResult]          # Best for soil and climate (None if guardrail not met)
    highest_profit: RotationResult
    best_soil: RotationResult                   # Best for your soil
    all_results: list
    current_plan_result: RotationResult
    guardrail_met: bool
    explanations: dict                          # "headline" | "highest_profit" | "best_soil" -> text
    example: bool = True


@dataclass
class TippingPoints:
    rainfall_curve: dict               # {"x": [mult], "series": {label: [score]}, "winner": [label], "crossovers": [x],
                                       #  "band": {"p10": {...}, "p90": {...}}}
    heat_curve: dict                   # same shape, x = heat shift in degC
    water_curve: dict                  # same shape, x = water supply in mm
    map_2d: dict                       # {"rain_mult": [..], "water_mm": [..], "winner": [[label]], "labels": [..]}
    bands: dict                        # 10th to 90th percentile of each crossover point
    note: str = "what-if adjustments to real years, not forecasts"
    example: bool = True


@dataclass
class QuestionValue:
    question: str
    evpi_per_acre: float               # expected value of perfect information, currency per acre (spec name)
    could_change_answer: bool
    example: bool = True


@dataclass
class Zone:
    polygon: list                      # [(lat, lon), ...]
    area_acres: float
    kind: str                          # "slope" | "low_spot" | "main"
    recommendation: RotationResult
    reason: str
    example: bool = True


@dataclass
class ValidationSummary:
    table: list                        # rows: {"site","crop","r","mae","r_corrected","mae_corrected"}
    sites: list
    example: bool = True


# ----------------------------------------------------------------------------------------- stub helpers

_CATALOG = ["maize", "soybean", "wheat", "sorghum", "rice", "cotton", "groundnut", "chickpea"]
_LEGUMES = {"soybean", "groundnut", "chickpea"}
_YIELD = {"maize": 6500, "soybean": 2400, "wheat": 3200, "sorghum": 3000, "rice": 4500, "cotton": 1300,
          "groundnut": 1800, "chickpea": 1200}
_KCAL_PER_KG = {"maize": 3650, "soybean": 4460, "wheat": 3390, "sorghum": 3390, "rice": 3600, "cotton": 0,
                "groundnut": 5670, "chickpea": 3640}


def _example_badges(*names) -> dict:
    return {n: "example" for n in names}


def _example_weather(lat: float, lon: float) -> pd.DataFrame:
    """Synthetic daily weather for 1981-2025. EXAMPLE ONLY: shaped like POWER output, not NASA data."""
    rng = np.random.default_rng(SEED)
    idx = pd.date_range("1981-01-01", "2025-12-31", freq="D")
    doy = idx.day_of_year.to_numpy()
    season = np.sin(2 * np.pi * (doy - 80) / 365.0)
    tmean = 18 + 9 * season + rng.normal(0, 2, len(idx))
    precip = np.where(rng.random(len(idx)) < 0.25, rng.gamma(0.9, 6.0, len(idx)), 0.0)
    return pd.DataFrame({
        "tmax": tmean + 5, "tmin": tmean - 5, "tmean": tmean, "rh": np.clip(65 + 15 * rng.normal(size=len(idx)), 20, 100),
        "wind2": np.clip(2.0 + rng.normal(0, 0.6, len(idx)), 0.2, 9), "precip": precip,
        "srad": np.clip(16 + 9 * season + rng.normal(0, 3, len(idx)), 1, 35)}, index=idx)


def default_inputs() -> UserInputs:
    """Convenience for the UI and tests: a plain rainfed farm."""
    return UserInputs(current_plan=["maize", "soybean", "maize", "soybean"], water=WaterInput(mode="rain"), farm_acres=100.0)


def default_sliders() -> Sliders:
    return Sliders()


def is_example(obj) -> bool:
    """True if this object (or anything inside a Recommendations/TippingPoints...) is stub data."""
    if isinstance(obj, (list, tuple)):
        return any(is_example(o) for o in obj)
    return bool(getattr(obj, "example", False))


def _make_result(plan_years: list, cover: list, k: float, current: Optional[RotationResult] = None) -> RotationResult:
    """A self-consistent example rotation. `k` scales the example economics (stubs only)."""
    ys = [{c: float(round(_YIELD.get(c, 3000) * (0.9 + 0.2 * k) * (1.1 if (i and c not in _LEGUMES and any(x in _LEGUMES for x in plan_years[i - 1])) else 1.0), 0))
           for c in year} for i, year in enumerate(plan_years)]
    cal = float(np.mean([sum(v * _KCAL_PER_KG.get(c, 3000) for c, v in y.items()) for y in ys]))
    soil = float(np.clip(40 + 14 * len({c for y in plan_years for c in y}) + 6 * sum(cover) + 5 * sum(
        any(c in _LEGUMES for c in y) for y in plan_years) - 8 * (len(plan_years) - len({tuple(y) for y in plan_years})), 0, 100))
    mean = float(round(520 + 260 * k + 18 * soil / 10, 0))
    res = RotationResult(
        crops=plan_years, cover_crops=cover, mean_profit=mean, worst10_profit=float(round(mean * (0.35 + 0.1 * k), 0)),
        calories=float(round(cal, -3)), irrigation_mm=float(round(40 * (1 - k) + 10, 0)),
        total_water_mm=float(round(430 + 70 * (1 - k), 0)), soil_score=float(round(soil, 0)), yields_by_year=ys,
        deltas_vs_current={}, badges=_example_badges("mean_profit", "worst10_profit", "calories", "irrigation_mm",
                                                     "total_water_mm", "soil_score", "yields_by_year"))
    if current is not None:
        res.deltas_vs_current = {key: float(round(getattr(res, key) - getattr(current, key), 3)) for key in DELTA_KEYS}
    else:
        res.deltas_vs_current = {key: 0.0 for key in DELTA_KEYS}
    return res


def _normalise_plan(plan: list) -> list:
    return [[c] if isinstance(c, str) else list(c) for c in plan] if plan else [["maize"]] * YEARS_IN_PLAN


# ------------------------------------------------------------------------------------------ the contract

def get_site(lat: float, lon: float) -> Site:
    """Everything the engine knows about a pin. STUB: example data."""
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"latitude {lat} / longitude {lon} is not a point on Earth")
    us = 24.5 <= lat <= 49.5 and -125 <= lon <= -66.5
    trend = ClimateTrend(early_years=(1981, 2000), late_years=(2006, 2025), season_rain_mm=(612.0, 571.0),
                         rain_variability_cv=(0.21, 0.27), heat_days=(9.0, 17.0), rainy_season_start_doy=(121, 131),
                         badges=_example_badges("season_rain_mm", "rain_variability_cv", "heat_days", "rainy_season_start_doy"))
    defaults = USDefaults(crops=["maize", "soybean", "wheat"], yields={"maize": 9200, "soybean": 3100, "wheat": 3300},
                          prices={"maize": 190.0, "soybean": 450.0, "wheat": 230.0},
                          costs={"maize": 1250.0, "soybean": 780.0, "wheat": 640.0}, irrigated_share=0.05,
                          badges=_example_badges("yields", "prices", "costs")) if us else None
    return Site(lat=lat, lon=lon, country="USA" if us else "EXAMPLE", us_state="KS" if us else None,
                us_county_fips="20113" if us else None, weather=_example_weather(lat, lon),
                soil=SoilInfo("silt loam", 160.0, 2.4, EXAMPLE_NOTE, "example"), elevation_m=420.0,
                climate_trend=trend, us_defaults=defaults, data_as_of="1970-01-01",
                badges=_example_badges("weather", "soil", "elevation_m", "us_defaults"))


def get_candidates(site: Site, inputs: UserInputs) -> list:
    """Crops that fit this climate (and, in the US, what the county grows). STUB: example list."""
    base = list(site.us_defaults.crops) if site.us_defaults else list(_CATALOG[:6])
    cur = {c for y in _normalise_plan(inputs.current_plan) for c in y}
    return sorted(set(base) | cur)


def recommend(site: Site, inputs: UserInputs, sliders: Sliders) -> Recommendations:
    """Three picks vs the current plan. STUB: example picks, guardrail logic is real."""
    plan = _normalise_plan(inputs.current_plan)
    current = _make_result(plan, [False] * YEARS_IN_PLAN, 0.5)
    cands = get_candidates(site, inputs)[:4] or ["maize", "soybean"]
    a, b = cands[0], cands[1 % len(cands)]
    lg = next((c for c in cands if c in _LEGUMES), b)
    hi_profit = _make_result([[a], [a], [lg], [a]], [False] * 4, 0.8, current)
    best_soil = _make_result([[a], [lg], [cands[-1]], [lg]], [True, False, True, False], 0.4, current)
    balanced = _make_result([[a], [lg], [a], [lg]], [False, True, False, True], 0.6, current)
    floor = current.mean_profit * (1 - sliders.profit_tolerance_pct / 100.0)
    met = balanced.mean_profit >= floor
    allr = [current, hi_profit, best_soil, balanced]
    expl = {"headline": explain(balanced, current), "highest_profit": explain(hi_profit, current),
            "best_soil": explain(best_soil, current)}
    return Recommendations(headline=balanced if met else None, highest_profit=hi_profit, best_soil=best_soil,
                           all_results=allr, current_plan_result=current, guardrail_met=met, explanations=expl)


def tipping_points(site: Site, inputs: UserInputs, sliders: Sliders) -> TippingPoints:
    """Where the best plan changes with rainfall, heat and water. STUB: example curves and map."""
    rain = [round(0.5 + 0.05 * i, 2) for i in range(17)]
    heat = [round(0.25 * i, 2) for i in range(13)]
    water = [0, 100, 200, 300, 400, 500, 600]
    labels = ["Your current plan", "Soil and climate pick"]

    def curve(x, cross):
        s1 = [round(100 + 40 * v / max(x) - (i % 3), 1) for i, v in enumerate(x)]
        s2 = [round(95 + 55 * v / max(x), 1) for v in x]
        win = [labels[1] if v >= cross else labels[0] for v in x]
        return {"x": x, "series": {labels[0]: s1, labels[1]: s2}, "winner": win, "crossovers": [cross],
                "band": {"p10": {"crossovers": [round(cross * 0.92, 2)]}, "p90": {"crossovers": [round(cross * 1.08, 2)]}}}
    rc, hc, wc = curve(rain, 0.8), curve(heat, 1.5), curve(water, 250)
    grid = [[labels[1] if (r >= 0.8 or w >= 300) else labels[0] for r in rain] for w in water]
    return TippingPoints(rainfall_curve=rc, heat_curve=hc, water_curve=wc,
                         map_2d={"rain_mult": rain, "water_mm": water, "winner": grid, "labels": labels},
                         bands={"rainfall": rc["band"], "heat": hc["band"], "water": wc["band"]})


def question_value(site: Site, inputs: UserInputs, sliders: Sliders) -> list:
    """What to measure next, ranked by expected value of perfect information. STUB: example ranking."""
    rows = [QuestionValue("What is your dry-year water supply?", 31.5, True),
            QuestionValue("What is your soil's water capacity?", 12.0, True),
            QuestionValue("What is your soil's organic matter?", 0.0, False)]
    return sorted(rows, key=lambda q: -q.evpi_per_acre)


def zones(site: Site, polygon: list, inputs: UserInputs, sliders: Sliders) -> list:
    """Stretch feature: up to three zones inside a drawn field. STUB: one example zone."""
    rec = recommend(site, inputs, sliders)
    pick = rec.headline or rec.best_soil
    return [Zone(polygon=list(polygon), area_acres=float(inputs.farm_acres), kind="main", recommendation=pick,
                 reason="EXAMPLE zone: elevation and soil splitting is not built yet.")]


def validation_summary() -> ValidationSummary:
    """Hindcast results across sites, with and without the correction. STUB: example rows."""
    rows = [{"site": "EXAMPLE county A", "crop": "maize", "r": 0.41, "mae": 640.0, "r_corrected": 0.58, "mae_corrected": 520.0},
            {"site": "EXAMPLE county B", "crop": "soybean", "r": 0.33, "mae": 280.0, "r_corrected": 0.47, "mae_corrected": 240.0}]
    return ValidationSummary(table=rows, sites=sorted({r["site"] for r in rows}))


def explain(rotation_result: RotationResult, current_plan_result: RotationResult) -> str:
    """Plain-English text for one pick, using only numbers in the results. STUB: deterministic template.
    The real version (explain.py, guarded) rejects any number or crop not present in the results."""
    d = rotation_result.deltas_vs_current or {}
    crops = ", ".join(sorted({c for y in rotation_result.crops for c in y}))
    return (f"EXAMPLE TEXT. This plan grows {crops}. Compared with your current plan, average profit changes by "
            f"{d.get('mean_profit', 0):+.0f} per hectare per year and the Soil Health Score changes by "
            f"{d.get('soil_score', 0):+.0f} points.")
