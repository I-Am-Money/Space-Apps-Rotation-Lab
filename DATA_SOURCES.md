# Data sources

Every dataset the app or its validation uses has a line here with its source, URL and download date (Build
Spec v4, A3). Owners add a row when they add a dataset. Status: **in use** means it is cached and used now;
**planned** means the v4 spec names it but it has not been downloaded in this repo yet.

## NASA data

| Data | Source and URL | Downloaded | Status | Used for |
|---|---|---|---|---|
| Daily weather 1981 to latest year (T2M_MAX, T2M_MIN, T2M, RH2M, WS2M, PRECTOTCORR, ALLSKY_SFC_SW_DWN) | NASA POWER daily point API, community AG: https://power.larc.nasa.gov/api/temporal/daily/point (docs https://power.larc.nasa.gov/docs/) | 2026-11-14 (India points); 2026-11-15 (the three example farms and the US validation sites, cached in `data/precache/weather/`; other pins are fetched when loaded) | in use | Water balance, scenarios, climate card, hindcast. -999 = missing. Solar radiation starts 1984, so the record used is 1984 to 2025. |
| Satellite map layers: SMAP L4 root-zone soil moisture, MODIS Terra NDVI 16-day | NASA GIBS WMTS, layer IDs from GetCapabilities: https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi?SERVICE=WMTS&REQUEST=GetCapabilities | 2026-11-14 (capabilities cached in `data/raw/gibs_capabilities_epsg3857.xml`, layer IDs in `data/gibs_layers.json`) | in use | Map context only, not model input |
| Elevation 30 m | NASA SRTM / NASADEM | not downloaded | not used in this version (field zones were not built) | None |

## Other data

| Data | Source and URL | Downloaded | Status | Used for |
|---|---|---|---|---|
| US county yields, prices received, crops grown (area harvested), irrigated share (Census of Agriculture) | USDA NASS Quick Stats: https://quickstats.nass.usda.gov (downloaded without a key through the website's spreadsheet export; the API at https://quickstats.nass.usda.gov/api needs `NASS_API_KEY` and was not used) | 2026-11-15, the 14 validation counties only | yields, prices, crops grown and irrigated share for the 14 counties cached in `data/precache/nass/`; other counties: cached copy, else the farmer enters values | US defaults, hindcast "actual" yields |
| US soil | USDA NRCS Soil Data Access (SSURGO; STATSGO fallback): https://sdmdataaccess.nrcs.usda.gov/ | 2026-11-15 (example and validation sites cached in `data/precache/soil/`; other pins are fetched when loaded) | in use (`engine/fetch_ssurgo.py`) | Soil water capacity, texture |
| Food energy per kilogram of each crop | USDA FoodData Central, SR Legacy: https://fdc.nal.usda.gov (each value in `config/assumptions/simulation.yaml` names the food and its FDC ID) | read 2026-11-15 | in use, for the crops listed in `docs/notes/person2.md`; crops with no verified value are not counted | Food energy on the recommendation cards |
| Global soil | ISRIC SoilGrids: https://soilgrids.org/ | 2026-11-14 (two India points, `data/raw/soil_*.json`) | in use (India) | Soil outside the US |
| US production costs (9 crops: corn, soybeans, wheat, sorghum, barley, oats, cotton, rice, peanuts), dollars per planted acre, latest year 2025 | USDA ERS Commodity Costs and Returns, one CSV per crop: https://www.ers.usda.gov/data-products/commodity-costs-and-returns | 2026-11-15 (`data/precache/costs/`) | in use (`engine/fetch_ers.py`) | Operating cost per hectare by Farm Resource Region |
| County to ERS Farm Resource Region (3,112 counties, regions 1 to 9) | USDA ERS, "Aggregating counties to ERS resource regions": https://www.ers.usda.gov/sites/default/files/images/reglink.xls | 2026-11-15 (`data/precache/geo/`) | in use | Picks the ERS cost region for a county; validation site regions |
| County internal points (lat/lon) and FIPS | US Census Bureau 2023 Gazetteer, counties: https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_counties_national.zip | 2026-11-15 (downloaded again the same day for the two added sites) | in use | Validation site coordinates (`config/validation/sites.yaml`) |
| Crop coefficients and stage lengths | FAO-56 (Allen et al. 1998) Tables 11 and 12: https://www.fao.org/4/x0490e/x0490e0b.htm ; Table 22: https://www.fao.org/4/x0490e/x0490e0e.htm | read 2026-11-14 and 2026-11-15 | in use | Crop water use; stand-in hindcast model |
| Yield response factor Ky | FAO I&D Paper 66 Table 1, "Seasonal Ky values from FAO I&D Paper No. 33": https://www.fao.org/4/i2800e/i2800e02.pdf | read 2026-11-14 and 2026-11-15 | in use | Yield response to water |
| Soil health principles | USDA NRCS, Soil Health on Cropland: https://www.nrcs.usda.gov/conservation-basics/soil/soil-health/soil-health-on-cropland ; Soil Health Principles: https://www.nrcs.usda.gov/sites/default/files/2023-06/Soil%20Health%20Principles%202.3.pdf | read 2026-11-15 | in use | The four principles behind the Soil Health Score. The score's weights are team choices, not NRCS numbers. |
| India district crop yields (optional validation) | ICRISAT/TCI District Level Database (DOI 10.21421/D2/XFB1BZ), apportioned table from the World Bank reproducibility archive: https://reproducibility.worldbank.org/catalog/409 (original: http://data.icrisat.org/dld/src/crops.html) | 2026-11-14 (checksums in `data/raw/icrisat_dld/SOURCE.json`) | in use | India hindcast (v3) and the v4 India validation pack: one district (Nalgonda, Telangana), jowar, bajra and pigeon pea, held-out years 2010 to 2017 (`config/validation/india.yaml`). |
| India MSP 2026-27 and national A2+FL costs | Press Information Bureau, Government of India: https://www.pib.gov.in/PressReleasePage.aspx?PRID=2260617 | 2026-11-14 (cached HTML) | in use (India version) | India prices and cost scaling |
| Telangana cost of cultivation 2020-21 | PJTAU: https://www.pjtau.edu.in/Cost_Cultivation_Crops.html | 2026-11-15 | in use (India version) | India rice and pigeon pea budgets |
| Urea bag price | PIB: https://www.pib.gov.in/PressReleasePage.aspx?PRID=2272695 | access date not recorded (release dated 14 June 2026) | in use (India version) | Nitrogen credit value |
| Paddy water parameters | FAO Irrigation Water Management training manual ch. 4: https://www.fao.org/4/t7202e/t7202e07.htm | 2026-11-14 | in use (India version) | Percolation, puddling water |
| District outline and centroid | OpenStreetMap contributors (ODbL), relation 2022221 | 2026-11-14 | in use (India version) | Offline map, weather point |
| Upstream dam points | Wikidata coordinates (see `config/region.yaml`) | 2026-11-14 | in use (India version) | Canal supply proxy |

More detail for the India version: `docs/NASA_DATA.md`, `docs/INDIA_DATA.md`.
