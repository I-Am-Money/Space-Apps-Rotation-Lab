# AI use: written with OpenAI Codex under the team's direction. See AI_USE.md.
"""Synthetic SDA horizon rows; not measurements of a real farm."""
import pytest
from engine import fetch_ssurgo as s


def rows():
    return [dict(mukey='EXAMPLE',muname='EXAMPLE unit',cokey='1',compname='EXAMPLE',comppct_r=90,hydgrp='B/D',
                 hzdept_r=top,hzdepb_r=bottom,awc_r=awc,om_r=om,texdesc='loam')
            for top,bottom,awc,om in [(0,25,.1,2),(25,100,.2,4)]]


def test_thickness_weighted_soil_matches_hand_calculation():
    out=s.summarize(rows())
    assert out['awc_mm_per_m']==175
    assert out['organic_matter_pct']==pytest.approx((2*25+4*5)/30,abs=.01)
    assert out['hydrologic_group']=='B' and out['hydrologic_group_raw']=='B/D'
    assert out['awc_depth_cm']==100


def test_invalid_water_content_never_reaches_site():
    data=rows()
    for row in data: row['awc_r']=float('nan')
    assert s.summarize(data) is None
    for row in data: row['awc_r']=-999
    assert s.summarize(data) is None


def test_statsgo_is_used_when_ssurgo_has_no_usable_horizons(monkeypatch):
    answers=iter([[],rows()])
    monkeypatch.setattr(s,'run_query',lambda *a,**kw: next(answers))
    result=s._fetch(40,-80)
    assert result['dataset']=='STATSGO2'
    assert result['awc_mm_per_m']==175
