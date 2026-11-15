# Person 4 source entries for Person 3 to merge

These entries supplement, and do not overwrite, the shared DATA_SOURCES.md.

| Source | What is used | Retrieval/check status |
| --- | --- | --- |
| [NASA GIBS WMTS capabilities](https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi?SERVICE=WMTS&request=GetCapabilities) | Real layer identifiers, Web Mercator matrix sets, URL templates, date intervals and temporal steps for SMAP soil moisture and MODIS NDVI | Live capabilities and image tile responses checked 2026-11-15; exact retrieval timestamp and dates in data/gibs_layers.json. |
| [NASA GIBS API documentation](https://nasa-gibs.github.io/gibs-api-docs/access-basics/) | WMTS parameters, projection and date conventions | Read 2026-11-15. |
| [ISRIC SoilGrids properties API](https://rest.isric.org/soilgrids/v2.0/properties/query) | sand/silt/clay fractions and 33/1500 kPa volumetric water retention at five 0–100 cm standard depth intervals | Endpoint connectivity checked 2026-11-15. Full three-point live requests timed out on the first check; fallbacks were recorded rather than disguised as SoilGrids estimates. See the delivered live-check report for the latest results. |
| [ISRIC units and depth documentation](https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_01.html) | d_factor conversion metadata, texture percentage, water volume percentage and prediction quantiles | Read 2026-11-15. SoilGrids is a spatial prediction, badged Estimated, not a farm observation. |
| [FAO-56, Table 19](https://www.fao.org/4/X0490E/x0490e0c.htm) | Published texture-based ranges of field capacity minus wilting point | Read 2026-11-15. Table-range midpoint is an Assumption. Clay loam / sandy clay loam / sandy clay use explicitly identified nearest-class assumptions because they lack direct rows; absent texture assumes loam and says so. |
| [USDA Agricultural Handbook 697](https://www.ers.usda.gov/media/7780/ah-697.pdf) | Standard 56 lb/bu corn and grain sorghum; 60 lb/bu soybeans and wheat; unit conversion references | Read 2026-11-15. Bushel conversion is rejected for unverified crop IDs. |
| Person 3's config/validation/sites.yaml, branch p3-validation | 12 validation county IDs, crop lists and county coordinates | Read from commit e5b395a on 2026-11-15. Do not replace Person 3's owned file with a stale copy. |

US price/cost data fetching remains Person 3's work. This module accepts normalized site defaults or farmer input and does not invent US defaults. The legacy INR/acre functions preserve their historical rounded area factor to keep the existing engine reproducible; the new v4 functions use the exact international acre. No currency exchange is performed.

FAO texture ranges and the conservative envelope constructed from SoilGrids marginal prediction quantiles are different things. Neither is advertised as a farm measurement or a calibrated joint uncertainty interval. Coarse fragments are not modeled in the SoilGrids AWC summary; organic matter is not inferred from texture.
