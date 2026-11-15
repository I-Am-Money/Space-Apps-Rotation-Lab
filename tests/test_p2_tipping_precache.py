# AI use: this file was written by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Saved tipping results for the example farms (engine/tipping_precache.py): a saved result is used only for
exactly the same farm, code and assumptions."""
import json
from types import SimpleNamespace as NS

import pandas as pd

from engine import tipping_precache as P


def _farm(plan=("maize", "maize", "maize", "maize"), rain=1.0, bad_year=0.3):
    days = pd.date_range("2020-01-01", "2021-12-31", freq="D")
    weather = pd.DataFrame({"precip": [rain] * len(days), "tmax": [25.0] * len(days)}, index=days)
    weather.attrs["last_full_year"] = 2021
    site = NS(lat=42.0375, lon=-93.4661, currency="USD", elevation_m=310.0, weather=weather,
              soil=NS(texture="loam", awc_mm_per_m=180.0, organic_matter_pct=1.6, hydrologic_group="B", ph=6.4,
                      data_as_of="2026-11-15"),
              us_defaults=NS(crops=["maize", "soybean"], yields={"maize": 11000.0}, prices={"maize": 170.0},
                             costs={"maize": 900.0}, irrigated_share=0.02, data_as_of="2026-11-15"))
    inputs = NS(current_plan=list(plan), water=NS(mode="rain", source="", normal_mm=0.0, dry_mm=0.0), farm_acres=300.0,
                soil_test=None, history=None, crop_overrides={})
    sliders = NS(bad_year=bad_year, water=0.0, soil=0.5, profit_tolerance_pct=0.0, climate_shift="historical")
    return site, inputs, sliders


def test_key_is_stable_and_follows_the_farm_the_weather_and_the_sliders():
    key = P.farm_key(*_farm())
    assert key == P.farm_key(*_farm())
    assert key != P.farm_key(*_farm(plan=("maize", "soybean", "maize", "soybean")))
    assert key != P.farm_key(*_farm(rain=1.1))
    assert key != P.farm_key(*_farm(bad_year=0.5))
    site, inputs, sliders = _farm()
    site.soil.data_as_of = site.us_defaults.data_as_of = "2027-01-01"     # the download date is not part of the farm
    assert key == P.farm_key(site, inputs, sliders)
    assert key == P.farm_key(site, inputs, vars(sliders))                 # sliders as a dict or an object


def test_saved_result_is_used_only_for_the_same_farm_code_and_assumptions(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "FOLDER", tmp_path)
    monkeypatch.setattr(P, "ROOT", tmp_path.parent)
    monkeypatch.setattr(P, "_FINGERPRINT", "code-and-assumptions-v1")
    farm = _farm()
    assert P.load(*farm) is None
    P.save("demo", *farm, {"headlines": ["x"], "method": {"seconds": 9.0}})
    got = P.load(*farm)
    assert got["headlines"] == ["x"] and got["method"]["precomputed"]
    assert P.load(*_farm(bad_year=0.6)) is None                           # a moved slider: worked out live
    monkeypatch.setattr(P, "_FINGERPRINT", "code-and-assumptions-v2")     # engine or assumptions changed: never shown
    assert P.load(*farm) is None
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")  # a damaged file never breaks the page
    assert P.load(*farm) is None


def test_committed_files_are_whole_and_name_the_example_farms():
    names = set(P.example_farms())
    assert names, "no rain-fed example farm in config/assumptions/setup.yaml"
    for path in P.FOLDER.glob("*.json"):
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert path.stem in names
        assert {"made", "fingerprint", "farm_key", "result"} <= set(saved)
        assert {"headlines", "map_2d", "rainfall_curve", "water_curve", "heat_curve", "method"} <= set(saved["result"])
        assert saved["result"]["method"]["scenarios_winner"] == saved["result"]["method"]["scenarios_bands"]
