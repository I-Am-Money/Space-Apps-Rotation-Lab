# AI use: written with OpenAI Codex under the team's direction. See AI_USE.md.
"""Feature 1 site assembly. Other features are reached exclusively through engine.api."""
import math
from concurrent.futures import ThreadPoolExecutor
import requests

from engine import cache, fetch_power, fetch_ssurgo, fetch_soilgrids, climate_card

CENSUS_URL = 'https://geocoding.geo.census.gov/geocoder/geographies/coordinates'


def locate(lat, lon, *, precache=False):
    """Census county lookup; never infer a county or country from a bounding box."""
    # Outside the western/northern hemisphere US region, US county data cannot apply.
    if lon > -60 or lat < 15:
        return {'country': 'Non-US', 'fips': None, 'state': None, 'badge': 'assumption'}
    key = 'census_' + cache.location_key(lat, lon, 5)
    def query():
        response = requests.get(CENSUS_URL, params={'x': lon, 'y': lat, 'benchmark': 'Public_AR_Current',
                                'vintage': 'Current_Current', 'layers': 'Counties', 'format': 'json'}, timeout=15)
        response.raise_for_status()
        counties = response.json().get('result', {}).get('geographies', {}).get('Counties') or []
        if not counties:
            return {'country': 'Non-US', 'fips': None, 'state': None, 'badge': 'observed'}
        row = counties[0]
        return {'country': 'USA', 'fips': row['GEOID'], 'state_fips': row['STATE'],
                'county': row.get('NAME'), 'badge': 'observed'}
    try:
        value, meta = cache.fetch_cached('geo', key, query, 'US Census coordinate geocoder', CENSUS_URL, precache=precache)
        return {**value, 'data_as_of': meta['data_as_of'], 'stale': meta['stale']}
    except cache.DataUnavailable:
        return {'country': 'Unknown', 'fips': None, 'state': None, 'badge': 'assumption',
                'note': 'County/country lookup unavailable. Enter economics manually; local validation is unconfirmed.'}


def get_site(lat, lon, *, precache=False, offline=False):
    from engine import api
    if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (lat, lon)) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError('Enter a finite latitude -90..90 and longitude -180..180.')
    if offline and not cache.offline():
        # Avoid a process-wide environment mutation that could affect other users.
        raise ValueError('Strict offline site loading requires ROTATIONLAB_OFFLINE=1 on the server.')
    with ThreadPoolExecutor(max_workers=2) as pool:
        weather_job = pool.submit(fetch_power.load_site_weather, lat, lon, precache=precache)
        geo = locate(lat, lon, precache=precache)
        weather = weather_job.result()
    if geo.get('fips'):
        state = api.us_state(geo['state_fips'])
        try:
            soil = fetch_ssurgo.get_soil_us(lat, lon, precache=precache)
        except cache.DataUnavailable:
            soil = None
        if soil is None:
            soil = fetch_soilgrids.fallback_soil(reason='SSURGO and STATSGO2 unavailable; texture assumed loam.')
        defaults = api.us_defaults(geo['fips'])
        rules = api.us_coverage(state, geo['fips'], defaults)
        defaults['crops'] = rules['offered']
        defaults['notes'] = {**defaults.get('notes', {}), 'coverage': rules}
        us = api.USDefaults(**{key: defaults.get(key) for key in ('crops', 'yields', 'prices', 'costs', 'irrigated_share', 'level', 'badges')})
    else:
        state, us = None, None
        soil = fetch_soilgrids.get_soilgrids(lat, lon, precache=precache, offline=offline)
    if geo.get('fips') and state in ('AK', 'HI'):
        raise ValueError('Alaska and Hawaii are not supported in this version.')
    trend = climate_card.climate_trend(weather, lat)
    info = api.SoilInfo(texture=soil.get('texture'), awc_mm_per_m=soil['awc_mm_per_m'],
                       organic_matter_pct=soil.get('organic_matter_pct'), source=soil['source'],
                       badge=str(soil['badge']).lower())
    # Carry genuine supporting metadata without changing the shared dataclass signature.
    for key in ('hydrologic_group', 'data_as_of', 'stale', 'mukey', 'map_unit', 'ph', 'badges'):
        if key in soil:
            setattr(info, key, soil[key])
    site = api.Site(float(lat), float(lon), geo['country'], state, geo.get('fips'), weather, info,
                    weather.attrs.get('elevation_m'), trend, us, weather.attrs.get('data_as_of'),
                    badges={'weather': 'estimated' if any(weather.attrs.get('filled_days', {}).values()) else 'observed',
                            'soil': info.badge, 'elevation_m': 'estimated', 'us_defaults': ('estimated' if defaults.get('available', True) and defaults.get('crops') else 'assumption') if us else 'your_input'},
                    example=False)
    site.currency = 'USD' if us is not None else None
    if us is not None:
        for key in ('notes', 'available', 'data_as_of', 'source'):
            setattr(us, key, defaults.get(key))
    site.source_dates = {'weather': weather.attrs.get('data_as_of'), 'soil': soil.get('data_as_of'),
                         'us_defaults': None if us is None else defaults.get('data_as_of')}
    site.notes = ([geo['note']] if geo.get('note') else []) + ([] if us is None else rules['notes'])
    if us is not None:
        site.notes += [str(v) for v in defaults.get('notes', {}).values() if isinstance(v, str) and str(v) not in site.notes]
    return site
