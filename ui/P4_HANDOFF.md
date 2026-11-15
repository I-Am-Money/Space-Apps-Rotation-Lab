# Charvik: v5 Feature 1, application shell and integration

The final v5 markdown overrides the earlier Person 4 lists. This branch includes the prior UI/data work, the latest owner modules from all active team branches, and Charvik's Feature 1 wiring. Only Charvik is authorized to merge to main under v5. A local integration is not a claim that GitHub main or a public deployment has changed.

## Working

- Shared badge(kind) in ui/components.py, including the five required labels, legacy aliases and a red EXAMPLE DATA style that does not depend on the theme. The attempted urgent single-file publication was rejected by GitHub.
- app.py six-page navigation plus the existing Nalgonda explorer. Feature 3's own latest recommendations/measurement pages and Feature 4's trust page are retained; ui/tipping.py was moved from the prior UI for Feature 2. Setup inputs survive editing; charts/results are not invented on a source failure.
- engine/api.py public simulation dispatch, site assembly, recommendation/EVPI/validation/explanation wiring, US-data wrappers and pre-cache hooks. Expensive recommendation scoring is cached by actual weather content, input/soil/economic data and assumption versions; slider selection stays the owner's operation. Frozen synthetic example providers are confined to tests.
- engine/site.py Census county lookup, real NASA weather, SSURGO/STATSGO2 or SoilGrids/FAO soil fallback, official US data/coverage via API wrappers, explicit unknown values and currency labeling. Actual price inputs/overrides use currency per tonne, matching the published contract.
- engine/cache.py shared expiring persistent cache with offline fallback, real data_as_of metadata, promotion into committed seeds, atomic unique temporary files, stable unchanged seed writes, finite-JSON and coordinate validation.
- engine/fetch_power.py shared real 1981-to-latest weather reader, source date-key preservation, bounded requests, careful range fallback, source gap/filling flags and Hargreaves days. No -999/NaN reaches a valid returned weather frame.
- engine/fetch_ssurgo.py wired survey soil with tested thickness-weighting, invalid-value rejection and STATSGO fallback; engine/fetch_soilgrids.py retains tested unit/depth parsing and explicit FAO assumptions; engine/fetch_gibs.py retains actual NASA layer/date discovery and the genuine catalog seed.
- engine/climate_card.py and its visible card compare the baseline/recent periods, with hand-checked precipitation, heat, variability and rain-start calculations. The configurable season/rain-start definitions are team assumptions, not a measured crop calendar or onset definition.
- ui/setup.py and config/assumptions/setup.yaml provide one source for the three demo presets. These now use the existing Story County IA, Sumner County KS and Mitchell County GA validation coordinates, avoiding duplicate demo data requests.
- scripts/precache.py calls only public APIs, verifies components, respects offline mode, and reports partial/missing data instead of a false completion.

## Verification and real data

The previous full integrated run passed 408 tests; final validation is recorded in START_HERE.md. The tests include eight US states and three non-US points via explicit providers, a hand-calculated climate comparison, real dispatch, SDA horizon arithmetic, persistent/offline cache reuse, source-unit handling, all six app pages, unit conversion and guardrail behavior. Real source checks are separate from synthetic tests.

All three revised demos genuinely load weather and SSURGO from persistent caches. The measured local site-load times were approximately 0.226, 0.119 and 0.091 seconds. A real Kansas-weather simulation with explicitly hypothetical farmer yield/price/cost inputs evaluated 16 rotations in about 1.111 seconds; a soil-slider update took about 0.002 seconds. These are local checks with compiled code/cache already available, not guarantees for all new pins.

The latest Person 3 configuration has 14 US validation counties, so the plan contains 17 entries including three demo roles (14 unique coordinates because demos reuse validation sites). A live run persisted real weather/soil for many locations. NASS_API_KEY is not configured, and some POWER requests failed; complete US defaults/historical validation and all-location pre-cache completion are not claimed. Exact run/retry/readiness reports are included under checks/. Public ERS cost/region seeds and the real GIBS catalog seed are included.

## Partial / not enabled

- The published API is real, but Recent/trend modes and the tipping service still await Feature 2's remaining module. Those choices produce a clear unavailable message rather than silently using Historical data.
- Full NASS defaults and held-out county validation require a real NASS_API_KEY in hosting/server secrets or real source caches. No key is included in any artifact.
- engine/zones.py and ui/zones.py are explicit disabled boundaries. Field drawing, official elevation/soil partitioning, per-zone recommendations and zone-area validation have not been delivered. This stretch stays disabled at the 5 PM cutoff if unfinished.
- The requested full cross-page visual pass is scheduled for 4 PM after Merge 2, with screenshot capture at 6 PM (America/New_York). Pixel-level mobile QA, real page screenshots and hosting are not claimed complete.
- GitHub writes remain denied (403 Resource not accessible by integration), including the basic badge update. No new public deployment or remote main update is claimed. The branch/bundle/patch preserve the exact local integration.

## Owner notes and deployment

Read docs/notes/charvik.md for the detailed feature handoff, ownership precedence, source notes, limitations and AI disclosure. The earlier ui/P4_API_INTEGRATION.patch is removed because engine/api.py is now directly wired; do not apply an old copy of that patch onto v5.

After authenticated publication, deploy app.py with Python 3.11 and the existing requirements.txt on Streamlit Community Cloud. Keys belong only in hosting Secrets. Verify the reachable public endpoint in a no-login/private session, the complete manual-input flow where NASS data is absent, imagery/source dates, every page, and mobile layout. A tested local app is not proof of public deployment.


## GitHub publication follow-up — November 15

The newly selected GitHub connection now permits branch/blob writes; the earlier 403 block above is historical. Refreshed main b1e3f2a includes Person 2 tipping and climate-shift modules. Those are merged, the owner tipping page calls through engine.api, and API recommendation scoring now separates climate modes and bypasses baseline memoization for transient what-if contexts. A regression test verifies this isolation. Publishing targets p4-app; main is not overwritten. NASS-key and disabled-zone limitations remain. Final test and publication outcome are reported with the pushed commit.


Latest audit and host setup instructions: docs/notes/charvik.md, section "API, data and security audit". The provided NASS key is configured only in ignored local secrets; live NASS access timed out here, so authentication remains unverified. New safety fixes cover credential errors, source totals, currency, cache isolation, input checks, measurement climate context and provenance. No key is included in this handoff or repository.
