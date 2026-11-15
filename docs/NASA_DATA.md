# NASA weather and map layers

## Numerical weather driver

NASA POWER daily point API, community AG: https://power.larc.nasa.gov/api/temporal/daily/point
Documentation: https://power.larc.nasa.gov/docs/

Cached parameters are T2M_MAX, T2M_MIN, T2M, RH2M, WS2M, PRECTOTCORR and ALLSKY_SFC_SW_DWN. Internal names are tmax, tmin, tmean, rh, wind2, precip and srad; units are degrees C, percent, m/s, mm/day and MJ/m2/day. Raw -999 sentinels become missing values; short gaps may be interpolated, while long gaps fail. Solar radiation is unavailable in the leading 1981-1983 period, so production uses the complete 1984-2025 record rather than inventing it. Leap days are removed only when forming 365-day scenario arrays.

District point: 16.877 N, 79.193 E, an area-weighted centroid calculated from OpenStreetMap Nalgonda relation 2022221. Grid-cell elevation 216.37 m comes from POWER response geometry. This is a regional grid estimate, not a field or village measurement. Centroid and lineage notes are retained in config/region.yaml.

Five upstream Krishna-basin anchor points are configured in region.yaml: headwaters, Bhima/Ujjani, Almatti, Tungabhadra and Srisailam. Their unweighted June-October mean rainfall is a proxy for canal availability; it is not catchment inflow, a reservoir-release series or a groundwater observation. Coordinates and topology come from the documented community sources and need basin-expert review. All six point downloads are cached in data/raw/power_*.json.

ET0 uses the FAO-56 Penman-Monteith calculation with a logged Hargreaves fallback where inputs require it. The test suite includes the worked-example tolerance and weather-range checks. Onset is a configurable planning calculation from daily rain, not an observed IMD onset date. What-if rainfall/heat/onset shifts are applied to real years, never labeled forecasts. Reference rainfall medians use the unmodified complete annual record.

## Satellite context

GIBS documentation: https://www.earthdata.nasa.gov/engage/open-data-services-software/earthdata-developer-portal/gibs-api
Capabilities: https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi?SERVICE=WMTS&REQUEST=GetCapabilities

Exact IDs and dated tile templates are recorded in data/gibs_layers.json from the original capability/tile checks. The cached primary selections are:

- SMAP_L4_Analyzed_Root_Zone_Soil_Moisture, date 2026-11-10, GoogleMapsCompatible_Level6.
- MODIS_Terra_L3_NDVI_16Day, date 2026-10-16, GoogleMapsCompatible_Level9.

These are dated regional visual overlays. Pixels are not ingested as field-scale model observations. The app prints each selected layer's date and source; it does not claim they are live measurements. Online tiles need connectivity. The default offline view uses assets/nalgonda_outline.json, a simplified cached district boundary attributed to OpenStreetMap contributors under ODbL; it is not a substitute satellite observation.

No NASA logos or endorsement claims are used. NASA POWER drives model calculations; GIBS provides geographic context.
