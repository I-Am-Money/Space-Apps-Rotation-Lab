"""Render every screen against cached real data without an API key."""
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from engine import api


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
    finally:
        st.cache_data.clear()
        api.set_annual(None)
