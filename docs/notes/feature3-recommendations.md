# Notes for Feature 3: recommendations and what to measure

Input for the team's LIMITATIONS.md, DATA_SOURCES.md and AI_USE.md. Named by feature, because the project rule is that no personal names appear anywhere in the repo.

## What was built

| File | State |
|---|---|
| `engine/candidates.py` | Working. Climate-fit filter (R5). Temperature limits are unverified (see below). |
| `engine/economics.py` | Working. v4 functions appended below the v3 India code, which is untouched. |
| `engine/soil_score.py` | Working (written earlier, reviewed). Now reads `config/assumptions/recommend.yaml`. |
| `engine/optimize.py` | Working. v4 functions appended below the v3 code. Uses a stand-in simulator until `api.simulate` exists. |
| `engine/evpi.py` | Working for soil water capacity and irrigation supply. Organic matter is not computed (see below). |
| `engine/explain.py` | Working (written earlier, reviewed). Guarded, cached, falls back to a template. |
| `ui/recommendations.py`, `ui/measure.py` | Working, plain Streamlit only. The app-shell owner does the design pass. |
| `config/assumptions/recommend.yaml` | Working. Holds the soil score, candidates, units, optimize and evpi parameters. |

## For LIMITATIONS.md

- The soil score is rule-based. It is not a soil test. Weights are team choices with ranges.
- Climate fit uses recalled temperature limits per crop, not yet read from FAO EcoCrop. Every row is marked team to verify. Crops outside the nine in the table are not filtered by climate.
- One crop per plan year in the enumeration. Two seasons per year (R9) is not built.
- Cover crops are offered only when the farmer enters a seed and planting cost. Only cereal rye is modelled.
- Prices and costs are fixed across scenarios. A missing price or cost is never defaulted: a candidate crop without them is left out and listed; a current-plan crop without them stops the money numbers until the farmer enters them.
- EVPI is an upper bound on what a perfect test is worth, judged on profit and risk only. It is computed over the 30 best rotations at the base inputs plus the current plan, for speed.
- Organic matter has no EVPI yet. It needs a verified relation between organic matter and water-holding capacity (`awc_mm_per_m_per_om_pct` in recommend.yaml, left empty on purpose).
- Rotation scoring does not yet depend on the climate-shift setting; that arrives with the simulation and scenarios.
- Calories per kg are recalled values, not read from USDA FoodData Central. The crop-science module is meant to own and source them.
- Bushel weights are standard USDA test weights; re-check against the NASS conversion table.

## For DATA_SOURCES.md

- Acre and pound conversions: NIST SP 811 (exact definitions).
- Bushel weights: USDA and NIST Handbook 44 standard test weights. Not yet re-verified.
- Crop season length: FAO-56 Table 11 (through `crops.py`, or `config/validation/standin_crops.yaml` until it has them).
- NRCS soil health principles (cover, roots, biodiversity, minimal disturbance) for the Soil Health Score; weights are team choices.

## For AI_USE.md

Claude Code (Anthropic) wrote this code and its tests under the team's direction. `engine/explain.py` calls Claude (claude-sonnet-5-5) only for the plain-English explanation of each pick. It sends computed numbers only, rejects any reply containing a number or crop that is not in the input, and falls back to a deterministic template. The app works with no API key.

## How the simulation is wired in

- `optimize.py` reads the simulation result through `_read_sim`: arrays shaped [scenarios, 4 years] named `yields_kg_ha`, `irrigation_mm`, `total_water_mm`, plus `weights`, `feasible` and `reason`. This matches the crop-simulation module's `SimResult`, and it uses its `simulate_many` batch call when present.
- Scenario weights are respected: the mean and the worst-10% are weighted, so the Recent and Trend climate modes work once they hand over re-weighted scenarios.
- A crop with no yield number comes back as NaN. A candidate crop like that is left out and listed as needing a yield; a crop in the current plan stops the money numbers and asks for the yield. A rotation marked infeasible is left out. Nothing is filled in.
- Contract note: the rule is to go through `engine/api.py`. `api.simulate` does not exist yet, so the optimizer falls back to `engine.simulate` directly, then to a flagged stand-in. Switch to `api.simulate` when it lands; nothing else changes.
- Speed on 81 rotations by 100 scenarios: about 4 s the first time (numba compiles), 0.1 s after. Moving a slider only re-runs the pick selection. `numba` must be installed (it is in requirements.txt); without it the simulation falls back to slow pure Python (about 45 s for the same run).
- All per-plan numbers are averages per plan year, in metric units per hectare. The UI converts to acres for display.
