# Validation config (Person 3, Feature 4)

- `sites.yaml`: 14 US counties covering all 9 USDA ERS Farm Resource Regions, used for the hindcast (R20).
  Lat/lon are county internal points from the Census 2023 Gazetteer; `ers_region` comes from ERS reglink.xls.
- `precache_list.csv`: the same 14 sites as a flat list (id, fips, lat, lon, crops) for pre-caching.
- `standin_crops.yaml`: settings for the stand-in yield model, used only until the real single-season yield function is available.
- `results.csv` (written by `python -m engine.correction`, last run 2026-11-15 on real NASS and ICRISAT yields): the
  validation table the app shows through `api.validation_summary()`. If it is missing, the app shows "validation not run yet".

## Pre-cache request (to the cache owner, engine/cache.py)

For every row of `precache_list.csv`, please pre-cache with `refresh="auto", precache=True`:
1. NASA POWER daily weather (community AG) at lat/lon, 1981 to the latest full year (`fetch_power`).
2. NASS Quick Stats for all 14 counties (done 2026-11-15 without a key, through the Quick Stats website export):
   `python -m engine.fetch_nass --precache-validation`. This writes `data/precache/nass/`, which can be committed (public data, the key is never stored).
ERS costs and regions are already pre-cached in `data/precache/costs/` and `data/precache/geo/` (downloaded 2026-11-15).
India: `india.yaml` adds one district (Nalgonda, Telangana; jowar, bajra, pigeon pea) checked against ICRISAT district
yields with the same method. It is included only when the ICRISAT loader works.
