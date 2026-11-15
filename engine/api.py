# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Shared A5/v5 contracts and thin dispatch to feature owners.

Internal units: mm, kg/ha, currency/ha; prices and overrides are currency/tonne.
Profit, food and water metrics are averages per plan year. Rotations have four
plan years, each containing one or two crop IDs; cover flags are per year.
Only explicit test fixtures contain invented EXAMPLE data. Missing features raise
clear errors instead of switching to a synthetic model. Charvik owns API wiring.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

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



def default_inputs():
    return UserInputs(['maize', 'soybean', 'maize', 'soybean'], WaterInput('rain'), 100.)


def default_sliders():
    return Sliders()


def is_example(obj):
    if isinstance(obj, dict):
        return obj.get('example') is True or any(is_example(v) for k, v in obj.items() if k != 'example')
    if isinstance(obj, (list, tuple)):
        return any(is_example(v) for v in obj)
    return bool(getattr(obj, 'example', False))


def get_site(lat, lon):
    from engine.site import get_site as load
    return load(lat, lon)


def precache_site(lat, lon, offline=False):
    from engine.site import get_site as load
    return load(lat, lon, precache=True, offline=offline)


def get_candidates(site, inputs):
    from engine.candidates import candidates
    return candidates(site, inputs)


def simulate(site, inputs, rotation, scenarios=None):
    from engine.simulate import simulate as run
    return run(site, inputs, rotation, scenarios)


def simulate_many(site, inputs, rotations, scenarios=None):
    from engine.simulate import simulate_many as run
    return run(site, inputs, rotations, scenarios)


def _rotation(value):
    if value is None or isinstance(value, RotationResult):
        return value
    from dataclasses import fields
    result = RotationResult(**{f.name: value[f.name] for f in fields(RotationResult) if f.name in value})
    for key, item in value.items():
        if not hasattr(result, key):
            setattr(result, key, item)
    return result


def recommend_details(site, inputs, sliders, most_food=False):
    from engine.optimize import score_candidates, assemble_recommendation
    from engine.cache import ArrayCache
    from dataclasses import asdict
    import hashlib, json
    from pathlib import Path
    from engine import climate_shift, simulate as simulation
    mode = climate_shift.normalize_mode(sliders.climate_shift)
    # Tipping requests carry transient rain/heat/water/scenario overrides.
    # They must never reuse the ordinary farm's scored bundle.
    if simulation.current_what_if():
        with climate_shift.use(mode):
            return assemble_recommendation(score_candidates(site, inputs), sliders, most_food=most_food)
    # Memoize the owner's expensive scoring, not its slider-dependent pick selection.
    global _RECOMMEND_CACHE
    if '_RECOMMEND_CACHE' not in globals():
        _RECOMMEND_CACHE = ArrayCache(32 * 1024 * 1024)
    root = Path(__file__).resolve().parents[1]
    versions = tuple((root / name).stat().st_mtime_ns for name in ('config/assumptions/recommend.yaml', 'config/assumptions/simulation.yaml'))
    spec = json.dumps({'inputs': asdict(inputs), 'soil': vars(site.soil),
                       'defaults': None if site.us_defaults is None else vars(site.us_defaults)}, sort_keys=True, default=str)
    weather_key = hashlib.sha256(pd.util.hash_pandas_object(site.weather, index=True).values.tobytes()).hexdigest()
    key = (weather_key, mode, site.lat, site.lon, site.elevation_m, versions, id(score_candidates), hashlib.sha256(spec.encode()).hexdigest())
    bundle = _RECOMMEND_CACHE.get(key)
    if bundle is None:
        with climate_shift.use(mode):
            bundle = score_candidates(site, inputs)
        _RECOMMEND_CACHE[key] = bundle
    return assemble_recommendation(bundle, sliders, most_food=most_food)


def recommend(site, inputs, sliders):
    raw = recommend_details(site, inputs, sliders)
    if raw.get('input_needed'):
        raise ValueError('Input needed: ' + ', '.join(str(v.get('field')) + ' for ' + str(v.get('crop')) for v in raw['input_needed']))
    if raw.get('current_plan_problem'):
        raise ValueError('Current plan cannot be simulated: ' + raw['current_plan_problem'])
    return Recommendations(_rotation(raw.get('headline')), _rotation(raw['highest_profit']), _rotation(raw['best_soil']),
                           [_rotation(v) for v in raw['all_results']], _rotation(raw['current_plan_result']),
                           raw['guardrail_met'], raw['explanations'], example=raw.get('example', False))


def tipping_points(site, inputs, sliders, progress=None):
    try:
        from engine.tipping import tipping_points as compute
    except ImportError as exc:
        raise NotImplementedError('Tipping-point estimates are not available in this build yet.') from exc
    return compute(site, inputs, sliders, progress=progress)


def question_value_details(site, inputs, sliders, test_costs=None):
    from engine.evpi import question_value as compute
    return compute(site, inputs, sliders, test_costs=test_costs)


def question_value(site, inputs, sliders):
    rows = question_value_details(site, inputs, sliders)
    result = []
    for row in rows:
        q = QuestionValue(row['question'], row.get('evpi_per_acre') or 0., bool(row.get('could_change_answer')), example=bool(row.get('example')))
        for key, value in row.items():
            setattr(q, key, value)
        result.append(q)
    return result


def zones(site, polygon, inputs, sliders):
    from engine.zones import zones as compute
    return compute(site, polygon, inputs, sliders)


def validation_summary():
    from engine.hindcast import validation_summary as summary
    return summary()


def explain(rotation_result, current_plan_result):
    from engine.explain import explain_pick
    return explain_pick(rotation_result, current_plan_result, use_api=False)


def gibs_layers(offline=False, precache=False):
    from engine.fetch_gibs import map_layers
    return map_layers(offline=offline, precache=precache)


def us_state(fips):
    from engine.fetch_nass import STATE_FIPS
    return STATE_FIPS.get(fips)


def us_defaults(fips):
    from engine.fetch_nass import us_defaults as load
    return load(fips)


def us_coverage(state, fips, defaults):
    from engine.us_rules import apply
    return apply(state, fips, defaults)


def precache_validation_site(spec, offline=False):
    from engine.fetch_nass import precache_county, NassUnavailable
    if offline:
        from engine import cache
        if not cache.offline():
            raise ValueError('Set ROTATIONLAB_OFFLINE=1 for a strict offline run.')
    try:
        raw = precache_county(spec['fips'], spec.get('crops'))
    except NassUnavailable:
        return {'complete': False, 'notes': {'nass': 'NASS historical yields unavailable: configure NASS_API_KEY or supply a real cache.'}}
    return {'complete': raw.get('available', False), 'data_as_of': raw.get('data_as_of'),
            'notes': raw.get('notes', {}), 'badges': raw.get('badges', {})}


def cache_info():
    from engine import cache
    count = sum(1 for root in (cache.PRECACHE_DIR, cache.RUNTIME_DIR) if root.exists() for _ in root.rglob('*.json.gz'))
    return {'persistent': count > 0, 'stored_entries': count, 'backend': 'engine.cache'}
