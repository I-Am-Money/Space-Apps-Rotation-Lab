# AI use: this file was written by Claude Code (Anthropic) under the team's direction, then reviewed by the team. See AI_USE.md.
"""Tests for the v4 US hindcast in engine/hindcast.py (Person 3, R20)."""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import hindcast as hc

# Hand-checked county: 5 training years then 8 held-out years.
# Training anomalies a and m are both orthogonal to [1, t] over the 5 training years, so the training trend lines
# are exactly the true lines and the detrended values are exactly a and m:
#   a = [1, -2, 0, 2, -1], m = [3, -3, -2, 1, 1]
#   r = sum(a*m) / sqrt(sum(a^2) * sum(m^2)) = (3 + 6 + 0 + 2 - 1) / sqrt(10 * 24) = 10 / sqrt(240) = 0.645497
# Held out: actual follows the training trend plus [+1,-1,...]; modeled has no trend plus the same pattern,
# so held-out detrended series are proportional and r_test = 1.
YEARS = list(range(2000, 2013))
A = [1, -2, 0, 2, -1]
M = [3, -3, -2, 1, 1]
PAT = [1, -1] * 4


def _county():
    t = np.array(YEARS, float)
    actual = 5000 + 100 * (t - 2000) + 50 * np.array(A + PAT, float)
    rel = 0.8 + 0.01 * np.array(M + PAT, float)
    return actual, rel


def test_hand_checked_r_for_one_county():
    actual, rel = _county()
    h = hc.hindcast_series("TEST-county", "maize", YEARS, actual, rel, holdout=8, min_years=5)
    assert h.status == "ok"
    assert h.r_train == pytest.approx(10 / math.sqrt(240), abs=1e-9)
    assert h.r_test == pytest.approx(1.0, abs=1e-9)
    assert h.test_years == list(range(2005, 2013))


def test_latest_8_years_held_out_and_never_used():
    actual, rel = _county()
    base = hc.hindcast_series("c", "maize", YEARS, actual, rel, holdout=8, min_years=5)
    changed = actual.copy()
    changed[-8:] *= 3.0                      # wreck the held-out years
    h2 = hc.hindcast_series("c", "maize", YEARS, changed, rel, holdout=8, min_years=5)
    assert h2.ym_kg_ha == base.ym_kg_ha     # Ym from training years only
    assert h2.r_train == base.r_train and h2.mae_train == base.mae_train
    assert sum(not t for t in h2.train_mask) == 8 and h2.mae_test != base.mae_test


def test_ym_is_training_trend_level_plus_p90():
    actual, rel = _county()
    h = hc.hindcast_series("c", "maize", YEARS, actual, rel, holdout=8, min_years=5)
    resid = 50 * np.array(A, float)
    assert h.ym_kg_ha == pytest.approx(5000 + 100 * 4 + np.percentile(resid, 90))
    assert h.modeled[0] == pytest.approx(h.ym_kg_ha * rel[0])


def test_not_enough_years_is_reported_not_faked():
    h = hc.hindcast_series("c", "maize", [2000, 2001, 2002], [1, 2, 3], [1, 1, 1], holdout=8)
    assert h.status == "not enough data" and h.r_test is None and h.modeled == []


def test_no_nass_data_is_honest():
    site = hc.validation_sites()[0]
    w = pd.DataFrame({"tmax": [30.0], "tmin": [15.0], "precip": [1.0]}, index=pd.to_datetime(["2000-06-01"]))
    h = hc.hindcast_county(site, "maize", weather=w, yields=pd.DataFrame(columns=["year", "yield_kg_ha"]))
    assert h.status == "no NASS data" and h.r_test is None


def _synthetic_weather(years, dry_years):
    idx = pd.date_range(f"{years[0] - 1}-01-01", f"{years[-1]}-12-31", freq="D")
    rng = np.random.default_rng(42)
    doy = idx.day_of_year.to_numpy()
    tmax = 18 + 12 * np.sin((doy - 100) / 365 * 2 * np.pi) + rng.normal(0, 2, len(idx))
    precip = np.where(rng.random(len(idx)) < 0.3, rng.gamma(2.0, 6.0, len(idx)), 0.0)
    precip[np.isin(idx.year, dry_years) & (doy > 150) & (doy < 260)] = 0.0
    return pd.DataFrame({"tmax": tmax, "tmin": tmax - 11, "precip": precip}, index=idx)


def test_standin_model_responds_to_drought_and_runs_county():
    years = list(range(1990, 2020))
    dry = [1995, 2002, 2012]
    w = _synthetic_weather(years, dry)
    rel = {y: hc.standin_relative_yield(w, "maize", y, 42.0) for y in years}
    assert all(0 <= v <= 1 for v in rel.values())
    assert max(rel[y] for y in dry) < np.median([rel[y] for y in years if y not in dry])
    yields = pd.DataFrame({"year": years, "yield_kg_ha": [6000 + 80 * (y - 1990) + 4000 * (rel[y] - 0.8) for y in years]})
    h = hc.hindcast_county({"id": "SYN", "fips": "00000", "lat": 42.0}, "maize", weather=w, yields=yields,
                           yield_fn=hc.standin_relative_yield, min_years=20)
    assert h.status == "ok" and h.r_train > 0.95 and len(h.test_years) == 8


def test_validation_sites_cover_regions():
    sites = hc.validation_sites()
    assert len(sites) >= 10
    assert len({s["region"] for s in sites}) >= 6
    assert all(len(s["fips"]) == 5 and -125 < s["lon"] < -66 and 24 < s["lat"] < 50 for s in sites)


def test_hindcast_reads_county_yields_through_fetch_nass(tmp_path, monkeypatch):
    """SYNTHETIC NASS records (not real values) flow through fetch_nass into hindcast_county, using the
    site's NON-IRRIGATED practice; the latest 8 years are the test years."""
    from engine import cache, fetch_nass
    monkeypatch.setattr(cache, "RUNTIME_DIR", tmp_path)
    monkeypatch.setenv("NASS_API_KEY", "test-key-not-real")
    recs = []
    for y in range(1990, 2024):
        for practice, v in (("ALL PRODUCTION PRACTICES", 150 + y - 1990), ("NON-IRRIGATED", 120 + y - 1990)):
            recs.append({"year": y, "Value": str(v), "commodity_desc": "CORN", "util_practice_desc": "GRAIN",
                         "unit_desc": "BU / ACRE", "prodn_practice_desc": practice, "reference_period_desc": "YEAR",
                         "class_desc": "ALL CLASSES"})
    monkeypatch.setattr(fetch_nass, "_get", lambda p: recs)
    df = hc.load_county_yields("31109", "maize", "NON-IRRIGATED")
    assert len(df) == 34 and df["yield_kg_ha"].iloc[0] == pytest.approx(120 * fetch_nass.kg_ha_per_unit("maize"))
    rng = np.random.default_rng(42)
    idx = pd.date_range("1989-01-01", "2023-12-31", freq="D")
    weather = pd.DataFrame({"tmax": 28 + rng.normal(0, 3, len(idx)), "tmin": 15 + rng.normal(0, 3, len(idx)),
                            "precip": rng.gamma(0.5, 6, len(idx))}, index=idx)
    site = {"id": "NE-lancaster", "fips": "31109", "lat": 40.78, "lon": -96.69, "nass_practice": "NON-IRRIGATED"}
    h = hc.hindcast_county(site, "maize", weather=weather)
    assert h.status == "ok" and h.test_years == list(range(2016, 2024))


def test_hindcast_exposes_validation_summary():
    v = hc.validation_summary()
    assert hasattr(v, "table") and hasattr(v, "sites") and len(v.sites) == len(hc.all_validation_sites()) >= 14
