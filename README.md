# RotationLab

NASA Space Apps 2026, challenge **Field Shift: Adapting Farms with NASA Data**.

RotationLab uses NASA data to show any farmer how their climate is already changing, and which crop rotation
will strengthen their soil and hold up as it keeps changing, without losing money.

Results are modeled estimates for planning. They are not a guarantee of yield or profit.

`main` runs version 4: any pin on Earth, with US auto-fill. Three example farms on the start screen (Iowa, Nebraska
and Texas) open a full result in one click. The earlier single-farm India build is still reachable from the start
screen and is described in `docs/INDIA_DATA.md` and `docs/NASA_DATA.md`.

## Setup

Use Python 3.11 (the numerical compiler, numba, does not support 3.14).

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m streamlit run app.py
```

Optional keys go in environment variables or Streamlit secrets, never in the repo:

- `NASS_API_KEY`: USDA NASS Quick Stats, for US yields, prices and crops grown.
- `ANTHROPIC_API_KEY`: Claude explanations. Without it the app uses a fixed template.

Without `NASS_API_KEY` the app still runs. US pins then use cached NASS copies if there are any, otherwise
they ask you for yield and price. ERS costs are committed in `data/precache/` and need no key.

To rebuild the validation table (with no `NASS_API_KEY`, the first command downloads the same records from
the public Quick Stats website export; the results in the repo were made that way on 2026-11-15):

```sh
.venv/bin/python -m engine.fetch_nass --precache-validation   # NASS county data for the 14 validation counties
.venv/bin/python -m engine.correction                         # writes config/validation/results.csv
```

## How it works

1. **You answer a few questions.** Current crops, water (rain only or irrigated, normal-year and dry-year
   supply), farm size, and optionally a soil test and field history. Then you drop a pin on the map.
2. **NASA weather.** Daily NASA POWER weather from 1981 to the latest year at your pin. The climate card
   compares the last 20 years with 1981 to 2000: season rain, rain variability, heat days and rainy-season start.
3. **Soil and local data.** In the US, soil comes from USDA SSURGO. County crops, yields (latest 5-year mean),
   prices received and the irrigated share come from USDA NASS (`engine/fetch_nass.py`). If NASS withholds a
   county value, the state average is used and labelled. Operating costs come from USDA ERS for the county's
   Farm Resource Region (`engine/fetch_ers.py`). US rules (`engine/us_rules.py`): mostly irrigated counties start
   from "irrigated" and ask about water first; orchards are not offered; Alaska and Hawaii are not supported yet;
   crops with no ERS cost need your cost. Outside the US, soil comes from ISRIC SoilGrids and you enter yield,
   price and cost.
4. **Crop science, not a black box.** A daily FAO-56 water balance and FAO-33 yield response to water run on
   real weather years: 4-year historical blocks, 500 bootstrap plans (seed 42) and named stress years.
5. **Every 4-year rotation is scored.** Mean profit, bad-year profit (worst 10%), food calories, irrigation
   and total water, and a **Soil Health Score** (0 to 100). The score is rule-based, from NRCS soil health
   principles: soil cover, living roots, diversity and legumes, residue carbon, a penalty for repeating the same
   crop, and tillage and field history. It is not a soil test (`engine/soil_score.py`).
6. **Three picks.** Best for soil and climate (never loses money against your current plan, unless you
   change the tolerance), Highest profit, and Best for your soil. Each shows the change from your current
   plan and a short plain-English explanation.
7. **Tipping points and what to measure next.** The rainfall, heat or water supply at which the best plan
   changes, and which unknown (water supply, soil water capacity, organic matter) would be most worth measuring.
8. **How good is this?** (`ui/trust.py`) A hindcast in 14 US counties covering all 9 ERS Farm Resource
   Regions (`config/validation/sites.yaml`):
   modeled against NASS county yields, detrended, with the latest 8 years held out. A small linear correction
   for rain, heat and year is fitted on training years only, and results are shown with and without it
   (`engine/hindcast.py`, `engine/correction.py`). Results from the 2026-11-15 run are mixed: in mostly
   rainfed counties the median held-out r is 0.42 (22 county and crop checks); in mostly irrigated counties it
   is -0.04 (9 checks), so irrigated areas are not validated. One India district is checked against ICRISAT
   yields the same way. Where there is no local yield data, or the local check did not pass, the app says
   "Not validated here". See `LIMITATIONS.md` items 21 and 22.

Every value carries a badge: Observed, Estimated, Your input, Assumption, or Placeholder ("team to verify").
All assumptions, with sources and ranges, are in `config/assumptions.yaml` and `config/assumptions/*.yaml`. Limits are in `LIMITATIONS.md` and
data sources in `DATA_SOURCES.md`.

## Repo layout

| Path | What it is |
|---|---|
| `engine/api.py` | The only interface between parts (Build Spec v4, A5) |
| `engine/fetch_*.py`, `cache.py`, `crops.py`, `et0.py`, `waterbalance.py`, `yieldmodel.py`, `economics.py` | Data and crop science |
| `engine/scenarios.py`, `optimize.py`, `tipping.py`, `evpi.py`, `climate.py` | Scenarios, scoring and picks |
| `engine/soil_score.py`, `explain.py` | Soil score, explanations |
| `engine/fetch_nass.py`, `fetch_ers.py`, `us_rules.py`, `hindcast.py`, `correction.py`, `ui/trust.py` | US data, validation and the How Good Is This? page |
| `app.py`, `ui/` | Streamlit app |
| `config/` | Assumptions (`assumptions.yaml`, `assumptions/<feature>.yaml`), validation sites |
| `data/precache/` | Pre-fetched public data (ERS costs and regions; demo and validation sites) |
| `docs/notes/` | Each owner's notes for LIMITATIONS, DATA_SOURCES and AI_USE |
| `tests/` | pytest tests for every module |

## AI use

AI coding assistants wrote most of the code, tests and docs under the team's direction: Claude Code (Anthropic) for
the engine, validation, recommendations and tipping points, and OpenAI Codex for the app shell, site and data
fetchers. In the app,
Claude (`claude-sonnet-5-5`) writes the plain-English explanations. It sees only computed numbers, and a guard
rejects any reply with a number or crop that is not in the results, falling back to a fixed template. AI made
up no data. Details are in `AI_USE.md`, and every code file has an AI-use header comment.

NASA data use does not imply NASA endorsement.
