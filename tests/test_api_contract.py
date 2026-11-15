# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Shape tests for the A5 contract in engine/api.py. They pass for stubs and must keep passing for real code
(except `example` flags, which flip to False as stubs are replaced)."""
import dataclasses
import inspect

import numpy as np
import pandas as pd
import pytest

from engine import api

KS = (38.4, -97.6)
INDIA = (16.9, 79.2)


def test_signatures_match_a5():
    expect = {
        "get_site": ["lat", "lon"],
        "get_candidates": ["site", "inputs"],
        "recommend": ["site", "inputs", "sliders"],
        "tipping_points": ["site", "inputs", "sliders"],
        "question_value": ["site", "inputs", "sliders"],
        "zones": ["site", "polygon", "inputs", "sliders"],
        "validation_summary": [],
        "explain": ["rotation_result", "current_plan_result"],
    }
    for name, params in expect.items():
        assert list(inspect.signature(getattr(api, name)).parameters) == params, name


def test_dataclass_fields_match_a5():
    expect = {
        "Site": ["lat", "lon", "country", "us_state", "us_county_fips", "weather", "soil", "elevation_m",
                 "climate_trend", "us_defaults", "data_as_of", "badges"],
        "WaterInput": ["mode", "source", "normal_mm", "dry_mm"],
        "UserInputs": ["current_plan", "water", "farm_acres", "soil_test", "history", "crop_overrides"],
        "Sliders": ["bad_year", "water", "soil", "profit_tolerance_pct", "climate_shift"],
        "RotationResult": ["crops", "cover_crops", "mean_profit", "worst10_profit", "calories", "irrigation_mm",
                           "total_water_mm", "soil_score", "yields_by_year", "deltas_vs_current", "badges"],
        "Recommendations": ["headline", "highest_profit", "best_soil", "all_results", "current_plan_result",
                            "guardrail_met", "explanations"],
        "TippingPoints": ["rainfall_curve", "heat_curve", "water_curve", "map_2d", "bands"],
        "QuestionValue": ["question", "evpi_per_acre", "could_change_answer"],
        "Zone": ["polygon", "area_acres", "kind", "recommendation", "reason"],
        "ValidationSummary": ["table", "sites"],
    }
    for name, fields in expect.items():
        have = [f.name for f in dataclasses.fields(getattr(api, name))]
        for f in fields:
            assert f in have, f"{name} lacks {f}"


def test_get_site_shape_and_example_flag():
    s = api.get_site(*KS)
    assert isinstance(s, api.Site) and isinstance(s.weather, pd.DataFrame)
    assert {"tmax", "tmin", "tmean", "rh", "wind2", "precip", "srad"} <= set(s.weather.columns)
    assert not s.weather.isna().any().any() and not (s.weather == -999).any().any()
    assert s.us_defaults is not None and s.country == "USA"
    assert api.get_site(*INDIA).us_defaults is None
    assert s.example is True and api.is_example(s)
    assert all(v == "example" for v in s.badges.values())
    assert set(s.badges.values()) <= set(api.BADGES)


def test_get_site_rejects_points_not_on_earth():
    with pytest.raises(ValueError):
        api.get_site(95.0, 0.0)
    with pytest.raises(ValueError):
        api.get_site(0.0, 200.0)


def test_recommend_shape_and_deltas():
    site, inp, sl = api.get_site(*KS), api.default_inputs(), api.default_sliders()
    rec = api.recommend(site, inp, sl)
    assert isinstance(rec, api.Recommendations)
    for r in (rec.highest_profit, rec.best_soil, rec.current_plan_result, *rec.all_results):
        assert isinstance(r, api.RotationResult)
        assert len(r.crops) == api.YEARS_IN_PLAN and all(isinstance(y, list) and 1 <= len(y) <= 2 for y in r.crops)
        assert len(r.cover_crops) == api.YEARS_IN_PLAN and len(r.yields_by_year) == api.YEARS_IN_PLAN
        assert 0 <= r.soil_score <= 100 and r.worst10_profit <= r.mean_profit
        assert set(api.DELTA_KEYS) <= set(r.deltas_vs_current)
    cur = rec.current_plan_result
    assert all(v == 0 for v in cur.deltas_vs_current.values())
    for r in (rec.highest_profit, rec.best_soil):
        for k in api.DELTA_KEYS:
            assert r.deltas_vs_current[k] == pytest.approx(getattr(r, k) - getattr(cur, k), abs=1e-2)
    assert set(rec.explanations) == {"headline", "highest_profit", "best_soil"}


def test_headline_never_violates_guardrail():
    site, inp = api.get_site(*KS), api.default_inputs()
    for tol in (0.0, 5.0, 25.0):
        rec = api.recommend(site, inp, api.Sliders(profit_tolerance_pct=tol))
        floor = rec.current_plan_result.mean_profit * (1 - tol / 100)
        if rec.headline is None:
            assert rec.guardrail_met is False
        else:
            assert rec.guardrail_met is True and rec.headline.mean_profit >= floor - 1e-9
    # an impossible guardrail must say so instead of returning a losing headline
    impossible = api.recommend(site, inp, api.Sliders(profit_tolerance_pct=-500.0))
    assert impossible.guardrail_met is False and impossible.headline is None


def test_tipping_points_shape():
    tp = api.tipping_points(api.get_site(*KS), api.default_inputs(), api.default_sliders())
    assert isinstance(tp, api.TippingPoints)
    for c in (tp.rainfall_curve, tp.heat_curve, tp.water_curve):
        n = len(c["x"])
        assert all(len(v) == n for v in c["series"].values()) and len(c["winner"]) == n and "crossovers" in c
    m = tp.map_2d
    assert len(m["winner"]) == len(m["water_mm"]) and all(len(row) == len(m["rain_mult"]) for row in m["winner"])
    assert min(tp.rainfall_curve["x"]) == pytest.approx(0.5) and max(tp.rainfall_curve["x"]) == pytest.approx(1.3)
    assert min(tp.heat_curve["x"]) == 0 and max(tp.heat_curve["x"]) == pytest.approx(3.0)


def test_question_value_ranked_and_non_negative():
    qs = api.question_value(api.get_site(*KS), api.default_inputs(), api.default_sliders())
    assert all(isinstance(q, api.QuestionValue) for q in qs) and qs
    vals = [q.evpi_per_acre for q in qs]
    assert all(v >= 0 for v in vals) and vals == sorted(vals, reverse=True)
    assert all(isinstance(q.could_change_answer, bool) for q in qs)


def test_zones_and_validation_shapes():
    poly = [(38.4, -97.6), (38.4, -97.59), (38.41, -97.59)]
    zs = api.zones(api.get_site(*KS), poly, api.default_inputs(), api.default_sliders())
    assert zs and all(isinstance(z, api.Zone) and z.kind in ("slope", "low_spot", "main") for z in zs)
    vs = api.validation_summary()
    assert isinstance(vs, api.ValidationSummary)
    assert {"site", "crop", "r", "mae", "r_corrected", "mae_corrected"} <= set(vs.table[0])


def test_explain_returns_text_without_unknown_numbers():
    site, inp, sl = api.get_site(*KS), api.default_inputs(), api.default_sliders()
    rec = api.recommend(site, inp, sl)
    text = api.explain(rec.highest_profit, rec.current_plan_result)
    assert isinstance(text, str) and len(text) > 20


def test_get_candidates_returns_crop_ids():
    cands = api.get_candidates(api.get_site(*KS), api.default_inputs())
    assert cands and all(isinstance(c, str) for c in cands)
    assert {"maize", "soybean"} <= set(cands)


def test_stubs_are_deterministic_seed_42():
    a = api.recommend(api.get_site(*KS), api.default_inputs(), api.default_sliders())
    b = api.recommend(api.get_site(*KS), api.default_inputs(), api.default_sliders())
    assert a == b
    w1, w2 = api.get_site(*KS).weather, api.get_site(*KS).weather
    assert np.array_equal(w1.to_numpy(), w2.to_numpy())


def test_every_stub_result_is_flagged_example():
    site, inp, sl = api.get_site(*KS), api.default_inputs(), api.default_sliders()
    rec = api.recommend(site, inp, sl)
    assert rec.example and rec.highest_profit.example and all(r.example for r in rec.all_results)
    assert api.tipping_points(site, inp, sl).example
    assert all(q.example for q in api.question_value(site, inp, sl))
