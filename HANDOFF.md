# Handoff: where RotationLab stands

Updated 2026-11-15 after the Build Spec v3 rebuild. Read this first, then `README.md`, `LIMITATIONS.md` and `AI_USE.md`.

The governing document is "RotationLab Build Spec v3 (Nalgonda)". `engine/CONTRACT.md` and `SPEC_CHANGES_INDIA.md` are older working notes kept for history; where they disagree with v3 or with the code, v3 and the code win.

## What this is
A decision-support tool for the NASA Space Apps 2026 challenge "Field Shift: Adapting Farms with NASA Data". A 40-acre black-soil rice farm in Nalgonda district, Telangana, compares four-year crop plans with rice every year (rotation A, "our farm today"). It uses NASA POWER weather, a FAO-56 daily soil water balance, an irrigated-paddy water model fed by canal and well supply, a monsoon-onset rule, a heat penalty at flowering, and a search for the water level where the best plan changes. Streamlit front end, five tabs.

## Run it
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/pytest -q                 # 114 tests, offline, about 25 seconds
.venv/bin/streamlit run app.py
```
Optional: `ANTHROPIC_API_KEY` for the written explanation. Without it the app uses a fixed template. Never commit keys; `.env` is gitignored.

## Repo map
- `engine/`: the model. `api.py` is the only module the front end calls.
  - `et0.py`, `waterbalance.py`, `yieldmodel.py`, `crops.py`: crop water use, soil water, paddy water, yield.
  - `monsoon.py`: the onset rule and sowing dates. `scenarios.py`: weather sequences, stress tests and what-ifs.
  - `economics.py`, `optimize.py`: profit, the objective, ranking, the plan rule.
  - `boundaries.py`: tipping-point map, crossovers, the value of a measurement. `hindcast.py`: check against district yields.
  - `explain.py`: the plain-English explanation (Claude with a template fallback). `fetch_*.py`: cached downloads.
- `config/`: `assumptions.yaml` (every model parameter with range, source, badge), `prices_india.yaml` (prices, costs, yield ceilings), `region.yaml`, `farm.yaml`.
- `data/raw/`: cached downloads so the app and tests run offline.
- `ui/`, `app.py`, `.streamlit/`: the front end. `PRODUCT.md` and `DESIGN.md` hold the design brief.
- `tests/`: `test_spec_v3.py` has one test per row of the spec's test table; the other files cover each module.

## Ground rules we follow
- No invented data. Every number is cached data, a calculation, a user input or a parameter with a source note. Unverified values say "team to verify" and carry an Assumption or Placeholder badge.
- A badge on every number: Observed, Modeled, Local input, Assumption, Placeholder.
- Privacy: no village name and no personal names or emails anywhere in the app or repo. Nobody under 18 appears by face, voice or name in the demo or on the project page.
- Never cut: the tipping-point map, the badges, the comparison with rice every year, the hindcast tab.
- Nothing is submitted to the Space Apps portal until the team agrees.

## What changed in the v3 rebuild
1. The made-up water charge is gone from profit. Costs are the Telangana cost-of-cultivation survey scaled to 2026-27 (rice, pigeon pea) and a documented estimate for bajra.
2. Rice yield is milled rice and is sold as paddy at the paddy price.
3. The objective is the v3 formula. The water slider now rewards plans that use less irrigation water; it does not change the profit shown.
4. Sowing follows a monsoon-onset rule. A late monsoon loses its early rain and sows late, and never raises yield.
5. Heat at flowering reduces yield. Soil cover follows a per-crop rule with a soil-carbon direction arrow.
6. The same non-rice crop four years running is not offered (79 plans). Rice every year stays as the baseline.
7. Stress tests are the four named in v3. The tipping map is coloured by the number of rice years, with a boundary line and an uncertainty band.
8. The toy stand-in engine used during early screen design was deleted, so the app can never show made-up numbers.
9. Tests are named after the spec's test table. `AI_USE.md`, `LIMITATIONS.md` and a header comment in every code file are in place.

## What is still placeholder or unverified (these drive the ranking)
1. **Eleven inputs in use are placeholders**: Ky for rice, bajra and pigeon pea; bajra early-season Kc; pigeon pea stage lengths; three fallow parameters; the pigeon-pea-after-pigeon-pea effect; soil-test cost; water-measurement cost. The app lists them under How Good Is This.
2. **Pigeon pea has no district yield record.** Its yield ceiling comes from a state cost survey. It is in most recommended plans, so this is the first thing to fix.
3. **ICRISAT district tables.** `data.icrisat.org` could not be reached from the build machine. Download the district CSVs for rice, sorghum, pearl millet and pigeon pea into `data/raw/icrisat_dld/`; the loader prefers them automatically. Steps are in `docs/INDIA_DATA.md`. Check the bajra 2014 and 2015 values (both exactly 500).
4. **Bajra cost** is an estimate (all-India cost per quintal times district yield ceiling).
5. **Water supply**: canal 600 mm and wells 400 mm a season are assumptions. The owner should confirm the water source and rough amounts.
6. **Parameters marked "team to verify"**: heat limits, late-sowing penalty, onset rule numbers, rotation effects, irrigation proxy parameters, hydrologic group D.
7. **Farm records.** `data/raw/farm_records.csv` (year, crop, area_acres, yield_quintals, irrigation_source, costs_rupees) would replace several assumptions. Never fake it.

## Left to do before submitting
1. Deploy to Streamlit Community Cloud (steps in `README.md`) and open the link in a private window.
2. Make the demo: a video of 30 seconds or less with English subtitles, or a deck of 7 slides or fewer including the title. Over the limit is ineligible.
3. Fill the form: project name, summary, description, NASA data used, other data and references, AI use (copy from `AI_USE.md`).
4. Confirm every teammate is on the team's Members tab and registered for the same event.
5. Click Submit for Judging before 11:59 PM in the Team Owner's local time on Sunday 15 November. Saving is not submitting.

## Portal rules, read from the Space Apps site on 2026-11-14
- Required fields: project name, high-level summary, demo link, final project link, detailed description, AI disclosure, NASA data used, references for every external resource.
- Demo and project links must be public with no login. English is required.
- Tick both boxes: terms and conditions, and "all work is original" with every external resource listed in References.
- AI-generated images or video need a visible watermark. No NASA logos or branding.
- Judging: Impact, Creativity, Validity, Relevance (NASA data as a core component), Presentation, each 1 to 5.
- The challenge asks for at least three strategies including the existing rotation; for each, the evidence, the information gaps and the risks that need local review; and a statement that the tool supports, not replaces, farmer judgment.
