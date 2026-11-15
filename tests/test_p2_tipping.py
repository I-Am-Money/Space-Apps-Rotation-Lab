# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Feature 2 (Person 2): tipping points (Build Spec v4 R18). Offline: synthetic weather, no network."""
import numpy as np
import pytest

from engine import simulate as SIM
from engine import tipping as T
from tests.test_p2_simulation import make_weather

MS = ["maize", "soybean", "maize", "soybean"]


@pytest.fixture(scope="module")
def weather():
    return make_weather(1981, 2025, seed=11)


def make_site(weather, prices=True):
    us = {"crops": ["maize", "soybean"], "yields": {"maize": 9000.0, "soybean": 3000.0}}
    if prices:
        us.update(prices={"maize": 180.0, "soybean": 420.0}, costs={"maize": 1100.0, "soybean": 650.0})
    return {"weather": weather, "lat": 41.0, "elevation_m": 300.0,
            "soil": {"awc_mm_per_m": 140.0, "hydrologic_group": "B"}, "us_defaults": us}


def make_inputs(mode="rain", normal=None, dry=None, plan=("maize", "maize", "maize", "soybean")):
    return {"current_plan": list(plan), "water": {"mode": mode, "normal_mm": normal, "dry_mm": dry}, "crop_overrides": {}}


@pytest.fixture(scope="module")
def own(weather):
    """The module's own ranking (no recommend() available), rain-fed farm."""
    return T.tipping_points(make_site(weather), make_inputs(), {"climate_shift": "historical"}, recommend=False)


def test_result_has_the_contract_parts_and_marks_the_farm(own):
    for part in ("rainfall_curve", "heat_curve", "water_curve", "map_2d", "bands"):
        assert part in own
    assert own["example"] is False and "not forecasts" in own["note"]
    rc, hc, wc, m = own["rainfall_curve"], own["heat_curve"], own["water_curve"], own["map_2d"]
    assert rc["x"] == pytest.approx([0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]) and rc["current_x"] == 1.0
    assert hc["x"] == [0.0, 1.0, 2.0, 3.0] and wc["x"][0] == 0.0 and wc["current_x"] == 0.0
    for c in (rc, hc, wc):
        assert len(c["winner"]) == len(c["x"]) and any(k.startswith(T.CURRENT) for k in c["series"])
        for name, mean in c["series"].items():
            lo, hi = np.array(c["band"]["p10"][name]), np.array(c["band"]["p90"][name])
            assert len(mean) == len(c["x"]) and (lo <= hi + 1e-9).all()
            assert (lo <= np.array(mean) + 1e-9).all() and (np.array(mean) <= hi + 1e-9).all()
        assert set(c["winner"]) <= set(c["series"])                      # every winner on a curve is drawn on it
    assert np.array(m["winner"]).shape == (len(m["water_mm"]), len(m["rain_mult"]))
    cur = m["current"]
    assert m["rain_mult"][cur["col"]] == 1.0 and m["water_mm"][cur["row"]] == 0.0 and cur["text"] == "rain only"
    assert m["winner"][cur["row"]][cur["col"]] == cur["winner"] == own["winner_now"]
    assert set(m["labels"]) == {v for row in m["winner"] for v in row}
    assert own["metric"]["name"] == "profit" and own["method"]["scenarios_bands"] == 500
    assert any("not by the recommendation engine" in n for n in own["notes"])
    assert own["headlines"] and own["climate"]["mode"] == "historical"


def test_less_rain_or_water_never_helps_a_plan(own):
    for c in (own["rainfall_curve"], own["water_curve"]):
        for mean in c["series"].values():
            assert (np.diff(mean) >= -1e-6).all()
    for mean in own["heat_curve"]["series"].values():
        assert (np.diff(mean) <= 1e-6).all()                             # more heat never helps


def test_tipping_is_deterministic(weather, own):
    again = T.tipping_points(make_site(weather), make_inputs(), {"climate_shift": "historical"}, recommend=False)
    assert again["map_2d"]["winner"] == own["map_2d"]["winner"]
    assert again["rainfall_curve"]["series"] == own["rainfall_curve"]["series"]
    assert again["bands"] == own["bands"]


def test_same_rotation_started_in_another_year_is_one_plan():
    a, b = T.rot_key(MS), T.rot_key(MS[1:] + MS[:1])
    assert a != b and T.same_rotation(a) == T.same_rotation(b)
    assert T.same_rotation(b, prefer=(a,)) == a
    assert T.rot_label(T.rot_key({"crops": [["corn"], ["soybeans"]], "cover_crops": [False, True]})) == \
        "Maize > Soybeans > Maize > Soybeans (with cover crops)"


def test_winner_comes_from_recommend_inside_the_what_if(weather):
    seen = []

    def recommend(site, inputs, sliders):
        """Stand-in for api.recommend: a dry-year plan wins below 0.8x rain or with no irrigation water."""
        wi = SIM.current_what_if()
        seen.append(wi)
        r = SIM.simulate(site, inputs, MS)                               # proves the what-if reaches simulate()
        dry = wi.get("rain_mult", 1.0) < 0.75 or (wi.get("water") or {}).get("normal_mm", 200.0) < 60.0
        pick = {"crops": [["soybean"]] * 4 if dry else [[c] for c in MS], "cover_crops": [False] * 4,
                "mean_profit": float(r.rel_yields.mean())}
        return {"headline": pick, "highest_profit": pick, "best_soil": pick, "all_results": [pick], "example": False}

    inp = make_inputs("irrigated", 200.0, 100.0, plan=MS)
    tp = T.tipping_points(make_site(weather), inp, {"climate_shift": "historical"}, recommend=recommend)
    assert "recommend()" in tp["method"]["winner_source"]
    rc, m = tp["rainfall_curve"], tp["map_2d"]
    wet, dry = f"{T.CURRENT}: Maize > Soybeans > Maize > Soybeans", "Soybeans > Soybeans > Soybeans > Soybeans"
    assert rc["winner"] == [dry] * 3 + [wet] * 6
    assert len(rc["crossovers"]) == 1 and 0.7 <= rc["crossovers"][0] <= 0.8
    band = tp["bands"]["rainfall"][0]
    assert band["between"] == [0.7, 0.8] and 0.7 <= band["p10"] <= band["p90"] <= 0.8
    assert m["water_mm"] == [0.0, 50.0, 100.0, 150.0, 200.0, 250.0] and m["current"]["water_mm"] == 200.0
    assert m["winner"][0] == [dry] * 9 and m["winner"][m["current"]["row"]] == rc["winner"]
    assert tp["water_curve"]["winner"] == [dry, dry, wet, wet, wet, wet]
    # the first call is the farm as it is; later calls carry the what-if and the weather plans to use
    assert seen[0].get("rain_mult") is None and any(w.get("rain_mult") == 0.5 for w in seen[1:])
    # this stand-in answers at once, so the search can afford every weather plan and says so
    assert all(w["scenarios"].n == 500 for w in seen[1:]) and SIM.current_what_if() == {}
    assert tp["method"]["scenarios_winner"] == 500 and not any("for speed" in n for n in tp["notes"])


def test_fewer_weather_plans_alone_never_show_a_tipping_point(weather, monkeypatch):
    """Two nearly tied plans can swap places when the search uses 100 weather plans instead of 500. That is not a
    tipping point: a change of plan is shown only where the same search picks differently than at the current setting."""
    rule = T.C.rule
    monkeypatch.setattr(T.C, "rule", lambda name: 0 if name == "tipping_full_search_s" else rule(name))
    sizes = []

    def recommend(site, inputs, sliders):
        wi = SIM.current_what_if()
        n = wi["scenarios"].n if wi.get("scenarios") is not None else 500
        sizes.append(n)
        swapped = n < 500                                                # the near-tie falls the other way on fewer plans
        dry = wi.get("rain_mult", 1.0) < 0.75
        crops = [["soybean"]] * 4 if dry else ([["maize"], ["soybean"], ["soybean"], ["soybean"]] if swapped else [[c] for c in MS])
        pick = {"crops": crops, "cover_crops": [False] * 4, "mean_profit": 1.0}
        return {"headline": pick, "highest_profit": pick, "best_soil": pick, "all_results": [pick], "example": False}

    tp = T.tipping_points(make_site(weather), make_inputs(plan=MS), {"climate_shift": "historical"}, recommend=recommend)
    wet, dry = f"{T.CURRENT}: Maize > Soybeans > Maize > Soybeans", "Soybeans > Soybeans > Soybeans > Soybeans"
    assert tp["method"]["scenarios_winner"] == 100 and 100 in sizes
    assert any("pick a different plan than they pick at your current setting" in n for n in tp["notes"])
    # the swap on fewer plans is not shown; the real change below 0.75 x rain still is
    assert tp["rainfall_curve"]["winner"] == [dry] * 3 + [wet] * 6
    assert tp["heat_curve"]["winner"] == [wet] * 4 and len(tp["rainfall_curve"]["crossovers"]) == 1
    assert {v for row in tp["map_2d"]["winner"] for v in row} == {wet, dry}


def test_stub_or_failing_recommend_is_never_shown_as_a_winner(weather):
    site, inp = make_site(weather), make_inputs()
    stub = T.tipping_points(site, inp, None, recommend=lambda s, i, sl: {"headline": {"crops": [["rice"]] * 4}, "example": True})
    assert any("example data" in n for n in stub["notes"]) and "rice" not in str(stub["map_2d"]["labels"]).lower()

    def boom(site, inputs, sliders):
        raise RuntimeError("no optimizer yet")
    failed = T.tipping_points(site, inp, None, recommend=boom)
    assert any("recommend() failed" in n for n in failed["notes"])
    assert failed["map_2d"]["winner"] == stub["map_2d"]["winner"]
    need = T.tipping_points(site, inp, None, recommend=lambda s, i, sl: {"input_needed": [{"crop": "maize", "field": "price"}]})
    assert any("price for maize" in n for n in need["notes"])


def test_no_price_means_yield_share_not_invented_money(weather):
    tp = T.tipping_points(make_site(weather, prices=False), make_inputs(), None, recommend=False)
    assert tp["metric"]["name"] == "yield_share"
    assert any("share of potential yield" in n and "no price or cost" in n for n in tp["notes"])
    for mean in tp["rainfall_curve"]["series"].values():
        assert 0.0 <= min(mean) and max(mean) <= 100.0 + 1e-9
    assert T.economics(make_site(weather, prices=False), make_inputs(), ["maize"]) == {"maize": None}
    assert T.economics(make_site(weather), {"crop_overrides": {"corn": {"price": 200.0}}}, ["maize"]) == {"maize": (200.0, 1100.0)}


def test_water_levels_follow_the_farmers_answer():
    rain = T.water_levels(make_inputs())
    assert [r["mm"] for r in rain["rows"]] == [0, 100, 200, 300, 400, 500] and rain["rows"][0]["current"]
    irr = T.water_levels(make_inputs("irrigated", 400.0, 100.0))
    assert [r["mm"] for r in irr["rows"]] == [0, 100, 200, 300, 400, 500] and irr["rows"][4]["current"]
    assert irr["rows"][2]["water"] == {"mode": "irrigated", "normal_mm": 200.0, "dry_mm": 50.0}
    free = T.water_levels(make_inputs("irrigated"))
    assert free["current_mm"] is None and not any(r["current"] for r in free["rows"])


def test_with_the_real_feature_3_optimizer(weather):
    """End to end with Feature 3's recommend_picks() (the default until engine/api.py exposes the v4 recommend())."""
    optimize = pytest.importorskip("engine.optimize")
    if not hasattr(optimize, "recommend_picks"):
        pytest.skip("Feature 3's v4 optimizer is not in this checkout")
    from types import SimpleNamespace as NS
    d = make_site(weather)
    us = NS(crops=["maize", "soybean"], yields=d["us_defaults"]["yields"], prices=d["us_defaults"]["prices"],
            costs=d["us_defaults"]["costs"], irrigated_share=0.05)
    site = NS(weather=weather, lat=41.0, lon=-93.0, elevation_m=300.0, us_defaults=us,
              soil=NS(awc_mm_per_m=140.0, hydrologic_group="B", organic_matter_pct=3.0, texture="silt loam"))
    inp = NS(current_plan=["maize", "maize", "maize", "soybean"], farm_acres=100.0, soil_test=None, history=None,
             crop_overrides={}, water=NS(mode="rain", normal_mm=None, dry_mm=None, source=None))
    sliders = NS(bad_year=0.3, water=0.0, soil=0.5, profit_tolerance_pct=0.0, climate_shift="historical")
    tp = T.tipping_points(site, inp, sliders)
    assert "recommend" in tp["method"]["winner_source"] and "own ranking" not in tp["method"]["winner_source"]
    assert not any("not by the recommendation engine" in n for n in tp["notes"]), tp["notes"]
    base = optimize.recommend_picks(site, inp, sliders, explain_text=False)
    pick = base["headline"] or base["highest_profit"]
    assert tp["winner_now"].endswith(T.rot_label(T.same_rotation(T.rot_key(pick), (T.rot_key(inp.current_plan),))))
    m = tp["map_2d"]
    assert m["winner"][m["current"]["row"]][m["current"]["col"]] == tp["winner_now"]
    assert all(isinstance(v, str) and v != "Not worked out" for row in m["winner"] for v in row)
    assert tp["metric"]["name"] == "profit"


def test_year_shifted_rotations_share_one_simulation(weather):
    """The tipping search simulates 'maize, soybean, maize, soybean' once for both starting years."""
    site = make_site(weather)
    inp = make_inputs("irrigated", 120.0, 60.0)
    a, b = ["maize", "soybean", "soybean", "maize"], ["soybean", "maize", "maize", "soybean"]      # b = a started 2 years later
    direct = SIM.simulate_many(site, inp, [a, b])
    with SIM.what_if(share_shifts=True):
        shared = SIM.simulate_many(site, inp, [a, b, ["rice"] * 4])
    assert [r.feasible for r in shared] == [True, True, True]
    assert [y[0] for y in shared[1].crops] == b
    # the shifted plan is the first plan with its plan years moved round: same numbers, renumbered years
    assert np.array_equal(shared[1].yields_kg_ha, np.roll(shared[0].yields_kg_ha, -2, axis=1))
    assert np.array_equal(shared[1].irrigation_mm, np.roll(shared[0].irrigation_mm, -2, axis=1))
    assert shared[1].yields_kg_ha.mean() == pytest.approx(shared[0].yields_kg_ha.mean())
    # and it agrees with simulating the shifted plan on its own to within sampling noise
    for d, s in zip(direct, shared):
        assert s.yields_kg_ha.mean(axis=0) == pytest.approx(d.yields_kg_ha.mean(axis=0), rel=0.03)
        assert s.irrigation_mm.mean() == pytest.approx(d.irrigation_mm.mean(), rel=0.05)
    # blocks of consecutive real years keep their order, so nothing is shared there
    hist = SIM.default_scenarios(site, "historical")
    with SIM.what_if(share_shifts=True):
        h = SIM.simulate_many(site, inp, [a, b], hist)
    plain = SIM.simulate_many(site, inp, [a, b], hist)
    assert np.array_equal(h[1].yields_kg_ha, plain[1].yields_kg_ha)
