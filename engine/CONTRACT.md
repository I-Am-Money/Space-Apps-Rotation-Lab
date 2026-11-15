# Current engine contract

The UI calls engine.api. Physics uses kg/ha, millimetres and daily weather; economics converts to rupees/acre in one module. Farm facts and model assumptions are in config/. Source observations must never be fabricated. Missing observations remain absent or explicitly labeled; model parameters have source notes and badges.

## Data

- annual weather: years plus et0, precip and tmax arrays [year,365], February 29 removed; upstream rainfall [year].
- ScenSet: et0/precip/tmax [scenario,4,365], onset_doy [scenario,4] (zero-based; 365 means none), optional upstream_season_rain [scenario,4], labels and cache key.
- PlanResult: yield/water/accounting fields [scenario,4]; closure_error_mm and storage_change_mm [scenario]. Sowing-day diagnostics are one-based; 366 means no planting. Batch output adds a leading rotation dimension.
- Crops: rice, bajra, jowar, pigeonpea are selected. All 4^4 sequences are evaluated. A is rice x4; B is rice,bajra,rice,bajra; C is rice,pigeonpea,bajra,rice.

## API

get_field_summary(), list_rotations(), compare(ids, params), recommend(params), land_split(alt_id, params), tipping_points(params), hindcast(params), assumptions_table(). All use cached public data; numeric outputs carry badges or badge dictionaries. Baseline ID is A; deltas are relative to rice-only.

Parameters include lam/w in [0,1], water_source, irrigation_mm, canal_supply_mm, well_supply_mm, awc_mm_per_m, soil_mode, current_rotation, heat_enabled, operating_costs, optional additional irrigation/measurement costs, water_value_rs_m3 in [0,5], and boundary_scenarios. Soil aliases farm/district are accepted. Invalid nonfinite or negative values fail clearly. Uploaded farm_records are accepted by hindcast as anonymous validated rows.

J = (1-lam)*mean_profit + lam*worst10_profit - w*water_value_rs_m3*4.04686*irrigation_mm. It uses an explicit fixed preference value, not a scenario-dependent normalization or a water tariff. Land splits combine outcomes under the same weather before computing the worst 10%. Tail sizes use ceil(0.1*S).

Boundary sweeps compare an explicitly stated candidate subset. They return rainfall crossovers, a rainfall/supply winner grid with 200-resample boundary bands, an onset-delay curve, an upstream/local-rain grid for combined supply, and EVPI for soil/supply. Unknown test costs are None and worth_measuring is None. Grid supply levels scale entered source capacities, including zero-current-supply cases. Main result caching is bounded and keyed by normalized parameters, source/config versions and the annual-data generation.

## Implementation and verification

_water_kernel.py compiles the same daily accounting equations with Numba, reusing identical plan prefixes and parallelizing independent weather sequences. A fixed-calendar reference remains for equation-equivalence tests. Source settings use ContextVar isolation, and model arrays use byte-bounded caches. Cache values own their small arrays rather than retaining concatenated sweep buffers. The numerical compiler is pinned for Python 3.11-3.13 wheels.

No keys, names, emails or village coordinates belong in the repository. No automatic mock fallback is allowed for calculation failures. ROTATIONLAB_MOCK is an explicitly labeled design-only mode. A repository push does not authorize public hosting or portal submission.
