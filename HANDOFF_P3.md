# Handoff: Person 3 (soil score, validation, explanations, docs)

Branch `p3-validation`, based on main at `18e8c38`. Nothing has been merged to main. Last test run: **182 passed**
(Python 3.11). Ownership changed on 2026-11-15, and work on the old Person 3 task list has stopped.

State key: **working** = done and tested; **partial** = code runs but something is missing or blocked;
**not started** = no work done.

## Files created

| File | State | Notes |
|---|---|---|
| `engine/soil_score.py` | working | Soil Health Score 0 to 100 (R11). Entry points: `soil_score(crops, cover_crops, yields, history, tillage)`, `score_result(rotation_result)`, `residue_carbon_kg_ha()`. Not yet called by `optimize.py` (Person 1 has to wire it in). |
| `engine/correction.py` | partial | Bias correction (R12) fitted on training years only, and `validation_summary()`. Tested. No `config/validation/results.csv` has been made yet, because there are no NASS yields. `api.validation_summary()` is not wired to it (Person 1's file). TODO at the top. |
| `config/validation/sites.yaml` | working | 12 US counties, 9 regions. Lat/lon and FIPS come from the Census 2023 Gazetteer. Crops per county are team picks that still need checking against NASS. |
| `config/validation/standin_crops.yaml` | partial (stand-in) | Settings for the stand-in hindcast yield model. Kc and stage lengths are from FAO-56 and Ky from FAO-66 (checked); root depth, p and planting days are "team to verify". TODO at the top. |
| `config/validation/README.md` | working | Pre-cache request for Person 2 (weather and NASS yields for each site). |
| `tests/test_soil_score.py` | working | 10 tests: a legume and cover crop rotation scores higher than the same crops without them; repetition penalty; residue carbon checked against a hand calculation. |
| `tests/test_hindcast_us.py` | working | 7 tests, including a hand-checked r (10/sqrt(240) = 0.6455) and the 8-year holdout never being used. |
| `tests/test_correction.py` | working | 7 tests, including that the correction never trains on held-out years. |
| `DATA_SOURCES.md` | working | Source, URL and download date per dataset. NASS, SSURGO, ERS and SRTM rows are marked "planned / not downloaded". |
| `docs/SUBMISSION_DRAFT.md` | partial | 7-slide deck outline and project page text. Screenshots and every result number are TBD. TODO at the top. |
| `HANDOFF_P3.md` | working | This file. |

## Files changed

| File | State | Notes |
|---|---|---|
| `engine/hindcast.py` | partial | v3 India functions kept unchanged (the current app uses them). Added the v4 US hindcast (R20): `hindcast_series`, `hindcast_county`, a stand-in single-season model, and loaders that call Person 2's `fetch_nass` and `fetch_power`. Real results are blocked on NASS yields, and on Person 2's `yieldmodel.season_relative_yield` replacing the stand-in. TODO at the top. |
| `engine/explain.py` | working | Guarded Claude explanations (R16): JSON payload of numbers only, `claude-sonnet-5-5`, number and crop guard with rounding, cache by input hash, template when there is no key. `explain_pick()` is the v4 entry point; the v3 `explain()` is kept and now guarded. Never tested against the live API (no key here). `api.explain` is not wired to it (Person 1's file). |
| `tests/test_explain.py` | working | 11 tests: a wrong number or wrong crop is rejected; the template works with no key; replies are cached; the v3 tests still pass. |
| `config/assumptions.yaml` | working | Appended a `soil_score:` section only. Other sections are untouched, and `api.assumptions_table()` still loads. |
| `README.md` | working | Rewritten for v4: setup, how it works, AI disclosure. Says plainly that main still runs the India build. |
| `LIMITATIONS.md` | working | v4 items (A10 list, model and validation limits, blocked items with their fallbacks); the India items are kept below. The "Logged by the team" section is empty. |
| `AI_USE.md` | working | Rewritten, with the header comment template. Lists 12 code files that still need the header, grouped by owner. |

## Not committed

- `data/raw/power_42.037538_-93.466093.json`: NASA POWER weather for Story County, IA, downloaded by
  `fetch_power` while testing. Public data, no secrets. Left untracked because pre-caching is Person 2's job.
- No secrets anywhere. No `.env` and no API keys are in the repo.

## Old tasks not started or not finished

- Real validation numbers (blocked: no `NASS_API_KEY`, no v4 NASS fetcher). When unblocked, run
  `python -m engine.correction`.
- Wiring into the v4 `engine/api.py`: `validation_summary` → `correction.validation_summary`,
  `explain` → `explain.explain_pick`, and the soil score in `optimize.py`. The v4 `api.py` was not on main.
- The AI-use header in the 12 files listed in `AI_USE.md` (owners haven't been asked yet).
- Deck screenshots (need the final v4 app).
- India (ICRISAT) in the v4 validation: deliberately not added.

## Environment

The repo's `.venv` is Python 3.13. Tests were run in a separate Python 3.11 venv outside the repo
(`~/.venvs/rl311`, made from `requirements.txt` plus pytest and anthropic).
