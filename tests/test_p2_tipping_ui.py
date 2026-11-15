# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Feature 2 (Person 2): the Tipping Points page renders with plain Streamlit. Offline: synthetic weather."""
from streamlit.testing.v1 import AppTest

PAGE = '''
import streamlit as st
from tests.test_p2_tipping import make_inputs, make_site
from tests.test_p2_simulation import make_weather
from ui import tipping as page

if "site" not in st.session_state and st.query_params.get("farm", "yes") == "yes":
    st.session_state["site"] = make_site(make_weather(1981, 2025, seed=11))
    st.session_state["inputs"] = make_inputs("irrigated", 200.0, 100.0)
    st.session_state["sliders"] = {"climate_shift": "recent"}
page.render()
'''


def test_page_renders_map_curves_and_labels():
    at = AppTest.from_string(PAGE, default_timeout=120).run()
    assert not at.exception, at.exception
    assert at.header[0].value == "Tipping points"
    assert [s.value for s in at.subheader] == ["Rainfall and water map", "If rainfall changes",
                                               "If your water supply changes", "If it gets hotter"]
    text = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "not forecasts" in text and "Your farm now" in text and "Recent" in text
    assert "`Estimated`" in text and "`Observed`" in text and "`Assumption`" in text      # data labels on the page
    assert "<span" not in text and "<div" not in text                                   # plain Streamlit, no HTML
    assert not at.error
    kept = at.session_state["_tipping_result"]
    at.run()                                                                            # second run reuses the result
    assert at.session_state["_tipping_result"][1] is kept[1]


def test_page_asks_for_a_farm_when_there_is_none():
    at = AppTest.from_string(PAGE, default_timeout=60)
    at.query_params["farm"] = "no"
    at.run()
    assert not at.exception and "Set up your farm first" in at.info[0].value
