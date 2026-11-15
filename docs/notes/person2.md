# Notes from Person 2 (Feature 2: simulation and tipping points)

Input for the team's LIMITATIONS.md, DATA_SOURCES.md and AI_USE.md, in the format asked for in
`docs/notes/person3.md`. No names, emails or photos of team members.

## What was built

| File | State |
|---|---|
| `config/assumptions/simulation.yaml` | Working. Every Feature 2 setting: rules, runoff, fallow, 20 crops, 4 cover crops. Each leaf has value, range, unit, source and badge. |
| `engine/crops.py` (v4 section) | Working. Crop library, climate normals, planting calendar, climate fit, calories per kg, residue. |
| `engine/et0.py` | Working. FAO-56 Penman-Monteith daily, Hargreaves when inputs are missing. |
| `engine/waterbalance.py` (v4 section) | Working. Continuous daily root-zone balance over the whole 4-year plan, compiled kernel. |
| `engine/yieldmodel.py` (v4 section) | Working. FAO-33 yield response, heat penalty toggle, potential yield, single-season function for hindcasts. |
| `engine/scenarios.py` (v4 section) | Working. Historical 4-year blocks, 500 bootstrap plans (seed 42), named stress tests labeled with real years. |
| `engine/simulate.py` | Working. `simulate()`, `simulate_many()`, and the `what_if()` block. |
| `engine/climate_shift.py` | Working. Historical, Recent, Continuing trend (R8). |
| `engine/tipping.py`, `ui/tipping.py` | Working. Curves with bands, 2D map, plain Streamlit page (R18). |

The v3 code above each "v4 section" is untouched and still passes its own tests.

## For LIMITATIONS.md

Simulation
- Planting and harvest days are the same in every scenario. They come from the site's long-term day-of-year temperature
  normals, not from each year's weather, so a late spring does not delay planting.
- Planting rules (planting temperature, growing temperature limits, winter wheat vernalization and maturity), the heat
  thresholds, the flowering window lengths and the harvest index are team rules of thumb. None was read in a primary
  source. Each is marked "team to verify" in `simulation.yaml`.
- Root depth is at its maximum from planting day (FAO-56 Table 22 gives a range; the middle is used). Young crops are
  therefore credited with more soil water than they can reach.
- Rice is simulated as an upland crop with full irrigation demand. Ponding, puddling and percolation losses of paddy
  fields are not modeled.
- Irrigation is applied with no losses: each day just enough to avoid stress, until the year's supply is used up.
  Irrigation efficiency, application timing rules and the cost of water are not modeled.
- The yearly water supply resets on 1 January. A dry year's supply is a straight line between the farmer's normal-year
  and dry-year answers, by that year's rainfall. A "dry year" is a 1-in-10 dry year (team choice).
- Runoff uses one SCS curve number for cropped days and one for fallow days per soil group. Slope, residue cover and
  rainfall intensity are not modeled. Snow is treated as rain on the day it falls.
- Cover crops use stand-in crop coefficients (winter wheat Kc from FAO-56 Table 12), because FAO-56 has no cover-crop
  rows. Their benefit to soil water (less evaporation, more infiltration) is not modeled; only their water use is.
- Yield response is the seasonal FAO-33 form (one Ky per crop), not the stage-by-stage form. Pests, disease, nutrients,
  frost damage, waterlogging and lodging are not modeled.
- Heat penalty: 1% of yield per day at or above the crop's heat threshold during the flowering window (carried over
  from the v3 spec, team to verify).
- Potential yield from a "typical yield" (the farmer's or the county's) is the typical yield divided by the model's
  median share of potential for that crop on that farm (never divided by less than 0.25). This makes a typical year
  reproduce the typical yield; it also means the same typical yield implies a lower potential on an irrigated farm.
- A crop with no yield number (no farmer entry and no county number) is reported as a share of potential only; its
  yield in kg is "not a number" and it is listed in `SimResult.missing_yield`. Nothing is filled in.
- Double crops are simulated, but Feature 3's enumeration uses one crop per plan year.
- Calories per kg are filled only for crops read from USDA FoodData Central on 2026-11-15 (see below): maize,
  soybean, winter wheat, spring wheat, barley, sorghum, rice, chickpea, lentil and potato. Not read yet, so empty and
  not counted: oats, pearl millet, dry bean, pea and pigeonpea. Peanut and sunflower have a value on record but are
  not counted, and canola and sugar beet are counted as zero, because the edible share of the harvested product was
  not verified. Cotton is a fibre crop and counts as zero. A plan that grows one of these crops shows fewer food
  calories than it really produces, so the "most food" pick is biased against them.
- Where this file has no calorie value for a crop, the recommendation engine falls back to its own table in
  `config/assumptions/recommend.yaml`. That table has recalled, unverified values for pearl millet (3,610 kcal per
  kg) and peanut (5,670, for shelled kernels but applied to in-shell yield), so those two crops are counted with
  placeholder values; the other empty crops count as zero.

Climate shift (R8). All three modes are what-ifs, not forecasts.
- Recent: the 500 bootstrap plans are drawn again with the last 20 calendar years of the record twice as likely.
  This is the same real years, picked more often. It is not a projection.
- Continuing trend: a straight line is fitted to the record's yearly rainfall, yearly mean daily maximum temperature
  and yearly reference evapotranspiration. Every real year is moved to the line's level 10 years after the record
  ends. The line is fitted whether or not the trend is statistically clear, and no significance test is shown. A
  year's rain is never scaled outside 0.5x to 1.5x, its ET0 never outside 0.8x to 1.25x (team guards).
- The trend in NASA POWER rainfall can reflect changes in the underlying reanalysis as well as the climate.
- Minimum temperature, planting dates and season lengths do not move with either mode.
- Historical 4-year blocks and stress tests cannot be redrawn, so in Recent mode they are re-weighted instead.

Tipping points (R18). What-if changes to real weather years, not forecasts.
- Rainfall what-if: every day's rain times a factor. The number of rainy days and their timing do not change.
- Heat what-if: degrees added to every day's maximum temperature. It changes the count of hot days at flowering only.
  The effect of heat on evapotranspiration is set to 0 until a value is verified (`heat_shift_et0_pct_per_c`), so
  the heat curve understates the damage of a hotter climate.
- Water what-if on a rain-fed farm ("what if you had 100 mm of irrigation") counts the yield gain but not the cost of
  getting the water, and assumes the same amount in dry years.
- Potential yields and planting dates stay those of the farm today at every what-if point.
- The winner away from the farm's current setting is searched among rotations of at most 4 crops (the current
  plan's, the three picks', then the most profitable others). It uses all 500 weather plans when that is expected to
  take no more than about 15 seconds; otherwise the first 100, with a short time budget fewer (never fewer than 40)
  and then a coarser map. The page says when it did. The curves and their bands always use all 500 plans.
- Two plans that are nearly tied can swap places when fewer weather plans are used. So the same search is also run
  at the farm's current setting, and a change of plan is shown only where the search picks differently than it does
  there. A real but small change that falls inside that noise is not shown.
- The same crops in the same order, started in a different year, count as one plan on the map and the curves. In
  the search they are simulated once and share the result with the plan years renumbered. That is exact for the
  bootstrap plans, whose four years are drawn independently; it is not used for blocks of consecutive real years.
- The band on a curve is the 10th to 90th percentile across weather plans of one plan's result. The range given for
  a tipping point is the 10th to 90th percentile of where the two plans' averages are equal when the weather plans
  are drawn again (200 draws, seed 42). When the winner changes because of the risk or soil settings rather than the
  average, only the two grid values it lies between are reported.
- If the recommendation engine cannot be used (missing price or cost, an error), the page ranks rotations itself by
  average profit, or by share of potential yield when a price or cost is missing, and says so. That ranking ignores
  soil health and bad-year protection.
- Profit on the curves is yield x price - cost with the same prices and costs as Feature 3 (farmer's entries, else
  the county numbers), fixed across scenarios and what-ifs. Only the first crop of each plan year is counted.

## For DATA_SOURCES.md

- NASA POWER daily (through `engine/fetch_power.py`): maximum and minimum temperature, humidity, wind, solar
  radiation, precipitation, 1981 to the latest full year. Used for scenarios, climate normals, ET0 and the trend fit.
- FAO Irrigation and Drainage Paper 56 (Allen et al. 1998), re-read from the FAO web copy on 2026-11-15:
  Table 11 (crop stage lengths) and Table 12 (Kc) at https://www.fao.org/4/x0490e/x0490e0b.htm ;
  Table 22 (root depth and depletion fraction p) at https://www.fao.org/4/x0490e/x0490e0e.htm ;
  chapter 4 Example 18 for the ET0 test.
- FAO Irrigation and Drainage Paper 66 (Steduto et al. 2012), Table 1, "Seasonal Ky values from FAO I&D Paper
  No. 33", at https://www.fao.org/4/i2800e/i2800e02.pdf , read 2026-11-15.
- USDA NRCS National Engineering Handbook Part 630, chapter 9, Table 9-1 (runoff curve numbers), read 2026-11-14 at
  https://irrigationtoolbox.com/NEH/Part630_Hydrology/H_210_630_09.pdf .
- USDA FoodData Central, SR Legacy, read from the FDC API on 2026-11-15 (https://fdc.nal.usda.gov): energy per
  100 g. Each value in `simulation.yaml` names the food description and its FDC ID.
- Not from a source (team rules of thumb, each marked "team to verify" in `simulation.yaml`): planting and growing
  temperatures, heat thresholds, flowering window, harvest index, fallow evaporation settings, cover crop Kc.

## For AI_USE.md

Claude Code (Anthropic) wrote the Feature 2 code, its tests and its settings file under the team's direction. The
team member directing it reviewed the results and made the decisions; they did not hand-write code. Crop parameters
were read by the AI from the FAO and USDA pages listed above and each carries its table reference; values the AI
could not read in a primary source are marked "team to verify" instead of being presented as sourced. No AI model
runs inside Feature 2 at run time: the simulation, climate modes and tipping points are plain numerical code.

## Wiring notes for the other owners

- `engine.api.tipping_points(site, inputs, sliders)` can be `return engine.tipping.tipping_points(site, inputs, sliders)`.
  The result is a dict with the A5 parts (`rainfall_curve`, `heat_curve`, `water_curve`, `map_2d`, `bands`) plus
  `headlines`, `notes`, `method`, `climate`, `metric`, `badges` and `example: False`.
- Page: `ui.tipping.render(site, inputs, sliders)`. With no arguments it reads `site`, `inputs` and `sliders` from
  `st.session_state`. It keeps its result in `st.session_state["_tipping_result"]` until an input changes.
- Climate setting in recommendations: build the scenario set with
  `engine.climate_shift.scenarios_for(site, sliders["climate_shift"])` and pass it as `scenarios`, or wrap the call in
  `with engine.climate_shift.use(mode):`. Recent and trend sets have equal weights, so plain averages are right.
- The tipping search asks for the winner with `engine.api.recommend(site, inputs, sliders)` once that is the v4
  function. Until then it calls `engine.optimize.recommend_picks` directly (the same transitional step Feature 3
  takes to reach `simulate()`), and the result's `method.winner_source` says which one was used.
- Inside `engine.simulate.what_if(...)` every `simulate()` call runs under that what-if. A cache that stores
  recommendation results across calls must include `engine.simulate.current_what_if()` in its key.
- Speed: a new farm's tipping analysis is 57 what-if points, each a recommendation over a short list of crops. With
  four crops it took about 15 seconds on the build machine (4 cores), and about 7 seconds for a two-crop farm using
  all 500 weather plans; expect longer on a small cloud machine, where the time budget (40 seconds) makes it use
  fewer weather plans and then a coarser map. Pre-cache it for the demo
  presets.
- Speed for Feature 3 (optional, one line): wrapping the recommendation call in
  `with engine.simulate.what_if(share_shifts=True):` simulates each rotation once for all of its starting years.
  Measured on the build machine with six crops (1,296 rotations): 6.5 seconds without it, 1.9 seconds with it, the
  same rotations picked, sometimes listed from a different starting year. It is off unless asked for, so Feature 3's
  results are unchanged today. It applies only to the 500 bootstrap plans.

## Tipping Points page: names, colors and summary line (after the 5 PM audit)

- A plan is written in the same year order as on the Recommendations page (the farm's current plan keeps its own
  order). Before this, the same rotation could read "Cotton > Cotton > Cotton > Winter wheat" on this page and
  "Cotton, Cotton, Winter wheat, Cotton" on Recommendations. The curves now simulate that same year order.
- One color per plan across the map and the three charts: green is the best plan today, grey is the current plan.
- When no single change (rainfall, heat or water) moves the best plan but some rainfall-and-water combinations
  on the map do, the summary line now says so and counts them, instead of saying the plan never changes.
- Display name of maize is "Corn" (US-first app). The crop id stays `maize`.

## Example farms: tipping results worked out ahead of time

- `engine/tipping_precache.py` saves the tipping result of each rain-fed example farm (all 500 weather plans at every
  what-if point) to `data/precache/tipping/<name>.json`. The Tipping Points page uses it only when the hash of
  every `engine/*.py` and `config/assumptions/*.yaml` file and the farm's key (place, full-year weather totals,
  soil, county defaults, answers, sliders) both match. Otherwise it computes live, as before.
- Why: on a slow or busy machine the live search drops to 100 weather plans and Nebraska's rainfall tipping point
  moved from 0.75x to 0.85x. The saved result makes the example farms open in about a second with the same
  numbers everywhere.
- After any change to the engine or the assumptions, run `python -m engine.tipping_precache` (about 30 seconds)
  and commit the three files. If nobody does, nothing breaks: the page computes live.
