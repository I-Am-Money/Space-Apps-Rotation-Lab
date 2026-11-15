# AI use: written with OpenAI Codex under the team's direction. See AI_USE.md.
"""ISRIC SoilGrids point soil estimates for non-US locations.

Unit conversions follow the API's d_factor, not a guessed /10. Available water
capacity is the thickness-weighted difference between 33-kPa and 1500-kPa water
content, in mm/m over 0–100 cm. Prediction quantiles are not farm measurements.
Missing water properties use FAO-56 Table 19 texture ranges, explicitly Assumption.
All runtime caching uses Person 2's engine.cache. No local-file cache is invented.
"""
from __future__ import annotations

import copy
import datetime as dt
import math
from numbers import Real

import requests
from engine.cache import ArrayCache
from engine import cache as data_cache

URL = 'https://rest.isric.org/soilgrids/v2.0/properties/query'
ISRIC_DOC = 'https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_01.html'
FAO56_SOURCE = 'https://www.fao.org/4/X0490E/x0490e0c.htm#table%2019'
DEPTHS = (('0-5cm', 5), ('5-15cm', 10), ('15-30cm', 15), ('30-60cm', 30), ('60-100cm', 40))
PROPERTIES = ('sand', 'silt', 'clay', 'wv0033', 'wv1500')
CACHE = ArrayCache(8 * 1024 * 1024)
TTL_SECONDS = 365 * 86400
# Direct ranges of theta_FC - theta_WP (m3/m3), Table 19, converted to mm/m.
FAO56_AWC_RANGES = {'sand': (50., 110.), 'loamy sand': (60., 120.),
                    'sandy loam': (110., 150.), 'loam': (130., 180.),
                    'silt loam': (130., 190.), 'silt': (160., 200.),
                    'silty clay loam': (130., 180.), 'silty clay': (130., 190.),
                    'clay': (120., 200.)}
# These texture names lack a direct row in Table 19. Do not assign an invented value.
NEAREST_TEXTURE = {'clay loam': 'loam', 'sandy clay loam': 'sandy loam', 'sandy clay': 'clay'}


def _valid(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def _coordinates(lat, lon):
    if not _valid(lat) or not _valid(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError('Latitude must be finite and between -90 and 90; longitude between -180 and 180.')
    return float(lat), float(lon)


def texture_class(sand, silt, clay):
    """USDA textural triangle, percentages of the fine-earth fraction."""
    if any(not _valid(v) or v < 0 or v > 100 for v in (sand, silt, clay)):
        raise ValueError('Invalid texture fractions.')
    total = sand + silt + clay
    if not 95 <= total <= 105:
        raise ValueError('Texture fractions do not sum approximately to 100%.')
    # Independently predicted fractions may differ slightly from 100; normalize transparently.
    sand, silt, clay = [v * 100 / total for v in (sand, silt, clay)]
    if silt + 1.5 * clay < 15:
        return 'sand'
    if silt + 2 * clay < 30:
        return 'loamy sand'
    if (7 <= clay < 20 and sand > 52 and silt + 2 * clay >= 30) or (clay < 7 and silt < 50 and silt + 2 * clay >= 30):
        return 'sandy loam'
    if 7 <= clay < 27 and 28 <= silt < 50 and sand <= 52:
        return 'loam'
    if (silt >= 50 and 12 <= clay < 27) or (50 <= silt < 80 and clay < 12):
        return 'silt loam'
    if silt >= 80 and clay < 12:
        return 'silt'
    if 20 <= clay < 35 and silt < 28 and sand > 45:
        return 'sandy clay loam'
    if 27 <= clay < 40 and sand <= 20:
        return 'silty clay loam'
    if 27 <= clay < 40 and 20 < sand <= 45:
        return 'clay loam'
    if clay >= 35 and sand > 45:
        return 'sandy clay'
    if clay >= 40 and silt >= 40:
        return 'silty clay'
    return 'clay'


def fallback_soil(texture=None, *, reason, data_as_of=None):
    requested = str(texture).lower().strip() if texture else None
    if requested is not None and requested not in FAO56_AWC_RANGES and requested not in NEAREST_TEXTURE:
        raise ValueError('Enter a supported USDA soil texture for the fallback.')
    used = NEAREST_TEXTURE.get(requested, requested) or 'loam'
    lo, hi = FAO56_AWC_RANGES[used]
    note = 'Texture assumed loam because no usable texture information was available.' if requested is None else ''
    if requested in NEAREST_TEXTURE:
        note = f'No direct Table 19 row for {requested}; nearest class {used} is a team assumption to verify.'
    return {'texture': requested or used, 'awc_mm_per_m': (lo + hi) / 2, 'awc_low': lo, 'awc_high': hi,
            'organic_matter_pct': None, 'source': 'FAO-56 Table 19 typical texture range',
            'source_url': FAO56_SOURCE, 'badge': 'Assumption', 'data_as_of': data_as_of,
            'badges': {'awc_mm_per_m': 'Assumption', 'texture': 'Assumption'},
            'fallback': True, 'fallback_reason': reason, 'note': note,
            'range_note': 'Published texture range; midpoint is a planning assumption, not a confidence interval.',
            'stale': False, 'depth_cm': [0, 100]}


def parse_soilgrids(payload, *, fallback_texture=None, data_as_of=None):
    """Parse the official JSON response. Missing depths never get silently dropped."""
    properties = payload.get('properties') if isinstance(payload, dict) else None
    if not isinstance(properties, dict) or not isinstance(properties.get('layers'), list):
        return fallback_soil(fallback_texture, reason='Malformed SoilGrids properties response.', data_as_of=data_as_of)
    layers = {layer.get('name'): layer for layer in properties['layers'] if isinstance(layer, dict)}
    def weighted(name, stat='mean'):
        layer = layers.get(name)
        if not layer:
            raise ValueError(f'SoilGrids property {name} is unavailable.')
        units = layer.get('unit_measure') or {}
        factor = units.get('d_factor')
        target = str(units.get('target_units', '')).lower().replace(' ', '').replace('^', '')
        expected = ('%', '10-2cm3/cm3', 'cm3/100cm3') if name.startswith('wv') else ('%', 'g/100g')
        if target not in expected:
            raise ValueError(f'SoilGrids target unit is unsupported or missing for {name}.')
        if not _valid(factor) or factor <= 0:
            raise ValueError(f'SoilGrids conversion metadata missing for {name}.')
        by_depth = {depth.get('label'): depth.get('values') or {} for depth in layer.get('depths', []) if isinstance(depth, dict)}
        total = 0.
        for label, thickness in DEPTHS:
            value = by_depth.get(label, {}).get(stat)
            if not _valid(value) or value < 0:
                raise ValueError(f'SoilGrids {name} {label} {stat} is missing or invalid.')
            total += value / factor * thickness
        return total / sum(thickness for _, thickness in DEPTHS)
    texture_values = {}
    texture = fallback_texture
    try:
        texture_values = {f'{name}_pct': weighted(name) for name in ('sand', 'silt', 'clay')}
        texture = texture_class(*(texture_values[f'{name}_pct'] for name in ('sand', 'silt', 'clay')))
    except ValueError:
        pass
    try:
        fc, wp = weighted('wv0033'), weighted('wv1500')
        if not 0 <= wp < fc <= 100:
            raise ValueError('SoilGrids water contents are not physically valid (0 <= WP < FC <= 100%).')
        awc = (fc - wp) * 10
        # Interval arithmetic uses the marginal extremes. It is a conservative envelope,
        # NOT a calibrated joint 90% confidence interval (cross-property correlation unknown).
        try:
            low = max(0., (weighted('wv0033', 'Q0.05') - weighted('wv1500', 'Q0.95')) * 10)
            high = max(awc, (weighted('wv0033', 'Q0.95') - weighted('wv1500', 'Q0.05')) * 10)
            if low > awc or high > 1000:
                raise ValueError('Invalid water prediction quantiles.')
        except ValueError:
            low, high = None, None
        out = {'texture': texture, **texture_values, 'awc_mm_per_m': awc, 'awc_low': low, 'awc_high': high,
               'field_capacity_pct': fc, 'wilting_point_pct': wp, 'organic_matter_pct': None,
               'source': 'ISRIC SoilGrids 2.0, 250 m prediction, 0–100 cm thickness-weighted',
               'source_url': URL, 'documentation_url': ISRIC_DOC, 'badge': 'Estimated',
               'badges': {'awc_mm_per_m': 'Estimated', 'texture': 'Estimated' if texture_values else 'Assumption'},
               'data_as_of': data_as_of, 'fallback': False, 'stale': False, 'depth_cm': [0, 100],
               'range_note': 'Conservative envelope from marginal 5th/95th predictions; not a joint confidence interval.',
               'note': 'Fine-earth water retention; no coarse-fragment correction. Organic matter is not inferred from texture. Texture classification normalizes valid fractions summing to 95–105%.'}
        return out
    except ValueError as exc:
        out = fallback_soil(texture, reason=str(exc), data_as_of=data_as_of)
        out.update(texture_values)
        if texture_values:
            out['badges']['texture'] = 'Estimated'
        return out


def _memory_soilgrids(lat, lon, *, texture=None, offline=False, force=False, cache=None, timeout=20, include_quantiles=False):
    """Location lookup for api.get_site's non-US soil piece.

    A caller can inject Person 2's persistent mapping-compatible cache when ready.
    Stale successful estimates may be used offline, with their original retrieval date.
    Fallback results are never stored as successful SoilGrids responses.
    """
    lat, lon = _coordinates(lat, lon)
    store = CACHE if cache is None else cache
    # Avoid location collisions: rounding only represents sub-centimeter precision.
    key = ('soilgrids-v2', round(lat, 8), round(lon, 8)) + (('quantiles',) if include_quantiles else ())
    cached = store.get(key)
    now = dt.datetime.now(dt.timezone.utc)
    if cached and (not force or offline):
        age = (now - dt.datetime.fromisoformat(cached['data_as_of'])).total_seconds()
        if age < TTL_SECONDS or offline:
            result = parse_soilgrids(cached['payload'], fallback_texture=texture, data_as_of=cached['data_as_of'])
            result.update(stale=age >= TTL_SECONDS, lat=lat, lon=lon)
            return result
    reason = 'Offline mode; no cached SoilGrids response.'
    if not offline:
        params = [('lat', lat), ('lon', lon)] + [('property', p) for p in PROPERTIES] + \
                 [('depth', d) for d, _ in DEPTHS] + [('value', stat) for stat in (('mean', 'Q0.05', 'Q0.95') if include_quantiles else ('mean',))]
        try:
            response = requests.get(URL, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError('SoilGrids response is not a JSON object.')
            result = parse_soilgrids(payload, fallback_texture=texture, data_as_of=now.isoformat())
            # Cache texture-only responses too, but always preserve their AWC fallback badge.
            if isinstance(payload.get('properties'), dict) and payload['properties'].get('layers'):
                store[key] = {'payload': copy.deepcopy(payload), 'data_as_of': now.isoformat()}
            result.update(lat=lat, lon=lon)
            return result
        except (requests.RequestException, ValueError) as exc:
            reason = f'SoilGrids unavailable ({type(exc).__name__}).'
    if cached:
        result = parse_soilgrids(cached['payload'], fallback_texture=texture, data_as_of=cached['data_as_of'])
        result.update(stale=True, fallback_reason=reason, lat=lat, lon=lon)
        return result
    result = fallback_soil(texture, reason=reason)
    result.update(lat=lat, lon=lon)
    return result


def get_soilgrids(lat, lon, *, texture=None, offline=False, force=False, cache=None, timeout=20,
                  include_quantiles=False, precache=False):
    """Persistent, offline-safe default using Person 2's published cache API.

    Injecting ArrayCache is supported for isolated tests and legacy adapters. No
    independent disk-cache backend is used. Invalid/no-data payloads are not seeded.
    """
    offline = offline or data_cache.offline()
    if cache is not None:
        return _memory_soilgrids(lat, lon, texture=texture, offline=offline, force=force, cache=cache,
                                 timeout=timeout, include_quantiles=include_quantiles)
    lat, lon = _coordinates(lat, lon)
    key = 'soilgrids_' + data_cache.location_key(lat, lon, ndigits=5) + ('_quantiles' if include_quantiles else '_mean')
    def download():
        params = [('lat', lat), ('lon', lon)] + [('property', p) for p in PROPERTIES] + \
                 [('depth', d) for d, _ in DEPTHS] + [('value', stat) for stat in
                 (('mean', 'Q0.05', 'Q0.95') if include_quantiles else ('mean',))]
        response = requests.get(URL, params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        parsed = parse_soilgrids(payload, fallback_texture=texture)
        if parsed.get('fallback') and 'sand_pct' not in parsed:
            raise ValueError('SoilGrids returned no usable profile at this point.')
        return payload
    if offline or data_cache.offline():
        cached = data_cache.read('soil', key)
        if cached is None:
            out = fallback_soil(texture, reason='Offline mode; no cached SoilGrids profile.')
            return {**out, 'lat': lat, 'lon': lon, 'persistent_cache': False}
        payload, meta = cached
        meta = {**meta, 'stale': not data_cache.is_fresh(meta)}
    else:
        try:
            payload, meta = data_cache.fetch_cached('soil', key, download, source='ISRIC SoilGrids 2.0',
                                                  url=URL, refresh='force' if force else 'auto', precache=precache)
        except data_cache.DataUnavailable:
            out = fallback_soil(texture, reason='SoilGrids is unavailable or returned no usable profile; no cached estimate exists.')
            return {**out, 'lat': lat, 'lon': lon, 'persistent_cache': False}
    if precache:
        data_cache.write('soil', key, payload, source='ISRIC SoilGrids 2.0', url=URL,
                         precache=True, data_as_of=meta['data_as_of'])
    out = parse_soilgrids(payload, fallback_texture=texture, data_as_of=meta['data_as_of'])
    persisted = data_cache.read('soil', key)
    out.update(lat=lat, lon=lon, stale=meta.get('stale', False), persistent_cache=bool(persisted and persisted[0] == payload),
               precache_written=bool(precache and (data_cache.PRECACHE_DIR / 'soil' / (key + '.json.gz')).is_file()))
    return out


# Explicit alias for Person 1's get_site composition.
get_soil = get_soilgrids
