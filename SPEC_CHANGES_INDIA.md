> Historical build notes. Current behavior and data are documented in README.md and engine/CONTRACT.md.

# SPEC_CHANGES_INDIA: overrides to RotationLab Build Spec v2

Source: team update pasted 2026-11-14. Where this file and the v2 spec disagree, this file wins. Everything not mentioned here stays as in the v2 spec (milestone order, provenance badges, offline cache, seed 42, tests-before-UI, no invented data).

## Open items for the team (marked TEAM in the update)
- [ ] **District name** for the farm. Needed to set lat/lon for NASA POWER and to match the pre-2014 ICRISAT district. Until given, `config/region.yaml` holds `district: TEAM_TO_FILL` and no weather is fetched.
- [ ] **Millet list.** Defaults to jowar (sorghum) and bajra (pearl millet). Edit if the farm grows others (e.g. ragi, foxtail).
- [ ] Optional `data/raw/farm_records.csv` (year, crop, area_acres, yield_quintals, irrigation_source, costs_rupees). Never fabricated; skipped if absent.

## 1. Crops (replaces maize, soybean, wheat, cotton)
| Crop | Water regime | Notes |
|---|---|---|
| Rice (paddy) | Irrigated paddy, new water model (section 2) | |
| Jowar (sorghum) | Rainfed, FAO-56 soil water balance | |
| Bajra (pearl millet) | Rainfed, FAO-56 soil water balance | |
| Pigeon pea (tur) | Rainfed, FAO-56 soil water balance | Legume rotation partner |

Reference rotations (4 plan years):
- A = rice, rice, rice, rice
- B = rice, jowar, rice, jowar
- C = rice, pigeon pea, jowar, rice

Parameters: Kc (initial, mid, end), stage lengths, root depth, depletion fraction p from FAO-56 tables (rice, sorghum, millet listed). Ky from FAO-33 where listed. Anything not found there is marked "team to verify" in `assumptions.yaml`. Pigeon pea is not a standard FAO-56 table entry, so expect "team to verify" there.

## 2. Rice water model (rice only)
- Daily need = ETc + percolation_seepage; plus a one-time land preparation and puddling amount at season start.
- Irrigation needed on a day = max(0, need - effective rain).
- Available irrigation per season is a farmer input in mm (default in `assumptions.yaml`, badge Assumption).
- Monsoon tie: `available_irrigation = base_available * (season_rainfall / median_season_rainfall) ^ k`, per scenario. Represents tanks and groundwater recharging less in dry years. `base_available` and `k` have ranges and the note "simplified recharge proxy, team to verify".
- If irrigation needed exceeds available water, rice is water stressed; apply the FAO-33 reduction using ETa/ETm.
- Report per rotation: total water use (rain + irrigation, mm) and irrigation water separately.
- `percolation_seepage` (mm/day, soil dependent) and `puddling_water` (mm) go in `assumptions.yaml` with ranges.
- Millets and pigeon pea keep the existing rainfed water balance.

## 3. Rotation effects (all badge Assumption, with ranges; unsourced = "team to verify")
- Rice after rice: small yield penalty.
- Millet or rice after pigeon pea: yield boost plus a nitrogen credit.
- Millet after millet: small penalty.

## 4. Decision boundary (main demo screen)
- **Primary chart:** x = season rainfall multiplier, y = available irrigation water (mm). Cell color = winning rotation. Shows the water level at which the farm should shift land from rice to millets.
- Keep: 1D rainfall crossover chart, late-monsoon what-if, bootstrap uncertainty bands.
- Keep: EVPI on soil water capacity.
- Add: EVPI on available irrigation water. Card text: "Is it worth measuring your borewell or tank capacity before deciding?"

## 5. Data
- **Hindcast:** ICRISAT DLD district yields for rice, sorghum, pearl millet, pigeon pea. Note in LIMITATIONS that district rice yields mix irrigated and rainfed fields.
- **Prices:** MSP for paddy, jowar, bajra, tur; latest kharif MSP, with year and source in `assumptions.yaml`.
- **Region:** the farm's district, matched to its pre-2014 district in ICRISAT.
- **Farm records:** if `data/raw/farm_records.csv` exists, show as "Local input" and plot on the hindcast chart beside district data.
- **Weather:** NASA POWER at the district centroid (unchanged method).
- `engine/fetch_nass.py` (USDA NASS, Kansas) is superseded for this region. It stays in the repo, unused, and is removed from the data-source list in the app. The NASS key is in the gitignored `.env`.

## 6. Tests to add (on top of v2 section 11.2)
- Rice irrigation need is never negative and drops to near zero during sustained heavy rain.
- Cutting available irrigation water never raises rice yield.
- Rotations with more millet use less total irrigation water than rice-only, under identical weather.
- Rice water accounting closes: rain + irrigation = ETa + percolation + runoff + change in storage, within tolerance.

## 7. Limitations to add
- The recharge proxy for irrigation availability is simplified.
- Rabi (yasangi) rice and other winter crops are not modeled.
- Groundwater depletion over many years is not simulated.
- District rice yields mix irrigated and rainfed fields.

## Consequences for earlier v2 text
- v2 "dryland only" is no longer true for rice. The UI header and LIMITATIONS must say rice is modeled as irrigated paddy with a limited, monsoon-linked water budget.
- v2 cereal-rye cover crop option and the corn heat penalty are dropped (no corn). Cover crop can return as a pigeon-pea or green-manure option only if the team asks.
- v2 feasibility rule (winter wheat after a late harvest) no longer applies. Kharif crops only, one per year, so all sequences are feasible.
- Currency becomes rupees per acre; yields in quintals/acre or kg/ha as ICRISAT reports (kg/ha), converted in one place.
