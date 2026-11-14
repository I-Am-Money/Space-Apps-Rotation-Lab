"""Plain-English explanation of a recommendation.

Only computed numbers are sent to the model, as JSON. If there is no ANTHROPIC_API_KEY, or anything
at all goes wrong, a deterministic template built from the same numbers is returned, so the app never
depends on the API.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

MODEL = "claude-sonnet-5-5"
SYSTEM_PROMPT = ("Explain to a farmer in plain English, 3 to 4 sentences, use only the numbers provided, "
                 "do not add facts, do not recommend beyond the model output.")
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache"
_MEM: dict[str, dict] = {}


def input_hash(inputs: dict) -> str:
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()[:20]


def _rs(x):
    return None if x is None else f"Rs {float(x):,.0f}"


def template_explanation(inputs: dict) -> str:
    """Deterministic fallback. Uses only keys present in `inputs`; skips sentences it has no numbers for."""
    g = inputs.get
    s = []
    if g("top_rotation"):
        line = f"For the settings you chose, the model ranks {g('top_rotation')} first"
        if g("runner_up"):
            line += f", with {g('runner_up')} second"
        s.append(line + ".")
    if g("top_mean_profit") is not None and g("top_worst10_profit") is not None:
        s.append(f"Over four years it averages {_rs(g('top_mean_profit'))} per acre, and about {_rs(g('top_worst10_profit'))} per acre "
                 "in the worst tenth of weather sequences.")
    if g("top_water_stress_mm") is not None:
        s.append(f"The model expects a water shortfall of about {float(g('top_water_stress_mm')):,.0f} mm over the plan.")
    if g("irrigation_shift_mm") is not None:
        s.append(f"At normal rainfall, the model switches from rice on every plot to a mix with millets around {float(g('irrigation_shift_mm')):,.0f} mm of irrigation water.")
    elif g("rain_crossover") is not None:
        s.append(f"The rice and millet choices cross over near {float(g('rain_crossover')):.2f} times the usual monsoon rainfall.")
    if not s:
        s.append("The model has no numbers to explain yet.")
    return " ".join(s[:4])


def explain(inputs: dict) -> dict:
    """Return {'text', 'source'} where source is 'model' or 'template'. Never raises."""
    key = input_hash(inputs)
    if key in _MEM:
        return _MEM[key]
    f = CACHE_DIR / f"explain_{key}.json"
    try:
        if f.exists():
            _MEM[key] = json.loads(f.read_text())
            return _MEM[key]
    except Exception:
        pass
    result = {"text": template_explanation(inputs), "source": "template"}
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic

            client = anthropic.Anthropic(timeout=20.0, max_retries=1)
            msg = client.messages.create(
                model=MODEL, max_tokens=350, system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": json.dumps(inputs, sort_keys=True, default=str)}],
            )
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
            if text:
                result = {"text": text, "source": "model"}
                try:
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    f.write_text(json.dumps(result))
                except Exception:
                    pass
        except Exception:
            pass
    _MEM[key] = result
    return result
