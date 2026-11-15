# AI use: Feature 1 app-shell tests revised for v5 page ownership. Test data is explicitly EXAMPLE.
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest
from engine import api
from ui.planner_model import area_value, input_errors, ACRES_PER_HECTARE

APP=str(Path(__file__).resolve().parents[1]/'app.py')


@pytest.fixture
def providers(monkeypatch):
    st.cache_data.clear()
    defaults=api.USDefaults(['maize','soybean'], {'maize':1000,'soybean':900}, {'maize':200,'soybean':400},
                            {'maize':100,'soybean':90}, .1)
    trend=api.ClimateTrend((1981,2000),(2006,2025),(500,480),(.2,.3),(3,5),(120,125),badges={'rain':'example'})
    site=api.Site(42.03,-93.62,'USA','IA','19169',pd.DataFrame(),api.SoilInfo('loam',150,None,'EXAMPLE','example'),
                  200,trend,defaults,'2026-11-15',badges={'weather':'example'})
    site.currency='USD'
    base=api.RotationResult([['maize']]*4,[False]*4,100,20,10000,50,500,40,[{'maize':1000}]*4,
                            {k:0 for k in api.DELTA_KEYS},{k:'example' for k in api.DELTA_KEYS})
    rec=api.Recommendations(base,base,base,[base],base,True,{'headline':'EXAMPLE explanation'})
    def details(*args,**kwargs): return asdict(rec)
    monkeypatch.setattr(api,'get_site',lambda *a: site)
    monkeypatch.setattr(api,'get_candidates',lambda *a: ['maize','soybean'])
    monkeypatch.setattr(api,'recommend',lambda *a: rec)
    monkeypatch.setattr(api,'recommend_details',details)
    monkeypatch.setattr(api,'gibs_layers',lambda **kw: [])
    monkeypatch.setattr(api,'validation_summary',lambda: api.ValidationSummary([],[]))
    monkeypatch.setattr(api,'tipping_points',lambda *a: api.TippingPoints(
        {'x':[.5,1.3],'series':{'EXAMPLE':[1,2]},'winner':['EXAMPLE']*2}, {}, {},
        {'rain_mult':[.5,1.3],'water_mm':[0,50],'winner':[['A','B'],['B','B']]},{}))
    monkeypatch.setattr(api,'question_value_details',lambda *a,**kw: [{'question':'EXAMPLE measure water',
        'plain':'Could change your answer','computed':True,'evpi_per_acre':2,'evpi_per_ha':2*ACRES_PER_HECTARE,
        'badge':'example','note':'EXAMPLE test only','could_change_answer':True}])
    return site,rec


def results_app(providers):
    site,rec=providers
    app=AppTest.from_file(APP,default_timeout=30)
    app.session_state['v4_site']=site
    app.session_state['v4_inputs']=api.default_inputs()
    app.session_state['v4_rec']=rec
    app.session_state['v4_screen']='results'
    return app.run()


def test_unit_helpers_and_required_inputs():
    assert area_value(ACRES_PER_HECTARE)==pytest.approx(1)
    assert area_value(100,True)==100
    errors=input_errors({'country':'Non-US'},['maize']*4,0,'irrigated','',None,None,{})
    assert len(errors)==5


def test_start_and_missing_contract(monkeypatch):
    monkeypatch.delattr(api,'get_site')
    app=AppTest.from_file(APP).run()
    assert not app.exception
    assert any(b.label=='Plan my farm' for b in app.button)
    assert any('v4 engine' in info.value for info in app.info)


def test_setup_blocks_missing_inputs_and_preserves_answers_when_editing(providers):
    app=AppTest.from_file(APP,default_timeout=30).run()
    next(b for b in app.button if b.label=='Plan my farm').click().run()
    next(b for b in app.button if b.label=='Load this location').click().run()
    next(b for b in app.button if b.label=='Compare my rotations').click().run()
    assert any('greater than zero' in w.value for w in app.warning)
    app.number_input(key='v4_farm_acres').set_value(123.).run()
    next(b for b in app.button if b.label=='Compare my rotations').click().run()
    assert not app.exception
    assert any('EXAMPLE DATA' in x.value for x in app.error) or any('EXAMPLE DATA' in x.value for x in app.warning)
    next(b for b in app.button if b.label=='Edit farm details').click().run()
    assert app.number_input(key='v4_farm_acres').value==123.


def test_example_farm_goes_straight_to_recommendations_and_stays_editable(providers):
    """One click on an example farm must reach a result: no empty form, no 'farm size' error."""
    app=AppTest.from_file(APP,default_timeout=30).run()
    next(b for b in app.button if b.label=='Explore Iowa').click().run()
    assert not app.exception
    assert not any('greater than zero' in w.value for w in app.warning)
    assert app.session_state['v5_page']=='Recommendations'
    assert any('Highest profit' in s.value for s in list(app.subheader) + list(app.markdown))
    assert app.session_state['v4_inputs'].current_plan==['maize']*4
    next(b for b in app.button if b.label=='Edit farm details').click().run()
    assert not app.exception
    assert app.number_input(key='v4_farm_acres').value==300.


def test_example_farms_have_complete_answers():
    from ui import setup
    presets=setup.demo_presets()
    assert len(presets)==3
    for preset in presets:
        assert len(preset['plan'])==4 and preset['acres']>0 and preset['water']=='rain' and preset['place']


def test_climate_card_rows_are_plain_and_rounded():
    from ui import setup
    rows=setup.climate_rows({'season_rain_mm':(557.086,524.601),'rain_variability_cv':(.274,.3117),'heat_days':(4.4,5.2),
                             'rainy_season_start_doy':(131.9,127.65),'heat_threshold_c':35.0})
    by={r['name']:r for r in rows}
    assert by['season_rain_mm']['Baseline']=='557 mm' and by['season_rain_mm']['Change'].startswith('-32 mm')
    assert by['heat_days']['Change']=='+0.8 days'
    assert by['rainy_season_start_doy']['Change']=='4 days earlier'
    assert not any('_' in r['Measure'] or 'Doy' in r['Measure'] for r in rows)


def test_all_pages_render_without_hidden_exceptions(providers):
    app=results_app(providers)
    for page in ('Recommendations','Tipping points','What to measure next','How good is this?','Farm setup'):
        app.radio(key='v5_page').set_value(page).run()
        assert not app.exception, [e.message for e in app.exception]
        assert not any('page could not' in e.value.lower() for e in app.error)


def test_repeated_unit_toggles_never_mutate_model_results(providers):
    expected=deepcopy(asdict(providers[1]))
    app=results_app(providers)
    for metric in (True,False,True,False):
        app.toggle(key='v4_metric').set_value(metric).run()
        assert not app.exception
        assert asdict(providers[1])==expected


def test_inconsistent_headline_is_withheld(providers):
    providers[1].headline=deepcopy(providers[1].headline)
    providers[1].headline.mean_profit=50
    app=results_app(providers)
    assert any('withheld' in w.value for w in app.warning)


def test_tipping_result_survives_other_page_visits(providers, monkeypatch):
    from engine import tipping
    from tests.test_p2_tipping import make_site, make_inputs
    from tests.test_p2_simulation import make_weather
    result=tipping.tipping_points(make_site(make_weather(1981,2025,seed=11)), make_inputs(),
                                  {'climate_shift':'historical'}, recommend=False)
    result['example']=True
    monkeypatch.setattr(api,'tipping_points',lambda *a,**kw: result)
    app=results_app(providers)
    app.radio(key='v5_page').set_value('Tipping points').run()
    assert not app.exception
    assert not app.error or all('placeholder values' in e.value for e in app.error)
    assert app.session_state['_tipping_result'][1] is result
    app.radio(key='v5_page').set_value('What to measure next').run()
    assert app.session_state['_tipping_result'][1] is result
    assert 'v4_questions' in app.session_state


def test_validation_failure_does_not_remove_recommendations(providers,monkeypatch):
    def fail(): raise RuntimeError('secret internal detail')
    monkeypatch.setattr(api,'validation_summary',fail)
    app=results_app(providers)
    assert not app.exception
    assert any('Validation records could not be loaded' in w.value for w in app.warning)
    assert any('Highest profit' in s.value for s in list(app.subheader) + list(app.markdown))
    assert not any('secret internal' in e.value for e in app.error)
