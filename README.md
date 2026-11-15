# RotationLab

NASA Space Apps 2026, challenge **Field Shift: Adapting Farms with NASA Data**.

RotationLab uses NASA data to show any farmer how their climate is already changing, and which crop rotation
will strengthen their soil and hold up as it keeps changing, without losing money.

Results are modeled estimates for planning. They are not a guarantee of yield or profit.

> **Status (2026-11-15).** The team is building version 4 (any pin on Earth, with US auto-fill) to Build Spec
> v4. Until the v4 merge, `main` runs the earlier India build (one farm district in Telangana, kharif season).
> This README describes v4. The India build is described in `docs/INDIA_DATA.md` and `docs/NASA_DATA.md`.

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

To rebuild the validation table once NASS yields are cached: `.venv/bin/python -m engine.correction`
(writes `config/validation/results.csv`).

## How it works

1. **You answer a few questions.** Current crops, water (rain only or irrigated, normal-year and dry-year
   supply), farm size, and optionally a soil test and field history. Then you drop a pin on the map.
2. **NASA weather.** Daily NASA POWER weather from 1981 to the latest year at your pin. The climate card
   compares the last 20 years with 1981 to 2000: season rain, rain variability, heat days and rainy-season start.
3. **Soil and local data.** In the US, soil comes from USDA SSURGO and county crops, yields, prices and costs
   come from USDA NASS and ERS. Elsewhere, soil comes from ISRIC SoilGrids and you enter yield, price and cost.
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
8. **How good is this?** A hindcast in 12 US counties across 9 regions (`config/validation/sites.yaml`):
   modeled against NASS county yields, detrended, with the latest 8 years held out. A small linear correction
   for rain, heat and year is fitted on training years only, and results are shown with and without it
   (`engine/hindcast.py`, `engine/correction.py`). Where there is no local yield data, the app says
   "Not validated here".

Every value carries a badge: Observed, Estimated, Your input, Assumption, or Placeholder ("team to verify").
All assumptions, with sources and ranges, are in `config/assumptions.yaml`. Limits are in `LIMITATIONS.md` and
data sources in `DATA_SOURCES.md`.

## Repo layout

| Path | What it is |
|---|---|
| `engine/api.py` | The only interface between parts (Build Spec v4, A5) |
| `engine/fetch_*.py`, `cache.py`, `crops.py`, `et0.py`, `waterbalance.py`, `yieldmodel.py`, `economics.py` | Data and crop science |
| `engine/scenarios.py`, `optimize.py`, `tipping.py`, `evpi.py`, `climate.py` | Scenarios, scoring and picks |
| `engine/soil_score.py`, `hindcast.py`, `correction.py`, `explain.py` | Soil score, validation, explanations |
| `app.py`, `ui/` | Streamlit app |
| `config/` | Assumptions, validation sites |
| `tests/` | pytest tests for every module |

## AI use

Claude Code (Anthropic) wrote most of the code, tests and docs under the team's direction. In the app,
Claude (`claude-sonnet-5-5`) writes the plain-English explanations. It sees only computed numbers, and a guard
rejects any reply with a number or crop that is not in the results, falling back to a fixed template. AI made
up no data. Details are in `AI_USE.md`, and every code file has an AI-use header comment.

NASA data use does not imply NASA endorsement.
