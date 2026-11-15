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
    assert len({r["County"] for r in rows}) >= 14


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


def test_banner_outside_us_hidden_only_near_validated_district():
    t = pd.DataFrame([{"site": "IN-x", "crop": "jowar", "fips": None, "status": "ok", "r": 0.3, "lat": 16.9, "lon": 79.2}])
    s = SimpleNamespace(table=t, sites=[])
    assert not trust.banner_for_site({"lat": 17.0, "lon": 79.0, "us_county_fips": None}, s)["show"]
    assert trust.banner_for_site({"lat": 20.0, "lon": 79.0, "us_county_fips": None}, s)["show"]


def test_badge_is_plain_text_without_styling():
    for kind in ("observed", "estimated", "your_input", "assumption", "placeholder", "example", "missing", None):
        label = trust.badge(kind)
        assert label and "<" not in label and "style" not in label.lower()
    assert trust.badge("placeholder").startswith("Placeholder")


def test_trust_page_has_no_custom_styling():
    src = (trust.ROOT / "ui" / "trust.py").read_text()
    for banned in ("unsafe_allow_html", "<style", "st.html", "color_discrete", "update_layout", "update_traces"):
        assert banned not in src


def test_site_points_one_per_site():
    pts = trust.site_points(trust.load_validation())
    assert len(pts) == pts["site"].nunique() >= 14


def test_us_and_india_rows_told_apart_after_csv_round_trip(tmp_path):
    """Empty CSV cells come back as NaN; India rows must not count as validated US counties."""
    t = pd.DataFrame([{"site": "IN-x", "crop": "jowar", "fips": "", "region": "Deccan Plateau (India)",
                       "ers_region": "", "status": "ok", "r": 0.3, "mae": 100, "n_train": 26, "n_test": 8},
                      {"site": "IA-story", "crop": "maize", "fips": "19169", "region": "Corn Belt",
                       "ers_region": "Heartland", "status": "no NASS data"}])
    f = tmp_path / "r.csv"
    t.to_csv(f, index=False)
    rows = trust.validation_rows(SimpleNamespace(table=pd.read_csv(f, dtype={"fips": str}), sites=[]))
    assert [r["Country"] for r in rows] == ["India", "US"]
    assert rows[0]["ERS region"] == "Deccan Plateau (India)" and rows[0]["Status"] == "validated"


def test_banner_still_warns_when_checked_but_model_does_not_track():
    """Synthetic table: a county that was checked but has held-out r <= 0 is not shown as validated."""
    s = _summary()
    s.table.loc[:, "r"] = -0.3
    b = trust.banner_for_site({"us_county_fips": "19169"}, s)
    assert b["show"] and "did not track" in b["text"] and "-0.30" in b["text"]


def test_validation_headline_is_computed_from_rows():
    rows = [{"Status": "validated", "Country": "US", "Water": "rain", "r (held out)": v} for v in ("0.20", "0.60", "-0.10")]
    rows += [{"Status": "validated", "Country": "India", "Water": "rain", "r (held out)": "0.40"},
             {"Status": "no NASS data", "Country": "US", "Water": "rain", "r (held out)": "n/a"}]
    lines = trust.validation_headline(rows)
    assert lines[0].startswith("Mostly rainfed US counties: median held-out r = 0.20 across 3") and "1 of them" in lines[0]
    assert lines[1].startswith("India districts: median held-out r = 0.40 across 1")


def test_pages_show_only_us_material():
    """The app is for US farms right now: nothing about the earlier single-farm version is displayed."""
    from ui import trust as T
    for name in T.DOCS:
        shown = T.us_only_text(T.doc_text(name))
        assert not T._NOT_US.search(shown), name
        assert len(shown.splitlines()) > 10
    ds = T.us_only_text(T.doc_text("Data sources"))
    assert "NASA POWER" in ds and "USDA NASS" in ds                   # the datasets the US app uses stay listed
    sample = "\n".join(["# A", "", "1. Keep this.", "2. Nalgonda only.", "   continued line", "3. Keep too.", "",
                        "## Earlier India version", "", "old text", "", "## Next", "", "kept"])
    out = T.us_only_text(sample)
    assert "Keep this." in out and "Keep too." in out and "kept" in out and "## Next" in out
    assert "Nalgonda" not in out and "continued line" not in out and "Earlier" not in out and "old text" not in out
