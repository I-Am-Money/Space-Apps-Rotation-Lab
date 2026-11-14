# Interface contract (all agents build against this; do not change without telling the lead)

Governing docs: RotationLab Build Spec v2 (summarised in the lead's brief) + `SPEC_CHANGES_INDIA.md` (wins on conflicts). Read both first.

## Global rules
- Python from `<repo>/.venv/bin/python`. Run tests with `.venv/bin/pytest`.
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

---
# ITERATION 2 CHANGES (owner answers, 2026-11-14; these override anything above)

1. **District = Nalgonda, Telangana.** ICRISAT match = the old pre-2016 Nalgonda district listed under Andhra Pradesh (the lineage must be verified from a primary source, not memory). Use the Nalgonda DISTRICT CENTROID (a sourced coordinate, cite where it comes from) for NASA POWER and the map. No village location. Remove `dev_placeholder` once the real centroid is in; re-fetch and cache POWER for it.
2. **Our farm today is rice only.** Rotation **A = rice x4 = "our farm today", the BASELINE** every alternative is compared against. Alternatives use crops grown in Nalgonda:
   - Millets: pick the one or two of jowar, bajra, ragi with the MOST COMPLETE Nalgonda yield record in ICRISAT (count years from the real data). Record the choice and year counts under `crop_selection:` in `config/region.yaml` (`millets: [..]`, `year_counts: {rice:, jowar:, bajra:, ragi:, pigeonpea:}`, `source`). Crop ids: `rice, jowar, bajra, ragi, pigeonpea`. Only the selected millets enter the candidate set (so 3 to 4 crops, 81 to 256 sequences).
   - Legume: pigeonpea.
   - B = rice, M, rice, M. C = rice, pigeonpea, M, rice. (M = the best millet.) `current_rotation` defaults to A.
3. **Water source** is `water_source: unset | canal | borewell | tank` in `config/region.yaml` (default `unset`; the owner has NOT yet chosen, so the UI must say "confirm your rice water source"). Modes:
   - `borewell` / `tank` / `unset`: local-rainfall recharge proxy as specified.
   - `canal`: availability depends on Nagarjuna Sagar reservoir releases, NOT local rain. Keep the same formula shape but label it "proxy for canal water availability"; `base_available` and `k` editable. Add a named stress test **"low canal release year"**. Do not invent reservoir release numbers; if real release data cannot be sourced, the stress test is a labelled what-if multiplier on available water.
   The water source is a `params` key: `water_source`.
4. **ICRISAT**: try the ICRISAT Dataverse DOI 10.21421/D2/XFB1BZ (https://doi.org/10.21421/D2/XFB1BZ) first, in a real browser. If unreachable, say so; the owner will place the CSV in `data/raw/icrisat_dld/` by hand. NEVER use fake yields for validation. A crop with no Nalgonda yield data: hindcast shows "no validation data" in the UI and LIMITATIONS.md.
5. **Framing**: the app opens on "A rice farm in Nalgonda, Telangana", rotation A preselected as baseline, and EVERY chart and table shows comparison to A (delta vs baseline). `engine.api` results carry `baseline_id: "A"` and per-rotation `delta_vs_baseline` fields (profit mean, worst10, water use, irrigation).

File ownership is unchanged. `region.yaml`: nasa-data owns everything except the `crop_selection:` block, which india-data owns (use targeted edits; re-read before editing).

---
# ITERATION 3 CHANGES (owner update, 2026-11-14; overrides iteration 2 where they conflict)

**Rice irrigation supply is now two sources.** `config/region.yaml: water_source: canal_and_well` (the older modes unset/borewell/tank/canal stay accepted for the selector, but `canal_and_well` is the default).
```
S = S_canal + S_well
S_canal = base_canal * (upstream_rain / median_upstream_rain) ** k_canal
S_well  = min(max_well, base_well * (local_rain / median_local_rain) ** k_well)
Order of use: canal first; wells cover the shortfall, up to S_well. Total irrigation used never exceeds S.
```
- `upstream_rain` = Jun-Oct season rainfall averaged over 3 to 5 NASA POWER points in the upper Krishna basin, UPSTREAM of Nagarjuna Sagar. nasa-data picks the points (coordinates and reasons from primary sources, e.g. India-WRIS basin maps or the Krishna Water Disputes Tribunal / CWC basin description; no guessing), lists them in `config/region.yaml: upstream_points`, and caches the data like the Nalgonda data. New module `engine/fetch_upstream.py` with `load_upstream_season_rain() -> DataFrame[year, mean_season_rain_mm, one column per point]` (same 1984-2025 window, same -999 rules).
- Labels: canal = "proxy for canal releases based on upstream monsoon rain; actual releases depend on reservoir operations." Wells = "simplified recharge proxy."
- `config/assumptions.yaml` (physics owns): `base_canal, k_canal, base_well, k_well, max_well` with ranges and note "team to verify".
- **Scenario arrays** gain `upstream_season_rain` shaped `[S, 4]` (mm, from fetch_upstream, aligned to the same years as each scenario; decision agent builds it). `median_upstream_rain` and `median_local_rain` are fixed at base climate, not rescaled by what-ifs.
- **PlanResult** gains `[S,4]` arrays `irrig_canal_mm`, `irrig_well_mm` (their sum equals `irrig_mm`), plus `supply_canal_mm`, `supply_well_mm` `[S,4]`.
- **params** gain `canal_supply_mm` and `well_supply_mm` overrides (None = use the formula).
- **Named stress test** "low canal release year" = the real year with the lowest upstream rainfall, labelled with that year (replaces the x0.5 what-if for this water source).
- **Tipping Points**: keep the rainfall multiplier x irrigation heat map, and ADD a second heat map: upstream rain multiplier (x) vs local rain multiplier (y), coloured by winning rotation. api key `tipping_points()["grid_upstream_local"] = {upstream_mult[], local_mult[], winner[][]}`.
- **Compare Futures** reports canal water and well water separately per rotation (`irrigation_canal_mm`, `irrigation_well_mm`).
- **Our Farm tab**: two overrides, canal supply and well supply (mm).
- **LIMITATIONS**: canal releases are a rainfall proxy, not a reservoir model; groundwater depletion is not simulated.
- **Tests (physics)**: S_canal and S_well never negative; S_well never exceeds max_well; less upstream rain never raises rice yield; less local rain never raises rice yield; wells are drawn only when canal falls short; total irrigation used never exceeds S.

---
# ITERATION 4 CHANGES (owner update, 2026-11-14)
- **Farm facts live in `config/farm.yaml`** (lead-owned; read-only for agents): 40 acres, black soil (cracking clay, vertisol-type), rice only today. Display name for the soil: "Black soil (farm input)", badge `local`.
- **Farm totals everywhere** (total profit, total irrigation water in m3 using `units.m3_per_acre_per_mm`, total water use) in addition to per-acre numbers. **Land-split slider**: "X of 40 acres in rice", the rest in the chosen alternative rotation; api `land_split(alt_id, params) -> {acres_rice[0..40], total_profit_mean, total_profit_worst10, total_irrigation_m3, ...}` with the baseline (40 acres rice) marked.
- **Soil**: SoilGrids at the Nalgonda centroid stays as the district estimate. If it disagrees strongly with a black soil, keep SoilGrids for the district but show the farm soil as "Black soil (farm input)" with a cited black-soil AWC range (FAO-56 or a cited Indian vertisol source), badge `local`/`assumption`; else "team to verify".
- **Paddy percolation_seepage** at the LOW end of its range (black soils drain slowly); AWC range high. Sourced or "team to verify".
- **PRIVACY (hard rule)**: never store or show the village name or ANY team member name or email anywhere in the app, docs, code comments, data files or commit messages. Use "the farm" and "your farm".
