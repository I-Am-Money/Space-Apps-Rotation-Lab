# AI use: written with AI coding assistants (Claude Code and OpenAI Codex) under the team's direction. See AI_USE.md.
"""Regression coverage for reconciling the upstream v3 rebuild and local completion."""
from pathlib import Path

import numpy as np
import pytest

from engine import api_v3 as api, optimize as opt, scenarios as sc
from tests.decision_fakes import fake_simulate_plan, synthetic_annual


@pytest.fixture
def fake_engine():
    old_n, old_boundary = api.N_SCEN, api.BOUNDARY_N_SCEN
    opt.set_simulator(fake_simulate_plan)
    api.set_annual(synthetic_annual(16))
    api.N_SCEN, api.BOUNDARY_N_SCEN = 40, 10
    yield
    api.N_SCEN, api.BOUNDARY_N_SCEN = old_n, old_boundary
    opt.set_simulator(None)
    api.set_annual(None)
    opt.set_sim_params()
    opt.set_economic_params()


def test_full_tipping_uses_requested_sequences_beyond_interactive_cap(fake_engine):
    interactive = api.tipping_points()
    full = api.tipping_points({"boundary_scenarios": 40})
    assert interactive["n_scenarios"] == 10
    assert full["n_scenarios"] == 40
    assert full["grid"]["boundary_band"]["n_boot"] == 200


def test_comparison_only_current_plan_cannot_be_recommended(fake_engine):
    rec = api.recommend({"current_rotation": ["bajra"] * 4})
    row = rec["metrics"].set_index("id").loc["bajra-bajra-bajra-bajra"]
    assert not row.offered and row["rank"] == 0
    assert rec["top"]["offered"] and rec["top"]["rank"] == 1
    assert rec["metrics"].offered.sum() == 253


def test_baseline_explanation_uses_actual_differences_and_sensitivity(fake_engine):
    from ui.tabs.priorities import explain_inputs
    rec = api.recommend({"w": 1.})
    inputs = explain_inputs(rec, None, rec["params"])
    base = rec["metrics"].set_index("id").loc["rice-rice-rice-rice"]
    assert inputs["diff_mean_profit"] == round(rec["top"]["mean_profit"] - base.mean_profit)
    assert inputs["diff_irrigation_mm"] == round(rec["top"]["irrigation_mm"] - base.irrigation_mm)
    assert "diff_mean_profit_if_no_rotation_effects" in inputs


def test_scenario_cache_identity_changes_with_source_version():
    annual = synthetic_annual(12)
    first = sc.bootstrap_plans(dict(annual, source_version=("first",)), 10)
    second = sc.bootstrap_plans(dict(annual, source_version=("second",)), 10)
    assert first.key != second.key
    np.testing.assert_array_equal(first.scen["year_idx"], second.scen["year_idx"])


def test_both_tipping_curves_draw_from_their_own_axes():
    from ui import charts
    plan = "rice-rice-rice-rice"
    colors = {plan: "#123456"}
    curves = {"rotations": {plan: {"J": [10., 5.]}}}
    onset, _ = charts.late_monsoon(dict(curves, days=[0, 30]), colors)
    heat, _ = charts.heat(dict(curves, dT=[0., 3.]), colors)
    assert list(onset.data[0].x) == [0, 30]
    assert list(heat.data[0].x) == [0., 3.]


def test_public_data_has_no_duplicate_yaml_keys():
    import yaml

    class UniqueLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        keys = [loader.construct_object(k, deep=deep) for k, _ in node.value]
        assert len(keys) == len(set(keys)), f"Duplicate YAML keys: {keys}"
        return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    root = Path(__file__).resolve().parents[1]
    for path in (root / "config").glob("*.yaml"):
        yaml.load(path.read_text(), Loader=UniqueLoader)
