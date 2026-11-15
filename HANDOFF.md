# RotationLab handoff

Current implementation completed locally on 2026-11-14. Read README.md, LIMITATIONS.md and engine/CONTRACT.md for current behavior. The earlier v2/v3 documents describe the build's history; they do not authorize portal submissions or external communications.

## Run and verify

```sh
.venv/bin/python -m engine check-data
.venv/bin/python -m pytest -q
.venv/bin/python -m streamlit run app.py
.venv/bin/python -m engine report --output output/planning-report.json
.venv/bin/python -m engine benchmark --scenarios 500 --include-tipping
.venv/bin/python scripts/prepare_deploy.py
```

No key is needed. Read docs/DEPLOYMENT.md before publishing. The owner has requested that the completed implementation be pushed to GitHub. Public deployment and portal submission remain separate steps.

## Completed

- Recovered and checksum-verified ICRISAT/TCI apportioned crop data from the World Bank archive RR_IND_2025_488. Nalgonda district code 59 has 52 positive-yield years, 1966-2017, for rice, kharif sorghum, bajra and pigeonpea; ragi has 17. Selected bajra and jowar, giving 256 rotations. Avoided double-counting annual and kharif sorghum.
- Updated potential yields from the real district series. Official 2026-27 ragi MSP is included. Per-acre cost budgets now use a transparent national A2+FL unit-cost proxy instead of arbitrary guesses. It remains an assumption, not a verified farm/state cost. Removed invented measurement quotes and avoided double-counting ordinary irrigation charges.
- Added onset-driven planting, false-onset rejection and flowering heat sensitivity. Completed continuous daily accounting, capped well supply, canal-first use and no-harvest behavior when planting/maturity falls outside the modeled year.
- Added compiled parallel numerical loops and exact shared-prefix reuse. The compiled fixed-calendar calculations match the reference equations to rounding precision. Request-specific settings are isolated with context variables; array and tipping-result caches are bounded. Large sweeps are chunked and cached views copied so old batch buffers are not retained.
- Unified the fixed monetary water preference across recommendations, boundaries, EVPI and farm splits. Added bootstrap bands to the main rainfall/supply map and exact count-weighted tail resampling. Supply overrides vary correctly with total supply in sweeps. Preserved duplicate nondominated Pareto points.
- Added 150-sequence interactive and 500-sequence full tipping modes, with 200 resamples. Main recommendations always use 500. Warm tipping responses reuse completed results.
- Added an offline district-outline map, local cost inputs, heat toggle, anonymous farm CSV import, farm-yield history overlay and CSV downloads. All five screens have automated render coverage without an API key or mock fallback.
- Validation now estimates both potential yield and trends using training data only and holds out the latest eight overlap years. Weak scores remain visible.
- Added data-check/report/benchmark CLI commands, Docker configuration, GitHub Actions, source-bundle preparation and deployment instructions. The bundle excludes credentials and private farm-record files.
- Optional Claude explanations require opt-in and use bounded memory caching. Template explanations always work offline.

## Performance

On this machine, with 256 rotations and 500 scenarios after native compilation: changed priorities approximately 0.06 s, changed supply approximately 0.79 s. Full tipping analysis approximately 18 s cold and 0.01 s cached. Initial imports and native compilation add startup time. Exact measurements are in output/benchmark-500.json when generated; timings depend on hardware and input settings.

## Remaining real-world work

All selected crops now have district validation data. Actual farm supply, local costs, agronomic calibration and measurement quotes cannot be established from public records alone. They remain clearly identified assumptions or optional local inputs; do not fabricate them or call regional proxies farm observations. Review LIMITATIONS.md before using rankings.

Public deployment requires a writable repository or a hosting account that can upload the prepared bundle. Browser automation was unavailable, so public/mobile visual review remains an external verification step. Do not submit anything to the Space Apps portal until the team explicitly authorizes submission. Never include village locations, team names, email addresses or keys in app artifacts.

## Final verification

The completed source passes 106 tests on Streamlit 1.67.0. The older 1.51 navigation path was also exercised before the final export refinements. An independently extracted source bundle passed 105 tests and all five numerical API paths passed with networking disabled. Final screen checks were repeated after the current-input source table and export changes. Source/ZIP manifests are in output/. A visual browser review and Docker build were unavailable; no public deployment is claimed.
