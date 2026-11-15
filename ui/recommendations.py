# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Recommendations page (Build Spec v4 R13 to R16). Owner: Feature 3.

Plain Streamlit only: no custom colors, CSS or styling (the design pass belongs to the app-shell owner). Data labels use badge() from
ui/components.py. Three pick cards (the headline first), a profit-versus-soil tradeoff chart, and the priority sliders.
The slow step (simulating every rotation) is cached; moving a slider only re-runs the fast pick selection.
Every number comes from engine/optimize.py. Nothing here is computed except display formatting.

    render(site, inputs, currency="USD", area_unit="ha", key="rec", simulate=None, scenarios=None, crops=None,
           recommend_fn=None)

`recommend_fn(sliders_dict, most_food) -> result` lets the app shell plug in engine.api.recommend later; without it
the page calls engine/optimize.py directly. While Person 2's simulate() is not available the result is flagged
EXAMPLE and the page says so.
"""
from __future__ import annotations

import hashlib
import json
import os

import plotly.graph_objects as go
import streamlit as st

from engine import economics, optimize as opt
from ui.components import badge

DISCLAIMER = "Modeled estimates for planning. Not a guarantee of yield or profit."
SOIL_LABEL = "Rule-based score from NRCS soil health principles. Not a soil test."
SHIFT_LABELS = {"historical": "Historical weather", "recent": "Recent 20 years count double", "trend": "Continuing observed trend"}
PICK_TITLES = {"headline": "Best for soil and climate", "highest_profit": "Highest profit", "best_soil": "Best for your soil"}


def show_badge(kind: str) -> None:
    """Display a data label with the shared badge() component."""
    out = badge(kind)
    if isinstance(out, str):
        st.markdown(out, unsafe_allow_html=True)


def crop_label(c: str) -> str:
    return str(c).replace("_", " ").capitalize()


def _unit(area_unit: str) -> str:
    return "acre" if area_unit == "acre" else "ha"


def _conv(v: float, area_unit: str) -> float:
    """Engine values are per hectare; show per acre when the farmer works in acres."""
    return economics.cost_per_ha_to_per_acre(v) if area_unit == "acre" else v


def money(per_ha: float, currency: str, area_unit: str) -> str:
    v = _conv(per_ha, area_unit)
    return f"{'-' if v < 0 else ''}{currency} {abs(v):,.0f}"


def pick_card(name: str, rot: dict | None, text: str, currency: str, area_unit: str, big: bool, example: bool) -> None:
    with st.container(border=True):
        (st.header if big else st.subheader)(PICK_TITLES[name])
        if example:
            show_badge("example")
        if rot is None:
            st.warning("No headline pick. No rotation keeps your average profit at or above your current plan minus your "
                       "tolerance. Raise the tolerance, or look at the other two picks.")
            return
        cols = st.columns(len(rot["crops"]))
        for i, (col, yr) in enumerate(zip(cols, rot["crops"])):
            col.write(f"Year {i + 1}: {crop_label(yr[0])}" + (" + cover crop" if rot["cover_crops"][i] else ""))
        d, u = rot["deltas_vs_current"], _unit(area_unit)
        m = st.columns(5)
        m[0].metric(f"Average profit ({currency}/{u}/yr)", money(rot["mean_profit"], currency, area_unit),
                    f"{_conv(d['mean_profit'], area_unit):+,.0f} vs current")
        m[1].metric(f"Bad-year profit ({currency}/{u}/yr)", money(rot["worst10_profit"], currency, area_unit),
                    f"{_conv(d['worst10_profit'], area_unit):+,.0f} vs current")
        m[2].metric("Water used (mm/yr)", f"{rot['total_water_mm']:,.0f}", f"{d['total_water_mm']:+,.0f} vs current", delta_color="inverse")
        m[3].metric("Soil Health Score", f"{rot['soil_score']:.0f}", f"{d['soil_score']:+,.0f} vs current")
        m[4].metric(f"Food (Mcal/{u}/yr)", f"{_conv(rot['calories'], area_unit) / 1000:,.0f}", f"{_conv(d['calories'], area_unit) / 1000:+,.0f} vs current")
        show_badge("estimated")
        st.write(text)


def tradeoff_chart(result: dict, currency: str, area_unit: str):
    """Profit against Soil Health Score for every rotation; colour = profit in bad years; picks and current highlighted."""
    allr = result["all_results"]
    fig = go.Figure(go.Scatter(
        x=[_conv(r["mean_profit"], area_unit) for r in allr], y=[r["soil_score"] for r in allr], mode="markers", name="Other rotations",
        marker=dict(size=7, color=[_conv(r["worst10_profit"], area_unit) for r in allr], showscale=True,
                    colorbar=dict(title="Bad-year profit")),
        text=[" > ".join(crop_label(yr[0]) for yr in r["crops"]) for r in allr],
        hovertemplate="%{text}<br>Average profit %{x:,.0f}<br>Soil Health Score %{y:.0f}<extra></extra>"))
    marks = [("Your current plan", result["current_plan_result"], "circle-open")]
    for k, sym in (("headline", "star"), ("highest_profit", "diamond"), ("best_soil", "square")):
        if result.get(k) is not None:
            marks.append((PICK_TITLES[k], result[k], sym))
    for label, r, sym in marks:
        fig.add_trace(go.Scatter(x=[_conv(r["mean_profit"], area_unit)], y=[r["soil_score"]], mode="markers", name=label,
                                 marker=dict(symbol=sym, size=16, line=dict(width=2))))
    fig.update_layout(height=420, legend=dict(orientation="h", y=-0.25, x=0))
    fig.update_xaxes(title=f"Average profit ({currency} per {_unit(area_unit)} per year)")
    fig.update_yaxes(title="Soil Health Score (0 to 100)", range=[0, 100])
    return fig


def cache_extra(crops, simulate, scenarios) -> str:
    """Part of the cache key: which crops, which simulation function and which scenarios were used."""
    n = getattr(scenarios, "n", None) or (len(scenarios) if hasattr(scenarios, "__len__") else scenarios)
    return f"{crops}|{getattr(simulate, '__module__', None)}.{getattr(simulate, '__qualname__', None)}|{type(scenarios).__name__}:{n}"


def _site_key(site, inputs, extra="") -> str:
    blob = json.dumps({"lat": getattr(site, "lat", None), "lon": getattr(site, "lon", None), "plan": inputs.current_plan,
                       "ov": getattr(inputs, "crop_overrides", None), "hist": getattr(inputs, "history", None),
                       "water": getattr(getattr(inputs, "water", None), "__dict__", None), "extra": extra}, default=str, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()


@st.cache_resource(show_spinner=False, max_entries=8)
def _scored_bundle(key: str, _site, _inputs, _crops, _simulate, _scenarios):
    return opt.score_candidates(_site, _inputs, crops=_crops, simulate=_simulate, scenarios=_scenarios)


def read_sliders(key: str) -> dict:
    st.subheader("What matters to you")
    c1, c2 = st.columns(2)
    with c1:
        bad = st.slider("Plan for an average year  to  Protect me in bad years", 0, 100, 30, key=f"{key}_bad",
                        help="0 picks the highest average profit. 100 picks the best profit in the worst 10% of years.")
        soil = st.slider("How much do you care about soil health?", 0, 100, 50, key=f"{key}_soil",
                         help="0 ranks by profit and risk only. 100 ranks by Soil Health Score.")
    with c2:
        water = st.slider("How much do you care about saving water?", 0, 100, 0, key=f"{key}_water")
        tol = st.slider("How much average profit can you give up? (percent)", 0, 25, 0, key=f"{key}_tol",
                        help="The headline never earns less on average than your current plan minus this much.")
    shift = st.radio("Climate", list(SHIFT_LABELS), format_func=SHIFT_LABELS.get, horizontal=True, key=f"{key}_shift")
    st.caption("Climate settings are what-if adjustments to real years, not forecasts.")
    return {"bad_year": bad / 100.0, "soil": soil / 100.0, "water": water / 100.0, "profit_tolerance_pct": float(tol), "climate_shift": shift}


def render(site, inputs, currency: str = "USD", area_unit: str = "ha", key: str = "rec", simulate=None, scenarios=None,
           crops=None, recommend_fn=None) -> dict | None:
    st.header("Recommendations")
    st.caption(DISCLAIMER)
    sliders = read_sliders(key)
    most_food = st.toggle("Most food instead of highest profit (changes the second card)", value=False, key=f"{key}_food")
    with st.spinner("Scoring every rotation against the weather record..."):
        if recommend_fn is not None:
            result = recommend_fn(sliders, most_food)
        else:
            bundle = _scored_bundle(_site_key(site, inputs, cache_extra(crops, simulate, scenarios)), site, inputs, crops, simulate, scenarios)
            result = opt.assemble_recommendation(bundle, sliders, most_food, explain_text=True)
    if "input_needed" in result:
        need = "; ".join(f"your {n['field']} for {crop_label(n['crop'])}" for n in result["input_needed"])
        st.warning(f"Input needed. Enter {need} before money numbers can be shown. Nothing is filled in for you.")
        return result
    if "current_plan_problem" in result:
        st.warning(f"Your current plan could not be simulated here: {result['current_plan_problem']}. "
                   "Check the crops and the site, then try again.")
        return result
    ex = bool(result.get("example"))
    if ex:
        show_badge("example")
        st.warning("EXAMPLE DATA. The crop simulation is not connected yet, so these results come from a stand-in. "
                   "Do not use them for decisions.")
    texts = result["explanations"]
    cur = result["current_plan_result"]
    head = result["headline"]
    if head is not None and head["crops"] == cur["crops"] and head["cover_crops"] == cur["cover_crops"]:
        st.info("Your current plan is already the best match for your priorities under your profit guardrail. "
                "No other rotation keeps your average profit at or above it and scores higher.")
    pick_card("headline", result["headline"], texts.get("headline", ""), currency, area_unit, True, ex)
    a, b = st.columns(2)
    with a:
        pick_card("highest_profit", result["highest_profit"], texts.get("highest_profit", ""), currency, area_unit, False, ex)
    with b:
        pick_card("best_soil", result["best_soil"], texts.get("best_soil", ""), currency, area_unit, False, ex)
    if result.get("excluded_crops"):
        st.caption("Left out until you enter them: " + ", ".join(f"{crop_label(x['crop'])} (needs {x['field']})" for x in result["excluded_crops"]) + ".")
    if result.get("cover_crop_note"):
        st.caption(result["cover_crop_note"])
    if os.environ.get("ANTHROPIC_API_KEY") and result.get("headline") is not None and st.button("Explain the headline pick in my own words", key=f"{key}_ai"):
        from engine import explain as ex_mod
        st.info(ex_mod.explain_pick(result["headline"], result["current_plan_result"], pick="headline", use_api=True))
    st.subheader("Profit against soil health, every rotation")
    st.plotly_chart(tradeoff_chart(result, currency, area_unit), width="stretch", key=f"{key}_chart")
    show_badge("assumption")
    st.caption(f"{SOIL_LABEL} Profit uses prices and costs you entered or official data, fixed across years. "
               f"Energy values and some crop limits are marked team to verify.")
    return result
