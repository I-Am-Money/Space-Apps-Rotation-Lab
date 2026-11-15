# RotationLab

A crop-rotation planning tool for one real question on one kind of farm: a 40-acre black-soil farm in Nalgonda, Telangana, grows rice every year. When irrigation water is limited, should some years move to millet or pigeon pea?

Built for NASA Space Apps 2026, challenge "Field Shift: Adapting Farms with NASA Data".

RotationLab runs every four-year plan of rice, bajra (pearl millet) and pigeon pea through 42 years of real NASA weather, compares each plan with rice every year, and shows the water level at which the best plan changes. Everything it shows is a modeled estimate for planning. It is not a guarantee of yield or profit, and it supports the judgment of the farmer and local experts without replacing it.

## What you see

| Tab | What it answers |
|---|---|
| Our Farm | What do we know about the farm, its weather, its soil and its water? Includes NASA satellite layers on a map and the monsoon start date for every year since 1984. |
| Compare Futures | How do rice every year and two alternatives do across the weather record, and in four named bad years? |
| Our Priorities | Which of the 79 plans is best for what this farm cares about: average profit, bad-year profit and saving irrigation water? |
| Tipping Points | At what rainfall and irrigation supply does the answer change, how sure is the model about that line, and what do a late monsoon or a hotter season do? |
| How Good Is This? | How well does the model match what the district actually harvested, what does it assume, and where does every number come from? |

Every number carries a badge: Observed, Modeled, Local input, Assumption or Placeholder (yellow, for an input with no verified source yet).

## What the model says today

At the default settings (priorities slider 30, water-saving slider 10), over 500 resampled four-year weather sequences, in rupees per acre over four years:

| Plan | Average profit | Worst 10% | Irrigation water |
|---|---|---|---|
| Rice every year (the farm today) | 35,114 | 24,612 | 2,474 mm |
| Rice, pigeon pea, rice, rice (recommended) | 35,398 | 25,460 | 1,850 mm |

So one pigeon pea year in four is modeled to earn about the same and use about a quarter less irrigation water. Read that with care: eleven inputs are still placeholders, pigeon pea has no yield record for the district, and the top plans are close to tied. `LIMITATIONS.md` has the full list.

## Run it

    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    .venv/bin/streamlit run app.py

The app runs offline from the files in `data/raw/`, except the satellite map layers, which load live from NASA.

Optional: set `ANTHROPIC_API_KEY` to have Claude write the short explanation on the Our Priorities tab from the computed numbers. Without a key the app writes it from a fixed template. Never commit a key.

Tests: `.venv/bin/pytest -q` (114 tests, about 25 seconds, no internet needed). `tests/test_spec_v3.py` has one test for every row of the build spec's test table.

## Deploy (Streamlit Community Cloud)

1. Sign in at share.streamlit.io with the GitHub account that owns this repository.
2. New app, this repository, branch `main`, main file `app.py`.
3. Optional: add `ANTHROPIC_API_KEY` under Secrets.
4. Open the public link in a private window before submitting, so it is awake.

## Where things are

- `app.py`, `ui/`: the Streamlit front end.
- `engine/`: the model. `api.py` is the only module the front end calls.
- `config/`: every setting. `assumptions.yaml` holds each model parameter with its range, source and badge; `prices_india.yaml` holds prices, costs and yield ceilings; `region.yaml` and `farm.yaml` describe the district and the farm.
- `data/raw/`: cached downloads.
- `docs/NASA_DATA.md`, `docs/INDIA_DATA.md`: every data source with its link and access date.
- `LIMITATIONS.md`: what the tool cannot tell you.
- `AI_USE.md`: how AI was used.
- `HANDOFF.md`: where the project stands and what is left.

The build follows "RotationLab Build Spec v3 (Nalgonda)". Where an older note in this repository disagrees with v3, v3 wins.

## Data

- NASA POWER daily weather, 1984 to 2025, at the centre of Nalgonda district and at five points upstream of Nagarjuna Sagar (used in the model).
- NASA GIBS map layers: SMAP root-zone soil moisture and MODIS NDVI (shown on the map for context, not used in the model).
- District rice and pearl millet yields, 1990 to 2015: a published panel built on ICRISAT district data (Mendeley Data, doi 10.17632/ywp3y5j9vv.1).
- Minimum support prices for kharif 2026-27 (Press Information Bureau, Government of India) and Telangana cost of cultivation (Directorate of Economics and Statistics, through the PJTSAU page).
- SoilGrids (ISRIC) for the district soil estimate; the farm's black soil is the owner's input.
- Methods: FAO-56 (crop water use), FAO-33 (yield response to water), SCS curve number (runoff).
- Libraries: streamlit, plotly, folium, streamlit-folium, numpy, pandas, scipy, pyyaml, requests, xlrd, anthropic, pytest.

## AI use

This project was built with AI assistance. Claude (Anthropic), through Claude Code, wrote the code, the tests and the documentation under the team's direction, and every code file says so in a header comment. Inside the app, Claude can write the short explanation on the Our Priorities tab from the computed numbers only; the app labels that text, and falls back to a fixed template when no key is set. No AI-generated images, video or audio are used. Details are in `AI_USE.md`.

NASA data are used. No NASA logo appears and no NASA endorsement is implied.
