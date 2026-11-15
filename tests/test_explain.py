# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import explain as ex

INPUTS = dict(top_rotation="Rice, Jowar, Rice, Jowar", runner_up="Rice x4", top_mean_profit=91000, top_worst10_profit=52000,
              top_irrigation_mm=1240, irrigation_shift_mm=600)


def test_fallback_without_key(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(ex, "CACHE_DIR", tmp_path)
    ex._MEM.clear()
    r = ex.explain(INPUTS)
    assert r["source"] == "template"
    assert "Rs 91,000" in r["text"] and "600 mm" in r["text"]
    assert 3 <= r["text"].count(".") <= 4


def test_fallback_on_api_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "bad-key")
    monkeypatch.setattr(ex, "CACHE_DIR", tmp_path)
    import anthropic

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("network down")

    monkeypatch.setattr(anthropic, "Anthropic", Boom)
    ex._MEM.clear()
    r = ex.explain(INPUTS)
    assert r["source"] == "template" and r["text"]


def test_template_is_deterministic_and_handles_empty():
    assert ex.template_explanation(INPUTS) == ex.template_explanation(dict(INPUTS))
    assert ex.template_explanation({})
    assert ex.input_hash(INPUTS) == ex.input_hash(dict(reversed(list(INPUTS.items()))))
