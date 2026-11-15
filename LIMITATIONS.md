# Limitations

RotationLab gives modeled estimates for planning. It does not guarantee yield or profit and it is not a
forecast. These limits are shown in the app and listed here (Build Spec v4, R22). Teammates: add anything you
log to the "Logged by the team" section, or tell Person 3.

## Out of scope in this version (A10)

1. Orchards and tree crops ("not supported yet"). Alaska and Hawaii are not supported in this version.
2. Intercropping.
3. Field-level validation. Validation compares against county averages, not single fields.
4. Measured soil carbon. The Soil Health Score is a rule-based score, not a soil test.
5. Groundwater depletion over many years.
6. Market price risk. Prices are fixed across weather scenarios.
7. SMS or offline access.
8. Field zones (splitting one farm into slope and low-spot zones). They are not in this version, so there is no Field zones page.

## Model and data limits (v4)

9. **Weather is a grid estimate.** NASA POWER is about a 0.5 degree grid, not a field station. Solar
   radiation starts in 1984, so the usable record is 1984 to 2025 and no values are invented for 1981 to 1983.
10. **Climate shift settings are what-ifs.** "Recent" and "Continuing trend" reweight or shift real weather
    years. They are not climate projections.
11. **Soil Health Score.** The NRCS principles (cover, living roots, diversity, minimal disturbance) are real.
    The weights, point values, harvest indices, residue carbon fraction and cover crop biomass that turn them
    into a 0 to 100 number are team choices. Many are marked "team to verify" with a Placeholder badge (see
    `config/assumptions.yaml`, section `soil_score`). If yields are missing, residue carbon is left out instead
    of guessed. Field history adjustments (erosion, waterlogging, salinity) shift every plan by the same amount.
12. **Hindcast model.** Validation uses the team's single-season yield function
    (`engine.yieldmodel.season_relative_yield`): the v4 FAO-56 water balance and FAO-33 Ky with the crop library
    in `config/assumptions.yaml`, the crop grown every year, rainfed, with a default soil water capacity. It has
    no pests, varieties or management changes. Agreement in mostly irrigated counties (Georgia, Mississippi Delta,
    Arkansas and California rice) is expected to be weaker, and that is reported, not hidden. The older stand-in
    model (`config/validation/standin_crops.yaml`) is used only if that function is missing, and its rows are
    badged "stand-in".
13. **Validation design.** Both series are detrended with lines fitted on training years only. The latest 8
    years are held out from the trend, the potential yield (Ym) and the correction. Pearson r on 8 held-out
    years is noisy. County yields average many farms. Agreement with county yields does not prove the model is
    right for a given field.
14. **Bias correction.** The linear correction (season rain, heat days, year) is fitted per county and crop on
    training years only, and only with at least 10 training years. It can soak up trend and bias, but it is a
    statistical fix, not crop science, and it may not carry over to years unlike the training years.
15. **Explanations.** Claude writes the explanation text from computed numbers only. The guard checks numbers
    and crop names, not wording. A reply that passes the guard can still word things loosely. Without an API key
    the fixed template is used.

## US data limits (Feature 4)

16. **Default yields and prices.** Default yield is the mean of the latest 5 published NASS county yields
    (team choice). If NASS withholds the county value, the state average is used and labelled "State
    average". Prices are the latest marketing-year price received in the state, or the national price
    (labelled). The hindcast never uses state numbers in place of county yields.
17. **Costs.** USDA ERS costs are "operating costs" for the county's Farm Resource Region (latest year 2025).
    They leave out land rent, unpaid labor and machinery capital recovery, because those are about the same
    whichever rotation is picked. ERS covers only 9 field crops, so any other crop needs your own cost before
    money numbers show. ERS does not split wheat into winter and spring. Rice uses the ERS U.S. average,
    because ERS reports rice by its own rice areas, not by Farm Resource Region. A crop that ERS does not survey
    in your region uses the U.S. average, labelled.
18. **County to region map.** This uses the ERS county file (3,112 counties). Counties created after it, such as
    the Connecticut planning regions from 2022, are not mapped and use the U.S. average.
19. **Irrigated default.** A county is "mostly irrigated" when Census irrigated acres are at least half of its
    cropland acres. The 50% threshold is a team choice. When the share is unknown, the app asks.
20. **Orchards** are recognized by name from a fixed list (`config/assumptions/us_data.yaml`), not by NASS category.

## US validation results and how the NASS data was obtained

21. **US validation results (run 2026-11-15) are mixed.** The hindcast ran on real USDA NASS county yields for
    all 14 validation counties: 31 county and crop pairs gave results, and Sumner County, Kansas sorghum did not
    (17 overlapping years, 20 needed). Numbers are in `config/validation/results.csv` and on the "How good is
    this?" page, exactly as they came out.
    - Mostly rainfed counties (22 pairs): held-out r runs from -0.43 to 0.87, median 0.42. It is 0.4 or better
      in 12 pairs and below zero in 7. With the correction the median is 0.57 and 2 pairs are below zero.
    - Mostly irrigated counties (9 pairs: Georgia, Mississippi Delta, Arkansas, California rice): held-out r
      runs from -0.68 to 0.42, median -0.04. The water-limited model does not track irrigated yields. Treat
      results in irrigated areas as unvalidated.
    - The correction lowered the average error (MAE) in 22 of 31 pairs and raised held-out r in 19. It made
      things worse in the rest.
    - Each held-out r comes from only 8 years, so a single odd year can move it a lot. Example: the model has
      no flooding or waterlogging, so it misses the 1993 Midwest flood year (Story County, Iowa corn was about
      4,900 kg/ha; the model gave its maximum).
    - In Lancaster County (Nebraska), Sumner County (Kansas) and Lubbock County (Texas) the comparison uses
      NASS non-irrigated yields. NASS stopped publishing those between 2007 and 2018, so the held-out years
      there are older (for example 2000 to 2007 for Kansas wheat), not the latest 8 calendar years.
22. **NASS data came from the Quick Stats website, not the API (no key).** No `NASS_API_KEY` was available on
    2026-11-15. The same Quick Stats records were downloaded through the public Quick Stats website's
    spreadsheet export (https://quickstats.nass.usda.gov), which needs no key, and saved in
    `data/precache/nass/`. This export is not a documented API and could change or be rate limited (it refused
    requests for a while after about 50 downloads). The running app does not call it unless `NASS_PUBLIC_CSV=1`
    is set. So: the 14 validation counties have real NASS yields, prices, crops grown and irrigated share
    cached; any other US pin without a key still shows "NASS data unavailable" and
    asks the farmer for yield and price. Nothing is filled in. Crop class, use and practice are read out of the
    export's "Data Item" text; this was checked against every yield item in the 14 counties. The key-based API
    path itself has still never been run live (team to verify once a key exists).

## Trust page and India check

23. **Trust page data path.** The "How good is this?" page reads the validation table through
    `api.validation_summary()`, which returns the saved `config/validation/results.csv`. The app never re-runs
    the hindcast or downloads yields while a farmer is using it, so the table is as of the last run (2026-11-15).
24. **India validation pack: one district.** The only India check is Nalgonda district, Telangana (ICRISAT/TCI
    District Level Database, which ends in 2017). It covers jowar, bajra and pigeon pea, rainfed, with the team's
    yield function. Training years are 1981 to 2009, and the held-out years are 2010 to 2017. Results are mixed
    and are shown as they came out (`config/validation/results.csv`). Held-out r ranges from 0.34 to 0.50 without
    the correction and from 0.45 to 0.57 with it. The correction made the average error larger for jowar and bajra
    and slightly smaller for pigeon pea. District boundaries changed in 2016, and the yields come from the older,
    larger district. Rice is left out because district rice mixes irrigated and rainfed fields. Pins outside the
    US count as "validated" only within 0.5 degrees of this district's centroid (team choice).

## Logged by the team

- **Example farms.** The three example farms on the start screen (Story County, Iowa; Lancaster County, Nebraska;
  Lubbock County, Texas) use real NASA weather, USDA soil and USDA county yields, prices and costs for the place.
  Their farm answers (the current crops, the size, rain only) are examples chosen by the team, not a real farm's
  records, and the page says so. They are listed with their sources in `config/assumptions/setup.yaml`.
- **Sentence under each recommendation card.** It is a fixed sentence filled in from that card's own numbers, in
  the units the farmer chose. The optional Claude explanation is a separate button and is only shown when an API
  key is configured.
- **Tipping points map.** Each square re-runs the search for the best plan. Where two plans are nearly tied,
  neighbouring squares can show different winners, so a single odd square is not a finding on its own.
- **NASA map layers.** SMAP soil moisture and MODIS vegetation index tiles are shown for context and need an
  internet connection. They are never model inputs.

## Earlier India version (v3, Telangana)

These apply to the earlier India build, which is still reachable from the start screen.

1. **Planning estimates.** The app supports farmer and local-expert judgment and does not guarantee yield or profit. It is not a forecast.
2. **Scope.** Nalgonda, kharif, one crop per year over four years. No rabi, intercropping, pest model, varietal model or market-risk model.
3. **Spatial resolution.** NASA POWER is a regional grid estimate at a district centroid, not a field measurement. The centroid is calculated from an OpenStreetMap district boundary. Upstream points are approximate sub-basin anchors, not a catchment-weighted rainfall integral.
4. **Weather period.** Solar-radiation gaps make the usable record 1984-2025. No invented values fill 1981-1983. Bootstrap plans resample real years with seed 42; overlapping historical blocks are dependent, and rare droughts outside the record may be missed.
5. **Onset and calendar.** Onset is the first five-day window after 1 June with at least 25 mm, without a following ten-day spell totaling under 5 mm in the next 30 days. These are planning assumptions, not official IMD dates. No clean onset by 1 September is flagged and that date is used. Sowing shifts from the crop calendar by onset relative to the record median, capped to mature within the year. Delay what-ifs remove early monsoon rain rather than moving it.
6. **Rice water.** Canal supply is an upstream-rain proxy; actual releases depend on reservoir operations and allocations. Wells use a capped local-rain recharge proxy. Supplies are not measured farm capacities. Canal plus well is the default planning scenario, not a confirmed observation of this farm. There is no multi-year groundwater depletion or reservoir simulation.
7. **Soil.** Black-soil type is local input. Its water-capacity range comes from literature and is not a farm soil test. SoilGrids is a separate modeled district-point estimate. Paddy seepage, curve numbers, initial soil moisture and fallow evaporation need local calibration.
8. **Crops.** FAO-style parameters, stage lengths, Ky, heat thresholds, rotation benefits, late-sowing penalties and nitrogen credits include assumptions needing agronomic review. Potential yields are derived P90 statistics, not farm observations. Heat uses crop-specific flowering windows and a toggleable 1% penalty per hot day. The late-sowing penalty is an unsourced 0.3% per day. Year 1 follows the farm's previous crop (rice); the sensitivity view removes rotation benefits and nitrogen savings.
9. **District validation.** ICRISAT/TCI apportioned Nalgonda covers an older, larger district and aggregates farms. Rice yields mix irrigation regimes and seasons; weather uses today's district point. The source labels historical rows Telangana. Crop selection uses 52 positive-yield years for bajra and kharif sorghum; zeros/missing records are not invented yields. Ragi's 17 years are not enough to make it a selected millet here. Bajra is exactly 500 kg/ha in both 2014 and 2015 in the archived source; those values are retained, not silently corrected.
10. **Hold-out.** The latest eight overlapping yield years are excluded from potential-yield and trend estimation. Held-out correlation and error are reported, but observational data, a simple model and a small sample cannot establish causal validity.
11. **Cost estimates.** Rice and pigeon-pea budgets scale official Telangana A2+FL 2020-21 cultivation surveys with national 2026-27/2020-21 unit-cost ratios. Millet budgets multiply national A2+FL unit costs by district potential yields. Scaling and proxies are modeling assumptions, not current farm budgets; rankings can change materially with local costs. A2+FL already includes irrigation. No separate water charge is deducted. Nitrogen savings use a urea-equivalent price and assumed credit.
12. **Economics.** MSPs and budgets are fixed across scenarios; procurement access and actual sale prices are not guaranteed. Rice district yields represent milled rice; sales convert them to paddy using 0.66 before applying paddy MSP. Plan profit is an undiscounted four-year sum; no byproduct income, land opportunity cost or extra subsidies are added.
13. **Preferences.** Risk mixes mean and worst-10% plan profit. The water-saving value defaults to Rs 5/m3 (50 Rs/mm/ha), is editable and stays fixed in sweeps. It is a preference, not a bill or market tariff. Worst 10% means complete weather sequences of the plan.
14. **Boundary approximation and plan rules.** Of 256 four-year combinations, the three non-rice monocultures are comparison-only (team rule). Tipping sweeps compare reference plans and leading offered candidates at each rice-year count, rather than all 253 offered rotations. Interactive mode uses 150 sequences and full mode 500. Rice-majority boundaries are interpolated between tested water levels. Bootstrap intervals treat a missing boundary as above the tested range and report its frequency. Rice years describe a rotation, not a parcel allocation.
15. **Information value.** EVPI is an upper bound under the stated uniform uncertainty range and risk/water preferences, not the value of a noisy real test. Unknown measurement quotes remain unknown and cannot support a cost/benefit verdict. Supply sweeps scale entered capacities in their current source ratio.
16. **Land split.** Outcomes share the same weather and combine profit before computing the lower tail. The model assumes equal per-acre management and supply, not water transfers, economies of scale or new infrastructure between parcels.
17. **Soil cover and carbon.** Soil cover is a bounded per-crop score with carry-over, not measured residue or a yield-derived measurement. Soil carbon is shown as a direction only. Nitrogen is a fixed credit, not a dynamic soil pool.
18. **Connectivity and privacy.** Calculations and the default district-outline map work from bundled files. Online basemaps/GIBS tiles and optional external fonts need connectivity. Farm uploads keep only anonymous crop/year/area/harvest/cost fields in the current session. Optional Claude explanations send computed totals only after opt-in; results are not persisted to disk.
19. **Deployment verification.** Offline calculations and screen flows are tested. Automated visual browser review was unavailable in the task environment. A public deployment must still be opened and checked in its hosting environment; a local health check is not proof of public availability.
