# RotationLab

A four-year kharif crop-rotation planner for a 40-acre rice farm in Nalgonda, Telangana. It compares rice-only against 256 sequences of rice, bajra, kharif sorghum and pigeon pea, using real NASA weather and a continuous daily water balance. Results support farmer and local-expert judgment; they are modeled estimates, not guarantees.

## Run

Python 3.11-3.13 is supported. Native wheels are pinned for the numerical compiler.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m engine check-data
.venv/bin/python -m pytest -q
.venv/bin/python -m streamlit run app.py
```

The first numerical call compiles or loads the native kernel. No API key is needed. Streamlit 1.51 uses compatible segmented navigation; releases with lazy tabs use native tabs.

## What works

- Five screens: farm inputs, rotation comparison, priorities, tipping points, and validation.
- Detected rainfall onset drives planting. A documented false-start check rejects a wet window followed by a long dry spell. A crop without onset or enough time to mature has no harvest.
- Paddy accounting separates canal and well supply, draws canal first, caps wells, and carries soil moisture between crops and fallow periods. Rainfed crops use FAO-56 depletion stress and FAO-33 yield response.
- Flowering heat sensitivity can be disabled. Rotation effects and nitrogen savings remain explicit assumptions.
- Risk and irrigation-saving preferences, Pareto frontier, farm totals and a shared-weather land split. The water preference is an editable monetary value, separate from irrigation charges.
- Rainfall/supply and upstream/local-rain decision maps, 200 bootstrap resamples, onset-delay curves, and perfect-information upper bounds. Interactive maps use 150 seeded sequences; the full option uses 500. Recommendations always use 500.
- Anonymous CSV farm-record import, local cost overrides, result/assumption CSV downloads, and a cached offline district outline. Online NASA GIBS layers remain available.

## Data and honesty

NASA POWER provides the cached 1984-2025 district weather record and five upstream Krishna-basin points. ICRISAT/TCI's apportioned district crop table was recovered from the World Bank reproducibility archive: 52 Nalgonda years, 1966-2017, for all selected crops. The source member and extracted file have recorded checksums. Ragi has only 17 positive-yield years and is not selected. Kharif sorghum is used without blending it with the annual sorghum column.

Official 2026-27 MSPs and national A2+FL costs per quintal are cached from PIB. Default per-acre budgets are an **explicit proxy**: national unit cost multiplied by detrended district potential yield. They are not observed Telangana or farm budgets. Ordinary irrigation is included in that cost concept; the additional irrigation charge defaults to zero to avoid double counting. Measurement quotes are unknown until entered; the app does not invent them or give a purchase verdict without one.

Validation estimates potential yield and trend lines from training years only and holds out the latest eight overlapping years. Weak correlations remain visible. See `LIMITATIONS.md`, `docs/INDIA_DATA.md`, and `docs/NASA_DATA.md`.

## Commands and deployment

```sh
.venv/bin/python -m engine report --output output/planning-report.json
.venv/bin/python -m engine benchmark --scenarios 500 --include-tipping
.venv/bin/python scripts/prepare_deploy.py
```

`output/rotationlab-deploy.zip` contains source, tests and required public data, with a SHA-256 manifest. It excludes secrets, virtual environments and personal farm-record files. See `docs/DEPLOYMENT.md` for Streamlit Community Cloud and Docker. GitHub Actions runs offline data checks and tests.

## Optional explanation and AI use

The default explanation is deterministic. To enable optional Claude explanations, configure `ANTHROPIC_API_KEY`; `ANTHROPIC_MODEL` optionally overrides the default model. Each user must opt in before computed totals are sent. Explanations are cached in bounded process memory, not written to disk. Never commit keys; `.env` and Streamlit secrets are ignored.

Code was built with Claude Code assistance and subsequently completed and tested with OpenAI Codex assistance. See `AI_USE.md`. `ROTATIONLAB_MOCK=1` is solely for explicitly labeled design previews. Production calculations never silently switch to invented data. NASA data use does not imply NASA endorsement.
