# AI use: this file was written by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Tests for engine.fetch_nass, engine.fetch_ers and engine.us_rules (Person 3, Feature 4).

NASS tests run against a fake Quick Stats layer. Every NASS record below is SYNTHETIC TEST DATA built to
exercise the code paths (suppression codes, unit conversion, state fallback); none of it is a real NASS
value. ERS tests use the real ERS files committed in data/precache/ (downloaded 2026-11-15).
"""
import pytest

from engine import cache, fetch_ers, fetch_nass, us_rules


@pytest.fixture
def iso_cache(tmp_path, monkeypatch):
    """Runtime cache in a temp folder; the committed pre-cache (ERS) stays readable."""
    monkeypatch.setattr(cache, "RUNTIME_DIR", tmp_path / "cache")
    monkeypatch.delenv("ROTATIONLAB_OFFLINE", raising=False)
    return tmp_path


def _rec(year, value, commodity="CORN", stat="YIELD", unit="BU / ACRE", level="COUNTY", **kw):
    r = {"year": year, "Value": value, "commodity_desc": commodity, "statisticcat_desc": stat, "unit_desc": unit,
         "agg_level_desc": level, "reference_period_desc": "YEAR", "prodn_practice_desc": "ALL PRODUCTION PRACTICES",
         "util_practice_desc": "GRAIN" if commodity == "CORN" else "ALL UTILIZATION PRACTICES", "class_desc": "ALL CLASSES"}
    r.update(kw)
    return r


def _fake_nass(monkeypatch, routes):
    """routes: function(params) -> list of records."""
    monkeypatch.setenv("NASS_API_KEY", "test-key-not-real")
    calls = []

    def fake_get(params):
        calls.append(dict(params))
        return routes(params)

    monkeypatch.setattr(fetch_nass, "_get", fake_get)
    return calls


# ------------------------------------------------------------------------------------------- NASS

def test_parse_value_handles_suppression_and_commas():
    assert fetch_nass.parse_value("1,234.5") == 1234.5
    for code in ("(D)", "(Z)", "(NA)", " (X) ", "", None):
        assert fetch_nass.parse_value(code) is None


def test_unit_conversion_corn_bushel():
    # 56 lb/bu * 0.45359237 kg/lb / 0.40468564224 ha/acre = 62.77 kg/ha per bu/acre
    assert fetch_nass.kg_ha_per_unit("maize") == pytest.approx(62.77, abs=0.01)
    assert fetch_nass.kg_ha_per_unit("soybean") == pytest.approx(67.25, abs=0.01)


def test_suppressed_county_falls_back_to_state_average_labelled(iso_cache, monkeypatch):
    def routes(p):
        if p["agg_level_desc"] == "COUNTY":      # every county value withheld
            return [_rec(y, "(D)") for y in range(2015, 2025)]
        return [_rec(y, "180", level="STATE") for y in range(2015, 2025)]
    _fake_nass(monkeypatch, routes)
    county_only = fetch_nass.county_yields("19169", "maize")
    assert county_only.empty                     # the hindcast never validates against a state number
    df = fetch_nass.county_yields("19169", "maize", allow_state=True)
    assert set(df["level"]) == {"state"} and len(df) == 10
    d = fetch_nass.default_yield("19169", "maize")
    assert d["level"] == "state" and d["badge"] == "estimated" and d["note"] == fetch_nass.STATE_NOTE
    assert d["yield_kg_ha"] == pytest.approx(180 * fetch_nass.kg_ha_per_unit("maize"), abs=0.1)


def test_county_yields_used_when_published(iso_cache, monkeypatch):
    _fake_nass(monkeypatch, lambda p: [_rec(2020, "200"), _rec(2021, "(D)"), _rec(2022, "210"),
                                       _rec(2022, "150", prodn_practice_desc="NON-IRRIGATED")])
    df = fetch_nass.county_yields("19169", "maize")
    assert list(df["year"]) == [2020, 2022] and set(df["level"]) == {"county"}
    nonirr = fetch_nass.county_yields("19169", "maize", practice="NON-IRRIGATED")
    assert list(nonirr["year"]) == [2022]


def test_no_key_and_no_cache_raises_and_us_defaults_says_unavailable(iso_cache, monkeypatch):
    monkeypatch.delenv("NASS_API_KEY", raising=False)
    with pytest.raises(fetch_nass.NassUnavailable):
        fetch_nass.county_yields("19169", "maize")
    d = fetch_nass.us_defaults("19169")
    assert d["available"] is False and d["yields"] == {} and d["prices"] == {}
    assert d["badges"]["nass"] == "missing"
    assert d["costs"]["maize"] > 0              # ERS costs still come from the committed pre-cache


def test_cached_copy_used_without_key(iso_cache, monkeypatch):
    calls = _fake_nass(monkeypatch, lambda p: [_rec(2020, "200")])
    fetch_nass.county_yields("19169", "maize")
    monkeypatch.delenv("NASS_API_KEY")
    df = fetch_nass.county_yields("19169", "maize")
    assert len(df) == 1 and len(calls) == 1


def test_price_state_then_national(iso_cache, monkeypatch):
    def routes(p):
        if p.get("agg_level_desc") == "STATE":
            return []
        return [_rec(2023, "4.50", stat="PRICE RECEIVED", unit="$ / BU", level="NATIONAL"),
                _rec(2024, "4.00", stat="PRICE RECEIVED", unit="$ / BU", level="NATIONAL")]
    _fake_nass(monkeypatch, routes)
    p = fetch_nass.prices_received("19", "maize")
    assert p["level"] == "national" and p["year"] == 2024
    assert p["usd_per_t"] == pytest.approx(4.00 * 1000 / (56 * 0.45359237), abs=0.01)


# ------------------------------------------------------------------------------------------- R2 rules

def test_irrigated_default_triggers_in_ca_central_valley(iso_cache, monkeypatch):
    """Fresno County, CA (06019), Central Valley. Census records here are synthetic, shaped like NASS output."""
    def routes(p):
        return [_rec(2022, "900,000", commodity="AG LAND", stat="AREA", unit="ACRES",
                     short_desc="AG LAND, IRRIGATED - ACRES"),
                _rec(2022, "1,100,000", commodity="AG LAND", stat="AREA", unit="ACRES",
                     short_desc="AG LAND, CROPLAND - ACRES")]
    _fake_nass(monkeypatch, routes)
    share = fetch_nass.irrigated_share("06019")
    assert share == pytest.approx(0.818, abs=0.001)
    w = us_rules.water_default(share)
    assert w["mode"] == "irrigated" and w["ask_water_first"] is True
    rules = us_rules.apply("CA", "06019", {"crops": ["maize", "almonds"], "irrigated_share": share, "costs": {}})
    assert rules["water"]["mode"] == "irrigated"
    assert rules["not_supported"] == ["almonds"] and rules["offered"] == ["maize"]


def test_rainfed_county_defaults_to_rain_and_unknown_asks():
    assert us_rules.water_default(0.05)["mode"] == "rain"
    assert us_rules.water_default(None)["mode"] is None


def test_alaska_and_hawaii_unsupported():
    for st in ("AK", "HI", "hi"):
        r = us_rules.apply(st, None, {"crops": ["maize"]})
        assert r["supported"] is False and r["message"] == us_rules.UNSUPPORTED_STATE_MSG
    assert us_rules.state_supported("IA")


@pytest.mark.parametrize("crop", ["almonds", "walnut", "apples", "oranges", "grapes", "citrus", "pecans"])
def test_orchard_crops_not_offered(crop):
    assert us_rules.is_orchard(crop)


@pytest.mark.parametrize("crop", ["maize", "soybean", "pea", "peanut", "potato", "oats", "wheat_winter"])
def test_field_crops_are_not_orchard(crop):
    assert not us_rules.is_orchard(crop)


def test_crops_without_ers_cost_require_farmer_input(iso_cache):
    assert us_rules.needs_farmer_cost("potato", "19169")
    assert us_rules.needs_farmer_cost("canola", "38017")
    assert not us_rules.needs_farmer_cost("maize", "19169")
    assert not us_rules.needs_farmer_cost("potato", "19169", costs={"potato": 2500.0})
    r = us_rules.apply("IA", "19169", {"crops": ["maize", "potato"], "costs": {}})
    assert r["needs_cost"] == ["potato"]


# ------------------------------------------------------------------------------------------- ERS

@pytest.mark.parametrize("fips,state,region", [
    ("19169", "IA", "Heartland"), ("17113", "IL", "Heartland"), ("38017", "ND", "Northern Great Plains"),
    ("20191", "KS", "Prairie Gateway"), ("42071", "PA", "Northern Crescent"), ("13205", "GA", "Southern Seaboard"),
    ("28151", "MS", "Mississippi Portal"), ("06019", "CA", "Fruitful Rim"), ("53075", "WA", "Basin and Range"),
])
def test_ers_region_mapping(iso_cache, fips, state, region):
    """Expected regions read from ERS reglink.xls (downloaded 2026-11-15); 9 counties in 9 states."""
    assert fetch_nass.STATE_FIPS[fips[:2]] == state
    assert fetch_ers.region_for_county(fips)["name"] == region


def test_ers_cost_matches_raw_csv_and_falls_back_to_us(iso_cache):
    c = fetch_ers.cost_for_county("19169", "maize")
    assert c["region"] == "Heartland" and c["year"] == 2025 and c["usd_per_acre"] == 474.71   # raw ERS value
    assert c["usd_per_ha"] == pytest.approx(474.71 / 0.40468564224, abs=0.01)
    ca = fetch_ers.cost_for_county("06019", "maize")              # ERS has no Fruitful Rim corn row
    assert ca["level"] == "us" and ca["region"] == "U.S. total"
    pn = fetch_ers.cost_for_county("13205", "peanut")             # sub-region matched by state
    assert pn["region"] == "Southern Seaboard (AL, GA)"
    assert fetch_ers.cost_for_county("19169", "potato") is None
