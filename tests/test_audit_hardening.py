# AI use: written with OpenAI Codex under the team's direction. See AI_USE.md.
"""Regression tests for actual audit findings. Provider data here is synthetic."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import datetime as dt
import gzip
import json
import numpy as np
import pandas as pd
import pytest
import requests
from engine import api, cache, economics, evpi, fetch_nass, optimize, simulate


@pytest.mark.parametrize('failure', [requests.Timeout, requests.ConnectionError, requests.HTTPError])
def test_nass_request_errors_never_leak_credentials(monkeypatch, failure):
    token='SYNTHETIC-TEST-SECRET'
    monkeypatch.setenv('NASS_API_KEY', token)
    def fail(*args, **kwargs):
        raise failure('https://provider.example/?key='+token)
    monkeypatch.setattr(fetch_nass.requests, 'get', fail)
    with pytest.raises(fetch_nass.NassUnavailable) as exc:
        fetch_nass._get({'year':2023})
    assert token not in str(exc.value)
    assert exc.value.__suppress_context__


@pytest.mark.parametrize('body', [{'error':['unauthorized']}, {'data':'invalid'}, {'data':[None]}])
def test_nass_invalid_json_is_not_cached_as_empty_success(monkeypatch, body):
    monkeypatch.setenv('NASS_API_KEY','SYNTHETIC')
    monkeypatch.setattr(fetch_nass.requests,'get',lambda *a,**kw: SimpleNamespace(status_code=200,json=lambda:body))
    with pytest.raises(fetch_nass.NassUnavailable):fetch_nass._get({})


@pytest.mark.parametrize('value', ['nan','inf','-1','-999'])
def test_nass_nonfinite_and_negative_values_are_missing(value):
    assert fetch_nass.parse_value(value) is None


@pytest.mark.parametrize('fips',['abc','00000','99169','19000','191690'])
def test_invalid_county_fips_fails_before_network(fips):
    with pytest.raises(ValueError):fetch_nass.split_fips(fips)


def test_nass_domain_breakdowns_do_not_replace_total_yields():
    rec={'commodity_desc':'CORN','unit_desc':'BU / ACRE','year':2023,'Value':'200',
         'util_practice_desc':'GRAIN','domain_desc':'TOTAL'}
    detail=dict(rec,Value='20',domain_desc='ECONOMIC CLASS')
    result=fetch_nass.yield_series([rec,detail],'maize')
    assert result[2023]==pytest.approx(200*fetch_nass.kg_ha_per_unit('maize'))


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1,True,'invalid'])
def test_invalid_economic_defaults_request_input(value):
    with pytest.raises(economics.InputNeeded):
        economics.crop_economics('maize',{'prices':{'maize':value},'costs':{'maize':1}})


def test_source_specific_economics_badges_survive():
    result=economics.crop_economics('maize',{'prices':{'maize':180},'costs':{'maize':1000},
        'badges':{'price:maize':'estimated','cost:maize':'estimated'}})
    assert result['price_badge']==result['cost_badge']=='estimated'


@pytest.mark.parametrize('value',[None,float('nan'),float('inf'),-1])
def test_profit_rejects_invalid_money(value):
    with pytest.raises(economics.InputNeededError):economics.profit_per_ha(1000,value,100)


def test_other_currency_never_relabels_usd_defaults():
    defaults=api.USDefaults(['maize'],{'maize':9000},{'maize':180},{'maize':1000},.1)
    site=SimpleNamespace(currency='INR',us_defaults=defaults)
    adjusted=api._currency_site(site)
    assert adjusted.us_defaults.prices==adjusted.us_defaults.costs=={}
    assert adjusted.us_defaults.yields==defaults.yields
    assert defaults.prices=={'maize':180}  # original cached site is unmodified


@pytest.mark.parametrize('controls',[{'bad_year':float('nan')},{'water':1.01},{'soil':-1},{'profit_tolerance_pct':101}])
def test_bad_sliders_fail_before_scoring(controls):
    with pytest.raises(ValueError):api.recommend_details(None,None,controls)


def test_measurement_value_uses_selected_climate_context(monkeypatch):
    contexts=[]
    monkeypatch.setattr(evpi,'question_value',lambda *a,**kw: contexts.append(simulate.current_what_if()) or [])
    api.question_value_details(SimpleNamespace(us_defaults=None),None,{'climate_shift':'recent'})
    assert contexts==[{'climate_shift':'recent'}]
    assert simulate.current_what_if()=={}


def test_recommendation_response_cannot_mutate_cached_bundle(monkeypatch):
    calls=[]
    monkeypatch.setattr(optimize,'score_candidates',lambda *a: calls.append(1) or {'nested':{'value':5}})
    monkeypatch.setattr(optimize,'assemble_recommendation',lambda bundle,*a,**kw: bundle)
    site=SimpleNamespace(weather=pd.DataFrame({'precip':[1.,2.]}),soil=SimpleNamespace(awc_mm_per_m=100),
                         us_defaults=None,lat=40.,lon=-90.,elevation_m=100.)
    first=api.recommend_details(site,api.default_inputs(),api.Sliders());first['nested']['value']=999
    assert api.recommend_details(site,api.default_inputs(),api.Sliders())['nested']['value']==5
    assert len(calls)==1


def test_corrupt_cache_metadata_is_ignored_and_future_date_is_not_fresh(tmp_path,monkeypatch):
    monkeypatch.setattr(cache,'RUNTIME_DIR',tmp_path);monkeypatch.setattr(cache,'PRECACHE_DIR',tmp_path/'seed')
    p=tmp_path/'soil'/'bad.json.gz';p.parent.mkdir()
    with gzip.open(p,'wt') as f:json.dump({'meta':{'data_as_of':'not a date'},'payload':{}},f)
    assert cache.read('soil','bad') is None
    assert not cache.is_fresh({'data_as_of':(dt.date.today()+dt.timedelta(days=1)).isoformat(),'expiry_days':365})


def test_oversized_array_cannot_defeat_memory_budget():
    memory=cache.ArrayCache(100);memory['huge']=np.zeros(1000)
    assert memory.bytes<=100 and 'huge' not in memory


@pytest.mark.parametrize('scores',[[[np.nan]],[[np.inf]],[],[[]]])
def test_unknown_information_value_is_not_reported_as_zero(scores):
    with pytest.raises(ValueError):evpi.evpi_value(scores)


def test_precache_reports_missing_county_observations(monkeypatch):
    monkeypatch.setattr(fetch_nass,'us_defaults',lambda f: {'available':True})
    monkeypatch.setattr(fetch_nass,'county_yields',lambda *a,**kw:pd.DataFrame())
    result=api.precache_validation_site({'fips':'19169','crops':['maize']})
    assert result['complete'] is False
    assert result['historical_yields']['maize']['available'] is False
    assert fetch_nass._PRECACHE.get() is False


def test_partial_multi_season_baseline_is_never_silently_scored():
    inputs=replace(api.default_inputs(), current_plan=[['maize','soybean']]*4)
    with pytest.raises(NotImplementedError, match='one cash crop'):
        api.recommend_details(None,inputs,api.Sliders())


@pytest.mark.parametrize('water',[api.WaterInput('unknown'),api.WaterInput('irrigated',normal_mm=50,dry_mm=100),
                                  api.WaterInput('irrigated',normal_mm=float('nan'),dry_mm=1)])
def test_invalid_water_answers_fail_before_modeling(water):
    with pytest.raises(ValueError):api._check_inputs(replace(api.default_inputs(),water=water))


def test_currency_input_validation_never_falls_back_to_usd():
    from ui.planner_model import input_errors
    defaults=api.USDefaults(['maize'],{'maize':9000},{'maize':180},{'maize':1000},.1)
    site=api.Site(40,-90,'USA','IA','19169',pd.DataFrame(),None,100,None,defaults,'2026-11-15')
    site.currency='INR'
    errors=input_errors(site,['maize']*4,100,'rain','',None,None,{})
    assert any('price' in e for e in errors) and any('cost' in e for e in errors)
    assert not any('yield' in e for e in errors)


def test_cli_nass_key_reads_ignored_server_secrets_only_when_env_absent(tmp_path,monkeypatch):
    secret=tmp_path/'secrets.toml';secret.write_text('NASS_API_KEY="SYNTHETIC-ONLY"\n')
    monkeypatch.setattr(fetch_nass,'SECRETS_PATH',secret)
    monkeypatch.delenv('NASS_API_KEY')
    assert fetch_nass._api_key()=='SYNTHETIC-ONLY'
    monkeypatch.setenv('NASS_API_KEY','')
    assert not fetch_nass.has_key()


def test_nass_preflight_does_not_claim_empty_query_authenticated(monkeypatch):
    monkeypatch.setattr(fetch_nass,'_get',lambda params:[])
    with pytest.raises(fetch_nass.NassUnavailable):api.check_nass()


def test_nass_cli_never_prints_unexpected_secret_errors(monkeypatch,capsys):
    from scripts import check_nass
    def fail():raise RuntimeError('SYNTHETIC-SECRET')
    monkeypatch.setattr(api,'check_nass',fail)
    assert check_nass.main()==1
    output=capsys.readouterr().out
    assert 'SYNTHETIC-SECRET' not in output
    assert json.loads(output)['authenticated'] is False


def test_failed_seed_promotion_is_not_reported_persisted(tmp_path,monkeypatch):
    monkeypatch.setattr(cache,'RUNTIME_DIR',tmp_path/'runtime');monkeypatch.setattr(cache,'PRECACHE_DIR',tmp_path/'seed')
    cache.write('nass','county',[], 'SYNTHETIC')
    monkeypatch.setattr(cache,'write',lambda *a,**kw:{'stored':False})
    data,meta=cache.fetch_cached('nass','county',lambda:pytest.fail('No network'), 'SYNTHETIC',precache=True)
    assert data==[] and meta['stored'] is False


def test_short_weather_interpolation_remains_flagged_as_estimated():
    from engine.fetch_power import _fill_series
    values=pd.Series([1.,np.nan,3.,4.], index=pd.date_range('2020-01-01',periods=4))
    filled,flags=_fill_series(values)
    assert filled.iloc[1]==2
    assert flags.tolist()==[False,True,False,False]
