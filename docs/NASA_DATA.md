# NASA data used by RotationLab

Access date for every fact below: **2026-11-14**, unless noted. Raw evidence is saved in `data/raw/` (`power_16.877_79.193.json`, `gibs_capabilities_epsg3857.xml`) and `data/raw/sources/` (POWER parameter definitions, CMR dataset records, GIBS layer metadata, POWER Daily API page). Anything not confirmed from one of those sources is marked **unverified** and is not used as a fact. Dataset names, versions and DOIs come from NASA's CMR catalogue (https://cmr.earthdata.nasa.gov/search/collections.umm_json).

## 1. NASA POWER daily (used in the model)
- Service: Daily API, point endpoint `https://power.larc.nasa.gov/api/temporal/daily/point`, community AG, API version v2.10.3 (from response header). Docs: https://power.larc.nasa.gov/docs/services/api/temporal/daily/ (saved as `power_doc_daily_api.html`).
- Record: the docs state daily data are available "from 1981/01/01 to Near Real Time". We requested 1981-01-01..2025-12-31 in one call; it succeeded (16,436 days cached; the model uses 1984-2025).
- Grid: the same docs page refers to a "0.5 x 0.5 global grid" and says "all parameters are available in their original source spatial resolution". The response header lists sources MERRA2, SRB, SYN1DEG, POWER. The exact native resolution of each source is **unverified** here. The UI must say "regional estimate", not "your field".
- Fill value: response header `fill_value: -999.0`; `time_standard: LST`.
- Parameters, units and definitions are quoted from `https://power.larc.nasa.gov/api/system/manager/parameters?community=ag&user=x&temporal=daily`:

| Column | POWER parameter | Units | Definition (POWER) |
|---|---|---|---|
| tmax | T2M_MAX | C | maximum hourly air temperature at 2 m |
| tmin | T2M_MIN | C | minimum hourly air temperature at 2 m |
| tmean | T2M | C | average air temperature at 2 m |
| rh | RH2M | % | vapor pressure / saturation vapor pressure, percent |
| wind2 | WS2M | m/s | average wind speed at 2 m |
| precip | PRECTOTCORR | mm/day | average MERRA-2 bias corrected total precipitation |
| srad | ALLSKY_SFC_SW_DWN | MJ/m^2/day | total (direct plus diffuse) irradiance on a horizontal plane, all-sky |

- Point: **Nalgonda district centroid, 16.877 N, 79.193 E** (config/region.yaml). Source: computed by the team from the OpenStreetMap boundary relation 2022221 (admin_level 5, Wikidata Q15384, LGD district code 514), fetched from Nominatim on 2026-11-14 and saved in `data/raw/sources/osm_relation_2022221_nalgonda.geojson`. Polygon area 7,209 km2 vs 7,222.78 km2 stated on https://en.wikipedia.org/wiki/Nalgonda_district (0.2 percent apart, accessed 2026-11-14). This is a computed centroid of the current district polygon, not the HQ town. The Wikidata coordinate (17.1, 79.3) was rejected: its only reference is "imported from English Wikipedia" and it lies near the HQ town. An official Census or Survey of India centroid was not found, so the centroid rests on OSM (secondary, community-maintained). Because POWER is a 0.5 degree grid, a few km of centroid error does not matter; it may matter for which grid cell is returned, which is unverified.
- Old DEV point (17.5, 78.5) was removed along with its cache file.
- Elevation 216.37 m from the response `geometry.coordinates[2]` (grid-cell value, not the farm). Cached record 1981-2025; model window 1984-2025 (42 years).
- Observed at the centroid (computed from the cache, 1984-2025): mean annual rainfall 787 mm (median 801, p10 573, p90 999, range 445-1217); mean Jun-Oct rainfall 667 mm (median 640, range 371-1098), 84.7% of the annual total.
- **Gap found in the data (verified 2026-11-14 in the downloaded JSON):** `ALLSKY_SFC_SW_DWN` is -999 for all 1,095 days of 1981-01-01..1983-12-31 (all other variables complete). That exceeds the 3-day interpolation limit. Why POWER has no solar values before 1984 is **unverified** (not stated on the pages we read). **Decision (lead): trim, do not fill.** `load_weather` returns 1984-01-01..2025-12-31 (15,341 days, 42 years); the trim is recorded in `df.attrs["trimmed_range"]`. The full 1981-2025 JSON stays in the cache untouched. A day-of-year-mean fill exists only behind the explicit opt-in `srad_leading_gap="doy_climatology"` (off by default, labelled assumption); `"raise"` fails loudly.
- Status: **used in model**.
- Citation text recommended by POWER: **unverified** (not read from the source). Cite as "NASA POWER Project, Daily API v2.10.3, https://power.larc.nasa.gov, accessed 2026-11-14".

## 2. NASA GIBS map overlays (shown on map only, not in model)
- Capabilities: https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi?SERVICE=WMTS&request=GetCapabilities (cached, HTTP 200, 5.8 MB). Layer IDs below are parsed from it by `engine/fetch_gibs.py`, results in `data/gibs_layers.json`.
- Layer metadata: https://gibs.earthdata.nasa.gov/layer-metadata/v1.0/<LAYER_ID>.json (saved under `data/raw/sources/gibs_meta_*.json`).

| Use | Layer ID | Matrix set | Format | Valid dates (from capabilities) | Verified tile |
|---|---|---|---|---|---|
| Soil moisture (chosen) | `SMAP_L4_Analyzed_Root_Zone_Soil_Moisture` | GoogleMapsCompatible_Level6 | image/png | 2015-03-31 to 2026-11-10, daily, with gaps (16 date ranges) | 2026-11-10, HTTP 200, 10,825 bytes |
| Soil moisture (alt) | `SMAP_L4_Analyzed_Surface_Soil_Moisture` | Level6 | image/png | 2015-03-31 to 2026-11-10 | 2026-11-10, HTTP 200 |
| NDVI (chosen) | `MODIS_Terra_L3_NDVI_16Day` | GoogleMapsCompatible_Level9 | image/png | 2000-03-05 to 2026-10-16, every 16 days | 2026-10-16, HTTP 200, 19,082 bytes |
| NDVI (alt) | `MODIS_Terra_L3_NDVI_Monthly` | Level7 | image/png | 2000-03-01 to 2026-10-01 | 2026-10-01, HTTP 200 |

- Tile check used the z5 overview tile row 14 / col 23, which covers the Nalgonda centroid (16.877 N, 79.193 E); re-verified 2026-11-14. SMAP layers are Level6 (max native zoom 6), so folium needs `max_native_zoom=6`; NDVI 16-day is Level9. Default map centre is the centroid (`center` in gibs_layers.json). The date-range gaps in SMAP mean the map must pick dates from `time_ranges`; `fetch_gibs.candidate_dates` does this.
- Underlying products per GIBS layer metadata: the SMAP root-zone layer lists SPL4SMAU "SMAP L4 Global 3-hourly 9 km EASE-Grid Surface and Root Zone Soil Moisture Analysis Update V008" (DOI 10.5067/02LGW4DGJYRX, from CMR). The NDVI layer lists MOD13Q1 "MODIS/Terra Vegetation Indices 16-Day L3 Global 250m SIN Grid" (CMR V061 DOI 10.5067/MODIS/MOD13Q1.061; GIBS metadata lists V006 among its concept ids, which version the displayed tiles use is **unverified**).
- Resolution: "9 km" and "250 m" are product names; the displayed tile resolution is limited by the matrix set levels above.
- Colour scale / legend meaning of the tile PNGs: **unverified**; do not print values from the overlay, show it as a qualitative picture.
- Helper: `engine.fetch_gibs.tile_url_template(layer, date)` returns an XYZ URL for folium, e.g. `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/<layer>/default/<date>/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png`.
- **Fallback if a layer or date fails:** a static Worldview screenshot labelled with layer ID and date. The model never depends on GIBS.
- Status: **shown on map**.

## 2b. Upstream Krishna basin rainfall (used in model, canal-supply proxy)
Module `engine/fetch_upstream.py`; points in `config/region.yaml: upstream_points`. Nagarjuna Sagar Dam is at 16.58 N, 79.31 E (Wikidata Q1112896, accessed 2026-11-14); the Krishna flows east, so the points below lie west of it and in its catchment.

| Point | lat, lon | Why upstream of Nagarjuna Sagar | Mean Jun-Oct rain 1984-2025 |
|---|---|---|---|
| Mahabaleshwar | 17.925, 73.6575 | Krishna rises here (en.wikipedia.org/wiki/Krishna_River, Course) | 1,754 mm |
| Ujjani (Bhima) | 18.0739, 75.12 | terminal dam on the Bhima, a principal Krishna tributary; catchment 14,850 km2 | 533 mm |
| Almatti | 16.331, 75.888 | main stem reservoir, Upper Krishna Project; catchment 33,375 km2 | 476 mm |
| Tungabhadra Dam | 15.2612, 76.3379 | principal tributary; joins at Srisailam reservoir; catchment 28,180 km2 | 464 mm |
| Srisailam | 16.0869, 78.8972 | confluence of Tungabhadra and Krishna; catchment 206,040 km2 vs 214,185-215,000 km2 at Nagarjuna Sagar | 606 mm |

Sources (all accessed 2026-11-14): coordinates are Wikidata P625 for each dam or town (community data, plus or minus 1 arcminute, **approximate**); river and catchment facts are English Wikipedia infoboxes and text (Krishna_River, Almatti_Dam, Ujjani_Dam, Tungabhadra_Dam, Srisailam_Dam, Nagarjuna_Sagar_Dam; saved in `data/raw/sources/`). These are secondary sources. The official India-WRIS and CWC basin pages were attempted but not readable (India-WRIS wiki page and cwc.gov.in returned no usable text); the catchment figures are therefore **unverified against CWC**. Points are sub-basin anchors chosen by the team, not catchment centroids, and the choice of five points is a judgement, not an optimum.
- Each point's POWER record is cached as `data/raw/power_<lat>_<lon>.json`; same -999 rules as the Nalgonda record (no gaps except the 1981-83 srad block, which is trimmed).
- Equal-weight mean of the five points: mean 767 mm, median 737 mm, range 502 (2015) to 1,177 (2020). **Real lowest year: 2015 (mean 502 mm)**, followed closely by 2003 (517) and 1986 (518). `fetch_upstream.lowest_upstream_year()` returns it; this is the "low canal release year" stress test.
- **Caveat:** the mean of a few 0.5 degree grid points is a proxy for basin rainfall, not catchment inflow. The Mahabaleshwar headwater point is about 3 times wetter than the others and dominates the equal-weight mean; area weighting was not done. Reservoir storage, operations, evaporation and inter-state sharing are not represented, so this is not a prediction of canal releases.

## 3. Other challenge datasets
Existence, version, DOI and start date come from CMR records (`data/raw/sources/cmr_umm_*.json`). Access findings are from live requests on 2026-11-14.

| Dataset | Exact record (CMR) | DOI | Access finding | Use / status |
|---|---|---|---|---|
| SMAP L4 soil moisture | SPL4SMGP V008 (3-hourly 9 km geophysical), from 2015-03-31 | 10.5067/T5RUATAQREF8 | Via GIBS tiles: open. Point values: Earthdata login required (not tested; unverified) | Map overlay via GIBS. Roadmap: point time series for validating modelled soil water |
| SMAP L3 enhanced | SPL3SMP_E V006 (daily 9 km), from 2015-03-31 | 10.5067/M20OXIZHY3RJ | login not tested; unverified | Roadmap |
| GPM IMERG Final daily | GPM_3IMERGDF V07, 1998-01-01 to 2025-09-30 per CMR | 10.5067/GPM/IMERGDF/DAY/07 | OPeNDAP at gpm1.gesdisc.eosdis.nasa.gov: the `.dds` metadata answers openly, but a data request returns HTTP 302 to urs.earthdata.nasa.gov, so **Earthdata login is required**. Not faked. Hydrology Data Rods point service shows a discontinuation notice (disc.gsfc.nasa.gov alert page). | Roadmap: cross-check POWER rainfall at the district point once the team has an Earthdata login |
| MODIS Terra NDVI | MOD13A1 V061 500 m 16-day (from 2000-02-18); MOD13Q1 V061 250 m | 10.5067/MODIS/MOD13A1.061, 10.5067/MODIS/MOD13Q1.061 | Via GIBS tiles: open. Raw HDF needs login | Map overlay (GIBS). |
| ECOSTRESS | ECO_L2T_LSTE V002 (tiled LST), from 2018-07-09 | 10.5067/ECOSTRESS/ECO_L2T_LSTE.002 | Earthdata login: unverified | Roadmap only (irregular revisit; too sparse for a daily model) |
| Landsat | HLS L30 (Landsat OLI surface reflectance, daily) V2.0, from 2013-04-11 | 10.5067/HLS/HLSL30.002 | Earthdata login: unverified. A plain "Landsat Collection 2" CMR record was not found under short name LANDSAT_OT_C2_L2 (0 hits), so that name is **unverified** | Roadmap: field-scale NDVI once a boundary is known |
| GRACE / GRACE-FO | JPL Mascon RL06.3 Mv04 (`TELLUS_GRAC-GRFO_MASCON_GRID_RL06.3_V4`); GRACEDADM_CLSM025GL_7D V3.0 (groundwater and soil moisture, 0.25 deg, 7-day, from 2003-02-03) | 10.5067/TEMSC-3MJ634; 10.5067/SZYMDFZ7TJ4H | login: unverified | Roadmap. Context for groundwater depletion, which the model does not simulate (SPEC_CHANGES_INDIA sec 7). Too coarse for a single farm |
| SRTM | SRTMGL1 V003, 1 arc second, 2000-02-11..21 | 10.5067/MEASURES/SRTM/SRTMGL1.003 | login: unverified | Roadmap: field elevation. Model currently uses the POWER grid-cell elevation (494.59 m) |

## 4. Honest scope
- Model inputs: POWER only (plus ICRISAT, MSP and soil data owned by other agents).
- GIBS layers are qualitative map overlays labelled with layer ID and date.
- Nothing from IMERG, ECOSTRESS, Landsat, GRACE or SRTM is used or shown. They are listed as roadmap because login-gated access was not set up; no numbers from them appear anywhere.
