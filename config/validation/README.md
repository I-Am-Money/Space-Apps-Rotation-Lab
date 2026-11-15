# Validation config (Person 3)

- `sites.yaml`: 12 US counties across 8 regions for the hindcast (R20), with Census Gazetteer centroids and
  the NASS Quick Stats query fields per crop.
- `results.csv` (written by `python -m engine.hindcast`): the validation table the app shows through
  `api.validation_summary()`. If it is missing, the app shows "validation not run yet".

## Request to Person 2 (pre-cache)

For every site in `sites.yaml`, please pre-cache:
1. NASA POWER daily weather (community AG) at the site lat/lon, 1981 to latest full year.
2. NASS Quick Stats county yields (SURVEY, COUNTY, YIELD, all years) for each listed crop, using the
   `crop_nass` fields; use `nass_practice` where the county series is split by practice.

The hindcast looks for a yield loader in `engine.fetch_nass` (`county_yields(fips, crop)` returning
year, yield_kg_ha). If yours has another name, tell Person 3 and it will be wired in hindcast.py.
India (ICRISAT) is not added: the v4 engine does not load it yet.
