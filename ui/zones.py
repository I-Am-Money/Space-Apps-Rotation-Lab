# TODO: stretch page awaits official elevation/soil zone integration and verified field-area conservation.
# AI use: written with OpenAI Codex under the team's direction. See AI_USE.md.
import streamlit as st


def render(site=None, inputs=None, sliders=None):
    st.header('Field zones')
    st.info('Field zones are not enabled yet. Whole-farm planning is available.')
    st.caption('No elevation zones, field boundaries or per-zone recommendations have been inferred.')
