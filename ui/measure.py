# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""What to measure next (Build Spec v4 R19). Owner: Feature 3.

Plain Streamlit only: no custom colors, CSS or styling (the design pass belongs to the app-shell owner). Data labels use badge() from
ui/components.py. Ranks the unknowns (water supply, soil water capacity, organic matter) by their expected value of
perfect information, in plain words: "could change your answer" or "probably won't". EVPI is an upper bound on what a
real test is worth, not what it will earn. All numbers come from engine/evpi.py.

    render(site, inputs, sliders=None, currency="USD", area_unit="ha", key="meas", simulate=None, scenarios=None,
           crops=None, question_fn=None)

`question_fn(test_costs) -> list[dict]` lets the app shell plug in engine.api.question_value later.
"""
from __future__ import annotations

import streamlit as st

from engine import evpi, optimize as opt
from ui.recommendations import DISCLAIMER, _site_key, cache_extra, show_badge

UPPER_BOUND = ("Some things about your farm are not known exactly. This page shows which of them could change your best plan. "
               "The money figure is an upper bound: the most a perfect answer could be worth. A real test is never perfect, so it is worth less.")
LABELS = {"soil_water": "Soil water capacity", "water_supply": "Irrigation water supply", "organic_matter": "Soil organic matter"}


@st.cache_resource(show_spinner=False, max_entries=8)
def _question_rows(key: str, bad_year: float, test_costs_key: str, _site, _inputs, _crops, _simulate, _scenarios, _test_costs):
    return evpi.question_value(_site, _inputs, {"bad_year": bad_year}, crops=_crops, simulate=_simulate,
                               scenarios=_scenarios, test_costs=_test_costs)


def _money(per_acre: float, per_ha: float, currency: str, area_unit: str) -> str:
    v = per_acre if area_unit == "acre" else per_ha
    return f"{currency} {v:,.0f} per {'acre' if area_unit == 'acre' else 'ha'}"


def show_row(rank: int, r: dict, currency: str, area_unit: str, example: bool) -> None:
    with st.container(border=True):
        st.subheader(f"{rank}. {r['question']}")
        if example:
            show_badge("example")
        st.write(r["plain"])
        if r["computed"]:
            st.metric("The most it could be worth to know this exactly", _money(r["evpi_per_acre"], r["evpi_per_ha"], currency, area_unit))
            show_badge(r["badge"])
        if r.get("worth_it") is not None and r.get("test_cost_per_ha") is not None:
            st.write("Your test quote: " + ("worth getting." if r["worth_it"] else "costs more than the most it could save."))
        if r["note"] and r["note"] != r["plain"]:
            st.caption(r["note"])


def render(site, inputs, sliders=None, currency: str = "USD", area_unit: str = "ha", key: str = "meas", simulate=None,
           scenarios=None, crops=None, question_fn=None) -> list | None:
    st.header("What to check first")
    st.caption(DISCLAIMER)
    st.caption(UPPER_BOUND)
    costs = {}
    with st.expander("I have a price quote for a test"):
        st.caption("Enter a quote per hectare in your currency to see whether knowing is worth it. Leave blank if you have none.")
        for name, label in LABELS.items():
            v = st.number_input(f"{label}: quote per ha ({currency})", min_value=0.0, value=None, step=10.0, key=f"{key}_{name}")
            if v is not None:
                costs[name] = float(v)
    bad = float((sliders or {}).get("bad_year", 0.3)) if isinstance(sliders, dict) else float(getattr(sliders, "bad_year", 0.3) or 0.3)
    is_example = bool(simulate is opt._stand_in_simulate or (simulate is None and opt._default_simulate()[1]))
    with st.spinner("Checking which unknowns could change your answer..."):
        rows = question_fn(costs) if question_fn is not None else _question_rows(
            _site_key(site, inputs, cache_extra(crops, simulate, scenarios)), round(bad, 2), repr(sorted(costs.items())), site, inputs, crops, simulate, scenarios, costs)
    if is_example and question_fn is None:
        show_badge("example")
        st.warning("EXAMPLE DATA. The crop simulation is not connected yet, so these values come from a stand-in. "
                   "Do not use them for decisions.")
    if rows and rows[0].get("input") == "prices":
        st.warning(f"Input needed. {rows[0]['note']}.")
        return rows
    for i, r in enumerate(rows, 1):
        show_row(i, r, currency, area_unit, is_example)
    return rows
