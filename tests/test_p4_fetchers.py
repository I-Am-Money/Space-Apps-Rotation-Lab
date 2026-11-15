# AI use: written with OpenAI Codex under the team's direction. See AI_USE.md.
"""Offline deterministic contract tests; live checks are recorded separately."""
import copy
import datetime as dt
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
import requests

from engine.cache import ArrayCache
from engine import economics as e, fetch_gibs as g, fetch_soilgrids as s
from scripts import precache as pc


@pytest.fixture(autouse=True)
def isolate_public_precache_hooks(monkeypatch):
    # Tests in this file inject providers; never call new real feature APIs accidentally.
    monkeypatch.delattr(pc.api, 'precache_site', raising=False)
    monkeypatch.setattr(pc.api, 'gibs_layers', lambda **kwargs: [], raising=False)


@pytest.mark.parametrize('crop,lb', [('maize', 56), ('sorghum', 56), ('soybean', 60), ('wheat_winter', 60)])
def test_bushel_hand_calculation(crop, lb):
    # A yield of exactly one standard bushel's kg on one acre must display 1 bu/acre.
    kg_ha = lb * .45359237 / .40468564224
    assert e.kg_ha_to_bushels_acre(kg_ha, crop) == pytest.approx(1, abs=1e-12)
    assert e.bushels_acre_to_kg_ha(1, crop) == pytest.approx(kg_ha)


def test_metric_profit_and_exact_units():
    np.testing.assert_allclose(e.profit_per_hectare([1000, 2000], .2, 150), [50, 250])
    assert e.currency_ha_to_acre(-1000) == pytest.approx(-404.68564224)
    assert e.kg_ha_to_quintals_per_acre(1000) == pytest.approx(4.0468564224)
    with pytest.raises(e.InputNeededError, match='no verified bushel weight'):
        e.kg_ha_to_bushels_acre(1000, 'cotton')


@pytest.mark.parametrize('price,cost', [(None, 1), (1, None), (np.nan, 1), (1, -1), (np.inf, 1)])
def test_no_missing_economic_defaults(price, cost):
    with pytest.raises(e.InputNeededError, match='Input needed'):
        e.profit_per_hectare(1000, price, cost)


def test_us_defaults_and_non_us_input_requirement():
    defaults = {'yields': {'maize': 1000}, 'prices': {'maize': .2}, 'costs': {'maize': 100}}
    assert e.resolve_crop_economics('maize', 'US', defaults)['price'] == .2
    with pytest.raises(e.InputNeededError):
        e.resolve_crop_economics('maize', 'India', defaults)
    result = e.resolve_crop_economics('maize', 'India', defaults,
                                     {'maize': {'yield': 1000, 'price': 0, 'cost': 0}})
    assert result['price'] == 0 and result['badges']['price'] == 'Your input'
    defaults['prices']['maize'] = {'value': .2, 'badge': 'placeholder'}
    with pytest.raises(e.InputNeededError, match='unverified'):
        e.resolve_crop_economics('maize', 'US', defaults)


def test_legacy_missing_price_is_input_needed(tmp_path):
    path = tmp_path / 'missing.yaml'
    path.write_text('operating_cost_rs_per_acre: {rice: 1}\n')
    prices = e.load_prices(path)
    assert prices['price_rs_per_quintal']['rice'] is None
    with pytest.raises(e.InputNeededError, match='price_rs_per_quintal'):
        e.plan_economics(['rice'], {'yield_kg_ha': np.array([[1000.]])}, prices=prices, n_credit=np.array([0.]))


def xml_fixture():
    return '''<Capabilities xmlns="http://www.opengis.net/wmts/1.0" xmlns:ows="http://www.opengis.net/ows/1.1"><Contents>
    <TileMatrixSet><ows:Identifier>ActualMatrixFromNASA</ows:Identifier><ows:SupportedCRS>urn:ogc:def:crs:EPSG::3857</ows:SupportedCRS><TileMatrix><ows:Identifier>5</ows:Identifier></TileMatrix></TileMatrixSet>
    <Layer><ows:Identifier>EXAMPLE_SMAP_ROOT_ZONE_SOIL_MOISTURE</ows:Identifier><ows:Title>EXAMPLE only</ows:Title><Format>image/png</Format>
    <Dimension><ows:Identifier>Time</ows:Identifier><Value>2026-01-01/2026-02-04/P16D</Value></Dimension>
    <TileMatrixSetLink><TileMatrixSet>ActualMatrixFromNASA</TileMatrixSet></TileMatrixSetLink>
    <ResourceURL resourceType="tile" format="image/png" template="https://gibs.earthdata.nasa.gov/wmts/EXAMPLE/default/{Time}/{TileMatrixSet}/{TileMatrix}/{TileRow}/{TileCol}.png"/>
    </Layer></Contents></Capabilities>'''


def test_date_steps_are_start_anchored_and_gaps_respected():
    layer = {'time_ranges': ['2026-01-01/2026-02-04/P16D', '2026-02-20']}
    assert g.candidate_dates(layer, n=4, on_or_before=dt.date(2026, 3, 1)) == [
        dt.date(2026, 2, 20), dt.date(2026, 2, 2), dt.date(2026, 1, 17), dt.date(2026, 1, 1)]
    layers = g.parse_layers(xml_fixture())
    ident = next(iter(layers))
    assert 'ActualMatrixFromNASA' in g.tile_url_template(ident, '2026-02-02', layers)
    with pytest.raises(ValueError, match='not advertised'):
        g.tile_url_template(ident, '2026-02-04', layers)


def test_calendar_months_do_not_drift_or_escape_range():
    layer = {'time_ranges': ['2024-01-31/2024-04-30/P1M']}
    assert g.candidate_dates(layer, n=10, on_or_before=dt.date(2024, 4, 30)) == [
        dt.date(2024, 4, 30), dt.date(2024, 3, 31), dt.date(2024, 2, 29), dt.date(2024, 1, 31)]


def test_actual_bundled_nasa_ids_not_guessed():
    layers = g.parse_layers(g.CAPS_FILE.read_text())
    assert any('SMAP' in name and 'Soil_Moisture' in name for name in layers)
    assert any('MODIS' in name and 'NDVI' in name for name in layers)
    assert all(layer['max_native_zoom'] >= 0 for layer in layers.values())


def test_gibs_cache_and_offline_metadata(monkeypatch):
    response = Mock(text=xml_fixture())
    response.raise_for_status.return_value = None
    fetch = Mock(return_value=response)
    monkeypatch.setattr(g.requests, 'get', fetch)
    cache = ArrayCache(100000)
    first = g.fetch_capabilities(cache=cache)
    second = g.fetch_capabilities(cache=cache, offline=True)
    assert first['data_as_of'] == second['data_as_of']
    assert fetch.call_count == 1
    assert second['stale'] is False


def soil_payload():
    values = {'sand': 400, 'silt': 400, 'clay': 200, 'wv0033': 300, 'wv1500': 150}
    return {'properties': {'layers': [
        {'name': name, 'unit_measure': {'d_factor': 10, 'target_units': '%'}, 'depths': [
            {'label': depth, 'values': {'mean': val, 'Q0.05': val - 10, 'Q0.95': val + 10}}
            for depth, _ in s.DEPTHS]}
        for name, val in values.items()]}}


def test_soil_units_depths_and_quantile_envelope():
    result = s.parse_soilgrids(soil_payload(), data_as_of='2026-11-15')
    assert result['awc_mm_per_m'] == pytest.approx(150)
    assert result['awc_low'] == pytest.approx(130)
    assert result['awc_high'] == pytest.approx(170)
    assert result['texture'] == 'loam'
    assert result['badge'] == 'Estimated'
    assert result['organic_matter_pct'] is None
    payload = soil_payload()
    payload['properties']['layers'][3]['depths'][-1]['values']['mean'] = 400
    assert s.parse_soilgrids(payload)['awc_mm_per_m'] == pytest.approx(190)


@pytest.mark.parametrize('point', [(17.5, 78.5), (-1.286389, 36.817223), (-15.78, -47.93)])
def test_three_non_us_points_with_shared_cache(point, monkeypatch):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = soil_payload()
    get = Mock(return_value=response)
    monkeypatch.setattr(s.requests, 'get', get)
    cache = ArrayCache(100000)
    first = s.get_soilgrids(*point, cache=cache)
    second = s.get_soilgrids(*point, cache=cache, offline=True)
    assert get.call_count == 1
    assert first == second
    assert first['lat'] == point[0] and first['lon'] == point[1]


def test_missing_water_keeps_estimated_texture_and_fao_badge():
    payload = soil_payload()
    payload['properties']['layers'][3]['depths'][0]['values']['mean'] = None
    result = s.parse_soilgrids(payload)
    assert result['fallback']
    assert result['awc_mm_per_m'] == 155
    assert result['awc_low'] == 130 and result['awc_high'] == 180
    assert result['badge'] == 'Assumption'
    assert result['badges']['texture'] == 'Estimated'


def test_no_data_offline_and_stale_soil(monkeypatch):
    fallback = s.get_soilgrids(0, 0, cache=ArrayCache(10000), offline=True, texture='sand')
    assert fallback['awc_mm_per_m'] == 80 and fallback['data_as_of'] is None
    cache = ArrayCache(100000)
    cache[('soilgrids-v2', 17.5, 78.5)] = {'payload': soil_payload(), 'data_as_of': '2020-01-01T00:00:00+00:00'}
    result = s.get_soilgrids(17.5, 78.5, offline=True, cache=cache)
    assert result['stale'] and result['data_as_of'].startswith('2020')
    with pytest.raises(ValueError):
        s.get_soilgrids(np.nan, 0)


def test_precache_refuses_to_claim_missing_api_complete(monkeypatch):
    monkeypatch.delattr(pc.api, 'get_site', raising=False)
    report = pc.precache(pc.DEMO_SITES)
    assert report['status'] == 'blocked'
    assert not report['persistent_cache_verified']
    assert pc.precache(pc.DEMO_SITES, dry_run=True)['status'] == 'planned'


def test_precache_report_checks_all_dependencies(monkeypatch):
    calls = []
    def lookup(lat, lon):
        calls.append((lat, lon))
        return {'weather': [1], 'soil': {'awc_mm_per_m': 150}, 'us_defaults': {
            'crops': ['maize'], 'yields': {'maize': 100}, 'prices': {'maize': .2},
            'costs': {'maize': 50}, 'irrigated_share': 0.1}}
    monkeypatch.setattr(pc.api, 'get_site', lookup, raising=False)
    monkeypatch.setattr(pc.api, 'cache_info', lambda: {'persistent': True}, raising=False)
    monkeypatch.setattr(pc.api, 'gibs_layers', lambda **kw: [{'id': 'EXAMPLE_SMAP'}, {'id': 'EXAMPLE_NDVI'}], raising=False)
    monkeypatch.setattr(pc.api, 'precache_validation_site', lambda spec, **kw: {'complete': True}, raising=False)
    specs = [*pc.DEMO_SITES, {'id': 'EXAMPLE-county', 'lat': 42, 'lon': -93, 'kind': 'validation', 'fips': '19169', 'crops': ['maize']}]
    report = pc.precache(specs)
    assert report['status'] == 'complete'
    assert len(calls) == 4
    assert pc.precache(specs, offline=True)['status'] == 'blocked'


def test_precache_never_exports_exception_credentials(monkeypatch):
    def fail(*args):
        raise RuntimeError('secret-key=DO_NOT_EXPORT')
    monkeypatch.setattr(pc.api, 'get_site', fail, raising=False)
    report = pc.precache(pc.DEMO_SITES)
    assert 'DO_NOT_EXPORT' not in str(report)
    assert all(site['status'] == 'failed' for site in report['sites'])


def test_legacy_missing_cost_is_not_invented(tmp_path):
    path = tmp_path / 'prices_only.yaml'
    path.write_text('msp_rs_per_quintal: {rice: 100}\n')
    prices = e.load_prices(path)
    assert prices['operating_cost_rs_per_acre']['rice'] is None
    with pytest.raises(e.InputNeededError, match='operating_cost'):
        e.plan_economics(['rice'], {'yield_kg_ha': np.array([[1000.]])}, prices=prices, n_credit=np.array([0.]))


def test_soil_malformed_data_and_unrecognized_units_fall_back():
    assert s.parse_soilgrids({'properties': None})['fallback']
    payload = soil_payload()
    payload['properties']['layers'][3]['unit_measure']['target_units'] = 'm3/m3'
    result = s.parse_soilgrids(payload)
    assert result['fallback'] and result['badge'] == 'Assumption'
    assert 'unit' in result['fallback_reason']


def test_profit_overflow_and_bad_shapes_are_rejected():
    with pytest.raises(e.InputNeededError, match='numeric range'):
        e.profit_per_hectare(1e308, 1e308, 0)
    with pytest.raises(ValueError, match='compatible'):
        e.profit_per_hectare([1, 2], [1, 2, 3], 0)


def test_soil_persistent_seed_survives_a_new_lookup(tmp_path, monkeypatch):
    from engine import cache
    monkeypatch.setattr(cache, 'RUNTIME_DIR', tmp_path / 'runtime')
    monkeypatch.setattr(cache, 'PRECACHE_DIR', tmp_path / 'seed')
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = soil_payload()
    get = Mock(return_value=response)
    monkeypatch.setattr(s.requests, 'get', get)
    first = s.get_soilgrids(30.5, 75.5, precache=True)
    assert first['precache_written']
    assert list((tmp_path / 'seed' / 'soil').glob('*.json.gz'))
    monkeypatch.setattr(cache, 'RUNTIME_DIR', tmp_path / 'new-runtime')
    second = s.get_soilgrids(30.5, 75.5, offline=True)
    assert get.call_count == 1
    assert second['awc_mm_per_m'] == first['awc_mm_per_m']
    assert second['data_as_of'] == first['data_as_of']


def test_gibs_persistent_cache_and_strict_offline(tmp_path, monkeypatch):
    from engine import cache
    monkeypatch.setattr(cache, 'RUNTIME_DIR', tmp_path / 'runtime')
    monkeypatch.setattr(cache, 'PRECACHE_DIR', tmp_path / 'seed')
    response = Mock(text=xml_fixture())
    response.raise_for_status.return_value = None
    get = Mock(return_value=response)
    monkeypatch.setattr(g.requests, 'get', get)
    first = g.fetch_capabilities(precache=True)
    assert first['precache_written']
    monkeypatch.setattr(cache, 'RUNTIME_DIR', tmp_path / 'new-runtime')
    second = g.fetch_capabilities(offline=True)
    assert first['xml'] == second['xml'] and get.call_count == 1
    assert first['data_as_of'] == second['data_as_of']


def test_precache_does_not_call_a_missing_historical_data_hook(monkeypatch):
    monkeypatch.delattr(pc.api, 'precache_validation_site', raising=False)
    monkeypatch.setattr(pc.api, 'get_site', lambda *a: {'weather': [1], 'soil': {'awc_mm_per_m': 100},
        'us_defaults': {'crops': ['maize'], 'yields': {'maize': 100}, 'prices': {'maize': None},
                        'costs': {'maize': 20}, 'irrigated_share': 0}}, raising=False)
    specs = [{'id': 'EXAMPLE-county', 'lat': 42, 'lon': -93, 'kind': 'validation', 'fips': '19169', 'crops': ['maize']}]
    report = pc.precache(specs)
    assert report['status'] == 'incomplete'
    assert any('input needed' in missing for missing in report['sites'][0]['missing'])
    assert any('historical county yields' in missing for missing in report['sites'][0]['missing'])


def test_global_offline_mode_is_respected_with_injected_caches(monkeypatch):
    monkeypatch.setenv('ROTATIONLAB_OFFLINE', '1')
    get = Mock(side_effect=AssertionError('Network forbidden'))
    monkeypatch.setattr(s.requests, 'get', get)
    soil = s.get_soilgrids(0, 0, cache=ArrayCache(100))
    catalog = g.fetch_capabilities(cache=ArrayCache(100))
    assert soil['fallback'] and catalog['stale']
    get.assert_not_called()
