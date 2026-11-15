# AI use: written and revised with OpenAI Codex under the team's direction. See AI_USE.md.
"""Feature 1 application shell. Feature calculations go exclusively through engine.api."""
from pathlib import Path
import logging
import os
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import streamlit as st

st.set_page_config(page_title='RotationLab', page_icon='🌱', layout='wide', initial_sidebar_state='collapsed')
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
    setup.style()
    pending = st.session_state.pop('_v5_go', None)
    if pending:
        st.session_state['v5_page'] = pending
    if 'v4_rec' not in st.session_state and st.session_state.get('v5_page') not in ('Farm setup', 'How good is this?', 'Field zones'):
        st.session_state['v5_page'] = 'Farm setup'
    st.session_state.setdefault('v5_page', 'Recommendations' if 'v4_rec' in st.session_state else 'Farm setup')
    with st.sidebar:
        page = st.radio('Pages', ['Farm setup', 'Recommendations', 'Tipping points', 'What to measure next', 'How good is this?', 'Field zones'], key='v5_page')
        if st.button('Start again'):
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
        elif page == 'Field zones':
            from ui import zones
            zones.render(st.session_state.get('v4_site'), st.session_state.get('v4_inputs'))
        elif 'v4_inputs' not in st.session_state:
            st.info('Complete your farm setup before viewing modeled results.')
        else:
            site, inputs = st.session_state['v4_site'], st.session_state['v4_inputs']
            st.info('Modeled estimates for planning. Not a guarantee of yield or profit.')
            if st.button('Edit farm details'):
                st.session_state['v4_screen'] = 'farm'
                st.session_state['_v5_go'] = 'Farm setup'
                st.rerun()
            st.toggle('Metric units (hectares and per-hectare values)', key='v4_metric')
            sliders = st.session_state.get('_v5_last_sliders', api.default_sliders())
            try:
                if 'v4_validation' not in st.session_state:
                    st.session_state['v4_validation'] = api.validation_summary()
                from ui.trust import banner_for_site
                banner = banner_for_site(site, summary=st.session_state['v4_validation'])
                if banner['show']:
                    st.warning(banner['text'])
            except Exception:
                logging.exception('Validation records could not be loaded')
                st.warning('Validation records could not be loaded. Not validated here; local performance is unconfirmed.')
            if page == 'Recommendations':
                setup.climate_card(site)
                from ui import recommendations
                def recommend_page(values, most_food):
                    from ui.planner_model import guardrail_allows
                    controls = api.Sliders(**values)
                    st.session_state['_v5_last_sliders'] = controls
                    raw = api.recommend_details(site, inputs, controls, most_food=most_food)
                    if raw.get('headline') and not guardrail_allows(raw, controls.profit_tolerance_pct):
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
                                       area_unit='ha' if st.session_state.get('v4_metric') else 'acre', recommend_fn=recommend_page)
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
                               area_unit='ha' if st.session_state.get('v4_metric') else 'acre', question_fn=question_page)
    except (NotImplementedError, ValueError) as exc:
        st.warning(str(exc))
    except Exception:
        logging.exception('RotationLab page failed')
        st.error('This page could not be loaded. Your farm answers are preserved; try again or return to Farm setup.')
