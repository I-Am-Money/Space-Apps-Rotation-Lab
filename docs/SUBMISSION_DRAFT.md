# Submission draft: deck and project page (for the team to edit)

Draft by Person 3. **Nothing here has been submitted.** Only a team member submits, from the Space Apps portal.
Rules for the deck (A9): 7 slides or fewer, app screenshots only, no faces, voices or photos of people, no
names (team name only until the Local Lead confirms). Every number marked **TBD** must come from the final app
or `config/validation/results.csv`. Do not fill one in by hand.

---

## Deck (7 slides)

### Slide 1: Title and challenge
- **RotationLab**
- NASA Space Apps 2026: Field Shift, Adapting Farms with NASA Data
- "Which crop rotation will strengthen my soil and hold up as my climate keeps changing, without losing money?"
- Team: [team name, TBD]
- Visual: [screenshot: start screen with the three demo presets]

### Slide 2: The problem
- Farmers plan rotations from past habits, but their weather is already shifting.
- Rotations that build soil (legumes, cover crops, more variety) can look risky when money is tight.
- Farmers need a clear answer for their own field: what changes, what it costs, and when the answer would flip.
- Visual: [screenshot: questions panel (current crops, water, farm size)]

### Slide 3: How your climate is changing (real location)
- Pick one demo preset, e.g. the Story County, Iowa validation site, or a preset Person 4 sets.
- From NASA POWER at that spot: last 20 years vs 1981 to 2000.
  - Season rain: TBD
  - Rain variability: TBD
  - Heat days: TBD
  - Rainy-season start: TBD
- Visual: [screenshot: climate card, with its "data as of" date]

### Slide 4: Three recommendations and tradeoffs
- Best for soil and climate (never loses money vs the current plan), Highest profit, Best for your soil.
- Each shows its change vs the current plan: average profit, bad-year profit, water, Soil Health Score, food.
- Soil Health Score: rule-based, from NRCS soil health principles. Not a soil test.
- Plain-English explanation per pick, checked number by number against the results.
- Visual: [screenshot: three recommendation cards] and [screenshot: profit vs Soil Health Score chart]

### Slide 5: Tipping points
- At what rainfall, heat or water supply the best plan changes, with 10th to 90th percentile bands.
- Map of rainfall vs water supply colored by the winning rotation, with this farm's current setting marked.
- What to measure next: the question worth the most to answer (TBD from the app).
- Visual: [screenshot: tipping point curves and 2D map]

### Slide 6: How good is this? (validation)
- Hindcast in 12 US counties across 9 regions (Corn Belt, Eastern Corn Belt, Great Plains, Northern Plains,
  Southern Plains, Pacific Northwest, Northeast, Southeast, Delta) against USDA NASS county yields.
- Latest 8 years held out. Detrended Pearson r and MAE, with and without the linear bias correction.
  - Median held-out r: TBD (model) / TBD (corrected)
  - Median held-out MAE: TBD kg/ha (model) / TBD (corrected)
- Honest about limits: county averages, not fields. Irrigated counties agree less with a water-limited model.
- Visual: [screenshot: validation table and map on the "How good is this?" tab]

### Slide 7: NASA data used and what's next
- NASA POWER daily weather (drives the model and the climate card).
- NASA GIBS: SMAP soil moisture, MODIS NDVI (map context).
- SRTM/NASADEM elevation (only if field zones ship).
- Next (out of scope now): orchards and tree crops, intercropping, field-level validation, measured soil carbon,
  groundwater depletion, market price risk, SMS or offline access, full 3D zones.
- Visual: [screenshot: map with GIBS layers on]

---

## Project page text

### Summary (short)
RotationLab uses NASA data to show any farmer how their climate is already changing, and which crop rotation
will strengthen their soil and hold up as it keeps changing, without losing money. Drop a pin, answer a few
questions, and get three rotation picks with their profit, bad-year risk, water use and a Soil Health Score,
plus the rainfall, heat or water level at which the best choice would change.

### Description
RotationLab is a free web app for crop rotation planning. A farmer enters their current crops, water source
and farm size, then drops a pin anywhere on Earth. RotationLab pulls daily NASA POWER weather for that spot
since 1981 and shows how the last 20 years differ from 1981 to 2000.

It then tests every feasible 4-year rotation, with optional cover crops, on real weather years. It uses
published crop science: the FAO-56 daily soil water balance and the FAO-33 yield response to water. No neural
networks are involved, so every result can be traced back to its inputs. Each rotation gets an average
profit, a bad-year profit (the worst 10% of weather sequences), food calories, water use and a Soil Health
Score. The score is a 0 to 100 rule-based score built from the NRCS soil health principles: soil cover,
living roots, diversity and legumes, residue carbon, and less disturbance. It is not a soil test.

The farmer gets three picks: Best for soil and climate (never loses money against their current plan),
Highest profit, and Best for their soil. Sliders re-weight bad-year protection, water saving and soil. The
tipping-point view shows at what rainfall, heat or water supply the best plan changes. "What to measure next"
ranks which unknown is most worth testing. Each pick has a short plain-English explanation. Claude writes it
from the computed numbers only, and every number and crop name in it is checked against the results.

To show how far to trust it, RotationLab hindcasts county yields in 12 US counties across 9 regions against
USDA NASS records, holding out the latest 8 years. Results are shown with and without a small statistical
correction. Every value carries a badge (Observed, Estimated, Your input, Assumption), and places with no
local yield data say "Not validated here".

### NASA data
- NASA POWER daily point API (community AG): temperature, humidity, wind, precipitation and solar radiation,
  1981 to the latest year. Drives the water balance, scenarios, climate card and validation.
- NASA GIBS WMTS: SMAP L4 root-zone soil moisture and MODIS Terra NDVI 16-day layers, for map context.
- NASA SRTM / NASADEM 30 m elevation: field zones, only if the stretch feature ships (TBD).

### Other data
See `DATA_SOURCES.md`. In short: USDA NASS Quick Stats (county yields, prices, crops grown, irrigated share),
USDA NRCS Soil Data Access (SSURGO/STATSGO), ISRIC SoilGrids, USDA ERS Commodity Costs and Returns, FAO-56
and FAO-33/FAO-66 crop parameters, USDA NRCS soil health principles, US Census Bureau county gazetteer for
validation sites. Optional India validation from the ICRISAT District Level Database was used only in the
earlier India version.

### AI use
Claude and Claude Code (Anthropic) wrote most of the code, tests and documentation under the team's
direction. The team set the design and modeling rules, checked results and approved every merge. In the app,
Claude (`claude-sonnet-5-5`) writes the plain-English explanation for each recommendation. It sees only
computed numbers, and a guard rejects any reply with a number or crop that is not in the results, falling
back to a fixed template. No data was generated by AI. Unverified values are marked "team to verify". Full
details are in `AI_USE.md`.

### Links (fill in at submission)
- Public GitHub repo: TBD
- Streamlit app (no login): TBD. Wake the app right before submitting.
