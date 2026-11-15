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
from streamlit_folium import st_folium
from engine import api
from ui.planner_model import (DEMO_SITES, record, area_value, provenance,
                              contains_example, input_errors, currency,
                              finite_number, guardrail_allows, badge_labels)

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_API = ('Site', 'WaterInput', 'UserInputs', 'Sliders', 'get_site', 'get_candidates',
                'recommend', 'tipping_points', 'question_value', 'validation_summary')


def crop_name(crop):
    """Plain crop name from the crop library, lower case: 'winter wheat' for wheat_winter."""
    try:
        from ui.recommendations import crop_label
        return crop_label(crop).lower()
    except Exception:
        return str(crop).replace('_', ' ')


def demo_presets():
    """Example farms from config/assumptions/setup.yaml: a place plus example answers, so one click reaches a result."""
    import yaml
    data = yaml.safe_load((ROOT / 'config/assumptions/setup.yaml').read_text())['demo_presets']
    value = lambda row, name, default=None: (row.get(name) or {}).get('value', default)
    return [dict(label=value(row, 'label'), lat=value(row, 'lat'), lon=value(row, 'lon'), place=value(row, 'place', ''),
                 plan=list(value(row, 'current_plan', []) or []), acres=float(value(row, 'farm_acres', 0) or 0),
                 water=value(row, 'water_mode', 'rain')) for row in data.values()]


def preset_summary(preset):
    plan = preset['plan']
    crops = (crop_name(plan[0]) + ' every year') if plan and len(set(plan)) == 1 else ', '.join(crop_name(c) for c in plan)
    water = 'rain only' if preset['water'] == 'rain' else 'irrigated'
    return f"{preset['place']} · {crops} · {water} · {preset['acres']:,.0f} acres"


DEFAULT_SLIDERS = dict(bad_year=.3, water=0., soil=.5, profit_tolerance_pct=0., climate_shift='historical')


def score_rotations(site, inputs):
    """Candidates then recommendations through the API. Returns False when no crop is available here."""
    candidates = api.get_candidates(site, inputs)
    st.write(f'Climate and crop availability checked: {len(candidates)} candidate crops.')
    if not candidates:
        st.warning('No supported crops are available here with these inputs.')
        return False
    st.write('Running weather scenarios and scoring rotations through the recommendation API…')
    rec = api.recommend(site, inputs, api.Sliders(**DEFAULT_SLIDERS))
    st.session_state.update(v4_inputs=inputs, v4_rec=rec, v4_screen='results', v4_controls=tuple(DEFAULT_SLIDERS.values()))
    st.session_state['_v5_go'] = 'Recommendations'
    st.session_state.pop('v4_tipping_result', None)
    st.session_state.pop('v4_questions', None)
    return True


def open_preset(preset):
    """One click on an example farm: load the place, fill in the example answers and go straight to the result.
    The answers stay editable under 'Edit farm details'. If anything is missing the farmer lands on the form instead."""
    lat, lon = float(preset['lat']), float(preset['lon'])
    for name in ('pin_lat', 'pin_lon', '_v4_farm_widgets', 'v4_inputs', 'v4_rec', 'v4_site', 'v4_location'):
        st.session_state.pop(name, None)
    st.session_state.update(v4_lat=lat, v4_lon=lon, v4_screen='farm')
    if missing_api() or len(preset['plan']) != 4 or preset['acres'] <= 0:
        return
    try:
        with st.status('Loading this example farm', expanded=True) as status:
            st.write('Fetching NASA weather and loading soil through the site API…')
            site = load_site(lat, lon)
            st.session_state.update(v4_site=site, v4_location=(lat, lon), v4_asof=record(site).get('data_as_of'))
            offered = list(record(record(site).get('us_defaults')).get('crops') or [])
            widgets = {'v4_farm_acres': preset['acres'], 'v4_water_mode': preset['water']}
            if getattr(site, 'currency', None):
                widgets['v4_currency'] = site.currency
            widgets.update({(f'v4_crop{i}' if offered else f'v4_crop_text{i}'): crop for i, crop in enumerate(preset['plan'])})
            st.session_state['_v4_farm_widgets'] = widgets
            if preset['water'] != 'rain' or (offered and any(c not in offered for c in preset['plan'])) or \
                    input_errors(site, preset['plan'], preset['acres'], 'rain', '', 0., 0., {}):
                return  # the form opens with the example answers filled in, and asks for what is missing
            inputs = api.UserInputs(current_plan=list(preset['plan']), water=api.WaterInput(mode='rain', source='', normal_mm=0., dry_mm=0.),
                                    farm_acres=preset['acres'], soil_test=None, history=None, crop_overrides={})
            if score_rotations(site, inputs):
                st.session_state['v4_example_farm'] = f"{preset['label']} ({preset_summary(preset)})"
                status.update(label='Rotations scored', state='complete')
    except Exception:
        logging.exception('Example farm could not be opened')
        st.session_state['v4_screen'] = 'farm'


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


def style():
    st.markdown('''<style>
    :root{--primary-color:#24734d} input{accent-color:#24734d}
    .stApp{background:#f6f8f3;color:#183b2b} .block-container{max-width:1240px;padding-top:2rem}
    h1,h2,h3{color:#183b2b;letter-spacing:-.035em} h1{font-size:clamp(2.4rem,6vw,4.8rem);line-height:1.03}
    [data-testid="stMetricValue"]{font-size:clamp(1.5rem,3vw,2.4rem)}
    [data-testid="stVerticalBlockBorderWrapper"]{background:#fff;border-radius:18px}
    .stButton>button[kind="primary"]{background:#24734d;border-color:#24734d;color:white}
    .rl-badge{display:inline-block;font-size:.72rem;font-weight:700;padding:.12rem .55rem;border-radius:999px;margin-right:.35rem;
      white-space:nowrap;line-height:1.5;border:1px solid transparent}
    .rl-badge.obs{background:#dcefe3;color:#17553a}.rl-badge.mod{background:#e1ecf7;color:#1f4e79}
    .rl-badge.loc{background:#efe7f7;color:#553285}.rl-badge.asm{background:#f1efe6;color:#5c5540;border-color:#d9d4bf}
    .rl-badge.ph{background:#fdf0c8;color:#7a5600;border-color:#ecd188}
    [data-testid="stMetricLabel"],[data-testid="stMetricLabel"] *{white-space:normal!important;overflow:visible!important;text-overflow:clip!important}
    [data-testid="stMetricValue"],[data-testid="stMetricValue"] *{white-space:normal!important;overflow:visible!important;text-overflow:clip!important;line-height:1.15}
    [data-testid="stMetricDelta"],[data-testid="stMetricDelta"] *{white-space:normal!important;overflow:visible!important}
    @media(max-width:640px){.block-container{padding:1rem} h1{font-size:2.5rem}}
    </style>''', unsafe_allow_html=True)


def start():
    st.caption('ROTATIONLAB / NASA DATA. FARM DECISIONS.')
    st.title('Healthier soil. A more resilient farm.')
    st.write('RotationLab uses NASA data to show how your climate is changing and which crop rotations could strengthen your soil while protecting profit.')
    st.caption('Four-year crop plans · Real weather years · Explainable tradeoffs')
    st.subheader('See it on an example farm')
    st.caption('One click: real NASA weather and USDA records for the place, with example answers you can change afterwards.')
    chosen = None
    for col, preset in zip(st.columns(3), demo_presets()):
        with col:
            with st.container(border=True):
                st.write(f"**{preset['label']}**")
                st.caption('Example farm: ' + preset_summary(preset))
                if st.button('Explore ' + preset['label'].split(' · ')[-1], use_container_width=True):
                    chosen = preset
    if chosen:
        open_preset(chosen)
        st.rerun()
    st.subheader('Or plan your own')
    if st.button('Plan my farm', type='primary'):
        st.session_state['v4_screen'] = 'farm'
        st.rerun()
    if missing_api():
        st.info('Global planning is waiting for the v4 engine interface. The existing Nalgonda farm explorer remains available below.')
    st.caption('Earlier single-farm version: a rice farm in Nalgonda district, Telangana, India.')
    if st.button('Open existing Nalgonda farm explorer'):
        st.session_state['legacy_app'] = True
        st.rerun()


@st.cache_data(ttl=3600, max_entries=64, show_spinner=False)
def load_site(lat, lon):
    return api.get_site(lat, lon)


def location_map():
    pending = st.session_state.pop('_v4_pending_pin', None)
    if pending:
        st.session_state.update(pin_lat=pending[0], pin_lon=pending[1])
    lat = st.number_input('Latitude', -90., 90., value=st.session_state.get('v4_lat', 42.03), key='pin_lat')
    lon = st.number_input('Longitude', -180., 180., value=st.session_state.get('v4_lon', -93.62), key='pin_lon')
    st.caption('Your input · Click the map to move your pin, or enter coordinates above.')
    m = folium.Map(location=[lat, lon], zoom_start=5, tiles='OpenStreetMap')
    folium.Marker([lat, lon], tooltip='Your farm').add_to(m)
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
        for index, layer in enumerate(layers):
            layer = record(layer)
            url = layer.get('url') or layer.get('tile_url_template')
            name = layer.get('name') or layer.get('title') or layer.get('id')
            if not url or not name:
                continue
            dates = layer.get('available_dates') or ([layer['date']] if layer.get('date') else [])
            if not dates:
                continue
            when = st.selectbox(f'{name} · available observation dates', dates, key=f'v4_layer_date_{index}')
            # Replace a specific advertised date only with another advertised date from the same layer.
            # This does not guess dates between composites or fill service gaps.
            default_date = layer.get('date') or dates[0]
            url = url.replace('{date}', when).replace('/' + default_date + '/', '/' + when + '/')
            # The first NASA layer is on when the map opens, so the satellite data is visible without hunting for the layer menu.
            folium.TileLayer(tiles=url, name=name, attr='NASA GIBS', overlay=True, show=(index == 0), opacity=.6,
                             max_native_zoom=layer.get('max_native_zoom', 8), max_zoom=18).add_to(m)
            st.caption(f"Observed · {name} · Image dated {when} · Catalog as of {layer.get('data_as_of') or 'not supplied'}")
            if layer.get('stale'):
                st.warning('Satellite catalog is an older offline snapshot; imagery may be unavailable.')
        folium.LayerControl(collapsed=False).add_to(m)
        st.caption('NASA satellite layers are shown on the map for context (switch them in the box on the map). They are not model inputs.')
    else:
        st.caption('NASA SMAP / MODIS NDVI overlays await the shared satellite-catalog API.')
    result = st_folium(m, height=360, use_container_width=True, key='v4_map', returned_objects=['last_clicked'])
    if result and result.get('last_clicked'):
        clicked = (result['last_clicked']['lat'], result['last_clicked']['lng'])
        if clicked != st.session_state.get('_v4_last_click'):
            st.session_state['_v4_last_click'] = clicked
            st.session_state['_v4_pending_pin'] = clicked
            st.rerun()
    return lat, lon


def farm():
    st.title('Tell us about your farm')
    st.write('Required: location, current four-year crop plan, farm size and water supply. Add missing economics before calculating.')
    saved = st.session_state.get('_v4_farm_widgets', {})
    for name, value in saved.items():
        st.session_state.setdefault(name, value)
    lat, lon = location_map()
    if st.button('Load this location', type='primary'):
        if missing_api():
            st.warning('Location lookup is waiting for Person 1’s v4 engine/api.py. No global results have been calculated.')
        else:
            try:
                with st.status('Loading location data', expanded=True) as status:
                    st.write('Fetching NASA weather and loading soil through the site API…')
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
        st.info('Load a location to see the supported crops and required farm questions.')
        return
    if st.session_state.get('v4_location') != (lat, lon):
        st.warning('The pin has changed. Load this location before continuing.')
        return
    stamp(site, record(site).get('badges'))
    current_currency = st.text_input('Currency code', value=getattr(site, 'currency', None) or '', key='v4_currency',
                                     help='Display label only. Enter all prices and costs in this same currency; no exchange conversion is performed.').strip().upper()
    site.currency = current_currency or None
    # Candidate filtering belongs to the engine. Current crops use the county defaults when supplied.
    crops = list(record(record(site).get('us_defaults')).get('crops') or [])
    if crops:
        plan = [col.selectbox(f'Year {i+1} current crop', crops, key=f'v4_crop{i}', format_func=lambda c: crop_name(c).capitalize())
                for i, col in enumerate(st.columns(4))]
    else:
        plan = [col.text_input(f'Year {i+1} current crop', key=f'v4_crop_text{i}').strip() for i, col in enumerate(st.columns(4))]
    acres = st.number_input('Farm size (acres) · required', min_value=0., value=0., key='v4_farm_acres')
    mode = st.radio('Water · required', ['rain', 'irrigated'],
                    index=int(float(record(record(site).get('us_defaults')).get('irrigated_share') or 0) > .5),
                    format_func=lambda x: 'Rain only' if x == 'rain' else 'Irrigated', horizontal=True, key='v4_water_mode')
    source, normal, dry = '', 0., 0.
    if mode == 'irrigated':
        source = st.text_input('Water source · required', placeholder='Well, canal, reservoir…', key='v4_water_source')
        normal = st.number_input('Normal-year supply (mm/season) · required', min_value=0., value=None, key='v4_normal_mm')
        dry = st.number_input('Dry-year supply (mm/season) · required', min_value=0., value=None, key='v4_dry_mm')
    overrides = {}
    with st.expander('Crop economics · required outside the US or when defaults are missing', expanded=True):
        st.caption('Your input · Yield kg/ha; price currency/tonne; cost currency/ha. Blank fields use engine defaults where available.')
        for crop in sorted(set(plan) - {''}):
            st.write(crop_name(crop).capitalize())
            cols = st.columns(3)
            vals = [cols[i].number_input(f'{field} · {crop}', min_value=0., value=None, key=f'v4_{crop}_{field}')
                    for i, field in enumerate(('yield', 'price', 'cost'))]
            overrides[crop] = {field: v for field, v in zip(('yield', 'price', 'cost'), vals) if v is not None}
    soil, history = None, None
    with st.expander('Soil test · optional'):
        if st.checkbox('Add a soil test', key='v4_add_soil'):
            soil = dict(organic_matter_pct=st.number_input('Organic matter (%)', 0., 100., value=None, key='v4_organic_matter'),
                        ph=st.number_input('pH', 0., 14., value=None, key='v4_ph'), texture=st.text_input('Texture', key='v4_texture'))
    with st.expander('Field history · optional'):
        if st.checkbox('Add field history', key='v4_add_history'):
            history = dict(tillage=st.selectbox('Tillage', ['No till', 'Reduced', 'Conventional'], key='v4_tillage'),
                           cover_crops=st.checkbox('Uses cover crops', key='v4_cover_crops'), erosion=st.checkbox('Erosion observed', key='v4_erosion'),
                           waterlogging=st.checkbox('Waterlogging observed', key='v4_waterlogging'), salinity=st.checkbox('Salinity observed', key='v4_salinity'))
    st.caption('Your input · Farm answers stay in this session.')
    st.session_state['_v4_farm_widgets'] = {
        name: st.session_state[name] for name in st.session_state
        if name.startswith(('v4_crop', 'v4_farm_', 'v4_water_', 'v4_add_', 'v4_normal_', 'v4_dry_'))
        or name in ('v4_organic_matter', 'v4_ph', 'v4_texture', 'v4_tillage', 'v4_cover_crops',
                    'v4_erosion', 'v4_waterlogging', 'v4_salinity', 'v4_currency')
        or any(name == f'v4_{crop}_{field}' for crop in plan for field in ('yield', 'price', 'cost'))}
    if st.button('Compare my rotations', type='primary'):
        errors = input_errors(site, plan, acres, mode, source, normal, dry, overrides)
        if len(current_currency) != 3 or not current_currency.isalpha():
            errors.append('Enter a three-letter currency code, such as USD or INR.')
        if errors:
            for error in errors:
                st.warning(error)
            return
        try:
            inputs = api.UserInputs(current_plan=plan, water=api.WaterInput(mode=mode, source=source, normal_mm=normal, dry_mm=dry),
                                    farm_acres=acres, soil_test=soil, history=history, crop_overrides=overrides)
            with st.status('Checking feasible rotations…', expanded=True) as status:
                if not score_rotations(site, inputs):
                    return
                st.session_state.pop('v4_example_farm', None)
                status.update(label='Rotations scored', state='complete')
            st.rerun()
        except Exception:
            logging.exception('Recommendation calculation failed')
            st.error('Could not calculate recommendations. Your farm details are preserved; try again.')


def _years(value, default):
    return f'{value[0]} to {value[1]}' if isinstance(value, (list, tuple)) and len(value) == 2 else str(value or default)


def _day_of_year(doy):
    """Day of year as a calendar date in a non-leap year, for example 132 -> 12 May."""
    import datetime
    d = datetime.date(2023, 1, 1) + datetime.timedelta(days=int(round(float(doy))) - 1)
    return f'{d.day} {d.strftime("%b")}'


def climate_rows(trend):
    """Display rows for the climate card: plain names, rounded values and the change. Display formatting only."""
    trend = record(trend)
    threshold = trend.get('heat_threshold_c')
    hot = f'Days above {threshold:g}°C ({threshold * 9 / 5 + 32:.0f}°F) per season' if finite_number(threshold) else 'Very hot days per season'
    spec = {'season_rain_mm': ('Growing-season rain', lambda v: f'{v:,.0f} mm', lambda a, b: f'{b - a:+,.0f} mm ({(b - a) / a * 100:+.0f}%)' if a else f'{b - a:+,.0f} mm'),
            'rain_variability_cv': ('Year-to-year swing in rain', lambda v: f'{v * 100:.0f}% of average', lambda a, b: f'{(b - a) * 100:+.0f} points'),
            'heat_days': (hot, lambda v: f'{v:.1f} days', lambda a, b: f'{b - a:+.1f} days'),
            'rainy_season_start_doy': ('Rains start (team rule of thumb)', _day_of_year,
                                       lambda a, b: 'no change' if round(b - a) == 0 else f'{abs(b - a):.0f} days ' + ('later' if b > a else 'earlier'))}
    rows = []
    for name, (label, fmt, change) in spec.items():
        pair = trend.get(name)
        if isinstance(pair, dict):
            pair = (pair.get('baseline'), pair.get('recent'))
        if not (isinstance(pair, (list, tuple)) and len(pair) == 2 and all(finite_number(v) for v in pair)):
            continue
        rows.append({'name': name, 'Measure': label, 'Baseline': fmt(pair[0]), 'Recent': fmt(pair[1]), 'Change': change(pair[0], pair[1]),
                     'Data label': provenance(record(trend.get('badges')).get(name, 'estimated'))})
    return rows


def climate_card(site):
    trend = record(record(site).get('climate_trend'))
    st.subheader('How your climate is changing')
    if not trend:
        st.info('Climate comparison is unavailable for this location.')
        return
    early, late = _years(trend.get('early_years'), '1981 to 2000'), _years(trend.get('late_years'), 'the latest 20 full years')
    st.caption(f'NASA POWER daily weather at your pin: {late} compared with {early}. What already changed here, not a forecast.')
    rows = climate_rows(trend)
    if rows:
        for col, row in zip(st.columns(len(rows)), rows):
            col.metric(row['Measure'], row['Recent'], row['Change'] + ' vs ' + early.replace(' to ', '–'), delta_color='off',
                       delta_arrow='off' if row['name'] == 'rainy_season_start_doy' else 'auto')
        table = pd.DataFrame(rows).drop(columns='name').rename(columns={'Baseline': early, 'Recent': late})
        with st.expander('The numbers behind this'):
            st.dataframe(table, hide_index=True, use_container_width=True)
            if trend.get('note'):
                st.caption(trend['note'])
    stamp(trend, trend.get('badges'))


def render():
    style()
    if st.session_state.get('v4_screen', 'start') == 'start':
        start()
    else:
        farm()
