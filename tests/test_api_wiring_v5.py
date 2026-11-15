# AI use: written with OpenAI Codex under the team's direction. See AI_USE.md.
"""Real public dispatch is tested independently from the frozen EXAMPLE provider."""
from engine import api, simulate as simulation, candidates, hindcast, explain


def test_public_simulate_delegates_without_replacing_the_result(monkeypatch):
    sentinel=object();calls=[]
    def run(*args): calls.append(args); return sentinel
    monkeypatch.setattr(simulation,'simulate',run)
    assert api.simulate('site','inputs','rotation','scenarios') is sentinel
    assert calls == [('site','inputs','rotation','scenarios')]


def test_candidate_validation_and_explanation_dispatch(monkeypatch):
    monkeypatch.setattr(candidates,'candidates',lambda *a: ['maize'])
    monkeypatch.setattr(hindcast,'validation_summary',lambda: 'real-summary')
    monkeypatch.setattr(explain,'explain_pick',lambda *a,**kw: 'guarded explanation')
    assert api.get_candidates(None,None)==['maize']
    assert api.validation_summary()=='real-summary'
    assert api.explain(None,None)=='guarded explanation'


def test_missing_features_never_fabricate_outputs():
    import importlib.util, pytest
    if importlib.util.find_spec('engine.evpi') is None:
        with pytest.raises(NotImplementedError): api.question_value(None,None,None)
    if importlib.util.find_spec('engine.tipping') is None:
        with pytest.raises(NotImplementedError): api.tipping_points(None,None,None)


def test_recommendation_modes_and_transient_whatifs_do_not_share_scoring(monkeypatch):
    from types import SimpleNamespace
    import pandas as pd
    from engine import optimize
    calls=[]
    monkeypatch.setattr(optimize,'score_candidates',lambda *a: calls.append(simulation.current_what_if()) or {'score':len(calls)})
    monkeypatch.setattr(optimize,'assemble_recommendation',lambda bundle,*a,**kw: bundle)
    site=SimpleNamespace(weather=pd.DataFrame({'rain':[1,2]}),soil=SimpleNamespace(awc_mm_per_m=150),us_defaults=None,
                         lat=42.,lon=-93.,elevation_m=200.)
    inputs=api.default_inputs()
    historical=api.Sliders(); recent=api.Sliders(climate_shift='recent')
    assert api.recommend_details(site,inputs,historical)==api.recommend_details(site,inputs,historical)
    api.recommend_details(site,inputs,recent)
    with simulation.what_if(rain_mult=.5):
        api.recommend_details(site,inputs,historical)
    assert len(calls)==3
    assert calls[0]['climate_shift']=='historical'
    assert calls[1]['climate_shift']=='recent'
    assert calls[2]['rain_mult']==.5
