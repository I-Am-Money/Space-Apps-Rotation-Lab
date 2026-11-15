# AI use: this file was written by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Tipping-point results worked out ahead of time for the example farms. Feature 2.

The tipping search re-runs the recommendation at 57 what-if points. On a small cloud machine that takes long
enough that the search falls back to fewer weather plans, so the same farm can show slightly different tipping
points on different machines. For the three example farms the result is therefore worked out once with every
weather plan and committed under data/precache/tipping/.

A saved result is used only when both of these match exactly, otherwise the page computes live as before:

    fingerprint()   a hash of every engine/*.py file and every config/assumptions/*.yaml file, so a result made
                    by different code or different assumptions is never shown
    farm_key()      the place, its weather record, soil and county defaults, the farmer's answers and the sliders

Make the files again after any engine or assumptions change:  python -m engine.tipping_precache
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data" / "precache" / "tipping"
_FINGERPRINT = None


def _get(obj, key, default=None):
    if obj is None:
        return default
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def fingerprint() -> str:
    """One hash for the code and the assumptions that produce a result (line endings ignored)."""
    global _FINGERPRINT
    if _FINGERPRINT is None:
        h = hashlib.sha256()
        files = sorted((ROOT / "engine").glob("*.py")) + sorted((ROOT / "config" / "assumptions").glob("*.yaml"))
        for f in files:
            h.update(f.relative_to(ROOT).as_posix().encode())
            h.update(f.read_bytes().replace(b"\r\n", b"\n"))
        _FINGERPRINT = h.hexdigest()
    return _FINGERPRINT


def _plain(value):
    """Dataclasses, dicts, lists and numbers as plain rounded JSON values (for hashing)."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    if hasattr(value, "__dict__"):
        return _plain(vars(value))
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return str(value)


def _weather_mark(weather) -> list:
    """A cheap mark of the weather record: its size, first and last day, and the column totals."""
    if weather is None:
        return []
    try:
        last = getattr(weather, "attrs", {}).get("last_full_year")     # only full years are sampled, so only they count
        if last:
            weather = weather.loc[:f"{int(last)}-12-31"]
        totals = {str(c): round(float(weather[c].sum()), 2) for c in weather.columns
                  if str(weather[c].dtype).startswith(("float", "int"))}
        return [len(weather), str(weather.index[0]), str(weather.index[-1]), totals]
    except Exception:
        return [len(weather)]


def farm_key(site, inputs, sliders) -> str:
    water = _get(inputs, "water")
    us = _get(site, "us_defaults")
    return _hash({
        "place": [round(float(_get(site, "lat")), 4), round(float(_get(site, "lon")), 4), _get(site, "currency"),
                  _plain(_get(site, "elevation_m"))],
        "weather": _weather_mark(_get(site, "weather")),
        "soil": _plain({k: _get(_get(site, "soil"), k) for k in ("texture", "awc_mm_per_m", "organic_matter_pct", "hydrologic_group", "ph")}),
        "county": _plain({k: _get(us, k) for k in ("crops", "yields", "prices", "costs", "irrigated_share")}),
        "answers": {"plan": _plain(_get(inputs, "current_plan")), "water": [_get(water, "mode"), _plain(_get(water, "normal_mm") or 0.0),
                                                                             _plain(_get(water, "dry_mm") or 0.0)],
                    "soil_test": _plain(_get(inputs, "soil_test")), "history": _plain(_get(inputs, "history")),
                    "overrides": _plain(_get(inputs, "crop_overrides") or {})},
        "sliders": {k: _plain(_get(sliders, k)) for k in ("bad_year", "water", "soil", "profit_tolerance_pct", "climate_shift")},
    })


def load(site, inputs, sliders) -> dict | None:
    """The saved result for exactly this farm, code and assumptions, or None."""
    try:
        if not FOLDER.is_dir():
            return None
        key, mark = farm_key(site, inputs, sliders), fingerprint()
        for path in sorted(FOLDER.glob("*.json")):
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved.get("farm_key") == key and saved.get("fingerprint") == mark:
                result = saved["result"]
                result.setdefault("method", {})["precomputed"] = saved.get("made")
                return result
    except Exception:
        return None
    return None


def _json(value):
    """numpy numbers and arrays as plain Python, for json.dumps."""
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def save(name: str, site, inputs, sliders, result: dict) -> Path:
    FOLDER.mkdir(parents=True, exist_ok=True)
    path = FOLDER / f"{name}.json"
    payload = {"made": time.strftime("%Y-%m-%d"), "fingerprint": fingerprint(), "farm_key": farm_key(site, inputs, sliders),
               "result": result}
    path.write_text(json.dumps(payload, default=_json, indent=1), encoding="utf-8")
    return path


def example_farms() -> dict:
    """name -> (lat, lon, crop plan, acres) for the rain-fed example farms on the start screen."""
    import yaml
    doc = yaml.safe_load((ROOT / "config" / "assumptions" / "setup.yaml").read_text(encoding="utf-8"))
    val = lambda d, k: d[k]["value"] if isinstance(d.get(k), dict) else d.get(k)
    out = {}
    for name, p in (doc.get("demo_presets") or {}).items():
        if val(p, "water_mode") == "rain":
            out[name] = (float(val(p, "lat")), float(val(p, "lon")), list(val(p, "current_plan")), float(val(p, "farm_acres")))
    return out


def build(names=None) -> None:
    """Work out and save the tipping result of each example farm, with every weather plan at every what-if point."""
    from engine import api
    from engine.tipping import tipping_points
    for name, (lat, lon, plan, acres) in example_farms().items():
        if names and name not in names:
            continue
        site = api.get_site(lat, lon)
        inputs = api.UserInputs(current_plan=plan, water=api.WaterInput(mode="rain", source="", normal_mm=0.0, dry_mm=0.0),
                                farm_acres=acres, soil_test=None, history=None, crop_overrides={})
        sliders = api.Sliders()                                    # the app's default slider positions
        result = tipping_points(api._currency_site(site), inputs, api._sliders(sliders), full_search=True, budget_s=3600)
        path = save(name, site, inputs, sliders, result)
        print(f"{name}: {result['method'].get('scenarios_winner')} weather plans, {result['method'].get('seconds')} s -> {path.relative_to(ROOT)}")


if __name__ == "__main__":
    import sys
    build(sys.argv[1:] or None)
