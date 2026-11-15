# AI use: this file was written by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Tests for ui/trust.py (Person 3): R21 banner logic, validation rows, assumptions table.
Validation numbers below are SYNTHETIC test values, not results."""
from types import SimpleNamespace

import pandas as pd

from ui import trust


def _summary(status="ok"):
    t = pd.DataFrame([{"site": "IA-story", "crop": "maize", "fips": "19169", "county": "Story County", "state": "IA",
                       "ers_region": "Heartland", "water": "rain", "r": 0.61, "mae": 900.0, "r_corrected": 0.66,
                       "mae_corrected": 700.0, "n_train": 30, "n_test": 8, "status": status, "badge": "Estimated",
                       "lat": 42.0, "lon": -93.5}])
    return SimpleNamespace(table=t, sites=[])


def test_banner_shows_outside_us():
    assert trust.banner_for_site({"us_county_fips": None}, _summary())["show"]
    assert trust.banner_for_site(None, _summary())["text"] == trust.NOT_VALIDATED


def test_banner_hidden_only_in_validated_county_and_crop():
    s = _summary()
    assert not trust.banner_for_site({"us_county_fips": "19169"}, s)["show"]
    assert not trust.banner_for_site(SimpleNamespace(us_county_fips="19169"), s, crop="maize")["show"]
    assert trust.banner_for_site({"us_county_fips": "19169"}, s, crop="soybean")["show"]
    assert trust.banner_for_site({"us_county_fips": "17113"}, s)["show"]


def test_banner_shows_when_validation_not_run():
    assert trust.banner_for_site({"us_county_fips": "19169"}, _summary("validation not run yet"))["show"]


def test_validation_rows_convert_mae_to_tonnes_and_hide_unrun():
    r = trust.validation_rows(_summary())[0]
    assert r["MAE t/ha"] == "0.90" and r["MAE corrected t/ha"] == "0.70" and r["Status"] == "validated"
    r2 = trust.validation_rows(_summary("no NASS data"))[0]
    assert r2["r (held out)"] == "n/a" and r2["Status"] == "no NASS data"


def test_real_validation_summary_lists_all_sites():
    rows = trust.validation_rows(trust.load_validation())
    assert len({r["County"] for r in rows}) == 14


def test_assumption_rows_badge_unverified_as_placeholder(tmp_path):
    f = tmp_path / "x.yaml"
    f.write_text("a:\n  b: {value: 1, source: 'FAO-56 table 12', range: [0, 2]}\n"
                 "  c: {value: 2, source: 'guess, team to verify'}\n  d: {value: 3}\n")
    rows = {r["Parameter"]: r for r in trust.assumption_rows([f])}
    assert rows["a.b"]["Badge"] == "assumption" and rows["a.b"]["Range"] == [0, 2]
    assert rows["a.c"]["Badge"] == "placeholder" and rows["a.d"]["Badge"] == "placeholder"


def test_assumption_rows_read_all_project_files():
    files = {r["File"] for r in trust.assumption_rows()}
    assert "config/assumptions/us_data.yaml" in files


def test_docs_load():
    for name in trust.DOCS:
        assert len(trust.doc_text(name)) > 50
