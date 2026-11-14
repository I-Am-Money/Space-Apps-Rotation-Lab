# India data sources (india-data agent)

All access dates 2026-11-14. Code: `engine/fetch_icrisat.py`, `engine/fetch_msp.py`, `engine/fetch_soil.py`. Config: `config/prices_india.yaml`.
DEV district: **Rangareddy** (undivided, contains the DEV point 17.5N 78.5E). It is a placeholder (`dev_placeholder: true`). To switch, set `district` / `icrisat_district` in `config/region.yaml`; nothing else changes.

## 1. ICRISAT District Level Database (yields, area)
- Primary: ICRISAT/TCI DLD, http://data.icrisat.org/dld/src/crops.html (apportioned, 1966-2017, CC BY 4.0; resource document http://data.icrisat.org/dldAPI/documentDownload/?fileName=unapportioned). Landing pages: https://tci.cornell.edu/data , https://vdsa.icrisat.org/vdsa-database.aspx.
- **Blocked:** `data.icrisat.org` timed out on TCP from this environment (curl, 15-60 s, and Playwright). No file from the primary portal was obtained. `engine.fetch_icrisat.try_download()` re-probes and writes `data/raw/icrisat_dld/FETCH_STATUS.json`.
- **Fallback actually used:** Mohapatra, "ICRISAT District-Level Data: Heterogeneous Climate Effect on Crop Yield...", Mendeley Data, doi:10.17632/ywp3y5j9vv.1 (CC BY 4.0, v1, 11 Jul 2023). File `main merge (droped _merge==2) (560 dist 1990-2015).xls`, cached at `data/raw/icrisat_mendeley/`. Third-party, derived from ICRISAT DLD, **unapportioned**, 1990-2015 only, and holds **rice and pearl millet only** (no sorghum, no pigeonpea). Telangana districts appear under the 10 undivided names.
- Result for Rangareddy: rice 26 years, bajra 24 years (1990-2015). Jowar and pigeonpea: no rows, `potential_yield` is a flagged placeholder. Nothing is invented.
- **Manual steps (to get 1966+ and all four crops):** open http://data.icrisat.org/dld/src/crops.html, choose states Telangana/Andhra Pradesh, crops Rice, Kharif Sorghum (or Sorghum), Pearl Millet, Pigeonpea, download the CSVs, and save them as `data/raw/icrisat_dld/*.csv`. The loader reads any wide DLD CSV with columns `Dist Name, State Name, Year, <CROP> AREA (...), <CROP> YIELD (Kg per ha)` and prefers these files automatically (a "1000 ha" area header is scaled to ha). Verify the column headers on first load.
- District matching: `match_district()` maps current names to the undivided district (exact, Telangana lineage table, fuzzy) and reports what matched. The lineage table (`TELANGANA_TO_ICRISAT`) is administrative knowledge typed by the agent, **team to verify** against Telangana's 2016 district formation orders; districts made from several parents (e.g. Siddipet, Kamareddy) use the main parent and are flagged.
- Caveats: district rice yields mix irrigated and rainfed fields. Missing years coded 0 or -1 are dropped. Unapportioned data is based on 2015 boundaries.
- Potential yield Ym = 90th percentile of linearly detrended yields (trend removed, re-centred on the final year). Computed: rice 2875 kg/ha, bajra 1146 kg/ha for Rangareddy (DEV).

## 2. MSP and cost (kharif 2026-27)
- Source (read and parsed): PIB, "Cabinet approves Minimum Support Prices (MSP) for Kharif Crops for Marketing Season 2026-27", 13 May 2026, https://www.pib.gov.in/PressReleasePage.aspx?PRID=2260617&reg=3&lang=1. Cached `data/raw/msp_kharif_2026_27_pib_PRID2260617.html`; `engine.fetch_msp.verify()` re-parses it and checks the YAML offline.
- Values (Rs/quintal, MSP / 2025-26 MSP / all-India cost A2+FL per quintal): Paddy common 2441 / 2369 / 1627; Jowar hybrid 4023 / 3699 / 2682 (Maldandi 4073); Bajra 2900 / 2775 / 1858; Tur 8450 / 8000 / 5496.
- Cost column: PIB's footnote describes all paid-out costs plus imputed family labour (A2+FL), all-India weighted average, per quintal, projected for 2026-27. It is not per acre and not state-specific.
- Not found: state-level (Telangana/AP) CACP cost of cultivation per acre. `operating_cost_rs_per_acre`, soil-test cost and borewell/tank measurement cost are `badge: placeholder` (null) for the team to fill. A news-site copy of the PIB prose quoted 2360 for 2025-26 paddy; the PIB table says 2369 and was used.

## 3. Soil (SoilGrids)
- Source: ISRIC SoilGrids 2.0 REST API, https://rest.isric.org/soilgrids/v2.0/properties/query (layers wv0033, wv1500, sand, silt, clay, depths 0-100 cm, mean and Q0.05/Q0.95). Unit scaling taken from the API response (`d_factor` 10). I did not open ISRIC's documentation pages; unit handling is from the API response itself.
- AWC = wv0033 - wv1500, thickness-weighted over 0-100 cm. DEV point (17.5, 78.5) is masked (urban Hyderabad); the nearest valid pixel 1.5 km away is used (`pixel_offset_km`) and cached as `data/raw/soil_17.5_78.5.json`.
- DEV result: AWC 128 mm/m, texture sandy clay (sand 47.7, silt 16.3, clay 35.9 %), group D.
- Uncertainty: the API 5-95 % band, combined in quadrature, is very wide (0 to 342 mm/m); layers are correlated so this overstates it. `awc_low_pm25/awc_high_pm25` give a flagged +-25 % alternative (96 to 160).
- Hydrologic group is an assumption mapped from texture class (SoilGrids does not provide it). Fallback if the API is unreachable: FAO-56 Table 19 typical TAW by texture (values typed by the agent, team to verify), badge `assumption`.
- Limits: 250 m model predictions, not a field measurement; the badge is `local` only in the sense of location-specific data.
