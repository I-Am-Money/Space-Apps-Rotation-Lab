"""Cached real engine access with anonymous uploads isolated to their session."""
from __future__ import annotations

import re

import streamlit as st

from engine import api

CROPS = ["rice", "jowar", "bajra", "pigeonpea"]
try:  # the engine decides which crops are candidates (iteration 2: selected millets only)
    from engine import optimize as _opt
    CROPS = list(_opt.CROPS)
except Exception:
    pass
CROP_LABEL = {"rice": "Rice", "jowar": "Jowar", "bajra": "Bajra", "ragi": "Ragi", "pigeonpea": "Pigeon pea"}
def _farm():
    try:
        import yaml
        from pathlib import Path
        d = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "farm.yaml").read_text()) or {}
    except Exception:
        d = {}
    f, so, u = d.get("farm", {}), d.get("soil", {}), d.get("units", {})
    return dict(acres=float(f.get("acres") or 0) or None, m3=float(u.get("m3_per_acre_per_mm") or 0) or None,
                soil_name=so.get("display_name") or "Black soil (farm input)", awc_range=so.get("awc_range_mm_per_m"), awc_source=so.get("awc_source"))


FARM = _farm()
ACRES = FARM["acres"]


def farm_total(per_acre):
    """Per-acre rupees to whole-farm rupees. Acres come from config/farm.yaml."""
    return None if per_acre is None or not ACRES else per_acre * ACRES


def m3(mm):
    """Millimetres of water on one acre, summed over the farm, in cubic metres."""
    return None if mm is None or not ACRES or not FARM["m3"] else mm * ACRES * FARM["m3"]


def _assump(key, default):
    try:
        import yaml
        from pathlib import Path
        d = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "assumptions.yaml").read_text())

        def find(x):
            if isinstance(x, dict):
                if key in x:
                    v = x[key]
                    return v.get("value") if isinstance(v, dict) else v
                for v in x.values():
                    r = find(v)
                    if r is not None:
                        return r
        r = find(d)
        return default if r is None else r
    except Exception:
        return default


BASE_IRR = float(_assump("base_available_irrigation_mm", 500))
BASE_K = float(_assump("recharge_exponent_k", 0.5))
BASE_CANAL = _assump("base_canal", None)
BASE_WELL = _assump("base_well", None)
SOURCE_LABELS = {"canal_and_well": "Canal and well", "unset": "Not sure yet", "canal": "Canal only", "borewell": "Borewell", "tank": "Tank"}
CANAL_LABEL = "Proxy for canal releases based on upstream monsoon rain; actual releases depend on reservoir operations."
WELL_LABEL = "Simplified recharge proxy."
DEFAULTS = dict(irrigation_mm=BASE_IRR, use_soil_test=False, soil_awc=140, rot0="rice", rot1="rice", rot2="rice", rot3="rice",
                lam=30, w=10, water_source="canal_and_well", recharge_k=BASE_K, canal_factor=1.0,
                canal_override=False, canal_supply=None, well_override=False, well_supply=None, soil_mode="farm", split_acres=None,
                heat_enabled=True, use_cost_overrides=False, cost_values={}, soil_test_cost=None, water_test_cost=None,
                water_value=float(_assump("water_price_proxy_rs_per_mm_ha", 50)) / 10)
DEFAULTS["full_tipping"] = False
ROT_NAME = {"A": "A: our farm today", "B": "Rotation B", "C": "Rotation C", "current": "Your rotation"}
ROT_SHORT = {"A": "A: all rice", "B": "B: rice and millet", "C": "C: rice, pigeon pea, millet"}


def plan_label(plan) -> str:
    if isinstance(plan, str):
        plan = plan.split("-")
    plan = list(plan)
    if len(set(plan)) == 1:
        return f"{CROP_LABEL.get(plan[0], plan[0])} every year"
    return ", ".join(CROP_LABEL.get(c, c) for c in plan)


def init_state():
    """User inputs live in session_state['_v'] so they survive tabs whose widgets are not rendered (lazy tabs)."""
    st.session_state.setdefault("_v", dict(DEFAULTS))
    for key, value in DEFAULTS.items():
        st.session_state["_v"].setdefault(key, value)
    st.session_state["_mock"] = False


def V() -> dict:
    return st.session_state["_v"]


def _sync(name):
    V()[name] = st.session_state["w_" + name]


def bind(name) -> dict:
    """kwargs for a widget so its value is mirrored into the persistent store."""
    return dict(key="w_" + name, on_change=_sync, args=(name,))


def params() -> dict:
    s = V()
    return dict(lam=s["lam"] / 100, w=s["w"] / 100,
                irrigation_mm=float(s["irrigation_mm"]) if s["water_source"] != "canal_and_well" else None,
                awc_mm_per_m=float(s["soil_awc"]) if s["use_soil_test"] else None,
                current_rotation=[s["rot0"], s["rot1"], s["rot2"], s["rot3"]], price_mult=1.0,
                water_source=s["water_source"], soil_mode=s["soil_mode"],
                heat_enabled=bool(s["heat_enabled"]),
                water_value_rs_m3=float(s["water_value"]),
                boundary_scenarios=500 if s["full_tipping"] else 150,
                **({"operating_costs": s["cost_values"],
                    "soil_test_cost_rs": s["soil_test_cost"], "water_measure_cost_rs": s["water_test_cost"]} if s["use_cost_overrides"] else {}),
                **({"canal_supply_mm": float(s["canal_supply"])} if s["canal_override"] and s["canal_supply"] is not None else {}),
                **({"well_supply_mm": float(s["well_supply"])} if s["well_override"] and s["well_supply"] is not None else {}),
                **({"canal_release_factor": float(s["canal_factor"])} if s["water_source"] == "canal" else {}),
                **({"recharge_exponent_k": float(s["recharge_k"])} if abs(s["recharge_k"] - BASE_K) > 1e-9 and s["water_source"] != "canal" else {}))


def is_mock() -> bool:
    """Always False: the toy stand-in engine was removed so the app can never show invented numbers."""
    return False


def _call(name, *args):
    return getattr(api, name)(*args), False


MSG = {"get_field_summary": "Loading the field record.",
       "compare": "Running the rotations through the weather record.",
       "recommend": "Scoring all rotations for your priorities. The first run takes about 10 seconds; later runs are instant.",
       "tipping_points": "Finding the tipping points. The first run takes about 20 seconds; later runs are instant.",
       "hindcast": "Checking the model against district yields.", "assumptions_table": "Loading assumptions."}


def _wrap(name):
    def raw(source_version, *args):
        return _call(name, *args)

    raw.__name__ = raw.__qualname__ = "engine_" + name  # cache_data keys on the name, so each wrapper needs its own
    cached = st.cache_data(show_spinner=False, max_entries=64, ttl=900)(raw)

    def outer(*args):
        from engine.configuration import version
        val, mock = cached(version(include_data=True), *args)
        if mock:
            st.session_state["_mock"] = True
        return val
    return outer


field_summary = _wrap("get_field_summary")
_compare = _wrap("compare")
recommend = _wrap("recommend")
tipping = _wrap("tipping_points")
_hindcast = _wrap("hindcast")
_land_split = _wrap("land_split")
assumptions = _wrap("assumptions_table")


def hindcast(p):
    records = st.session_state.get("farm_records")
    if records:
        # Uploaded observations stay in this session, outside the shared result cache.
        value, mock = _call("hindcast", dict(p, farm_records=records))
        if mock:
            st.session_state["_mock"] = True
        return value
    return _hindcast(p)


def compare(ids, p):
    return _compare(list(ids), p)


_C = r"(?:rice|jowar|bajra|ragi|pigeon ?pea)"
_PLAN_RE = re.compile(rf"\b{_C}(?:-{_C}){{3}}\b")


def humanize(text: str) -> str:
    """Engine text names plans by id (rice-jowar-rice-jowar). Show crop names instead; numbers are untouched."""
    t = _PLAN_RE.sub(lambda m: plan_label(m.group(0).replace("pigeon pea", "pigeonpea")), text or "")
    t = re.sub(r"(?<=[.!?] )([a-z])", lambda m: m.group(1).upper(), t)
    return t[:1].upper() + t[1:] if t else t


def delta(rots: dict, rid: str, key: str, base: str = "A"):
    """Difference of a rotation from the baseline (A, our farm today). Uses the engine's delta_vs_baseline when present."""
    d = rots[rid].get("delta_vs_baseline")
    if isinstance(d, dict) and key in d:
        return d[key]
    return rots[rid][key] - rots[base][key]


def compare_ids(p) -> tuple:
    """A (our farm today, the baseline), B, C, plus the user's own rotation when it differs from A."""
    ids = ["A", "B", "C"]
    if list(p["current_rotation"]) != ["rice"] * 4:
        ids.append("current")
    return tuple(ids)


def land_split(alt_id, p):
    return _land_split(alt_id, p)


def supply_words(p) -> str:
    """How to name the farm's irrigation supply in a sentence, from the chosen water source."""
    return {"canal_and_well": "canal and well supply", "canal": "canal supply", "borewell": "borewell supply",
            "tank": "tank supply"}.get((p or {}).get("water_source"), "borewell, tank or canal supply")


def placeholder_inputs() -> list:
    """Names of model inputs still badged Placeholder (no verified source). Empty if none."""
    try:
        t = assumptions()
        rows = t.to_dict("records") if hasattr(t, "to_dict") else list(t)
        return [str(r.get("name")) for r in rows if str(r.get("badge", "")).lower() == "placeholder" and r.get("in_use", True)]
    except Exception:
        return []
