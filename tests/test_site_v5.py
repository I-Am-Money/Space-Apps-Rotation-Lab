# AI use: written with OpenAI Codex under the team's direction. See AI_USE.md.
"""Synthetic provider fixtures verify Feature 1 assembly; they are not live validation."""
import numpy as np
import pandas as pd
import pytest
from engine import api, site, climate_card


@pytest.fixture
def weather():
    dates = pd.date_range('1981-01-01', '2025-12-31')
    late = dates.year >= 2006
    frame = pd.DataFrame({'tmax': np.where(late, 36., 30.), 'tmin': 15., 'tmean': 22.,
                          'rh': 60., 'wind2': 2., 'srad': 15., 'precip': np.where(late, 10., 5.), 'et0': 4.}, index=dates)
    frame.attrs.update(last_full_year=2025, elevation_m=200., data_as_of='2026-11-15', filled_days={})
    return frame


def test_climate_card_matches_hand_calculation(weather):
    card = climate_card.climate_trend(weather, 40)
    assert card.early_years == (1981, 2000)
    assert card.late_years == (2006, 2025)
    assert card.season_rain_mm == pytest.approx((153*5, 153*10))
    assert card.heat_days == pytest.approx((0, 153))
    assert card.rain_variability_cv == pytest.approx((0, 0))
    assert card.rainy_season_start_doy == pytest.approx((121.25,121.25))
    assert card.example is False
    assert card.badges['rainy_season_start_doy'] == 'assumption'


@pytest.mark.parametrize('state,fips,lat,lon', [
    ('IA','19169',42.03,-93.62), ('KS','20191',37.24,-97.49), ('GA','13205',31.23,-84.19),
    ('AR','05111',35.57,-90.68), ('CA','06019',36.74,-119.78), ('WA','53075',46.91,-117.54),
    ('TX','48303',33.61,-101.82), ('PA','42071',40.04,-76.25),
])
def test_get_site_eight_us_states(state,fips,lat,lon,weather,monkeypatch):
    monkeypatch.setattr(site,'locate',lambda *a,**k: {'country':'USA','fips':fips,'state_fips':fips[:2]})
    monkeypatch.setattr(site.fetch_power,'load_site_weather',lambda *a,**k: weather)
    monkeypatch.setattr(site.fetch_ssurgo,'get_soil_us',lambda *a,**k: {'texture':'loam','awc_mm_per_m':150.,
                        'organic_matter_pct':None,'source':'EXAMPLE TEST SURVEY','badge':'Observed'})
    monkeypatch.setattr(api,'us_defaults',lambda *a: {'crops':['maize'], 'yields':{'maize':1000.}, 'prices':{'maize':200.},
                        'costs':{'maize':100.}, 'irrigated_share':.2,'level':'county','badges':{}})
    monkeypatch.setattr(api,'us_coverage',lambda *a: {'offered':['maize'],'notes':[]})
    result=api.get_site(lat,lon)
    assert result.us_state == state and result.us_county_fips == fips
    assert result.us_defaults.prices['maize'] == 200  # per tonne; no hidden kg conversion
    assert result.soil.organic_matter_pct is None
    assert not result.weather.isna().any().any()
    assert not (result.weather == -999).any().any()


@pytest.mark.parametrize('lat,lon',[(30.5,75.5),(-.5,35.5),(-16.,-48.5)])
def test_non_us_site_uses_soilgrids(lat,lon,weather,monkeypatch):
    calls=[]
    monkeypatch.setattr(site,'locate',lambda *a,**k: {'country':'Non-US','fips':None})
    monkeypatch.setattr(site.fetch_power,'load_site_weather',lambda *a,**k: weather)
    def soil(*a,**kw):
        calls.append(a)
        return {'texture':'loam','awc_mm_per_m':150.,'source':'EXAMPLE TEST SOIL','badge':'Estimated'}
    monkeypatch.setattr(site.fetch_soilgrids,'get_soilgrids',soil)
    result=api.get_site(lat,lon)
    assert calls == [(lat,lon)] and result.us_defaults is None
    assert result.country == 'Non-US'


def test_invalid_pin_never_reaches_a_fetcher(monkeypatch):
    monkeypatch.setattr(site,'locate',lambda *a,**k: pytest.fail('No lookup for invalid point'))
    with pytest.raises(ValueError): api.get_site(float('nan'),0)
    with pytest.raises(ValueError): api.get_site(91,0)
