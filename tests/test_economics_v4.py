# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Feature 3 economics: conversions checked against hand calculations; missing price or cost is never defaulted."""
import numpy as np
import pytest

from engine import economics as ec


def test_bushels_per_acre_to_kg_per_ha_hand_calculation():
    # 1 bu maize = 56 lb x 0.45359237 = 25.4012 kg; 1 acre = 0.404686 ha  ->  62.771 kg/ha per bu/ac
    assert ec.kg_per_bushel("maize") == pytest.approx(25.40117, abs=1e-4)
    assert ec.bu_ac_to_kg_ha(1.0, "maize") == pytest.approx(62.7712, abs=0.01)
    assert ec.bu_ac_to_kg_ha(180.0, "maize") == pytest.approx(11298.8, abs=2.0)
    assert ec.bu_ac_to_kg_ha(50.0, "soybean") == pytest.approx(3360.9, abs=2.0)   # 60 lb/bu = 27.2155 kg


def test_round_trips():
    for crop in ("maize", "soybean", "wheat_winter", "sorghum"):
        assert ec.kg_ha_to_bu_ac(ec.bu_ac_to_kg_ha(123.4, crop), crop) == pytest.approx(123.4)
        assert ec.price_per_tonne_to_per_bu(ec.price_per_bu_to_per_tonne(5.5, crop), crop) == pytest.approx(5.5)
    assert ec.ha_to_acres(ec.acres_to_ha(80.0)) == pytest.approx(80.0)
    assert ec.cost_per_ha_to_per_acre(ec.cost_per_acre_to_per_ha(600.0)) == pytest.approx(600.0)


def test_price_and_cost_conversions_hand_calculation():
    assert ec.price_per_bu_to_per_tonne(4.50, "maize") == pytest.approx(177.16, abs=0.05)   # 4.50 / 25.4012 x 1000
    assert ec.cost_per_acre_to_per_ha(600.0) == pytest.approx(1482.6, abs=0.2)             # 600 / 0.404686
    assert ec.acres_to_ha(100.0) == pytest.approx(40.4686, abs=1e-3)


def test_profit_per_ha_by_hand_and_vectorised():
    # 10 000 kg/ha = 10 t at 180 per tonne = 1800, minus 1200 cost = 600
    assert ec.profit_per_ha(10000.0, 180.0, 1200.0) == pytest.approx(600.0)
    p = ec.profit_per_ha(np.array([0.0, 5000.0, 10000.0]), 180.0, 1200.0)
    assert list(p) == pytest.approx([-1200.0, -300.0, 600.0])
    assert ec.profit_per_ha(-50.0, 180.0, 1200.0) == pytest.approx(-1200.0)   # a negative yield is treated as zero


def test_missing_price_or_cost_raises_input_needed_never_defaults():
    with pytest.raises(ec.InputNeeded) as e:
        ec.crop_economics("quinoa")
    assert e.value.crop == "quinoa" and e.value.field == "price"
    with pytest.raises(ec.InputNeeded) as e:
        ec.crop_economics("quinoa", crop_overrides={"quinoa": {"price": 900.0}})
    assert e.value.field == "cost"


def test_farmer_entry_beats_us_data_and_badges_say_which():
    us = {"prices": {"maize": 180.0}, "costs": {"maize": 1200.0}}
    got = ec.crop_economics("maize", us)
    assert got["price_per_t"] == 180.0 and got["price_badge"] == "observed"
    got = ec.crop_economics("maize", us, {"maize": {"price": 200.0}})
    assert got["price_per_t"] == 200.0 and got["price_badge"] == "your_input"
    assert got["cost_per_ha"] == 1200.0 and got["cost_badge"] == "observed"


def test_unknown_bushel_crop_asks_for_metric_input():
    with pytest.raises(KeyError):
        ec.kg_per_bushel("quinoa")
