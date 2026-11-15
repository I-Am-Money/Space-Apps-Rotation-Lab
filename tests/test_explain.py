# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import explain as ex

INPUTS = dict(top_rotation="Rice, Jowar, Rice, Jowar", runner_up="Rice x4", top_mean_profit=91000, top_worst10_profit=52000,
              top_irrigation_mm=1240, irrigation_shift_mm=600)

PICK = SimpleNamespace(crops=["maize", "soybean", "wheat_winter", "soybean"], cover_crops=["cereal_rye", None, None, None],
                       mean_profit=412.6, worst10_profit=-35.2, irrigation_mm=0.0, total_water_mm=2150.0,
                       soil_score=78.4, calories=5.1e7, deltas_vs_current={"mean_profit": 18.4, "soil_score": 22.1})
CURRENT = SimpleNamespace(crops=["maize"] * 4, cover_crops=None, mean_profit=394.2, worst10_profit=-60.0,
                          irrigation_mm=0.0, total_water_mm=2200.0, soil_score=56.3, calories=6.0e7)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(ex, "CACHE_DIR", tmp_path)
    ex._MEM.clear()


def _fake_claude(monkeypatch, reply):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    calls = []

    def fake(payload):
        calls.append(payload)
        return reply
    monkeypatch.setattr(ex, "call_claude", fake)
    return calls


# ---- v4: guard
def test_guard_accepts_numbers_from_results_with_rounding():
    p = ex._plain(ex.build_payload(PICK, CURRENT, "Best for soil and climate"))
    ok = ("Growing maize, soybean and winter wheat with cereal rye earns about 413 per hectare a year, "
          "18 more than today, and lifts the Soil Health Score by 22 points to 78. "
          "In the worst 10 percent of years it still loses about 35. These are modeled estimates.")
    assert ex.check_text(ok, p) == []
    assert ex.passes_guard("Profit is about 410 per hectare.", p)        # 412.6 rounded to 2 significant figures


def test_fake_explanation_with_wrong_number_is_rejected(monkeypatch):
    p = ex._plain(ex.build_payload(PICK, CURRENT))
    bad = "This plan earns 650 per hectare, much more than the current plan."
    assert any("650" in m for m in ex.check_text(bad, p))
    _fake_claude(monkeypatch, bad)
    r = ex.explain_payload(ex.build_payload(PICK, CURRENT))
    assert r["source"] == "template" and r["rejected"] and "650" not in r["text"]


def test_fake_explanation_with_wrong_crop_is_rejected(monkeypatch):
    p = ex._plain(ex.build_payload(PICK, CURRENT))
    bad = "Adding cotton after soybean earns about 413 per hectare."
    assert any("cotton" in m for m in ex.check_text(bad, p))
    _fake_claude(monkeypatch, bad)
    text = ex.explain_pick(PICK, CURRENT)
    assert "cotton" not in text.lower() and text == ex.template_from_payload(ex._plain(ex.build_payload(PICK, CURRENT)))


def test_good_reply_is_used_and_cached(monkeypatch):
    good = "This rotation of maize and soybean averages about 413 per hectare. These are modeled estimates."
    calls = _fake_claude(monkeypatch, good)
    assert ex.explain_pick(PICK, CURRENT) == good
    assert ex.explain_pick(PICK, CURRENT) == good
    assert len(calls) == 1                     # second call served from the input-hash cache


def test_payload_has_only_computed_numbers_and_crops():
    p = ex.build_payload(PICK, CURRENT)
    assert set(p) <= {"pick", "years_in_plan", "bad_year_definition", "worst_share_pct", "soil_score_max", "plan",
                      "current_plan", "change_vs_current"}
    assert p["plan"]["crops_by_year"] == ["maize", "soybean", "winter wheat", "soybean"]
    import json
    json.dumps(p)                              # JSON-serializable


# ---- template, no key
def test_template_works_with_no_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = ex.explain_payload(ex.build_payload(PICK, CURRENT, "Best for soil and climate"))
    assert r["source"] == "template"
    assert "413" in r["text"] and "maize" in r["text"] and "not a guarantee" in r["text"]
    assert ex.check_text(r["text"], ex._plain(ex.build_payload(PICK, CURRENT, "Best for soil and climate"))) == []
    assert isinstance(ex.explain_pick(PICK, CURRENT), str)


def test_template_without_current_plan_or_numbers():
    t = ex.explain_pick(SimpleNamespace(crops=["maize"]), None, use_api=False)
    assert "maize" in t and "not a guarantee" in t


# ---- v3 interface kept for the current app
def test_fallback_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = ex.explain(INPUTS)
    assert r["source"] == "template"
    assert "Rs 91,000" in r["text"] and "600 mm" in r["text"]
    assert 3 <= r["text"].count(".") <= 4


def test_fallback_on_api_failure(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "bad-key")
    import anthropic

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("network down")

    monkeypatch.setattr(anthropic, "Anthropic", Boom)
    r = ex.explain(INPUTS)
    assert r["source"] == "template" and r["text"]


def test_v3_interface_is_guarded(monkeypatch):
    _fake_claude(monkeypatch, "Rice and jowar earn Rs 120,000 per acre.")
    assert ex.explain(INPUTS)["source"] == "template"


def test_template_is_deterministic_and_handles_empty():
    assert ex.template_explanation(INPUTS) == ex.template_explanation(dict(INPUTS))
    assert ex.template_explanation({})
    assert ex.input_hash(INPUTS) == ex.input_hash(dict(reversed(list(INPUTS.items()))))
