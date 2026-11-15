# Charvik — v5 Feature 1 and app-shell integration

## Scope and owner handoff

The v5 markdown replaces prior role assignments. Charvik now owns site/cache/weather/soil/GIBS/climate-card/setup, API wiring, integration and deployment. The referenced RotationLab_Final_Assignments_v5.pdf was not attached or found in two Library title searches; implementation follows the explicit v5 markdown and the published A5 contract. The missing PDF's section 3 could not be checked independently. Public simulate(site, inputs, rotation, scenarios=None) delegates to Person 2's published SimResult without changing its object.

All active team branches passed their own suites before local integration (p2-data 201, p3-validation 237, sahas-feature 163, Sahas-Feature 223). Additional owner updates were incorporated as they arrived, including compiled simulation/result aliases, real recommendation scoring/weights/missing-yield handling, and the hindcast's complete weather fixture. Existing India behavior remains under api_v3 and the legacy explorer. Public main is not claimed updated: every write attempt still returned 403 Resource not accessible by integration.

Feature 3 owns ui/recommendations.py and ui/measure.py. Its latest versions take precedence over Charvik's earlier page drafts. The shell supplies recommend_fn/question_fn callbacks that call engine.api; its recommendation callback also withholds an inconsistent headline. Feature 2 receives ui/tipping.py, moved/adapted from the earlier UI, and owns the remaining sensitivity implementation. Feature 4's own ui/trust.py is preserved. Prior ui/planner.py is a compatibility shim. ui/components.badge(kind) supports Observed, Estimated, Your input, Assumption, EXAMPLE DATA and legacy aliases; EXAMPLE DATA is red even without a theme. The attempted urgent single-file update to main was denied.

## Working Feature 1 pieces

- engine/api.py now exposes real site/simulation/recommendation/EVPI/validation/explanation dispatch and data pre-cache helpers. Its recommendation cache stores the owner's scored bundle, keyed by weather content, inputs/soil/economics and assumption-file versions; slider pick selection remains the owner's fast operation. No synthetic site/weather fallback is used in production. Frozen contract example providers live only in tests/fixtures_api_examples.py.
- engine/site.py composes NASA POWER, Census county geography, SSURGO/STATSGO2 or non-US SoilGrids, and the US defaults/coverage functions through API wrappers. Unknown county/country is labeled Unknown rather than guessed; farmer economics are required when US defaults are absent. Organic matter stays unknown when unavailable. Currency outside the US is a farmer-provided display label; no exchange rate is invented.
- engine/cache.py preserves Person 2's disk cache, adds promotion of fresh runtime entries to committed seeds, atomic unique temporary files, deterministic/unchanged seed writes, invalid-coordinate/refresh checks, and non-finite JSON rejection. Stored=false explicitly reports read-only failures.
- engine/fetch_power.py preserves the shared real-weather loader, retains actual date keys and reindexes missing dates, rejects duplicate/non-monotonic dates, bounds HTTP timeouts, and chunks rejected range/size requests without multiplying ordinary outage/rate-limit failures. Long-gap source filling remains explicit in weather metadata, and those ET0 days use Hargreaves per Person 2's implementation.
- engine/fetch_ssurgo.py is wired and now has hand-calculated thickness-weighting, invalid-value and STATSGO fallback tests. Non-finite and sentinel horizon values never become an AWC estimate.
- engine/climate_card.py compares 1981–2000 with the latest 20 complete years. Season window, heat threshold and rain-start proxy definitions are in config/assumptions/setup.yaml with source/range notes. Rain-start is a team proxy, not a measured onset. Baseline/recent coverage counts are disclosed; southern cross-year onset uses a circular mean.
- ui/setup.py provides start/presets/questions/pin/layers and real status boundaries. The app shell routes all six pages, preserves/edit farm inputs, passes shared badges/dates, and keeps the existing explorer available.

## Pre-cache and live status

Person 3's latest list contains 14 US validation counties, so the current plan is 17 sites including three demos (earlier 12-county/15-site counts are superseded). A real run fetched weather and soil for many sites and recorded remaining failures; exact reports are delivered in checks/. No NASS_API_KEY is configured, so county yields/prices/irrigated-share and historical county validation cannot be fully populated. Public ERS costs/region seeds and the genuine GIBS catalog seed are present. A partial cache is not labeled complete.

## Remaining / not advertised as delivered

- Recent/trend climate-shift modes await Feature 2; the public interface rejects those modes rather than silently returning Historical results. Tipping service wiring also waits for its owner's module. The tipping page is present and handles unavailable data honestly.
- Full US automatic defaults and historical validation need a valid NASS_API_KEY in server/hosting secrets or actual source caches. Field-level accuracy and local validation are never inferred from a matching region alone.
- Zone/elevation/field-drawing stretch is not enabled. No synthetic elevation, zone partition or zone-area test result is claimed. Remove/leave disabled at the 5 PM cutoff if unfinished.
- Public deployment is blocked by GitHub write access; no public endpoint is claimed. Mobile pixel-level visual QA and real full-page screenshots remain unverified; the cloud browser cannot reach the workspace's local server. Full theme/layout/chart consistency pass is reserved for the requested 4–6 PM window after Merge 2, screenshots at 6 PM.

## Sources for the shared DATA_SOURCES document

Existing NASA POWER, GIBS, USDA SDA/SSURGO/STATSGO2, ISRIC SoilGrids and FAO-56 source entries remain applicable. See ui/P4_DATA_SOURCES.md for the earlier detailed source notes. Added US Census coordinate geography API: https://geocoding.geo.census.gov/geocoder/geographies/coordinates and documentation https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html (checked 2026-11-15). County/source cache records retain actual retrieval dates. No farm-specific observations, source values or citations are fabricated.

## AI use and validation

Charvik's additions/integration were produced with OpenAI Codex assistance. Existing Claude/teammate headers remain. Source/API/fixture checks and the full pytest suite were run repeatedly; the previous full integrated run passed 408 tests. The final package records the latest validation after all final integration changes. Unit tests use explicitly synthetic providers where live keys/services are unavailable; this is distinct from real live validation.


## GitHub publication follow-up — November 15

The newly selected GitHub connection now permits branch/blob writes; the earlier 403 block above is historical. Refreshed main b1e3f2a includes Person 2 tipping and climate-shift modules. Those are merged, the owner tipping page calls through engine.api, and API recommendation scoring now separates climate modes and bypasses baseline memoization for transient what-if contexts. A regression test verifies this isolation. Publishing targets p4-app; main is not overwritten. NASS-key and disabled-zone limitations remain. Final test and publication outcome are reported with the pushed commit.


## API, data and security audit — November 15, after the GitHub publication

The supplied screenshot contains a NASS Quick Stats credential. It was read into the git-ignored local .streamlit/secrets.toml with owner-only permissions, never placed in source, committed, printed or included in any upload. The runtime NASS endpoint and even its public documentation page timed out from this workspace. The key's format was read successfully, but live authentication is **unverified**; an outage/egress timeout is not evidence that the key is invalid. The official API docs were independently checked at https://quickstats.nass.usda.gov/api (record limit 50,000, domain_desc=TOTAL, authentication and field definitions).

Working audit fixes:

- engine/fetch_nass.py: remove credential-bearing request URLs from errors and suppress exception chaining; reject malformed response bodies, non-finite/negative observations and invalid FIPS; constrain survey queries to annual field-crop totals and exclude domain breakouts from parsed totals; isolate seed-writing state with ContextVar; carry history metadata and report missing or unwritten county histories as incomplete. Local CLI tools can read the ignored Streamlit secrets file when the environment variable is absent. An explicitly empty environment value disables the credential.
- engine/api.py: validate sliders, four-year plans, area and water inputs before scoring; preserve climate modes for measurement-value calculations; return independent recommendation objects so one user's edits cannot mutate another user's cached results. Non-USD inputs cannot silently reuse USD prices/costs. One-cash-crop-per-year recommendation scoring is explicit; the lower-level simulator supports multi-season rotations, but the optimizer does not score them completely and now refuses them rather than undercounting.
- engine/economics.py: invalid/missing prices or costs request farmer input; profit arithmetic rejects non-finite money and preserves source-specific badges (including estimated national prices and ERS costs).
- engine/cache.py: ignore corrupt metadata, distrust future-dated freshness, respect the byte budget for a single oversized entry, and disclose failed seed promotion instead of claiming persistence.
- engine/evpi.py: reject a non-finite/empty payoff matrix instead of silently reporting unknown value of information as zero.
- engine/fetch_power.py: short interpolated weather gaps are also flagged as estimated; non-finite/physically invalid rain, wind, radiation and humidity are treated as missing; reject inverted daily temperature bounds.
- engine/site.py, ui/setup.py and ui/planner_model.py: preserve availability/fallback notes and extra dataclass fields, show source limitations, distinguish missing automatic defaults, stop currency relabeling, and disclose that optional soil-test measurements do not yet alter yield/water capacity through an unverified relation.
- app.py: Start again also removes the owner's tipping cache and recommendation/measurement widgets.
- scripts/check_nass.py: a small safe authenticated preflight through engine.api, with no credential or raw exception text in output.
- tests/conftest.py: isolate ambient server credentials from deterministic unit/UI tests. tests/test_audit_hardening.py adds regression coverage for the findings above.

Verification: full pytest, undefined-name/static scan, Python compilation, pip dependency check, legacy source-data check, and real cached-source demo runs. The three demos exercised Historical, Recent and Trend modes, 16 rotations each and selected-climate measurement value; farmer yield/price/cost entries were explicitly hypothetical test inputs, not measured or auto-filled USDA values. Observed local timing: cold first scoring about 1.1 s, warm slider changes about 0.002 s. These are local warm-data measurements, not a guarantee for uncached pins.

The 17-entry pre-cache plan remains incomplete: CA-Colusa and AR-Poinsett have no weather seed, and NASS history/defaults cannot be completed until a network reaches the live service. No US validation accuracy was invented. Zones remain disabled. Organic-matter measurement value remains uncomputed without a verified relation. Pixel-level UI review/screenshots are still a separate phase.

### What the host owner must do

Set NASS_API_KEY in the deployed app's server secrets (Streamlit hosting: Settings > Secrets), using the credential already supplied. Local secrets do not automatically transfer to a deployment. Do not put it in GitHub source. No other paid API key is required for the core model; explanations have a deterministic template fallback.

From the project directory on a network that can reach NASS:

```sh
python scripts/check_nass.py
# Continue only when authenticated is true:
python scripts/precache.py --output output/precache.json
python -m engine.correction
python -m pytest -q
```

Review the reports for suppressed/missing source data; a successful connection alone does not mean every county series is available.

Final audit verification: **475 tests passed** (one third-party pytest deprecation warning); selected undefined-name lint, Python compilation, dependency consistency and legacy source-data checks passed. All three real cached demo pipelines passed Historical/Recent/Trend and measurement-value smoke checks. The credential scan passed over every tracked/unignored file, including decompressed source caches.
