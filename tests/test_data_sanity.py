"""Data sanity for NASA POWER weather. Runs offline from data/raw/ cache."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from engine import fetch_power

ROOT = Path(__file__).resolve().parent.parent
REGION = yaml.safe_load((ROOT / "config" / "region.yaml").read_text())


@pytest.fixture(scope="module")
def wx():
    return fetch_power.load_weather(REGION["lat"], REGION["lon"])


def test_columns_and_index(wx):
    assert list(wx.columns) == ["tmax", "tmin", "tmean", "rh", "wind2", "precip", "srad"]
    assert wx.index[0] == pd.Timestamp("1984-01-01") and wx.index[-1] == pd.Timestamp("2025-12-31")


def test_date_range_complete(wx):
    assert len(wx) == 15341
    assert wx.index.is_unique and wx.index.is_monotonic_increasing
    assert (wx.index == pd.date_range("1984-01-01", "2025-12-31", freq="D")).all()


def test_no_nan_no_missing_flag(wx):
    assert not wx.isna().any().any()
    assert not (wx == -999).any().any()


def test_unit_ranges(wx):
    assert wx.tmax.between(0, 55).all()
    assert wx.precip.between(0, 500).all()
    assert wx.srad.between(0, 40).all()
    assert wx.rh.between(0, 100).all()
    assert wx.wind2.between(0, 50).all()


def test_tmin_le_tmax(wx):
    assert (wx.tmin <= wx.tmax).all()


def test_srad_gap_trimmed_not_filled(wx):
    # POWER srad is -999 for 1981-1983 in the raw file; default trims it, no invented values.
    assert wx.attrs["trimmed_range"] == ("1981-01-01", "1983-12-31")
    assert wx.attrs["srad_filled_range"] is None
    raw = json.loads(fetch_power.cache_path(REGION["lat"], REGION["lon"]).read_text())
    s = raw["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]
    assert sum(v == -999 for v in s.values()) == 1095  # no other srad gaps


def test_opt_in_fill_is_labelled():
    w = fetch_power.load_weather(REGION["lat"], REGION["lon"], srad_leading_gap="doy_climatology")
    assert len(w) == 16436 and w.attrs["srad_filled_range"] == ("1981-01-01", "1983-12-31")
    assert "assumption" in w.attrs["srad_fill_method"]


def test_strict_mode_raises():
    with pytest.raises(ValueError):
        fetch_power.load_weather(REGION["lat"], REGION["lon"], srad_leading_gap="raise")


def test_long_gap_raises():
    s = pd.Series(1.0, index=pd.date_range("2000-01-01", periods=20))
    s.iloc[5:10] = np.nan
    with pytest.raises(ValueError):
        fetch_power._fill_gaps(s, "x")
    s2 = pd.Series(np.arange(20.0), index=pd.date_range("2000-01-01", periods=20))
    s2.iloc[5:8] = np.nan
    assert not fetch_power._fill_gaps(s2, "x").isna().any()


def test_describe(wx):
    d = fetch_power.describe(wx)
    assert d["n_days"] == 15341 and d["n_years"] == 42
    assert 0 < d["monsoon_JunOct_rain_mm"]["mean"] < d["annual_rain_mm"]["mean"]


def test_region_config():
    assert REGION["district"] == "TEAM_TO_FILL" and REGION["dev_placeholder"] is True
    assert REGION["icrisat_district"] == "TEAM_TO_FILL" and REGION["country"] == "India"


def test_gibs_layers_file():
    g = json.loads((ROOT / "data" / "gibs_layers.json").read_text())
    for key in ("soil_moisture", "ndvi"):
        pid = g["primary"][key]
        assert pid
        assert any(l["id"] == pid and l["verified_tile"]["status"] == 200 for l in g["layers"][key])
