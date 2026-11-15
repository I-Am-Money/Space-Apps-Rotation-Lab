# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""The address box on the setup page, run headlessly with a fake network."""
import requests
from streamlit.testing.v1 import AppTest

from engine import address, fetch_cdl

CENSUS = {"result": {"addressMatches": [{"matchedAddress": "123 COUNTY ROAD 5, AMES, IA, 50010", "coordinates": {"x": -93.62, "y": 42.2},
          "geographies": {"States": [{"STUSAB": "IA", "STATE": "19"}], "Counties": [{"BASENAME": "Story", "STATE": "19", "COUNTY": "169"}]}}]}}
HISTORY = {2021: "Corn", 2022: "Corn", 2023: "Soybeans", 2024: "Corn", 2025: "Grass/Pasture"}


class R:
    def __init__(self, text="", js=None):
        self.text, self._js = text, js

    def json(self):
        return self._js

    def raise_for_status(self):
        pass


def fake_get(url, params=None, **k):
    if "geocoding" in url:
        return R(js=CENSUS if "Ames" in params["address"] else {"result": {"addressMatches": []}})
    cat = HISTORY[int(params["year"])]
    return R(text=f'<Result>{{x: 1.0, y: 2.0, value: 1, category: "{cat}", color: "#000"}}</Result>')


def _app():
    from ui import autofill
    autofill.render()


def _fresh(monkeypatch):
    address._lookup.cache_clear(); fetch_cdl._history.cache_clear()
    monkeypatch.setattr(requests, "get", fake_get)


def _text(at):
    parts = [e.value for g in (at.markdown, at.caption, at.info, at.warning, at.success, at.error) for e in g]
    for t in at.table:
        parts.append(t.value.to_string())
    return " ".join(parts)


def test_found_address_shows_what_public_records_say_and_asks_to_confirm(monkeypatch):
    _fresh(monkeypatch)
    at = AppTest.from_function(_app, default_timeout=60).run()
    at.text_input(key="v4_addr").set_value("123 County Road 5, Ames, IA").run()
    at.button(key="v4_addr_go").click().run()
    assert not at.exception
    t = _text(at)
    assert "We found" in t and "Story County, IA" in t and "Corn" in t and "Grass/Pasture" in t
    assert "county records, which are not connected yet" in t and "Is this your land?" in t
    assert any(b.key == "v4_addr_yes" for b in at.button) and any(b.key == "v4_addr_no" for b in at.button)


def test_confirming_sets_the_pin_the_crop_plan_and_loads_the_site(monkeypatch):
    _fresh(monkeypatch)
    at = AppTest.from_function(_app, default_timeout=60).run()
    at.text_input(key="v4_addr").set_value("123 County Road 5, Ames, IA").run()
    at.button(key="v4_addr_go").click().run()
    at.button(key="v4_addr_yes").click().run()
    s = at.session_state
    assert s["_v4_pending_pin"] == (42.2, -93.62) and s["_v4_autoload"] is True
    assert s["v4_cdl_plan"] == ["maize", "soybean", "maize", None]        # 2022-2025; the pasture year is left blank
    assert "applied below" in _text(at)


def test_clearing_forgets_everything(monkeypatch):
    _fresh(monkeypatch)
    at = AppTest.from_function(_app, default_timeout=60).run()
    at.text_input(key="v4_addr").set_value("123 County Road 5, Ames, IA").run()
    at.button(key="v4_addr_go").click().run()
    at.button(key="v4_addr_no").click().run()
    assert "v4_found" not in at.session_state and "v4_cdl_plan" not in at.session_state and "_v4_autoload" not in at.session_state


def test_unknown_address_gives_a_clear_message_and_no_apply_button(monkeypatch):
    _fresh(monkeypatch)
    at = AppTest.from_function(_app, default_timeout=60).run()
    at.text_input(key="v4_addr").set_value("10 Downing Street, London").run()
    at.button(key="v4_addr_go").click().run()
    assert not at.exception and "US addresses only" in _text(at)
    assert not any(b.key == "v4_addr_yes" for b in at.button)


def test_a_spot_outside_the_lower_48_still_confirms_the_location_without_crops(monkeypatch):
    _fresh(monkeypatch)
    far = {"result": {"addressMatches": [{"matchedAddress": "1 MAIN ST, FAIRBANKS, AK, 99701", "coordinates": {"x": -147.7, "y": 64.84},
           "geographies": {"States": [{"STUSAB": "AK", "STATE": "02"}], "Counties": [{"BASENAME": "Fairbanks North Star", "STATE": "02", "COUNTY": "090"}]}}]}}
    monkeypatch.setattr(requests, "get", lambda url, params=None, **k: R(js=far))
    at = AppTest.from_function(_app, default_timeout=60).run()
    at.text_input(key="v4_addr").set_value("1 Main St, Fairbanks, AK").run()
    at.button(key="v4_addr_go").click().run()
    assert not at.exception and "lower 48" in _text(at) and any(b.key == "v4_addr_yes" for b in at.button)
    at.button(key="v4_addr_yes").click().run()
    assert at.session_state["v4_cdl_plan"] == []


def test_address_is_never_written_to_disk(monkeypatch, tmp_path):
    _fresh(monkeypatch)
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_function(_app, default_timeout=60).run()
    at.text_input(key="v4_addr").set_value("123 County Road 5, Ames, IA").run()
    at.button(key="v4_addr_go").click().run()
    assert list(tmp_path.iterdir()) == []
