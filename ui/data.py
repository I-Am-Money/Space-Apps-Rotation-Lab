"""Engine access. Uses engine.api; falls back to engine.mock_api per call when the real module (or one of its
own imports or data files) is missing, and records that so the app can show a visible banner."""
from __future__ import annotations

import streamlit as st

from engine import mock_api

import os
import re

try:
    if os.environ.get("ROTATIONLAB_MOCK") == "1":
        raise ImportError("mock forced for design review")
    from engine import api  # type: ignore
except ImportError:
    api = mock_api

CROPS = ["rice", "jowar", "bajra", "pigeonpea"]
CROP_LABEL = {"rice": "Rice", "jowar": "Jowar", "bajra": "Bajra", "pigeonpea": "Pigeon pea"}
DEFAULTS = dict(irrigation_mm=500, use_soil_test=False, soil_awc=140, rot0="rice", rot1="rice", rot2="rice", rot3="rice", lam=30, w=30)
ROT_NAME = {"A": "Rotation A", "B": "Rotation B", "C": "Rotation C", "current": "Your current rotation"}
ROT_SHORT = {"A": "A: all rice", "B": "B: rice and jowar", "C": "C: rice, pigeon pea, jowar"}


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
    return dict(lam=s["lam"] / 100, w=s["w"] / 100, irrigation_mm=float(s["irrigation_mm"]),
                awc_mm_per_m=float(s["soil_awc"]) if s["use_soil_test"] else None,
                current_rotation=[s["rot0"], s["rot1"], s["rot2"], s["rot3"]], price_mult=1.0)


def is_mock() -> bool:
    return bool(st.session_state.get("_mock")) or api is mock_api or bool(getattr(api, "IS_MOCK", False))


def _call(name, *args):
    try:
        return getattr(api, name)(*args), False
    except (ImportError, FileNotFoundError):
        return getattr(mock_api, name)(*args), True


def _wrap(name):
    def raw(*args):
        return _call(name, *args)

    raw.__name__ = raw.__qualname__ = "engine_" + name  # cache_data keys on the name, so each wrapper needs its own
    cached = st.cache_data(show_spinner="Running the model. The first run takes a little while.", max_entries=64)(raw)

    def outer(*args):
        val, mock = cached(*args)
        if mock:
            st.session_state["_mock"] = True
        return val
    return outer


field_summary = _wrap("get_field_summary")
_compare = _wrap("compare")
recommend = _wrap("recommend")
tipping = _wrap("tipping_points")
hindcast = _wrap("hindcast")
assumptions = _wrap("assumptions_table")


def compare(ids, p):
    return _compare(list(ids), p)


_PLAN_RE = re.compile(r"\b(?:rice|jowar|bajra|pigeonpea)(?:-(?:rice|jowar|bajra|pigeonpea)){3}\b")


def humanize(text: str) -> str:
    """Engine text names plans by id (rice-jowar-rice-jowar). Show crop names instead; numbers are untouched."""
    t = _PLAN_RE.sub(lambda m: plan_label(m.group(0)), text or "")
    return t[:1].upper() + t[1:] if t else t
