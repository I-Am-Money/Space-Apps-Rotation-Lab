# RotationLab

A four-year kharif crop-rotation planner for a 40-acre rice farm in Nalgonda, Telangana. It evaluates 253 offered sequences of rice, bajra, kharif sorghum and pigeon pea, using real NASA weather and a continuous daily water balance. Results support farmer and local-expert judgment; they are modeled estimates, not guarantees.

## Run

Python 3.11-3.13 is supported. Native wheels are pinned for the numerical compiler.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m engine check-data
.venv/bin/python -m pytest -q
.venv/bin/python -m streamlit run app.py
```

The first numerical call compiles or loads the native kernel. No API key is needed. Streamlit 1.58 or newer is required; releases with lazy tabs use native tabs.

## What works

- Five screens: farm inputs, rotation comparison, priorities, tipping points, and validation.
- Detected rainfall onset drives planting. A documented false-start check rejects a wet window followed by a long dry spell. Sowing follows the onset shift relative to the weather record median, capped so the crop matures within the calendar year. Years without a clean onset are flagged.
- Paddy accounting separates canal and well supply, draws canal first, caps wells, and carries soil moisture between crops and fallow periods. Rainfed crops use FAO-56 depletion stress and FAO-33 yield response.
- Flowering heat sensitivity can be disabled. Rotation effects and nitrogen savings remain explicit assumptions.
- Risk and irrigation-saving preferences, Pareto frontier, farm totals and a shared-weather land split. The water preference is an editable monetary value, never deducted from displayed profit.
- Rainfall/supply and upstream/local-rain decision maps, 200 bootstrap resamples, onset-delay curves, and perfect-information upper bounds. Interactive maps use 150 seeded sequences; the full option uses 500. Recommendations always use 500.
- Anonymous CSV farm-record import, local cost overrides, result/assumption CSV downloads, and a cached offline district outline. Online NASA GIBS layers remain available.

## Data and honesty

NASA POWER provides the cached 1984-2025 district weather record and five upstream Krishna-basin points. ICRISAT/TCI's apportioned district crop table was recovered from the World Bank reproducibility archive: 52 Nalgonda years, 1966-2017, for all selected crops. The source member and extracted file have recorded checksums. Ragi has only 17 positive-yield years and is not selected. Kharif sorghum is used without blending it with the annual sorghum column.

Official 2026-27 MSPs and national A2+FL costs per quintal are cached from PIB. Rice and pigeon-pea budgets use verified Telangana A2+FL cultivation costs scaled to 2026-27 with national cost ratios; millet budgets use national unit-cost proxies multiplied by district potential yields. Both methods remain assumptions, not farm budgets. Rice district yields are milled rice and are converted to paddy only when calculating sales. No separate water charge is deducted from profit. Measurement quotes remain unknown until entered.

The team rule excludes the same non-rice crop in all four years. Such a plan can still be compared as the current rotation, but cannot be recommended. Rotation effects include the previous crop on the farm; the app shows a sensitivity check with those effects removed.

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

Code was built with Claude Code assistance and subsequently completed and tested with OpenAI Codex assistance. See `AI_USE.md`. The toy preview engine has been removed. Calculation failures never switch to invented data. NASA data use does not imply NASA endorsement.
