# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""R5: climate fit and county filter, on synthetic weather with known answers."""
import numpy as np
import pandas as pd

from engine import candidates as cd


class _Inputs:
    def __init__(self, plan):
        self.current_plan = plan


class _Site:
    def __init__(self, weather, us_defaults=None):
        self.weather, self.us_defaults = weather, us_defaults


def _weather(mean_c, amp_c=0.0, years=25, min_gap=5.0, start_year=2001):
    idx = pd.date_range(f"{start_year}-01-01", periods=int(years * 365.25), freq="D")
    doy = idx.day_of_year.to_numpy()
    t = mean_c + amp_c * np.sin(2 * np.pi * (doy - 110) / 365.25)
    return pd.DataFrame({"tmean": t, "tmin": t - min_gap}, index=idx)


def test_warm_tropics_fits_warm_crops_and_not_winter_wheat():
    site = _Site(_weather(27.0, amp_c=1.0))
    got = cd.candidates(site, _Inputs([["rice"]] * 4))
    assert {"rice", "maize", "sorghum"} <= set(got)
    assert "wheat_winter" not in got and "wheat_spring" not in got


def test_cold_climate_drops_frost_sensitive_crops():
    site = _Site(_weather(2.0, amp_c=14.0, min_gap=6.0))     # long cold winters, frost most years
    got = cd.candidates(site, _Inputs([["wheat_spring"]] * 4))
    assert "maize" not in got and "rice" not in got and "cotton" not in got


def test_us_county_filter_keeps_only_crops_the_county_grows():
    site = _Site(_weather(18.0, amp_c=9.0), us_defaults={"crops": ["maize", "soybean"]})
    rows = {r["crop"]: r for r in cd.candidate_report(site, _Inputs([["maize"]] * 4))}
    assert rows["sorghum"]["in_county"] is False and rows["sorghum"]["candidate"] is False
    assert "not grown in this county" in rows["sorghum"]["note"]
    assert rows["maize"]["in_county"] is True


def test_current_plan_crops_are_always_kept_with_a_note():
    site = _Site(_weather(27.0, amp_c=1.0))
    rows = {r["crop"]: r for r in cd.candidate_report(site, _Inputs([["wheat_winter"]] * 4))}
    assert rows["wheat_winter"]["candidate"] is True
    assert "kept because it is in your current plan" in rows["wheat_winter"]["note"]


def test_share_of_years_is_reported_and_bounded():
    r = cd.climate_fit(_weather(27.0, amp_c=1.0), "rice")
    assert r["years_total"] == 20 and 0.0 <= r["share"] <= 1.0 and r["fits"] is True


def test_unknown_crop_is_reported_not_guessed():
    r = cd.climate_fit(_weather(20.0), "quinoa")
    assert r["fits"] is None and "no season or temperature data" in r["reason"]


def test_short_weather_record_is_not_judged():
    r = cd.climate_fit(_weather(20.0, years=0.2), "maize")
    assert r["fits"] is None
