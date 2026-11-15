# AI use: revised with OpenAI Codex under the team's direction. See AI_USE.md.
"""Discover GIBS layers, dates and tile URLs from NASA's WMTS capabilities.

Never synthesize layer IDs, matrix-set IDs or observation dates. Runtime caching
uses Person 2's engine.cache. Bundled XML is an explicitly stale offline snapshot,
not a second runtime cache. This imagery is visual context, never crop-model input.
"""
from __future__ import annotations

import calendar
import copy
import datetime as dt
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from engine.cache import ArrayCache
from engine import cache as data_cache

ROOT = Path(__file__).resolve().parent.parent
CAPS_URL = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi?SERVICE=WMTS&request=GetCapabilities'
CAPS_FILE = ROOT / 'data/raw/gibs_capabilities_epsg3857.xml'
OUT = ROOT / 'data/gibs_layers.json'
NS = {'w': 'http://www.opengis.net/wmts/1.0', 'ows': 'http://www.opengis.net/ows/1.1'}
CACHE = ArrayCache(16 * 1024 * 1024)
CAPABILITIES_TTL_SECONDS = 7 * 86400


def _utcnow():
    return dt.datetime.now(dt.timezone.utc)


def _memory_capabilities(*, force=False, offline=False, cache=None, timeout=20):
    store = CACHE if cache is None else cache
    cached = store.get(('gibs-capabilities', CAPS_URL))
    now = _utcnow()
    if cached and (not force or offline):
        age = (now - dt.datetime.fromisoformat(cached['data_as_of'])).total_seconds()
        if age < CAPABILITIES_TTL_SECONDS or offline:
            return {**cached, 'stale': age >= CAPABILITIES_TTL_SECONDS}
    error = None
    if not offline:
        try:
            response = requests.get(CAPS_URL, timeout=timeout)
            response.raise_for_status()
            xml = response.text
            parsed = parse_layers(xml)
            if not parsed:
                raise ValueError('NASA capabilities contain no usable imagery layers.')
            value = {'xml': xml, 'source': CAPS_URL, 'data_as_of': now.isoformat(), 'stale': False}
            store[('gibs-capabilities', CAPS_URL)] = value
            return dict(value)
        except (requests.RequestException, ValueError, ET.ParseError) as exc:
            error = type(exc).__name__
    if cached:
        return {**cached, 'stale': True, 'fallback_reason': error or 'Offline mode'}
    if CAPS_FILE.exists():
        xml = CAPS_FILE.read_text()
        if not parse_layers(xml):
            raise ValueError('Bundled NASA capabilities contain no usable layers.')
        # Clone time is not the dataset retrieval time.
        try:
            asof = json.loads(OUT.read_text()).get('retrieved')
        except (OSError, ValueError):
            asof = None
        return {'xml': xml, 'source': CAPS_URL, 'data_as_of': asof, 'stale': True,
                'fallback_reason': error or 'Offline bundled capabilities snapshot'}
    raise ConnectionError('NASA GIBS unavailable and no capabilities snapshot is present.')



def fetch_capabilities(*, force=False, offline=False, cache=None, timeout=20, precache=False):
    """Use Person 2's expiring disk/seed cache; injected ArrayCache remains test-compatible."""
    offline = offline or data_cache.offline()
    if cache is not None:
        return _memory_capabilities(force=force, offline=offline, cache=cache, timeout=timeout)
    kind, key = 'gibs', 'wmts_epsg3857_v1'
    def download():
        response = requests.get(CAPS_URL, timeout=timeout)
        response.raise_for_status()
        if not parse_layers(response.text):
            raise ValueError('NASA capabilities contain no usable layers.')
        return {'xml': response.text}
    if offline or data_cache.offline():
        cached = data_cache.read(kind, key)
        if cached is None:
            return _memory_capabilities(offline=True, cache=ArrayCache(1))
        payload, meta = cached
        meta = {**meta, 'stale': not data_cache.is_fresh(meta)}
    else:
        try:
            payload, meta = data_cache.fetch_cached(kind, key, download, source='NASA GIBS WMTS capabilities',
                                                  url=CAPS_URL, refresh='force' if force else 'auto', precache=precache)
        except data_cache.DataUnavailable:
            return _memory_capabilities(offline=True, cache=ArrayCache(1))
    if precache:
        # Promote a fresh runtime entry as well: fetch_cached can return it without writing a seed.
        data_cache.write(kind, key, payload, source='NASA GIBS WMTS capabilities', url=CAPS_URL,
                         precache=True, data_as_of=meta['data_as_of'])
    persisted = data_cache.read(kind, key)
    return {'xml': payload['xml'], 'source': CAPS_URL, 'data_as_of': meta['data_as_of'],
            'stale': meta.get('stale', False), 'persistent_cache': bool(persisted and persisted[0] == payload),
            'precache_written': bool(precache and (data_cache.PRECACHE_DIR / kind / (key + '.json.gz')).is_file())}

def get_capabilities(force=False, **kwargs):
    """Compatibility wrapper for existing callers expecting XML text."""
    return fetch_capabilities(force=force, **kwargs)['xml']


def parse_layers(xml_text=None):
    root = ET.fromstring(xml_text if xml_text is not None else get_capabilities())
    contents = root.find('w:Contents', NS)
    if contents is None:
        return {}
    matrices = {}
    for matrix in contents.findall('w:TileMatrixSet', NS):
        name = matrix.findtext('ows:Identifier', namespaces=NS)
        crs = matrix.findtext('ows:SupportedCRS', namespaces=NS) or ''
        if name and (crs.endswith('3857') or crs.endswith('900913')):
            levels = [int(m.findtext('ows:Identifier', namespaces=NS)) for m in matrix.findall('w:TileMatrix', NS)
                      if (m.findtext('ows:Identifier', namespaces=NS) or '').isdigit()]
            if levels:
                matrices[name] = max(levels)
    out = {}
    for layer in contents.findall('w:Layer', NS):
        ident = layer.findtext('ows:Identifier', namespaces=NS)
        matrix_sets = [link.findtext('w:TileMatrixSet', namespaces=NS) for link in layer.findall('w:TileMatrixSetLink', NS)]
        matrix_sets = [name for name in matrix_sets if name in matrices]
        formats = [el.text for el in layer.findall('w:Format', NS)]
        templates = [r for r in layer.findall('w:ResourceURL', NS)
                     if r.get('resourceType') == 'tile' and r.get('format', '') in ('image/png', 'image/jpeg')]
        template = next((r.get('template') for r in templates if '{Time}' in (r.get('template') or '')), None)
        dimension = next((d for d in layer.findall('w:Dimension', NS)
                          if (d.findtext('ows:Identifier', namespaces=NS) or '').lower() == 'time'), None)
        if not ident or not matrix_sets or not template or dimension is None:
            continue
        ranges = [el.text for el in dimension.findall('w:Value', NS) if el.text]
        if not ranges:
            continue
        out[ident] = {'title': layer.findtext('ows:Title', namespaces=NS) or ident,
                      'format': next((fmt for fmt in formats if fmt in ('image/png', 'image/jpeg')), None),
                      'tile_matrix_set': matrix_sets, 'max_native_zoom': matrices[matrix_sets[0]],
                      'time_ranges': ranges, 'tile_template': template,
                      'default_time': dimension.findtext('w:Default', namespaces=NS)}
    return out


def _date(value):
    # Daily/composite imagery is selected by date. Subdaily ranges are rejected below.
    return dt.date.fromisoformat(value[:10])


def _period(value):
    match = re.fullmatch(r'P([1-9]\d*)([DMY])', value)
    if not match:
        raise ValueError(f'Unsupported imagery period {value}; choose a daily or calendar composite layer.')
    return int(match[1]), match[2]


def _shift_months(anchor, months):
    y, m = divmod(anchor.year * 12 + anchor.month - 1 + months, 12)
    return dt.date(y, m + 1, min(anchor.day, calendar.monthrange(y, m + 1)[1]))


def candidate_dates(layer, n=6, *, on_or_before=None):
    """Newest advertised dates; intervals are anchored at their START, never their end.

    Handles date gaps, singleton days, PnD, PnM and PnY composites. No extrapolation
    outside the actual intervals and no guessed observation dates.
    """
    if n <= 0:
        return []
    limit = on_or_before or _utcnow().date()
    dates = set()
    for interval in layer.get('time_ranges', []):
        parts = interval.split('/')
        if len(parts) == 1:
            value = _date(parts[0])
            if value <= limit:
                dates.add(value)
            continue
        if len(parts) != 3:
            raise ValueError('Malformed NASA imagery time interval.')
        start, end = _date(parts[0]), min(_date(parts[1]), limit)
        step, unit = _period(parts[2])
        if end < start:
            continue
        if unit == 'D':
            count = (end - start).days // step
            for i in range(count, max(-1, count - n), -1):
                dates.add(start + dt.timedelta(days=i * step))
        else:
            months = step * (12 if unit == 'Y' else 1)
            count = ((end.year - start.year) * 12 + end.month - start.month) // months
            while count >= 0 and _shift_months(start, count * months) > end:
                count -= 1
            for i in range(count, max(-1, count - n), -1):
                dates.add(_shift_months(start, i * months))
    return sorted(dates, reverse=True)[:n]


def tile_url_template(layer, date, layers=None):
    layers = parse_layers() if layers is None else layers
    if layer not in layers:
        raise ValueError('Layer is absent from NASA capabilities.')
    item = layers[layer]
    when = _date(str(date))
    if when not in candidate_dates(item, n=1, on_or_before=when):
        raise ValueError('Date is not advertised for this NASA layer.')
    url = item['tile_template'].replace('{Time}', when.isoformat()).replace('{TileMatrixSet}', item['tile_matrix_set'][0])
    return url.replace('{TileMatrix}', '{z}').replace('{TileRow}', '{y}').replace('{TileCol}', '{x}')


def lonlat_to_tile(lat, lon, z):
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or not 0 <= z <= 24:
        raise ValueError('Invalid map coordinates or zoom.')
    lat = max(-85.05112878, min(85.05112878, lat))
    n = 2 ** z
    x = max(0, min(n - 1, int((lon + 180) / 360 * n)))
    y = max(0, min(n - 1, int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)))
    return z, y, x


def check_tile(layer, date, layers=None, tile=None, timeout=15):
    z, y, x = tile or lonlat_to_tile(17.5, 78.5, 5)
    url = tile_url_template(layer, date, layers).format(z=z, y=y, x=x)
    response = requests.get(url, timeout=timeout)
    mime = response.headers.get('content-type', '').split(';')[0].lower()
    valid = response.status_code == 200 and mime in ('image/png', 'image/jpeg') and bool(response.content)
    return {'url': url, 'status': response.status_code, 'bytes': len(response.content),
            'content_type': mime, 'valid_image_response': valid}


def discover_layers(*, offline=False, force=False, verify_tiles=False, cache=None, lat=17.5, lon=78.5, precache=False):
    caps = fetch_capabilities(offline=offline, force=force, cache=cache, precache=precache)
    layers = parse_layers(caps['xml'])
    groups = {'soil_moisture': [], 'ndvi': []}
    for ident, item in layers.items():
        name = ident.upper()
        if 'SMAP' in name and 'SOIL_MOISTURE' in name and 'UNCERTAINTY' not in name:
            groups['soil_moisture'].append(ident)
        elif 'MODIS' in name and 'NDVI' in name:
            groups['ndvi'].append(ident)
    groups['soil_moisture'].sort(key=lambda x: ('ROOT_ZONE' not in x.upper(), 'ANALYZED' not in x.upper(), x))
    groups['ndvi'].sort(key=lambda x: ('16DAY' not in x.upper(), 'TERRA' not in x.upper(), x))
    out = {'capabilities_url': CAPS_URL, 'retrieved': caps['data_as_of'], 'data_as_of': caps['data_as_of'],
           'stale': caps['stale'], 'fallback_reason': caps.get('fallback_reason'),
           'cache_note': 'Person 2 engine.cache disk/seed backend (7-day GIBS expiry).',
           'persistent_cache': caps.get('persistent_cache', False), 'precache_written': caps.get('precache_written', False),
           'center': {'lat': lat, 'lon': lon, 'default_zoom': 8}, 'layers': {}, 'primary': {}}
    for kind, identifiers in groups.items():
        entries = []
        verification_attempts = 0
        # One selected layer per family keeps discovery bounded; use the next if verification fails.
        for ident in identifiers:
            item = layers[ident]
            try:
                dates = candidate_dates(item, n=8)
            except ValueError:
                continue
            if not dates:
                continue
            chosen = dates[0]
            verified = None
            if verify_tiles:
                for when in dates[:3]:
                    if verification_attempts >= 3:
                        break
                    verification_attempts += 1
                    try:
                        response = check_tile(ident, when, layers, tile=lonlat_to_tile(lat, lon, min(5, item['max_native_zoom'])), timeout=8)
                    except requests.RequestException:
                        continue
                    if response['valid_image_response']:
                        chosen, verified = when, {'date': when.isoformat(), **response}
                        break
                if verified is None:
                    if verification_attempts >= 3:
                        break
                    continue
            entry = {**copy.deepcopy(item), 'id': ident, 'name': item['title'], 'date': chosen.isoformat(),
                     'available_dates': [d.isoformat() for d in dates],
                     'first_date': min(_date(v.split('/')[0]) for v in item['time_ranges']).isoformat(),
                     'last_date': dates[0].isoformat(), 'verified_tile': verified,
                     'tile_url_template': tile_url_template(ident, chosen, layers),
                     'url': tile_url_template(ident, chosen, layers),
                     'badge': 'Observed', 'data_as_of': caps['data_as_of'], 'stale': caps['stale']}
            entries.append(entry)
            break
        out['layers'][kind] = entries
        out['primary'][kind] = entries[0]['id'] if entries else None
    out['fallback'] = 'If no advertised layer/date is available, omit that overlay. Never fabricate a satellite image.'
    return out


def map_layers(**kwargs):
    """Public integration piece: api.gibs_layers() can delegate to this."""
    result = discover_layers(**kwargs)
    return [entry for group in result['layers'].values() for entry in group]


def main():
    result = discover_layers(verify_tiles=True, precache=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    CAPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    caps = fetch_capabilities()
    # Keep the exported XML and its retrieval metadata consistent for offline use.
    CAPS_FILE.write_text(caps['xml'])
    # This is a user-requested export for the existing map, not runtime cache storage.
    OUT.write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    print(json.dumps(main(), indent=2))
