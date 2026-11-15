# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Address lookup and crop history from public records, tested with a fake network (no internet needed).
One optional live test runs only when RL_LIVE=1."""
import os

import pytest
import requests

from engine import address, fetch_cdl as cdl


class Resp:
    def __init__(self, text="", js=None, code=200):
        self.text, self._js, self.status_code = text, js, code

    def json(self):
        if self._js is None:
            raise ValueError("no json")
        return self._js

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def cdl_reply(category):
    return Resp(text=f'<ns1:R><Result>{{x: 1.0, y: 2.0, value: 1, category: "{category}", color: "#000"}}</Result></ns1:R>')


# ------------------------------------------------------------------------------------------------ projection
def test_albers_projection_matches_the_reference_library():
    pyproj = pytest.importorskip("pyproj")
    t = pyproj.Transformer.from_crs(4326, 5070, always_xy=True)
    for lon, lat in [(-93.62, 42.20), (-97.60, 38.40), (-83.60, 31.50), (-120.1, 36.6), (-70.0, 44.0), (-110.0, 33.0)]:
        a, b = t.transform(lon, lat)
        x, y = cdl.to_albers(lon, lat)
        assert abs(a - x) < 0.01 and abs(b - y) < 0.01


def test_albers_origin_is_zero_at_23n_96w():
    x, y = cdl.to_albers(-96.0, 23.0)
    assert abs(x) < 1e-6 and abs(y) < 1e-6


# ------------------------------------------------------------------------------------------------ crop history
def test_categories_map_to_crop_ids_and_unknowns_are_not_supported():
    assert cdl.classify("Corn")["crop"] == "maize" and cdl.classify("Soybeans")["crop"] == "soybean"
    assert cdl.classify("Winter Wheat")["crop"] == "wheat_winter" and cdl.classify("Peanuts")["crop"] == "peanut"
    d = cdl.classify("Dbl Crop WinWht/Soybeans")
    assert d["crop"] == "wheat_winter" and "double cropped" in d["note"]
    for c in ("Grass/Pasture", "Developed/Low Intensity", "Fallow/Idle Cropland", "Open Water", "", None):
        assert cdl.classify(c)["supported"] is False


def test_every_mapped_crop_exists_in_the_crop_library():
    from engine import crops
    lib = set(crops.crop_library())
    assert set(cdl.CROP_MAP.values()) <= lib


def test_crop_history_reads_each_year_oldest_first(monkeypatch):
    cdl._history.cache_clear()
    by_year = {2021: "Corn", 2022: "Corn", 2023: "Soybeans", 2024: "Corn", 2025: "Corn"}
    monkeypatch.setattr(requests, "get", lambda url, params=None, **k: cdl_reply(by_year[int(params["year"])]))
    h = cdl.crop_history(42.2, -93.62)
    assert [r["year"] for r in h] == [2021, 2022, 2023, 2024, 2025]
    assert [r["crop"] for r in h] == ["maize", "maize", "soybean", "maize", "maize"]


def test_one_failed_year_does_not_break_the_others(monkeypatch):
    cdl._history.cache_clear()
    def fake(url, params=None, **k):
        if int(params["year"]) == 2023:
            raise requests.ConnectionError("down")
        return cdl_reply("Corn")
    monkeypatch.setattr(requests, "get", fake)
    h = {r["year"]: r for r in cdl.crop_history(42.21, -93.63)}
    assert h[2023]["crop"] is None and "did not answer" in h[2023]["note"] and h[2024]["crop"] == "maize"


def test_outside_the_lower_48_is_refused_with_a_clear_message():
    for lat, lon in [(64.8, -147.7), (21.3, -157.8), (17.5, 78.5), (51.5, -0.1)]:    # Alaska, Hawaii, India, UK
        with pytest.raises(ValueError, match="lower 48"):
            cdl.crop_history(lat, lon)


def test_suggested_plan_uses_the_last_four_years_and_leaves_pasture_blank():
    hist = [{"year": y, **cdl.classify(c)} for y, c in [(2021, "Corn"), (2022, "Corn"), (2023, "Soybeans"), (2024, "Grass/Pasture"), (2025, "Corn")]]
    s = cdl.suggest_plan(hist)
    assert s["years"] == [2022, 2023, 2024, 2025] and s["plan"] == ["maize", "soybean", None, "maize"] and s["complete"] is False
    assert any("2024" in m and "left blank" in m for m in s["messages"])
    full = cdl.suggest_plan([{"year": y, **cdl.classify("Corn")} for y in (2022, 2023, 2024, 2025)])
    assert full["complete"] is True and full["plan"] == ["maize"] * 4 and not full["messages"]


def test_double_crop_year_is_explained_in_the_messages():
    s = cdl.suggest_plan([{"year": y, **cdl.classify(c)} for y, c in [(2022, "Winter Wheat"), (2023, "Dbl Crop WinWht/Soybeans"), (2024, "Sorghum"), (2025, "Soybeans")]])
    assert s["plan"] == ["wheat_winter", "wheat_winter", "sorghum", "soybean"] and any("double cropped" in m for m in s["messages"])


# ------------------------------------------------------------------------------------------------ address
CENSUS_OK = {"result": {"addressMatches": [{"matchedAddress": "123 MAIN ST, AMES, IA, 50010", "coordinates": {"x": -93.62, "y": 42.03},
             "addressComponents": {"state": "IA"}, "geographies": {"States": [{"STUSAB": "IA", "STATE": "19"}],
             "Counties": [{"BASENAME": "Story", "NAME": "Story County", "STATE": "19", "COUNTY": "169"}]}}]}}


def test_address_lookup_returns_location_state_and_county(monkeypatch):
    address._lookup.cache_clear()
    monkeypatch.setattr(requests, "get", lambda *a, **k: Resp(js=CENSUS_OK))
    g = address.geocode("  123 Main St,  Ames, IA ")
    assert g["lat"] == 42.03 and g["lon"] == -93.62 and g["state"] == "IA" and g["county"] == "Story" and g["county_fips"] == "19169"


def test_address_with_no_match_says_so_and_points_to_the_map(monkeypatch):
    address._lookup.cache_clear()
    monkeypatch.setattr(requests, "get", lambda *a, **k: Resp(js={"result": {"addressMatches": []}}))
    with pytest.raises(address.AddressNotFound, match="US addresses only"):
        address.geocode("10 Downing Street, London")


def test_address_service_down_gives_a_friendly_error(monkeypatch):
    address._lookup.cache_clear()
    def boom(*a, **k):
        raise requests.ConnectionError("x")
    monkeypatch.setattr(requests, "get", boom)
    with pytest.raises(address.AddressLookupError, match="could not be reached"):
        address.geocode("123 Main St, Ames, IA")


def test_too_short_or_too_long_addresses_are_refused_before_any_request(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("no request should be made"))
    for bad in ("", "  ", "ab", "x" * 300):
        with pytest.raises(address.AddressNotFound):
            address.geocode(bad)


@pytest.mark.skipif(os.environ.get("RL_LIVE") != "1", reason="live test: set RL_LIVE=1 to run against the real services")
def test_live_address_and_crop_history():
    g = address.geocode("1600 Pennsylvania Ave NW, Washington, DC 20500")
    assert g["state"] == "DC"
    h = cdl.crop_history(42.20, -93.62)
    assert len(h) == 5 and any(r["crop"] == "maize" for r in h)
