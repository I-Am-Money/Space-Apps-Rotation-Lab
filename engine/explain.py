# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Plain-English explanation of a recommendation (Build Spec v4, R16). Owner: Person 3.

Only computed numbers are sent to Claude (claude-sonnet-5-5, key in ANTHROPIC_API_KEY), as JSON. The reply
goes through a guard: every number and every crop name in it is extracted, and if any is not in the input
JSON (allowing for rounding), the reply is discarded and a fixed template built from the same numbers is
used. Results are cached by a hash of the input. With no API key, or on any error, the template is used, so
the app never depends on the API.

    explain_pick(rotation_result, current_plan_result) -> str     # what api.explain() should call (A5)
    explain(inputs: dict, use_api=True) -> {"text", "source"}      # earlier v3 app interface, also guarded
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import OrderedDict
from pathlib import Path

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
SYSTEM_PROMPT = (
    "You explain a crop rotation recommendation to a farmer. Write plain English, 3 to 4 sentences, no lists "
    "or headings. Use only the numbers and crop names in the JSON you are given, written as given or rounded. "
    "Do not compute new numbers, do not add facts, causes, places or crops that are not in the JSON, and do not "
    "recommend anything beyond the model output. Say these are modeled estimates, not a guarantee."
)
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "cache" / "explain"
_MEM: OrderedDict = OrderedDict()
_MEM_MAX = 256

# Crop words the guard looks for in a reply. Any of these that appears must be a crop in the input JSON.
CROP_WORDS = {
    "maize": "maize", "corn": "maize", "soybean": "soybean", "soybeans": "soybean", "soy": "soybean",
    "wheat": "wheat", "winter wheat": "wheat", "spring wheat": "wheat", "cotton": "cotton",
    "sorghum": "sorghum", "milo": "sorghum", "rice": "rice", "paddy": "rice", "peanut": "peanut",
    "peanuts": "peanut", "groundnut": "peanut", "groundnuts": "peanut", "barley": "barley", "oats": "oats",
    "oat": "oats", "rye": "rye", "cereal rye": "rye", "clover": "clover", "crimson clover": "clover",
    "vetch": "vetch", "hairy vetch": "vetch", "alfalfa": "alfalfa", "canola": "canola", "sunflower": "sunflower",
    "sunflowers": "sunflower", "potato": "potato", "potatoes": "potato", "sugarbeet": "sugarbeet",
    "sugar beet": "sugarbeet", "millet": "millet", "bajra": "millet", "jowar": "sorghum", "ragi": "millet",
    "pigeon pea": "pigeonpea", "pigeonpea": "pigeonpea", "tur": "pigeonpea", "chickpea": "chickpea",
    "lentil": "lentil", "lentils": "lentil", "beans": "beans", "dry beans": "beans", "peas": "peas",
    "radish": "radish", "tomato": "tomato", "tomatoes": "tomato", "sugarcane": "sugarcane", "flax": "flax",
}
_CROP_RE = re.compile(r"\b(" + "|".join(sorted((re.escape(k) for k in CROP_WORDS), key=len, reverse=True)) + r")\b",
                      re.IGNORECASE)
_NUM_RE = re.compile(r"(?<![\w.])[-+−]?\$?\d[\d,]*(?:\.\d+)?")


# ---------------------------------------------------------------- payload

def _num(x):
    try:
        import numpy as np
        if isinstance(x, np.generic):
            x = x.item()
    except Exception:
        pass
    return x


def _plain(x):
    """JSON-safe copy: numpy scalars -> python, arrays -> mean (explanations only use summary numbers)."""
    try:
        import numpy as np
        if isinstance(x, np.ndarray):
            return float(x.mean()) if x.size else None
    except Exception:
        pass
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    x = _num(x)
    if isinstance(x, float):
        return round(x, 2)
    return x


def _get(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _crop_label(c) -> str:
    if isinstance(c, (list, tuple)):
        return " then ".join(_crop_label(x) for x in c)
    c = str(c)
    for season in ("winter", "spring"):          # wheat_winter -> winter wheat
        if c.endswith("_" + season):
            c = season + "_" + c[: -len(season) - 1]
    return c.replace("_", " ")


def build_payload(rotation_result, current_plan_result=None, pick: str | None = None) -> dict:
    """The only data sent to Claude: crop names and computed numbers of the pick and the current plan.
    Money is per hectare in the engine's currency (A5 units)."""
    def summary(r):
        if r is None:
            return None
        crops = _get(r, "crops") or []
        covers = [c for c in (_get(r, "cover_crops") or []) if c]
        soil = _get(r, "soil_score")
        soil = _get(soil, "score", soil) if not isinstance(soil, (int, float)) else soil
        return {"crops_by_year": [_crop_label(c) for c in crops], "cover_crops": [_crop_label(c) for c in covers],
                "mean_profit_per_ha": _plain(_get(r, "mean_profit")),
                "bad_year_profit_per_ha": _plain(_get(r, "worst10_profit")),
                "irrigation_mm": _plain(_get(r, "irrigation_mm")), "total_water_mm": _plain(_get(r, "total_water_mm")),
                "soil_health_score": _plain(soil), "calories": _plain(_get(r, "calories"))}

    p = {"pick": pick or "recommended plan", "years_in_plan": len(_get(rotation_result, "crops") or []),
         "bad_year_definition": "average of the worst 10 percent of weather sequences", "worst_share_pct": 10,
         "soil_score_max": 100,
         "plan": summary(rotation_result), "current_plan": summary(current_plan_result)}
    d = _get(rotation_result, "deltas_vs_current")
    if d:
        p["change_vs_current"] = _plain(d)
    return p


# ---------------------------------------------------------------- guard

def _numbers_in(obj) -> list[float]:
    out = []
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, dict):
        for v in obj.values():
            out += _numbers_in(v)
        return out
    if isinstance(obj, (list, tuple)):
        for v in obj:
            out += _numbers_in(v)
        return out
    if isinstance(obj, str):
        return [float(m.replace(",", "").replace("$", "").replace("−", "-").lstrip("+")) for m in _NUM_RE.findall(obj)]
    return out


def _crops_in(obj) -> set[str]:
    return {CROP_WORDS[m.lower()] for m in _CROP_RE.findall(json.dumps(obj, default=str).replace("_", " "))}


def _tolerance(token: str) -> float:
    """How far a number written as `token` may be from the true value and still be a rounding of it."""
    t = token.replace(",", "").replace("$", "").replace("−", "-").lstrip("+-")
    if "." in t:
        return 0.5 * 10 ** -len(t.split(".")[1]) + 1e-9
    digits = t.lstrip("0") or "0"
    zeros = len(digits) - len(digits.rstrip("0"))
    # Allow rounding to at most 2 significant figures: "1,200" may stand for 1,234; "1,000" for 950..1,049.
    k = min(zeros, max(len(digits) - 2, 0))
    return 0.5 * 10 ** k + 1e-9


def check_text(text: str, payload: dict) -> list[str]:
    """Problems with a reply: numbers or crops not in the payload. Empty list = passes the guard."""
    problems = []
    allowed = [abs(v) for v in _numbers_in(payload)]
    for token in _NUM_RE.findall(text):
        val = abs(float(token.replace(",", "").replace("$", "").replace("−", "-").lstrip("+-") or 0))
        tol = _tolerance(token)
        if not any(abs(val - a) <= tol for a in allowed):
            problems.append(f"number {token.strip()} is not in the results")
    have = _crops_in(payload)
    for crop in {CROP_WORDS[m.lower()] for m in _CROP_RE.findall(text)}:
        if crop not in have:
            problems.append(f"crop '{crop}' is not in the results")
    return problems


def passes_guard(text: str, payload: dict) -> bool:
    return bool(text and text.strip()) and not check_text(text, payload)


# ---------------------------------------------------------------- template

def _money(x) -> str:
    return f"{abs(float(x)):,.0f}"


def template_from_payload(p: dict) -> str:
    """Fixed template. Uses only numbers and crop names from the payload, so it always passes the guard."""
    plan, cur, d = p.get("plan") or {}, p.get("current_plan") or {}, p.get("change_vs_current") or {}
    s = []
    crops = ", ".join(plan.get("crops_by_year") or []) or "this plan"
    cov = plan.get("cover_crops") or []
    s.append(f"The {p.get('pick', 'recommended plan')} plan grows {crops}" + (f" with {', '.join(cov)} as a cover crop" if cov else "") + ".")
    if plan.get("mean_profit_per_ha") is not None and plan.get("bad_year_profit_per_ha") is not None:
        def money(x):
            return f"a loss of {_money(x)}" if x < 0 else f"a profit of {_money(x)}"
        s.append(f"It averages {money(plan['mean_profit_per_ha'])} per hectare a year, "
                 f"and {money(plan['bad_year_profit_per_ha'])} per hectare in bad years.")
    dm, ds = d.get("mean_profit"), d.get("soil_score")
    if dm is not None and cur:
        line = f"Compared with the current plan that is {_money(dm)} {'more' if dm >= 0 else 'less'} per hectare on average"
        if ds is not None:
            line += f", and the Soil Health Score is {abs(ds):g} points {'higher' if ds >= 0 else 'lower'}"
        s.append(line + ".")
    elif plan.get("soil_health_score") is not None:
        s.append(f"Its Soil Health Score is {plan['soil_health_score']:g} out of 100.")
    s.append("These are modeled estimates for planning, not a guarantee.")
    return " ".join(s[:4])


# ---------------------------------------------------------------- cache + API

def input_hash(inputs: dict) -> str:
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()[:20]


def _cache_get(key):
    if key in _MEM:
        return _MEM[key]
    f = CACHE_DIR / f"{key}.json"
    if f.exists():
        try:
            v = json.loads(f.read_text())
            _MEM[key] = v
            return v
        except Exception:
            return None
    return None


def _cache_put(key, value, disk=True):
    _MEM[key] = value
    while len(_MEM) > _MEM_MAX:
        _MEM.popitem(last=False)
    if disk:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            (CACHE_DIR / f"{key}.json").write_text(json.dumps(value))
        except Exception:
            pass


def call_claude(payload: dict) -> str | None:
    """One Claude call with the payload as JSON. None on no key, refusal or any error."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(timeout=30.0, max_retries=1)
        msg = client.messages.create(
            model=MODEL, max_tokens=2000, system=SYSTEM_PROMPT,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": json.dumps(payload, sort_keys=True)}],
        )
        if getattr(msg, "stop_reason", None) in ("refusal", "max_tokens"):
            return None
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        return text or None
    except Exception:
        return None


def explain_payload(payload: dict, use_api: bool = True, template=template_from_payload) -> dict:
    """{'text', 'source', 'rejected'}: source is 'model' (passed the guard) or 'template'. Never raises."""
    payload = _plain(payload)
    api_on = bool(use_api and os.environ.get("ANTHROPIC_API_KEY"))
    key = input_hash({"payload": payload, "model": MODEL, "api": api_on, "v": 2})
    hit = _cache_get(key)
    if hit is not None:
        return hit
    result = {"text": template(payload), "source": "template", "rejected": []}
    if api_on:
        text = call_claude(payload)
        if text is not None:
            problems = check_text(text, payload)
            if problems:
                result["rejected"] = problems
            else:
                result = {"text": text, "source": "model", "rejected": []}
    _cache_put(key, result, disk=api_on)
    return result


def explain_pick(rotation_result, current_plan_result=None, pick: str | None = None, use_api: bool = True) -> str:
    """A5 api.explain(rotation_result, current_plan_result) -> str, guarded."""
    return explain_payload(build_payload(rotation_result, current_plan_result, pick), use_api)["text"]


# ---------------------------------------------------------------- v3 app interface (kept until api.py moves to v4)

def _rs(x):
    return None if x is None else f"Rs {float(x):,.0f}"


def template_explanation(inputs: dict) -> str:
    """Deterministic fallback for the v3 app. Uses only keys present in `inputs`."""
    g = inputs.get
    s = []
    if g("top_rotation"):
        if g("same_as_today"):
            line = "For the settings you chose, the model keeps rice every year, the same as the farm today"
        else:
            line = f"For the settings you chose, the model ranks {g('top_rotation')} first"
        if g("runner_up"):
            line += f", with {g('runner_up')} second"
        s.append(line + ".")
    if g("top_mean_profit") is not None and g("top_worst10_profit") is not None:
        s.append(f"Over four years it averages {_rs(g('top_mean_profit'))} per acre, and about {_rs(g('top_worst10_profit'))} per acre "
                 "in the worst tenth of weather sequences.")
    if not g("same_as_today") and g("diff_mean_profit") is not None and g("diff_irrigation_mm") is not None:
        dm, dw, di = float(g("diff_mean_profit")), g("diff_worst10_profit"), float(g("diff_irrigation_mm"))
        line = (f"Against rice every year that is {_rs(abs(dm))} per acre {'more' if dm >= 0 else 'less'} on average")
        if dw is not None:
            line += f", {_rs(abs(float(dw)))} {'more' if float(dw) >= 0 else 'less'} in bad years"
        line += f", and {abs(di):,.0f} mm {'less' if di <= 0 else 'more'} irrigation water."
        s.append(line)
    elif g("top_irrigation_mm") is not None:
        s.append(f"It uses about {float(g('top_irrigation_mm')):,.0f} mm of irrigation water over the plan.")
    if g("irrigation_shift_mm") is not None:
        s.append(f"At normal rainfall, plans with two or more rice years start to win once about {float(g('irrigation_shift_mm')):,.0f} mm of irrigation water is available in a season.")
    elif g("rain_crossover") is not None:
        s.append(f"The number of rice years in the best plan changes near {float(g('rain_crossover')):.2f} times the usual monsoon rainfall.")
    if not s:
        s.append("The model has no numbers to explain yet.")
    return " ".join(s[:4])


def explain(inputs: dict, use_api: bool = True) -> dict:
    """v3 interface: {'text', 'source'} with source 'model' or 'template'. Now guarded too. Never raises."""
    r = explain_payload(inputs, use_api, template=template_explanation)
    return {"text": r["text"], "source": r["source"]}
