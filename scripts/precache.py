# Source completion is reported per site; suppressed observations remain unavailable.
# AI use: written with OpenAI Codex under the team's direction. See AI_USE.md.
"""Warm demo/validation locations through engine.api; report missing integrations honestly.

python scripts/precache.py --dry-run
python scripts/precache.py --validation-sites config/validation/sites.yaml --output output/precache.json

No direct fetcher imports, guessed prices, API keys in output, or separate caching
backend. Exported JSON is a run report, not a replacement for Person 2's cache.
"""
from __future__ import annotations

import argparse
from dataclasses import fields, is_dataclass
import datetime as dt
import inspect
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml
from engine import api

_DEMO_CONFIG = yaml.safe_load((ROOT / 'config/assumptions/setup.yaml').read_text())['demo_presets']
DEMO_SITES = [{'id': 'demo-' + key, 'lat': row['lat']['value'], 'lon': row['lon']['value'], 'kind': 'demo'}
              for key, row in _DEMO_CONFIG.items()]


def record(value):
    if is_dataclass(value):
        return {f.name: getattr(value, f.name) for f in fields(value)}
    return value if isinstance(value, dict) else {}


def site_list(validation_path):
    path = Path(validation_path)
    if not path.exists():
        raise FileNotFoundError(f'Person 3 validation-site list is missing: {path}. Pull their merged list or pass --validation-sites.')
    config = yaml.safe_load(path.read_text()) or {}
    sites = [dict(site) for site in DEMO_SITES]
    seen = {s['id'] for s in sites}
    for row in config.get('sites', []):
        if not isinstance(row, dict) or not all(key in row for key in ('id', 'lat', 'lon', 'fips', 'crops')):
            raise ValueError('Validation sites need id, lat, lon, fips and crops.')
        lat, lon = float(row['lat']), float(row['lon'])
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError('Validation coordinates must be finite and in range.')
        if row['id'] in seen:
            raise ValueError(f'Duplicate site ID: {row["id"]}')
        seen.add(row['id'])
        sites.append({**row, 'kind': 'validation', 'lat': lat, 'lon': lon})
    if len(sites) == len(DEMO_SITES):
        raise ValueError('The validation-site list is empty.')
    return sites


def check_site(site):
    data = record(site)
    missing = []
    weather = data.get('weather')
    if weather is None or not hasattr(weather, '__len__') or len(weather) == 0:
        missing.append('NASA weather')
    awc = record(data.get('soil')).get('awc_mm_per_m')
    if not isinstance(awc, (int, float)) or not math.isfinite(awc) or awc <= 0:
        missing.append('usable soil water capacity')
    defaults = record(data.get('us_defaults'))
    for key in ('crops', 'yields', 'prices', 'costs'):
        if not defaults.get(key):
            missing.append(f'US {key}')
        elif key != 'crops':
            for crop in defaults.get('crops') or []:
                value = defaults[key].get(crop)
                value = value.get('value') if isinstance(value, dict) else value
                if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    missing.append(f'US {key} for {crop}: input needed')
    if defaults.get('irrigated_share') is None:
        missing.append('US irrigation coverage')
    return missing


def precache(sites, *, offline=False, dry_run=False):
    result = {'run_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'status': 'planned' if dry_run else 'running',
              'sites': [], 'problems': [], 'persistent_cache_verified': False}
    if dry_run:
        result['sites'] = [{**s, 'status': 'planned'} for s in sites]
        return result
    lookup = getattr(api, 'precache_site', None) or getattr(api, 'get_site', None)
    if not callable(lookup):
        result.update(status='blocked', problems=['Person 1 must expose v4 engine.api.get_site before this run.'])
        return result
    if offline and 'offline' not in inspect.signature(lookup).parameters:
        result.update(status='blocked', problems=['get_site does not expose offline mode; refusing to make potentially online calls.'])
        return result
    cache_info = getattr(api, 'cache_info', None)
    if callable(cache_info):
        try:
            result['persistent_cache_verified'] = record(cache_info()).get('persistent') is True
        except Exception as exc:
            result['problems'].append(f'Cache status unavailable ({type(exc).__name__}).')
    for spec in sites:
        row = {**spec}
        try:
            site = lookup(spec['lat'], spec['lon'], **({'offline': True} if offline else {}))
            missing = check_site(site)
            row.update(status='incomplete' if missing else 'loaded', missing=missing,
                       data_as_of=record(site).get('data_as_of'), badges=record(site).get('badges'))
            if spec['kind'] == 'validation':
                # County defaults are not the historical yield series required by the hindcast.
                hook = getattr(api, 'precache_validation_site', None)
                if not callable(hook):
                    row['status'] = 'incomplete'
                    row['missing'].append('historical county yields: Person 1/3 must expose precache_validation_site')
                else:
                    report = record(hook(spec, offline=offline))
                    row['validation'] = report
                    if not report.get('complete'):
                        row['status'] = 'incomplete'
                        row['missing'].append('complete historical county yields')
        except Exception as exc:
            row.update(status='failed', error_type=type(exc).__name__)
            # Exception strings may contain query credentials; never include them in exports.
        result['sites'].append(row)
    imagery = getattr(api, 'gibs_layers', None)
    if callable(imagery):
        try:
            layers = imagery(offline=offline, precache=True)
            result['gibs_layers'] = [{key: record(layer).get(key) for key in ('id', 'date', 'data_as_of', 'stale')} for layer in layers]
            if len(layers) < 2:
                result['problems'].append('Both required GIBS imagery families are not available.')
        except Exception as exc:
            result['problems'].append(f'GIBS discovery failed ({type(exc).__name__}).')
    else:
        result['problems'].append('Person 1 must expose api.gibs_layers for imagery pre-caching.')
    if callable(cache_info):
        try:
            result['persistent_cache_verified'] = record(cache_info()).get('persistent') is True
        except Exception:
            pass
    if not result['persistent_cache_verified']:
        result['problems'].append('Persistent cache is not verified through api.cache_info(); wire the published Person 2 disk/seed cache into the public API.')
    result['status'] = 'complete' if all(r['status'] == 'loaded' for r in result['sites']) and not result['problems'] else 'incomplete'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validation-sites', type=Path, default=ROOT / 'config/validation/sites.yaml')
    parser.add_argument('--output', type=Path, default=ROOT / 'output/precache-report.json')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args(argv)
    if args.offline:
        import os
        os.environ['ROTATIONLAB_OFFLINE'] = '1'
    try:
        sites = site_list(args.validation_sites)
        report = precache(sites, offline=args.offline, dry_run=args.dry_run)
    except (OSError, ValueError) as exc:
        report = {'status': 'blocked', 'problems': [str(exc)], 'sites': []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({'status': report['status'], 'sites': len(report['sites']), 'output': str(args.output), 'problems': report.get('problems', [])}, indent=2))
    return 0 if report['status'] in ('complete', 'planned') else 2


if __name__ == '__main__':
    raise SystemExit(main())
