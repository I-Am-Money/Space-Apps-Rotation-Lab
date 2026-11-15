# TODO: final mobile visual pass and real screenshots remain pending; zones and unavailable source data stay explicitly labeled.
# AI use: written with OpenAI Codex under the team's direction.
"""Person 4's v4 UI. All scientific operations use engine.api exclusively."""
from pathlib import Path
import logging

import folium
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from ui import autofill
from ui.theme import crop_name
from streamlit_folium import st_folium
from engine import api
from ui.planner_model import (DEMO_SITES, record, area_value, provenance,
                              contains_example, input_errors, currency,
                              finite_number, guardrail_allows, badge_labels)

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_API = ('Site', 'WaterInput', 'UserInputs', 'Sliders', 'get_site', 'get_candidates',
                'recommend', 'tipping_points', 'question_value', 'validation_summary')


def demo_presets():
    import yaml
    data = yaml.safe_load((ROOT / 'config/assumptions/setup.yaml').read_text())['demo_presets']
    return [(row['label']['value'], row['lat']['value'], row['lon']['value']) for row in data.values()]


def provenance(value):
    from ui.planner_model import provenance as original
    return 'Your input' if str(value).strip().lower().replace('_', ' ') == 'your input' else original(value)


def record(value):
    from dataclasses import is_dataclass
    if is_dataclass(value):
        return dict(vars(value))
    return value if isinstance(value, dict) else {}


def missing_api():
    return [name for name in REQUIRED_API if not hasattr(api, name)]


def stamp(value=None, badges=None):
    b = record(badges)
    labels = sorted(badge_labels(b)) or ['Estimated']
    if api.is_example(value) or contains_example(value) or contains_example(badges):
        st.error('EXAMPLE DATA · Demonstration output; do not use for decisions.')
    asof = record(value).get('data_as_of') or st.session_state.get('v4_asof')
    from ui.components import badge
    st.markdown(' '.join(badge(label) for label in labels), unsafe_allow_html=True)
    st.caption('Data as of ' + str(asof or 'not supplied by engine'))
    for note in dict.fromkeys(n for n in (record(value).get('notes') or []) if isinstance(n, str)):   # each note once
        st.caption(note)


def style():
    """One shared look for every page: tokens and components live in ui/theme.py."""
    from ui import theme
    theme.inject_v5()


def start():
    st.markdown('<div class="rl-brand">RotationLab</div>', unsafe_allow_html=True)
    st.title('Healthier soil. A more resilient farm.')
    st.write('Tell us where you farm in the United States and what you grow. RotationLab tests four-year crop plans against decades '
             'of NASA weather records for your location, then shows which plan is best for your soil without earning you less.')
    if st.button('Plan my farm', type='primary'):
        st.session_state['v4_screen'] = 'farm'
        st.rerun()
    st.subheader('Or look at an example farm')
    for col, (label, lat, lon) in zip(st.columns(3), demo_presets()):
        with col:
            with st.container(border=True):
                region, _, state = label.partition(' · ')
                st.markdown(f'**{state or region}**')
                st.caption(f'An example location in the {region}.' if state else 'An example location.')
                if st.button('Explore ' + label.split(' · ')[-1], use_container_width=True):
                    st.session_state.update(v4_lat=lat, v4_lon=lon, v4_screen='farm', _v4_autoload=True)
                    st.rerun()
    if missing_api():
        st.info('Planning is waiting for the v4 engine interface. Please try again shortly.')


@st.cache_data(ttl=3600, max_entries=64, show_spinner=False)
def load_site(lat, lon):
    return api.get_site(lat, lon)


def location_map():
    pending = st.session_state.pop('_v4_pending_pin', None)
    if pending:
        st.session_state.update(pin_lat=pending[0], pin_lon=pending[1])
    st.caption('Click the map to put the pin on your field. Zoom in with the + button.')
    with st.expander('Type map coordinates instead'):
        lat = st.number_input('Latitude', -90., 90., value=st.session_state.get('v4_lat', 42.03), key='pin_lat')
        lon = st.number_input('Longitude', -180., 180., value=st.session_state.get('v4_lon', -93.62), key='pin_lon')
    m = folium.Map(location=[lat, lon], zoom_start=6, tiles='OpenStreetMap')
    folium.CircleMarker([lat, lon], radius=11, color='#12303a', weight=3, fill=True, fill_color='#1d6f78', fill_opacity=.9,
                        tooltip='Your farm').add_to(m)
    # Only capability-verified layer metadata supplied through the public API is accepted.
    site = st.session_state.get('v4_site')
    layers = record(site).get('gibs_layers') or []
    layer_api = getattr(api, 'gibs_layers', None)
    if callable(layer_api):
        try:
            layers = layer_api()
        except Exception:
            logging.exception('Satellite catalog unavailable')
            st.caption('Satellite catalog could not be refreshed. Farm calculations do not depend on imagery.')
    if layers:
        box = st.expander('Show NASA satellite pictures on the map')
        box.caption('Pick a date, then switch the picture on with the layers button at the top right of the map.')
        for index, layer in enumerate(layers):
            layer = record(layer)
            url = layer.get('url') or layer.get('tile_url_template')
            name = layer.get('name') or layer.get('title') or layer.get('id')
            if not url or not name:
                continue
            dates = layer.get('available_dates') or ([layer['date']] if layer.get('date') else [])
            if not dates:
                continue
            when = box.selectbox(f'{name}: picture date', dates, key=f'v4_layer_date_{index}')
            # Replace a specific advertised date only with another advertised date from the same layer.
            # This does not guess dates between composites or fill service gaps.
            default_date = layer.get('date') or dates[0]
            url = url.replace('{date}', when).replace('/' + default_date + '/', '/' + when + '/')
            folium.TileLayer(tiles=url, name=name, attr='NASA GIBS', overlay=True, show=False,
                             max_native_zoom=layer.get('max_native_zoom', 8), max_zoom=18).add_to(m)
            box.caption(f"Observed · {name} · Image dated {when} · Catalog as of {layer.get('data_as_of') or 'not supplied'}")
            if layer.get('stale'):
                box.warning('Satellite catalog is an older offline snapshot; imagery may be unavailable.')
        folium.LayerControl().add_to(m)
    else:
        st.caption('NASA SMAP / MODIS NDVI overlays await the shared satellite-catalog API.')
    result = st_folium(m, height=380, use_container_width=True, key='v4_map', returned_objects=['last_clicked'])
    if result and result.get('last_clicked'):
        clicked = (result['last_clicked']['lat'], result['last_clicked']['lng'])
        if clicked != st.session_state.get('_v4_last_click'):
            st.session_state['_v4_last_click'] = clicked
            st.session_state['_v4_pending_pin'] = clicked
            st.rerun()
    return lat, lon


def farm():
    st.title('Tell us about your farm')
    st.write('Start with where you farm. Then tell us what you grow, how big the farm is and where your water comes from.')
    st.subheader('1. Where is your farm?')
    saved = st.session_state.get('_v4_farm_widgets', {})
    for name, value in saved.items():
        st.session_state.setdefault(name, value)
    autofill.render()
    lat, lon = location_map()
    if st.button('Load this location', type='primary') or st.session_state.pop('_v4_autoload', False):
        if missing_api():
            st.warning('Location lookup is waiting for Person 1’s v4 engine/api.py. No global results have been calculated.')
        else:
            try:
                with st.status('Loading location data', expanded=True) as status:
                    st.write('Getting NASA weather records and soil data for this spot…')
                    site = load_site(lat, lon)
                    if st.session_state.get('v4_location') != (lat, lon):
                        for name in st.session_state.get('_v4_farm_widgets', {}):
                            st.session_state.pop(name, None)
                        st.session_state.pop('_v4_farm_widgets', None)
                    st.session_state.update(v4_site=site, v4_location=(lat, lon), v4_asof=record(site).get('data_as_of'))
                    status.update(label='Location data loaded', state='complete')
            except Exception:
                logging.exception('Location lookup failed')
                st.error('Could not load this location. Check the coordinates and try again.')
    site = st.session_state.get('v4_site')
    if site is None:
        st.info('Put the pin on your field and press "Load this location". The rest of the questions appear after that.')
        return
    if st.session_state.get('v4_location') != (lat, lon):
        st.warning('You moved the pin. Press "Load this location" again to use the new spot.')
        return
    stamp(site, record(site).get('badges'))
    st.subheader('2. What do you grow now?')
    guess = getattr(site, 'currency', None) or (currency(site) if currency(site) != 'local currency' else '')
    current_currency = st.text_input('Currency for prices and profit (three letters, such as USD)', value=guess, key='v4_currency',
                                     help='A label only. Enter every price and cost in this same currency. Nothing is converted.').strip().upper()
    site.currency = current_currency or None
    if getattr(site, 'us_defaults', None) is not None and current_currency not in ('', 'USD'):
        st.info('USDA prices and costs are in USD. Enter every price and cost in your selected currency; no automatic exchange conversion is available.')
    # Candidate filtering belongs to the engine. Current crops use the county defaults when supplied.
    crops = list(record(record(site).get('us_defaults')).get('crops') or [])
    if crops:
        for i, c in enumerate(st.session_state.get('v4_cdl_plan') or []):
            if c in crops:
                st.session_state.setdefault(f'v4_crop{i}', c)
        st.caption('Your usual four-year rotation, one crop a year. If you used the address lookup, these are the last four years from the satellite record.')
        plan = [col.selectbox(f'Year {i+1}', crops, key=f'v4_crop{i}', format_func=crop_name) for i, col in enumerate(st.columns(4))]
    else:
        st.caption('Type the crop you grow in each of four years, for example maize, soybean, wheat.')
        plan = [col.text_input(f'Year {i+1}', key=f'v4_crop_text{i}').strip() for i, col in enumerate(st.columns(4))]
    st.subheader('3. Your farm and its water')
    acres = st.number_input('How big is your farm? (acres)', min_value=0., value=0., key='v4_farm_acres')
    mode = st.radio('Where does the water for your crops come from?', ['rain', 'irrigated'],
                    index=int(float(record(record(site).get('us_defaults')).get('irrigated_share') or 0) > .5),
                    format_func=lambda x: 'Rain only' if x == 'rain' else 'Rain plus irrigation', horizontal=True, key='v4_water_mode')
    source, normal, dry = '', 0., 0.
    if mode == 'irrigated':
        source = st.text_input('Where does the irrigation water come from?', placeholder='Well, canal, reservoir…', key='v4_water_source')
        normal = st.number_input('Irrigation water you can count on in a normal year (mm per season)', min_value=0., value=None, key='v4_normal_mm')
        dry = st.number_input('Irrigation water you can count on in a dry year (mm per season)', min_value=0., value=None, key='v4_dry_mm')
    overrides = {}
    has_defaults = bool(record(record(site).get('us_defaults')).get('crops'))
    with st.expander('Your own yields, prices and costs' + (' (optional)' if has_defaults else ' (needed here)'), expanded=not has_defaults):
        st.caption('Leave a box empty to use the official county or regional figure where one exists. '
                   'Yield in kg per hectare, price per tonne, cost per hectare.' if has_defaults else
                   'There are no official figures for this location, so enter your own for each crop. '
                   'Yield in kg per hectare, price per tonne, cost per hectare.')
        words = {'yield': 'Yield', 'price': 'Price', 'cost': 'Cost'}
        for crop in sorted(set(plan) - {''}):
            st.markdown(f'**{crop_name(crop)}**')
            cols = st.columns(3)
            vals = [cols[i].number_input(f'{words[field]} · {crop_name(crop)}', min_value=0., value=None, key=f'v4_{crop}_{field}')
                    for i, field in enumerate(('yield', 'price', 'cost'))]
            overrides[crop] = {field: v for field, v in zip(('yield', 'price', 'cost'), vals) if v is not None}
    soil, history = None, None
    with st.expander('Soil test results (optional)'):
        if st.checkbox('Add a soil test', key='v4_add_soil'):
            st.caption('Recorded for your reference. These measurements do not change simulated water capacity or yield; a verified relation is not available yet.')
            soil = dict(organic_matter_pct=st.number_input('Organic matter (%)', 0., 100., value=None, key='v4_organic_matter'),
                        ph=st.number_input('pH', 0., 14., value=None, key='v4_ph'), texture=st.text_input('Texture', key='v4_texture'))
    with st.expander('How the field has been farmed (optional)'):
        if st.checkbox('Add field history', key='v4_add_history'):
            history = dict(tillage=st.selectbox('Tillage', ['No till', 'Reduced', 'Conventional'], key='v4_tillage'),
                           cover_crops=st.checkbox('Uses cover crops', key='v4_cover_crops'), erosion=st.checkbox('Erosion observed', key='v4_erosion'),
                           waterlogging=st.checkbox('Waterlogging observed', key='v4_waterlogging'), salinity=st.checkbox('Salinity observed', key='v4_salinity'))
    st.caption('Your answers stay in this browser session. Nothing is saved.')
    st.session_state['_v4_farm_widgets'] = {
        name: st.session_state[name] for name in st.session_state
        if name.startswith(('v4_crop', 'v4_farm_', 'v4_water_', 'v4_add_', 'v4_normal_', 'v4_dry_'))
        or name in ('v4_organic_matter', 'v4_ph', 'v4_texture', 'v4_tillage', 'v4_cover_crops',
                    'v4_erosion', 'v4_waterlogging', 'v4_salinity', 'v4_currency')
        or any(name == f'v4_{crop}_{field}' for crop in plan for field in ('yield', 'price', 'cost'))}
    if st.button('Compare my rotations', type='primary'):
        errors = input_errors(site, plan, acres, mode, source, normal, dry, overrides)
        if len(current_currency) != 3 or not current_currency.isalpha():
            errors.append('Enter a three-letter currency code, such as USD.')
        if errors:
            for error in errors:
                st.warning(error)
            return
        try:
            inputs = api.UserInputs(current_plan=plan, water=api.WaterInput(mode=mode, source=source, normal_mm=normal, dry_mm=dry),
                                    farm_acres=acres, soil_test=soil, history=history, crop_overrides=overrides)
            with st.status('Working out your crop plans…', expanded=True) as status:
                candidates = api.get_candidates(site, inputs)
                st.write(f'{len(candidates)} crops suit your climate and area.')
                if not candidates:
                    st.warning('No supported crops are available here with these inputs.')
                    return
                st.write('Testing every four-year plan against past weather…')
                sliders = api.Sliders(bad_year=.3, water=.1, soil=.5, profit_tolerance_pct=0., climate_shift='historical')
                rec = api.recommend(site, inputs, sliders)
                st.session_state.update(v4_inputs=inputs, v4_rec=rec, v4_screen='results',
                                        v4_controls=(.3, .1, .5, 0., 'historical'))
                st.session_state['_v5_go'] = 'Recommendations'
                st.session_state.pop('v4_tipping_result', None)
                st.session_state.pop('v4_questions', None)
                status.update(label='Crop plans ready', state='complete')
            st.rerun()
        except Exception:
            logging.exception('Recommendation calculation failed')
            st.error('Could not calculate recommendations. Your farm details are preserved; try again.')


CLIMATE_WORDS = {'season_rain_mm': 'Rain in the growing season (mm)', 'rain_variability_cv': 'How much the rain varies from year to year (0 = steady)',
                 'heat_days': 'Very hot days in a year', 'rainy_season_start_doy': 'Day of the year the rains start'}


def climate_card(site):
    trend = record(record(site).get('climate_trend'))
    st.subheader('How your climate is changing')
    if not trend:
        st.info('A climate comparison is not available for this location.')
        return
    early, late = trend.get('early_years', '1981 to 2000'), trend.get('late_years', 'the last 20 years')
    span = lambda v: f'{v[0]} to {v[1]}' if isinstance(v, (list, tuple)) and len(v) == 2 else str(v)
    then, now = f'Then ({span(early)})', f'Now ({span(late)})'
    rows = []
    for name in ('season_rain_mm', 'rain_variability_cv', 'heat_days', 'rainy_season_start_doy'):
        pair = trend.get(name)
        label = CLIMATE_WORDS.get(name, name.replace('_', ' ').capitalize())
        fmt = (lambda v: None if v is None else round(float(v), 2 if name == 'rain_variability_cv' else 0))
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            rows.append({'What we looked at': label, then: fmt(pair[0]), now: fmt(pair[1]),
                         'Source': provenance(record(trend.get('badges')).get(name, 'estimated'))})
        elif isinstance(pair, dict):
            rows.append({'What we looked at': label, then: fmt(pair.get('baseline')), now: fmt(pair.get('recent'))})
    st.caption('From NASA POWER weather records for the area around your farm. This is what has already changed, not a forecast.')
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    if trend.get('note'):
        st.caption(trend['note'])
    stamp(trend, trend.get('badges'))


def render():
    style()
    if st.session_state.get('v4_screen', 'start') == 'start':
        start()
    else:
        farm()
