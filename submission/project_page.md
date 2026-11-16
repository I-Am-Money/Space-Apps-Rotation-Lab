# RotationLab project page text

Written for the team to paste into the Space Apps project page. **Nothing here has been submitted.** A team
member submits from the portal. No team member names, emails or photos, and no village name. Lines in
[square brackets] are for the team to fill in. Every number comes from `config/validation/results.csv`
(run 2026-11-15).

## Summary

RotationLab uses NASA data to show a US farmer how their climate is already changing, and which crop rotation
will strengthen their soil and hold up as it keeps changing, without losing money. Type an address, answer a few
questions, and get three rotation picks with their profit, bad-year risk, water use and a Soil Health Score,
plus the rainfall, heat or water level at which the best choice would change. We tested it against real county
yields and report the result as it came out: fair in rainfed counties, not validated in irrigated ones.

## Description

RotationLab is a free web app for crop rotation planning. This version covers the United States. A farmer types
an address or drops a pin, then confirms their current crops, water source and farm size. Three
example farms (Iowa, Nebraska and Texas) open a full result in one click. The example farms use real NASA
weather and USDA data for the place; their farm answers are examples chosen by the team, and the page says so.

**What it shows.** RotationLab pulls daily NASA POWER weather for the spot from 1981 on. A climate card
compares the last 20 years with 1981 to 2000: season rain, rain variability, heat days and the start of the
rainy season. Soil comes from USDA soil surveys, and county yields, prices and costs come from USDA
NASS and ERS where they are available. Where a value is missing the farmer enters it, and nothing is guessed.

**How it decides.** It runs every feasible 4-year rotation, with optional cover crops, on real weather years.
The crop science is published and simple: the FAO-56 daily soil water balance and the FAO-33 yield response to
water. There is no neural network, so every result can be traced back to its inputs. Each rotation gets an
average profit, a bad-year profit (the worst 10% of weather sequences), food energy, water use and a Soil
Health Score. The score is a 0 to 100 rule-based score from the NRCS soil health principles: soil cover,
living roots, diversity and legumes, residue carbon and less disturbance. It is not a soil test.

**What the farmer gets.** Three picks: Best for soil and climate (it must not lose money against the current
plan), Highest profit, and Best for your soil. Each shows its change from the current plan. A tipping-point
page ("What could change it") shows the rainfall, heat or water supply at which a different rotation becomes
the best one. The climate settings behind it (historical, recent years counted double, continuing trend) are
what-ifs, not forecasts. "What to check first" ranks which unknown is most worth measuring before deciding.

**How good it is.** We re-ran the model on past weather in 14 US counties across all 9 USDA farm regions and
compared it with USDA NASS county yields, holding out the latest 8 years of each record. That gave 31 county
and crop checks. The results are mixed:

- Mostly rainfed counties (22 checks): median held-out r is 0.42, ranging from -0.43 to 0.87. Seven checks are
  at or below zero. A small statistical correction, fitted on the earlier years only, raises the median to
  0.57 and cuts the typical miss from 0.89 to 0.52 tonnes per hectare.
- Mostly irrigated counties (9 checks: Georgia, Mississippi Delta, Arkansas, California rice): median held-out
  r is -0.04, and six of nine are at or below zero. The model tracks water stress, so it does not follow
  irrigated yields. **Irrigated areas are not validated.**
- One India district (Telangana) checked against ICRISAT district yields, held-out years 2010 to 2017: r is
  0.34 for jowar, 0.50 for bajra and 0.42 for pigeon pea. This check is in the repo only; the app is for US
  farms and shows the US checks.

Each r comes from only 8 held-out years, so it is rough, and county averages are not single fields. The app
shows the US tables on its "Can I trust this?" page. Anywhere without a passing local check, results carry a
"Not validated here" banner. Every value in the app carries a label: Observed, Estimated, Your input,
Assumption or Placeholder ("team to verify").

**Limits.** Results are modeled estimates for planning, not a guarantee of yield or profit and not a forecast.
Prices are fixed across weather years. The model has no flooding, pests, varieties or orchards, field zones
are not in this version, and Alaska, Hawaii and farms outside the US are not covered. Many settings, such as the Soil Health Score weights, are team choices still marked
"team to verify". The full list is in `LIMITATIONS.md`.

## NASA data

- **NASA POWER** daily point API (agroclimatology community): maximum, minimum and mean temperature, humidity,
  wind, precipitation and solar radiation, from 1981 to the latest year. It drives the water balance, the
  weather scenarios, the climate card and the validation. Solar radiation starts in 1984, so for 1981 to 1983
  crop water demand is worked out from temperature alone. POWER is a grid of about half a degree, not a field
  station.
- **NASA GIBS** map tiles: SMAP Level 4 root-zone soil moisture and MODIS Terra 16-day vegetation index (NDVI).
  They are shown on the map for context and are never model inputs.

NASA elevation data (SRTM / NASADEM) was planned for field zones. Field zones were not built, so it is not used.

NASA data use does not imply NASA endorsement.

## Other data

Sources, URLs and download dates are in `DATA_SOURCES.md`. In short:

- USDA NASS Quick Stats: county yields, prices received, crops grown and irrigated share. For the 14
  validation counties these were downloaded on 2026-11-15 through the public Quick Stats website export,
  because no API key was available.
- USDA NASS Cropland Data Layer (CropScape) and the US Census Bureau Geocoder: suggest the current crops and
  location from a US address. The farmer confirms every year.
- USDA NRCS Soil Data Access (SSURGO, with STATSGO as fallback) for US soil; ISRIC SoilGrids elsewhere.
- USDA ERS Commodity Costs and Returns and the ERS Farm Resource Regions county file: operating costs for
  9 field crops.
- USDA FoodData Central: food energy per kilogram of crop.
- FAO-56 crop coefficients and FAO-33 / FAO-66 yield response factors.
- USDA NRCS soil health principles, behind the Soil Health Score.
- US Census Bureau 2023 county gazetteer: validation site coordinates.
- ICRISAT District Level Database: India district yields for the India check (repo only).

## Use of AI

AI coding assistants wrote most of the code, tests and documentation while the team directed them: Claude Code
(Anthropic) for the simulation, tipping points, recommendations, US data, validation and docs, and OpenAI Codex
for the app shell, farm setup and site and data fetchers. The team chose what to build, set the modeling
rules, checked the results and approved every merge. Every code file starts with a line saying how AI was
used. This page and the slide text were drafted with Claude Code from the repo's own results and documents.

In the app, the sentence under each recommendation card is a fixed template filled in from that card's
numbers. An optional explanation written by Claude (`claude-sonnet-5-5`) appears only when the app has an API
key. Claude is sent the computed numbers only, and a guard rejects any reply containing a number or crop that
is not in the results, falling back to the template. The live app has no API key, so it shows the template only.

In the 30-second video every view of the app is a real screen recording. Any farmland shot at the start or end
that is not a screen recording was made with an AI video tool (Higgsfield) and carries a visible AI-generated
watermark. There are no people, voices or NASA branding.

No data was generated by AI. Weather, soil, yields, prices and costs come from the sources above or from the
farmer. Values the team has not checked against a source are marked "team to verify". Full details are in
`AI_USE.md`.

## Links

- Code: https://github.com/I-Am-Money/Space-Apps-Rotation-Lab [team to confirm the repo is public, and that
  showing this GitHub account name is acceptable]
- Live app (no login): https://space-apps-rotation-lab-production.up.railway.app (wake it right before submitting)
- 30-second demo video: [team to fill in; script in `submission/deck.md`]
- Slides: [team to fill in; text in `submission/deck.md`]
