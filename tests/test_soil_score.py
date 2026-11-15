# AI use: this file was written by Claude Code (Anthropic) under the team's direction, then reviewed by the team. See AI_USE.md.
"""Tests for engine/soil_score.py (Person 3, R11)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import soil_score as ss

Y = {"maize": 11000.0, "soybean": 3500.0, "wheat_winter": 4000.0}


def test_label_wording():
    r = ss.soil_score(["maize", "soybean", "maize", "soybean"], yields=Y)
    assert r.label == "Rule-based score from NRCS soil health principles. Not a soil test."
    assert ss.section()["label"]["value"] == r.label


def test_score_bounded():
    for crops in (["maize"] * 4, ["maize", "soybean", "wheat_winter", "soybean"]):
        for till in ss.TILLAGE:
            r = ss.soil_score(crops, yields=Y, tillage=till, history={"erosion": True, "salinity": True})
            assert 0 <= r.score <= 100


def test_legume_and_cover_crop_beat_same_crops_without_them():
    # Same cash crops; the second version swaps a maize year for a soybean (legume) year and adds cover crops.
    without = ss.soil_score(["maize", "wheat_winter", "maize", "wheat_winter"], yields=Y)
    with_lc = ss.soil_score(["maize", "wheat_winter", "soybean", "wheat_winter"],
                            cover_crops=["cereal_rye", None, "crimson_clover", None], yields=Y)
    assert with_lc.score > without.score
    # Cover crops alone, same cash crops and yields, also raise the score.
    plain = ss.soil_score(["maize", "soybean", "maize", "soybean"], yields=Y)
    covered = ss.soil_score(["maize", "soybean", "maize", "soybean"], cover_crops="cereal_rye", yields=Y)
    assert covered.score > plain.score
    assert covered.components["roots"] > plain.components["roots"]


def test_legume_presence_raises_diversity():
    no_leg = ss.soil_score(["maize", "wheat_winter", "maize", "wheat_winter"], yields=Y)
    leg = ss.soil_score(["maize", "wheat_winter", "soybean", "wheat_winter"], yields=Y)
    assert leg.components["diversity"] > no_leg.components["diversity"]


def test_continuous_single_crop_gets_repetition_penalty():
    rp = ss.section()["repetition"]
    mono = ss.soil_score(["maize"] * 4, yields=Y)
    expected = -(3 * rp["points_per_repeat"]["value"] + rp["monoculture_extra_points"]["value"])
    assert mono.points["repetition"] == expected
    rot = ss.soil_score(["maize", "soybean", "maize", "soybean"], yields=Y)
    assert rot.points["repetition"] == 0
    assert mono.score < rot.score
    assert ss.repetition_count([["wheat_winter", "soybean"], ["soybean", "maize"]]) == (1, False)


def test_residue_carbon_matches_hand_calculation():
    # maize: HI 0.50, dry matter 0.845, carbon fraction 0.45 (assumptions.yaml)
    # 10,000 kg/ha * 0.845 = 8,450 kg grain DM; residue DM = 8,450 * (1 - 0.5) / 0.5 = 8,450; C = 8,450 * 0.45
    assert ss.residue_carbon_kg_ha("maize", 10000) == pytest.approx(3802.5)
    assert ss.residue_carbon_kg_ha("corn", 10000) == pytest.approx(3802.5)       # alias
    # soybean: 3,000 * 0.87 = 2,610 DM grain; residue = 2,610 * 0.58 / 0.42 = 3,604.2857; C * 0.45 = 1,621.93
    assert ss.residue_carbon_kg_ha("soybean", 3000) == pytest.approx(3000 * 0.87 * 0.58 / 0.42 * 0.45)
    # Plan mean carbon: (3,802.5 + 1,621.93) / 2 years
    r = ss.soil_score(["maize", "soybean"], yields=[10000, 3000])
    assert r.residue_c_t_ha_yr == pytest.approx((3802.5 + 3000 * 0.87 * 0.58 / 0.42 * 0.45) / 2 / 1000)


def test_tillage_and_history_adjust():
    crops = ["maize", "soybean", "maize", "soybean"]
    nt = ss.soil_score(crops, yields=Y, history={"tillage": "no-till"})
    ct = ss.soil_score(crops, yields=Y, history={"tillage": "conventional"})
    assert nt.score > ct.score and nt.points["tillage_used"] == "no_till"
    hurt = ss.soil_score(crops, yields=Y, history={"tillage": "no-till", "erosion": "yes", "waterlogging": True})
    assert hurt.points["history"] == -8 and hurt.score < nt.score


def test_missing_yields_is_honest_and_unknown_crop_is_placeholder():
    r = ss.soil_score(["maize", "soybean"])
    assert r.components["residue"] is None and r.residue_c_t_ha_yr is None and r.notes
    u = ss.soil_score(["quinoa", "maize"], yields=[2000, 9000])
    assert "quinoa" in u.placeholders and u.badge == "Placeholder"


def test_score_result_reads_rotation_result_shape():
    import numpy as np
    from types import SimpleNamespace

    rr = SimpleNamespace(crops=["maize", ["wheat_winter", "soybean"]], cover_crops=["cereal_rye", None],
                         yields_by_year=[np.array([9000.0, 11000.0]), [4000.0, np.array([2500.0, 3500.0])]])
    a = ss.score_result(rr)
    b = ss.soil_score(["maize", ["wheat_winter", "soybean"]], ["cereal_rye", None], [10000.0, [4000.0, 3000.0]])
    assert a.score == b.score


def test_every_soil_score_leaf_has_source_and_badge():
    def walk(node):
        if isinstance(node, dict) and "value" in node:
            assert node.get("source") and node.get("badge") in ("observed", "assumption", "placeholder")
            return
        for v in node.values():
            walk(v)
    walk(ss.section())
