# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""R19: EVPI is never negative, matches a hand value, and ranks what to measure."""
import types

import numpy as np
import pytest

from engine import evpi

F = np.linspace(0.2, 1.6, 10)
US = {"prices": {"maize": 200.0, "sorghum": 150.0, "soybean": 400.0}, "costs": {"maize": 300.0, "sorghum": 100.0, "soybean": 200.0}}


def make_site(awc=150.0, om=2.0):
    return types.SimpleNamespace(us_defaults=US, soil=types.SimpleNamespace(awc_mm_per_m=awc, organic_matter_pct=om))


def make_inputs(mode="rain", normal=None):
    return types.SimpleNamespace(current_plan=["sorghum"] * 4, crop_overrides={}, history=None,
                                 water=types.SimpleNamespace(mode=mode, normal_mm=normal, dry_mm=None))


def fake_simulate(site, inputs, rotation, scenarios):
    cap = min(1.0, site.soil.awc_mm_per_m / 150.0)                 # maize is cut when soil holds less than 150 mm/m
    cols = []
    for yr in rotation["crops"]:
        c = yr[0]
        cols.append({"maize": 8000 * F * cap, "sorghum": 3500 + 500 * F, "soybean": 3000 * (0.7 + 0.3 * F)}[c])
    y = np.stack(cols, axis=1)
    return {"yields_kg_ha": y, "irrigation_mm": np.zeros_like(y), "total_water_mm": np.full_like(y, 400.0)}


def run(site=None, inputs=None, bad_year=0.0, **kw):
    return evpi.question_value(site or make_site(), inputs or make_inputs(), {"bad_year": bad_year},
                               crops=["maize", "sorghum", "soybean"], simulate=fake_simulate, scenarios=list(range(10)), **kw)


def test_evpi_matches_a_hand_calculation():
    # two equally likely values, two rotations: [10, 0] and [0, 10]. Knowing the value gets 10 every time;
    # not knowing, either rotation averages 5.  EVPI = 10 - 5 = 5.
    assert evpi.evpi_value([[10, 0], [0, 10]]) == pytest.approx(5.0)
    assert evpi.evpi_value([[3, 1], [3, 1], [3, 1]]) == pytest.approx(0.0)       # one rotation always wins
    assert evpi.evpi_value([[5.0]]) == 0.0


def test_evpi_is_never_negative_on_random_matrices():
    rng = np.random.default_rng(42)
    for _ in range(200):
        J = rng.normal(size=(int(rng.integers(1, 12)), int(rng.integers(1, 30)))) * 100
        assert evpi.evpi_value(J) >= 0.0


def test_soil_water_can_change_the_answer_and_has_positive_value():
    rows = {r["input"]: r for r in run()}
    sw = rows["soil_water"]
    assert sw["computed"] and sw["could_change_answer"] is True and sw["evpi_per_acre"] > 0
    assert "Could change your answer" in sw["plain"]


def test_an_input_that_never_changes_the_best_plan_says_so():
    site = make_site(awc=400.0)                       # far above the 150 mm/m cap even 25% lower: maize always full yield
    rows = {r["input"]: r for r in run(site=site)}
    assert rows["soil_water"]["evpi_per_acre"] == pytest.approx(0.0)
    assert rows["soil_water"]["could_change_answer"] is False and "Probably won't change" in rows["soil_water"]["plain"]


def test_rain_only_farm_has_no_water_supply_question():
    r = {x["input"]: x for x in run()}["water_supply"]
    assert r["applicable"] is False and r["computed"] is False and "rain only" in r["note"]


def test_irrigated_farm_gets_a_computed_water_supply_row():
    rows = {r["input"]: r for r in run(inputs=make_inputs("irrigated", 400.0))}
    ws = rows["water_supply"]
    assert ws["computed"] and ws["applicable"] and ws["evpi_per_acre"] >= 0.0


def test_organic_matter_is_not_computed_from_a_guess():
    om = {r["input"]: r for r in run()}["organic_matter"]
    assert om["computed"] is False and om["evpi_per_acre"] == 0.0 and "team to verify" in om["note"]


def test_rows_are_ranked_by_value_with_uncomputed_last():
    rows = run(inputs=make_inputs("irrigated", 400.0))
    computed = [r for r in rows if r["computed"]]
    assert [r["evpi_per_acre"] for r in computed] == sorted([r["evpi_per_acre"] for r in computed], reverse=True)
    assert all(not r["computed"] for r in rows[len(computed):])
    assert all(r["evpi_per_acre"] >= 0 for r in rows)


def test_per_acre_is_per_hectare_times_ha_per_acre():
    sw = {r["input"]: r for r in run()}["soil_water"]
    assert sw["evpi_per_acre"] == pytest.approx(sw["evpi_per_ha"] * 0.40468564224)


def test_comparison_with_the_test_cost_the_farmer_enters():
    sw = {r["input"]: r for r in run(test_costs={"soil_water": 1e9})}["soil_water"]
    assert sw["worth_it"] is False and "worth less than the test" in sw["plain"]
    sw = {r["input"]: r for r in run(test_costs={"soil_water": 0.0})}["soil_water"]
    assert sw["worth_it"] is True


def test_missing_price_asks_for_input_first():
    inputs = make_inputs()
    inputs.current_plan = ["quinoa"] * 4
    rows = evpi.question_value(make_site(), inputs, {}, crops=["maize"], simulate=fake_simulate, scenarios=list(range(10)))
    assert rows[0]["computed"] is False and "input needed" in rows[0]["note"]


def test_deterministic():
    assert run() == run()
