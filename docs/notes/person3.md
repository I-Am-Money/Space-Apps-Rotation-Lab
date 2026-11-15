# Notes from Person 3 (Feature 4: US data, trust and submission)

Other owners: add your own `docs/notes/person<N>.md` with the same three headings. Person 3 compiles these
into LIMITATIONS.md, DATA_SOURCES.md and AI_USE.md. No names, emails or photos of team members.

## For LIMITATIONS.md

- NASS: no `NASS_API_KEY` in the build environment (2026-11-15). The 14 validation counties were downloaded
  without a key through the public Quick Stats website spreadsheet export and cached in `data/precache/nass/`.
  That export is not a documented API and was rate limited after about 50 downloads. The app does not call it
  unless `NASS_PUBLIC_CSV=1`. Other US pins without a key show "NASS data unavailable" and ask the farmer.
- US validation ran on real NASS county yields (31 county and crop pairs). Mostly rainfed: median held-out
  r 0.42 (22 pairs, 7 at or below zero). Mostly irrigated: median -0.04 (9 pairs). See LIMITATIONS item 21.
- The key-based API path has still never been run live. Class, use and practice names were checked against the
  website export for the 14 counties.
- Suppressed county data falls back to the state average, labelled. The hindcast never uses state numbers.
- Default yield = mean of the latest 5 published county yields (team choice, range 3 to 10).
- ERS costs: "operating costs" basis (seed, fertilizer, chemicals, fuel, repairs, custom work, irrigation
  water, interest). Land, unpaid labor and machinery capital recovery are left out on purpose. Latest year
  in the 2026-11-15 download is 2025.
- ERS covers 9 field crops only (corn, soybeans, wheat, sorghum, barley, oats, cotton, rice, peanuts). Every
  other crop needs a cost from the farmer (R2).
- ERS wheat is not split into winter and spring, so both use the same wheat cost. Rice uses ERS rice areas,
  not Farm Resource Regions, so rice uses the ERS U.S. total. A crop that ERS does not survey in a region uses
  the U.S. total, labelled.
- County to region mapping is the ERS reglink.xls file (3,112 counties). Counties created or renamed after it
  (for example Connecticut's 2022 planning regions) are not mapped and fall back to the U.S. total.
- "Mostly irrigated" = irrigated acres at least 50% of cropland acres (team choice, range 30 to 70%).
- Orchard and tree crops are matched by name from a fixed list in `config/assumptions/us_data.yaml`.

## For DATA_SOURCES.md

- USDA ERS Commodity Costs and Returns, 9 crop CSVs, https://www.ers.usda.gov/data-products/commodity-costs-and-returns , downloaded 2026-11-15, cached in `data/precache/costs/`.
- USDA ERS Farm Resource Regions county file, https://www.ers.usda.gov/sites/default/files/images/reglink.xls , downloaded 2026-11-15, cached in `data/precache/geo/`.
- US Census 2023 Gazetteer counties (re-downloaded 2026-11-15 for Warren County KY and Colusa County CA).
- USDA NASS Quick Stats, https://quickstats.nass.usda.gov , website spreadsheet export (no key), downloaded 2026-11-15 for the 14 validation counties, cached in `data/precache/nass/`.

## For AI_USE.md

- Claude Code wrote `engine/fetch_nass.py`, `engine/fetch_ers.py`, `engine/us_rules.py`, `ui/trust.py`,
  the hindcast and correction wiring, their tests, and these docs, under Person 3's direction.
- The ERS numbers come from ERS files. Tests that need NASS use synthetic records that are labelled as
  synthetic in the test file. No AI-generated values are used as data.
