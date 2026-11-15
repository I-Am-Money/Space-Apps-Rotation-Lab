# AI use: written with AI coding assistants (Claude Code and OpenAI Codex) under the team's direction. See AI_USE.md.
"""Render every screen against cached real data without an API key."""
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from engine import api_v3 as api


def test_five_screens_and_supply_override(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ROTATIONLAB_MOCK", raising=False)
    monkeypatch.setattr(api, "N_SCEN", 20)
    monkeypatch.setattr(api, "BOUNDARY_N_SCEN", 20)
    api.set_annual(None)
    st.cache_data.clear()
    path = Path(__file__).resolve().parents[1] / "app.py"
    try:
        for view in ("My Field", "Compare Futures", "My Priorities", "Tipping Points", "How Good Is This?"):
            app = AppTest.from_file(str(path), default_timeout=120)
            app.session_state["nav"] = view
            app.run()
            assert not app.exception, [(e.message, e.stack_trace) for e in app.exception]
            assert app.session_state["_mock"] is False
            if view == "My Field":
                # Streamlit 1.51's testing API represents single-select button groups as lists.
                for group in app.get("button_group"):
                    value = group.value
                    if not hasattr(type(group), "formatted_values") and isinstance(value, str):
                        group.set_value([value])
                app.checkbox(key="w_canal_override").check().run()
                assert not app.exception
                assert app.session_state["_v"]["canal_supply"] == 600
                app.checkbox(key="w_use_cost_overrides").check().run()
                assert not app.exception
                assert app.number_input(key="w_soil_test_cost").value is None
                assert app.number_input(key="w_water_test_cost").value is None
                assert app.session_state["_v"]["soil_test_cost"] is None
                assert app.session_state["_v"]["water_test_cost"] is None
    finally:
        st.cache_data.clear()
        api.set_annual(None)
