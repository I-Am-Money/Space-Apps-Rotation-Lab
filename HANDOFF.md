# Handoff: how to carry RotationLab forward

Written 2026-11-14 for the team. Read this first, then `engine/CONTRACT.md` (the interface and every design change so far, in order), `SPEC_CHANGES_INDIA.md`, `LIMITATIONS.md` and `docs/`.

## What this is
A decision-support tool for the NASA Space Apps 2026 challenge "Field Shift: Adapting Farms with NASA Data". A 40-acre black-soil rice farm in Nalgonda district, Telangana, compares crop rotations against rice-only (rotation A, "our farm today") using NASA POWER weather, a FAO-56 daily soil water balance, an irrigated-rice water model (canal plus wells), and decision boundaries with expected value of perfect information. Streamlit UI, five tabs.

## Run it
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # if requirements.txt is missing: numpy pandas streamlit plotly folium streamlit-folium requests pyyaml pytest anthropic scipy xlrd
.venv/bin/pytest -q                      # all tests; runs offline from data/raw/
.venv/bin/streamlit run app.py
```
Optional: `ANTHROPIC_API_KEY` for the written explanation. Without it the app uses a deterministic template. Never commit keys; `.env` is gitignored.

## Repo map
- `engine/`: physics and decision code. `api.py` is the only thing the UI calls. `CONTRACT.md` explains shapes and ownership.
- `config/`: `region.yaml` (district, centroid, crop selection, upstream basin points, water source), `farm.yaml` (acres, soil), `assumptions.yaml` (every model parameter with range, source, badge), `prices_india.yaml` (MSP, costs, potential yields).
- `data/raw/`: cached downloads so the demo works offline. `docs/NASA_DATA.md` and `docs/INDIA_DATA.md` list every source with URL and access date.
- `ui/`, `app.py`, `.streamlit/`: the front end. `PRODUCT.md` and `DESIGN.md` hold the design brief.
- `tests/`: the test suite.

## Ground rules we followed
- No invented data. Every number is cached data, a calculation, a user input or a parameter with a source note. Unverified values say "team to verify" and show a Placeholder or Assumption badge.
- Provenance badges on every number: Observed, Modeled, Local input, Assumption, Placeholder.
- Privacy: no village name and no personal names or emails anywhere in the app or repo.
- Nothing is submitted to the Space Apps portal until the team says so.

## What is still placeholder or unverified (fix these first; they drive the ranking)
1. **Real ICRISAT district yield tables.** `data.icrisat.org` and the Dataverse DOI (10.21421/D2/XFB1BZ) were unreachable from the build environment. Yields currently come from a labelled third-party panel (Mendeley, doi 10.17632/ywp3y5j9vv.1) with rice and bajra only, 1990 to 2015. Download the district CSVs into `data/raw/icrisat_dld/`; the loader prefers them automatically. Then re-check which millets have the most complete Nalgonda record and update `crop_selection` in `config/region.yaml` (currently bajra, provisional). Jowar, ragi and pigeon pea have no yield data, so their hindcast says "no validation data". Check the bajra 2014 and 2015 values (both exactly 500).
2. **Potential yields (Ym)**: pigeon pea is a placeholder and was driving the top rank. Jowar and ragi too if selected.
3. **Costs**: operating cost per acre, irrigation cost, soil-test cost, and borewell or tank measurement cost are placeholders. Replace with sourced figures (state cost-of-cultivation data) or the farm's own records in `data/raw/farm_records.csv` (year, crop, area_acres, yield_quintals, irrigation_source, costs_rupees; never fake it).
4. **Irrigation supply parameters** in `assumptions.yaml` (`base_canal`, `k_canal`, `base_well`, `k_well`, `max_well`, percolation): all "team to verify". Canal supply is a rainfall proxy from five upstream Krishna-basin weather points, not a reservoir model.
5. **FAO-33 Ky** for rice, millets and pigeon pea, ragi values, pigeon pea crop parameters, rotation effects, sowing dates: marked "team to verify". Someone with agronomy knowledge or farm records should review these.
6. **Nalgonda centroid** is derived from OpenStreetMap boundary data, not an official centroid. Old-district lineage rests on Wikipedia.
7. **Upstream basin points** come from Wikidata and Wikipedia; the official basin pages could not be read.
8. **Rice water source** was left unconfirmed by the farm; the model defaults to `canal_and_well`.

## What was in flight when this was written
The last rounds of work (canal and well supply, upstream rainfall, black-soil inputs, farm totals and the 40-acre land-split slider, `/taste` design pass, second Tipping Points heat map) were being built by parallel agents. Run `pytest -q` and click through all five tabs before trusting any of it; fix or finish whatever is incomplete. The engine and data layers were passing their tests at last check.

## Submission (do not submit until the team agrees)
Portal rules, read from the Space Apps site on 2026-11-14:
- Deadline Sunday Nov 15, 11:59 PM in the Team Owner's local time (Universal Event rule).
- A Universal Event team needs 2 to 6 confirmed members on the portal's Members tab. Confirm every teammate has joined the team and registered for the Universal Event.
- Required form fields: project name, high-level summary, demo link, final project link, detailed description, use of SI (AI) disclosure, NASA data used, references for every external resource.
- Demo must be a video of 30 seconds or less OR a deck of 7 slides or fewer, hosted at a public link with no login. English required (non-English video needs English subtitles). No one under 18 in demo or project.
- Tick both boxes: terms and conditions, and "all work is original" with every external resource (including open-source code) listed in References.
- Disclose AI use: this code was written with AI assistance. Generated images or video need a visible watermark. No NASA logos or branding in generated content.
- Judging: Impact, Creativity, Validity, Relevance (NASA data as a core component), Presentation, each 1 to 5.
- Challenge asks: compare at least three strategies including the existing rotation; for each, evidence, information gaps and risks that need local review; say the tool supports, not replaces, farmer judgment.

## Next steps
1. Fill the placeholders above, starting with the ICRISAT tables and costs.
2. Deploy to Streamlit Community Cloud so the "Link to Final Project" works; test the link in a private window.
3. Make the demo (30 s video or 7-slide deck) and draft the form text and AI-use disclosure.
4. Review the "team to verify" parameters with an agronomist or the farm's own records.
5. When the team agrees, submit through the portal.

## Status at last push
All 82 tests pass. All five tabs were opened in a browser on the real engine (no mock data, no errors, no names): My Field with canal and well overrides and the black-soil card, Compare Futures, My Priorities (land-split slider and farm totals present), Tipping Points, How Good Is This. Not yet checked: phone-width layout for the newest elements, the `/taste` design pass, and the second Tipping Points heat map by eye.
Fixed in the last pass: `assumptions_table()` crashed on crops without prices; it now lists potential yields and the farm's 40 acres. The header shows a Draft note whenever model inputs are still unsourced placeholders (currently many: see How Good Is This?).
