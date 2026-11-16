# AI use: written and revised with OpenAI Codex under the team's direction. See AI_USE.md.
"""Feature 1 application shell. Feature calculations go exclusively through engine.api."""
from pathlib import Path
import logging
import os
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import streamlit as st

st.set_page_config(page_title='RotationLab', page_icon=str(Path(__file__).resolve().parent / 'assets' / 'favicon.svg'),
                   layout='wide', initial_sidebar_state='expanded')
try:
    for name in ('ANTHROPIC_API_KEY', 'NASS_API_KEY'):
        if name in st.secrets:
            os.environ.setdefault(name, str(st.secrets[name]))
except FileNotFoundError:
    pass

if st.session_state.get('legacy_app') or st.session_state.get('nav'):
    if st.button('← Global planner'):
        st.session_state.pop('legacy_app', None)
        st.session_state.pop('nav', None)
        st.rerun()
    from ui.legacy_app import render
    render()
else:
    from engine import api
    from ui import setup
    pending = st.session_state.pop('_v5_go', None)
    if pending:
        st.session_state['v5_page'] = pending
    if 'v4_rec' not in st.session_state and st.session_state.get('v5_page') not in ('Farm setup', 'How good is this?'):
        st.session_state['v5_page'] = 'Farm setup'
    st.session_state.setdefault('v5_page', 'Recommendations' if 'v4_rec' in st.session_state else 'Farm setup')
    PAGE_NAMES = {'Farm setup': '1. Your farm', 'Recommendations': '2. Best crop plans', 'Tipping points': '3. What could change it',
                  'What to measure next': '4. What to check first', 'How good is this?': 'Can I trust this?'}
    # The side panel holds everything you can press: the page list, the controls of the open page, then the farm actions.
    with st.sidebar:
        st.title('RotationLab')
        st.caption('Four-year crop plans tested against decades of NASA weather records.')
        page = st.radio('Pages', list(PAGE_NAMES), key='v5_page', format_func=PAGE_NAMES.get)
        controls = st.container()                 # each page puts its sliders and inputs here
        st.divider()
        if 'v4_inputs' in st.session_state and page not in ('Farm setup', 'How good is this?'):
            st.toggle('Show hectares instead of acres', key='v4_metric')
            if st.button('Edit farm details', use_container_width=True):
                st.session_state['v4_screen'] = 'farm'
                st.session_state['_v5_go'] = 'Farm setup'
                st.rerun()
        if st.button('Start again', help='Clear this farm and go back to the first page.', use_container_width=True):
            for key in list(st.session_state):
                if key.startswith(('v4_', '_v4_', 'v5_', '_v5_', 'rec_', 'meas_')) or key in ('pin_lat', 'pin_lon', '_tipping_result'):
                    del st.session_state[key]
            st.rerun()
    try:
        if page == 'Farm setup':
            if st.session_state.get('v4_screen') == 'results':
                st.session_state['v4_screen'] = 'farm'
            setup.render()
        elif page == 'How good is this?':
            from ui import trust
            trust.render()
        elif 'v4_inputs' not in st.session_state:
            st.info('Fill in the "Your farm" page first. The crop plans are worked out from your answers.')
        else:
            site, inputs = st.session_state['v4_site'], st.session_state['v4_inputs']
            sliders = st.session_state.get('_v5_last_sliders', api.default_sliders())

            def notices():
                """The standing notes for every results page: the disclaimer, the example-farm note and the accuracy check."""
                st.caption('Modeled estimates for planning. Not a guarantee of yield or profit. This tool supports, and does not replace, '
                           'your own judgment and local advice.')
                if st.session_state.get('v4_example_farm'):
                    st.caption('Example farm: ' + st.session_state['v4_example_farm'] + '. The weather, soil, yields, prices and costs are real '
                               'records for this place. The farm answers are an example: change them with "Edit farm details".')
                try:
                    if 'v4_validation' not in st.session_state:
                        st.session_state['v4_validation'] = api.validation_summary()
                    from ui.trust import banner_for_site
                    banner = banner_for_site(site, summary=st.session_state['v4_validation'])
                    if banner['show']:
                        st.warning(banner['text'])
                    elif banner.get('text'):
                        st.caption(banner['text'])
                except Exception:
                    logging.exception('Validation records could not be loaded')
                    st.warning('Validation records could not be loaded. Not validated here; local performance is unconfirmed.')
            notices()
            if page == 'Recommendations':
                from ui import recommendations
                def recommend_page(values, most_food):
                    from ui.planner_model import guardrail_allows
                    controls_now = api.Sliders(**values)
                    st.session_state['_v5_last_sliders'] = controls_now
                    raw = api.recommend_details(site, inputs, controls_now, most_food=most_food)
                    if raw.get('headline') and not guardrail_allows(raw, controls_now.profit_tolerance_pct):
                        st.warning('The returned headline has been withheld because it does not meet your profit guardrail.')
                        raw = dict(raw, headline=None, guardrail_met=False)
                    old = st.session_state.get('_v5_controls')
                    current = tuple(values.values())
                    if old is not None and old != current:
                        st.session_state.pop('v4_tipping_result', None)
                        st.session_state.pop('v4_questions', None)
                    st.session_state['_v5_controls'] = current
                    st.session_state['v4_rec'] = raw
                    return raw
                recommendations.render(site, inputs, currency=getattr(site, 'currency', None) or 'local currency',
                                       area_unit='ha' if st.session_state.get('v4_metric') else 'acre', recommend_fn=recommend_page,
                                       controls=controls, extra_tabs={'Your climate': lambda: setup.climate_card(site)})
            elif page == 'Tipping points':
                from ui import tipping
                tipping.render(site, inputs, sliders)
            else:
                from ui import measure
                def question_page(costs):
                    rows = api.question_value_details(site, inputs, sliders, test_costs=costs)
                    st.session_state['v4_questions'] = rows
                    return rows
                measure.render(site, inputs, sliders, currency=getattr(site, 'currency', None) or 'local currency',
                               area_unit='ha' if st.session_state.get('v4_metric') else 'acre', question_fn=question_page, controls=controls)
    except (NotImplementedError, ValueError) as exc:
        st.warning(str(exc))
    except Exception:
        logging.exception('RotationLab page failed')
        st.error('This page could not be loaded. Your farm answers are preserved; try again or return to Farm setup.')
