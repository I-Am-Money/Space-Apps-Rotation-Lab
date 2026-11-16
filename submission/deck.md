# RotationLab deck text (7 slides) and 30-second video script

Written for the team to paste into the slide tool. **Nothing here has been submitted.** A team member submits
from the Space Apps portal.

Rules followed (see `CHECKLIST.md`):

- 7 slides, counting the title slide. Do not add an eighth.
- App screenshots only. No people, faces, voices, photos or other likeness. No team member names, no emails,
  no village name.
- Every number comes from `config/validation/results.csv` (run 2026-11-15). Slides 3 to 5 carry no numbers in
  the text on purpose: their numbers are whatever the app shows in the screenshot for the example farm.
- Lines in [square brackets] are for the team to fill in or confirm. They are not facts.

Screenshots: `assets/screens/` still holds the screens of the earlier India build. Take new ones from the
current app (start screen, "Your climate" tab, "2. Best crop plans", "3. What could change it", "Can I trust this?") before building
the slides.

---

## Slide 1: Title

**RotationLab**

Which crop rotation will strengthen my soil and hold up as my climate keeps changing, without losing money?

- NASA Space Apps 2026. Challenge: Field Shift: Adapting Farms with NASA Data
- Team: MACS
- Team members: [team to confirm with Local Lead; see the open decision in `CHECKLIST.md`]

Visual: [screenshot: start screen with the three example farms]

## Slide 2: The problem

- Farmers plan rotations from habit, but their weather is already shifting.
- Rotations that build soil (legumes, cover crops, more variety) can look risky when money is tight.
- A farmer needs an answer for their own field: what changes, what it costs, and when the answer would flip.

Visual: [screenshot: farm setup page (current crops, water, farm size, pin on the map)]

## Slide 3: Your own climate, from NASA data

- Type a US address or drop a pin, or open an example farm in one click. This version covers the United States.
- RotationLab pulls daily NASA POWER weather for that spot from 1981 on.
- The climate card compares the last 20 years with 1981 to 2000: season rain, rain variability, heat days and
  the start of the rainy season.
- Soil, county yields, prices and costs fill in from USDA data. Every value carries a label:
  Observed, Estimated, Your input, Assumption or Placeholder.

Visual: [screenshot: climate card for an example farm, with its "data as of" date]

## Slide 4: Three rotation picks and their tradeoffs

- Every 4-year rotation is run through a daily soil water balance (FAO-56) and a yield response to water
  (FAO-33) on real weather years. No neural network: each result can be traced to its inputs.
- Three picks: Best for soil and climate (must not lose money against the current plan), Highest profit, and
  Best for your soil.
- Each pick shows the change from the current plan: average profit, bad-year profit, water, food energy and
  a Soil Health Score.
- The Soil Health Score is rule-based, from NRCS soil health principles. It is not a soil test.

Visual: [screenshot: the three recommendation cards]

## Slide 5: When would the answer change?

- Tipping points: the rainfall, heat or water supply at which a different rotation becomes the best one.
- Climate settings (historical, recent years counted double, continuing trend) are what-ifs, not forecasts.
- What to check first: which unknown (water supply, soil water capacity) is most worth measuring before
  deciding.

Visual: [screenshot: tipping point charts and the rainfall by water supply map]

## Slide 6: Can I trust this? Mixed, and we show it

We re-ran the model on past NASA weather in 14 US counties across all 9 USDA farm regions and compared it
with USDA NASS county yields. The latest 8 years of each record were held out. 31 county and crop checks.

| | Checks | Median held-out r | At or below zero |
|---|---|---|---|
| Mostly rainfed counties | 22 | 0.42 (0.57 with correction) | 7 (2 with correction) |
| Mostly irrigated counties | 9 | -0.04 | 6 |

- Rainfed: r runs from -0.43 to 0.87. Typical miss 0.89 t/ha, or 0.52 t/ha with the correction.
- **Irrigated counties are not validated.** The model tracks water stress, so it does not follow irrigated
  yields (Georgia, Mississippi Delta, Arkansas, California rice).
- Each r comes from only 8 years, so it is rough. County averages are not single fields.
- Anywhere without a passing local check, the app says "Not validated here".

Visual: [screenshot: validation tables and site map on the "Can I trust this?" page]

## Slide 7: NASA data, AI use, limits and what's next

- **NASA data:** POWER daily weather (drives the model, the climate card and the validation). GIBS map layers
  (SMAP root-zone soil moisture, MODIS vegetation index) for map context only.
- **Other data:** USDA NASS, ERS, NRCS soil and FoodData Central; ISRIC SoilGrids; FAO crop parameters.
- **AI use:** AI coding assistants (Claude Code and OpenAI Codex) wrote most of the code under the team's
  direction. In the app, an optional Claude explanation is checked number by number against the results.
  AI made up no data.
- **Limits:** modeled estimates for planning, not a guarantee of yield or profit. Prices are fixed. No
  flooding, pests or orchards. US farms only. Many settings are still marked "team to verify".
- **Next:** field-level validation, irrigated crops, field zones, measured soil carbon, price risk.

Visual: [screenshot: map with a NASA GIBS layer turned on]

NASA data use does not imply NASA endorsement.

---

## Notes behind slide 6 (not on the slide)

All from `config/validation/results.csv`; fuller wording in `LIMITATIONS.md` items 21 and 22.

- 14 counties, 8 crops (corn, soybeans, winter wheat, spring wheat, sorghum, cotton, rice, peanuts). 31 checks
  gave results. One more (Sumner County, Kansas sorghum) had 17 overlapping years where 20 are needed.
- All 31 together: median held-out r 0.18, and 0.32 with the correction. 13 at or below zero, 7 with the
  correction.
- Rainfed: 12 of 22 checks have r of 0.4 or better. Median miss 891 kg/ha, and 522 kg/ha with the correction.
- Irrigated: range -0.68 to 0.42; 2 of 9 have r of 0.4 or better.
- Best: Lancaster County, Nebraska corn (0.87), Warren County, Kentucky corn (0.85). Worst: Colusa County,
  California rice (-0.68).
- The correction lowered the average miss in 22 of 31 checks and raised r in 19. It made the rest worse.
- India: one district in Telangana against ICRISAT district yields, held-out years 2010 to 2017. Jowar 0.34,
  bajra 0.50, pigeon pea 0.42 (0.45, 0.57 and 0.45 with the correction). In the repo only; the app shows the US
  checks.
- NASS yields were downloaded on 2026-11-15 through the public Quick Stats website export, because no API key
  was available. Same records as the API.
- If a judge asks "is 0.42 good?": it means the model follows some of the year-to-year ups and downs in
  rainfed counties and misses a lot. We do not claim more than that.

---

## 30-second video script

Limit: 30 seconds. A longer video makes the project ineligible for Global Judging (`CHECKLIST.md`).

Every view of the app is a real screen recording. **No voice-over, no webcam, no people.** The guide forbids
audio and likeness of anyone under 18, so the words go on screen as captions. A short farmland shot at the start
or end may be AI-generated (Higgsfield); it must carry a visible AI-generated watermark for its whole time on
screen, show no people and no NASA branding, and never redraw the app. Music is optional; use only AI-generated
music the team has the right to use, or none.

| Time | On screen | Caption |
|---|---|---|
| 0 to 4 s | Start screen with the three example farms | RotationLab: which crop rotation holds up as your climate changes? |
| 4 to 9 s | Click "Explore Iowa" (Story County); on "2. Best crop plans" open the "Your climate" tab | NASA POWER weather since 1981 shows how this spot has already changed. |
| 9 to 16 s | "2. Best crop plans", "Best plans" tab; scroll across the three cards | Three picks: best for soil and climate, highest profit, best for your soil. |
| 16 to 21 s | "3. What could change it"; charts and map | See the rainfall, heat or water level where the best plan flips. |
| 21 to 27 s | "Can I trust this?"; the headline lines and chart | Checked against USDA yields in 14 counties. Rainfed: median r 0.42, best 0.87. Irrigated: not validated. |
| 27 to 30 s | End card: app name and the two lines on the right | Modeled estimates for planning, not a guarantee. Built with NASA POWER and GIBS data. |

Before recording: wake the hosted app, open the example farm once so it is cached, and record at a size where
the captions stay readable. Check the final file is 30 seconds or less.
