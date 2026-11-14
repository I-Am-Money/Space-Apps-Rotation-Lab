# Interface contract (all agents build against this; do not change without telling the lead)

Governing docs: RotationLab Build Spec v2 (summarised in the lead's brief) + `SPEC_CHANGES_INDIA.md` (wins on conflicts). Read both first.

## Global rules
- Python from `/Users/naveenkonreddy/Space-Apps-Rotation-Lab/.venv/bin/python`. Run tests with `.venv/bin/pytest`.
- Stay inside the files you own (table below). Need a change elsewhere? Write it to `engine/REQUESTS.md` (append a line) instead of editing.
- **Never invent data.** Every number is cached data, a computed value, user input, or an `assumptions.yaml`-style parameter with a `source` note. If you cannot verify a source, write `source: "literature range, team to verify"`. Missing real values get `badge: placeholder`.
- Badges: `observed` (NASA/ICRISAT/MSP official data), `modeled`, `local` (soil data, farmer entry, farm_records.csv), `assumption`, `placeholder`.
- Cache every download to `data/raw/`. Anything must work offline from cache. Seed 42.
- No git commits, no pushes, no touching `.env` contents, no Space Apps portal actions, nothing submitted anywhere.
- District is unknown (`district: TEAM_TO_FILL`). Use a DEV point (`lat 17.5, lon 78.5`, central Telangana, flagged `dev_placeholder: true`) so code and tests run; swapping the real district must be a one-line change in `config/region.yaml`.
- Units: temperature degC, rain/ET mm/day, wind m/s at 2 m, srad MJ/m2/day, RH %, yield kg/ha, money Indian rupees per acre (convert kg/ha to per-acre in ONE place: `economics.py`). Prices in rupees/quintal.
- Crop ids: `rice`, `jowar`, `bajra`, `pigeonpea`. Reference rotations A `[rice]*4`, B `[rice,jowar,rice,jowar]`, C `[rice,pigeonpea,jowar,rice]`. Candidate set: all 4^4 = 256 sequences.

## Data shapes
- **Weather** (`engine.fetch_power.load_weather(lat, lon) -> pandas.DataFrame`): daily index 1981-01-01..2025-12-31, columns `tmax, tmin, tmean, rh, wind2, precip, srad`. No NaN, no -999. Cached JSON in `data/raw/`.
- **Scenario arrays**: `dict` with float arrays shaped `[S, 4, 365]` named `et0, precip, tmax` (Feb 29 dropped), plus `labels: list[str]` (e.g. "1996-1999"). One scenario = 4 consecutive plan years of real weather.
- **PlanResult** (`engine.waterbalance.simulate_plan(...)` output): dict of arrays `[S, 4]`: `yield_kg_ha, eta_mm, etm_mm, rain_mm, irrig_mm, irrig_needed_mm, runoff_mm, drainage_mm`, and `[S]`: `storage_change_mm`, `closure_error_mm`. Rice irrigation fields are zero for non-rice years.
- **RotationMetrics**: `plan` (list), `mean_profit, worst10_profit, water_stress_mm, irrigation_mm, total_water_mm, J` (rupees/acre or mm), plus `badges` dict.

## File ownership
| Owner agent | Files |
|---|---|
| nasa-data | `engine/fetch_power.py`, `engine/fetch_gibs.py`, `config/region.yaml`, `data/raw/power_*`, `data/raw/gibs_*`, `tests/test_data_sanity.py`, `data/gibs_layers.json`, `docs/NASA_DATA.md` |
| india-data | `engine/fetch_icrisat.py`, `engine/fetch_msp.py`, `engine/fetch_soil.py`, `config/prices_india.yaml`, `data/raw/icrisat_*`, `data/raw/msp_*`, `data/raw/soil_*`, `docs/INDIA_DATA.md` |
| engine-physics | `engine/et0.py`, `engine/crops.py`, `engine/waterbalance.py`, `engine/yieldmodel.py`, `config/assumptions.yaml`, `tests/test_et0.py`, `tests/test_waterbalance.py`, `tests/test_yield.py`, `tests/test_rice.py` |
| engine-decision | `engine/scenarios.py`, `engine/economics.py`, `engine/optimize.py`, `engine/boundaries.py`, `engine/hindcast.py`, `engine/api.py`, `tests/test_scenarios.py`, `tests/test_optimize.py`, `tests/test_boundaries.py`, `tests/test_determinism.py`, `LIMITATIONS.md` |
| frontend | `app.py`, `ui/` (all), `.streamlit/config.toml`, `engine/explain.py`, `engine/mock_api.py`, `tests/test_explain.py`, `PRODUCT.md`, `DESIGN.md`, `README.md`, `assets/` |

## Physics API (engine-physics provides; engine-decision consumes)
```python
# engine/et0.py
def et0_daily(weather: DataFrame, lat: float, elevation_m: float) -> np.ndarray   # mm/day, FAO-56 PM, Hargreaves fallback logged
# engine/crops.py
def load_crops() -> dict[str, CropParams]     # reads config/assumptions.yaml; fields: kc_ini, kc_mid, kc_end, stages_days (4), root_depth_m, p, ky, sowing_doy, plus rice extras
# engine/waterbalance.py
def simulate_plan(scen: dict, plan: Sequence[str], awc_mm_per_m: float, irrigation_available_mm: float,
                  params: dict | None = None) -> PlanResult
#   continuous daily root-zone balance across all 4 years incl. fallow; rice = irrigated paddy (spec changes sec 2);
#   irrigation_available is base_available BEFORE monsoon scaling; scaling by (season_rain/median)^k happens inside.
# engine/yieldmodel.py
def season_yield(ym_kg_ha: float, ky: float, eta: np.ndarray, etm: np.ndarray, rotation_factor: np.ndarray) -> np.ndarray
def rotation_factor(plan: Sequence[str], params: dict | None = None) -> np.ndarray   # per year multiplier + N-credit info
def nitrogen_credit_kg_ha(plan, params=None) -> np.ndarray
```
Potential yield `Ym` per crop comes from `config/assumptions.yaml` key `ym_kg_ha` (set from ICRISAT data by india-data into `config/prices_india.yaml: potential_yield_kg_ha`; physics reads it via a small loader and falls back to flagged placeholder).

## Decision API (engine-decision provides to the frontend) in `engine/api.py`
All functions return plain Python dicts / DataFrames / numpy; every numeric field has a sibling `*_badge` or sits in a `badges` dict. `params` dict keys: `lam` (0..1), `w` (0..1), `irrigation_mm`, `awc_mm_per_m` (None = soil default), `current_rotation` (list of 4 crop ids), `price_mult` (default 1.0).
```python
get_field_summary() -> dict          # region, climate summary (monthly means, annual rain, monsoon rain), soil, yield history, farm_records or None
list_rotations() -> list[dict]       # id, plan, label for A,B,C,"current", and all 256
compare(rotation_ids: list, params) -> dict       # per-rotation: profit distribution [S], per-year yield [S,4]/mean, water stress, irrigation_mm, total_water_mm, residue_index[4], named stress tests table
recommend(params) -> dict            # top, runner_up, metrics, pareto points for all 256 (+frontier flags), three_strategy_report (A/B/C+current: why, evidence, benefits, info_gaps, risks_for_local_review)
tipping_points(params) -> dict       # rainfall crossover (1D) with p10/p90 bootstrap band, late-monsoon what-if, grid {rain_mult[], irrigation_mm[], winner[][]}, evpi_awc {value, test_cost, text}, evpi_irrigation {value, test_cost, text}
hindcast() -> dict                   # per crop: years, observed, modeled, detrended anomalies, pearson_r, mae, heldout_r (last 10 yrs), farm_records overlay or None, baseline table
assumptions_table() -> DataFrame     # name, value, range, unit, source, badge
```
Sliders must recompute in under ~1 s (vectorise; cache scenario arrays and per-rotation simulations keyed by params).

## Frontend (consumes `engine.api`; until it exists use `engine/mock_api.py`)
`mock_api.py` mirrors `engine/api.py` signatures exactly and returns clearly labelled `placeholder` data so the UI can be built and screenshotted now. `app.py` imports `engine.api` and falls back to `engine.mock_api` only when the real module raises ImportError, showing a visible banner when mock data is on screen.
