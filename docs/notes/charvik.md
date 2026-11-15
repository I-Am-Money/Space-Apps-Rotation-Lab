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
