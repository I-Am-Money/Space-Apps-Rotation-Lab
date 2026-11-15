# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Best crop plans page (Build Spec v4 R13 to R16). Owner: Feature 3.

The answer comes first: three plan cards (the headline is larger), each with the four years, the average profit in the
farmer's own units, one plain sentence against what they grow today, and a small table. Under that, the priority
controls and a chart of every plan. Styling comes from ui/theme.py; data labels use badge() from ui/components.py.
Every number comes from engine/optimize.py. Nothing here is computed except display formatting and unit conversion.

    render(site, inputs, currency="USD", area_unit="ha", key="rec", simulate=None, scenarios=None, crops=None,
           recommend_fn=None)

`recommend_fn(sliders_dict, most_food) -> result` lets the app shell plug in engine.api. The slow step is cached;
moving a control only re-runs the fast pick selection.
"""
from __future__ import annotations

import hashlib
import html
import json

import plotly.graph_objects as go
import streamlit as st

from engine import economics, optimize as opt
from ui.components import badge, delta_html, md
from ui.theme import T, crop_name

DISCLAIMER = "Modeled estimates for planning. Not a guarantee of yield or profit."
SOIL_LABEL = "Rule-based score from NRCS soil health principles. Not a soil test."
SHIFT_LABELS = {"historical": "The weather as it has been", "recent": "The last 20 years count double", "trend": "The recent trend continues"}
PICK_TITLES = {"headline": "Best for soil and climate", "highest_profit": "Highest profit", "best_soil": "Best for your soil"}
PICK_WHY = {"headline": "The best balance of soil health, bad-year protection and profit, without earning less than you do today.",
            "highest_profit": "The plan that earns the most for the priorities you set.",
            "best_soil": "The plan with the highest Soil Health Score."}
MM_PER_INCH = 25.4


def show_badge(kind: str) -> None:
    """Display a data label with the shared badge() component."""
    out = badge(kind)
    if isinstance(out, str):
        st.markdown(out, unsafe_allow_html=True)


def crop_label(c: str) -> str:
    return crop_name(c)


def _unit(area_unit: str) -> str:
    return "acre" if area_unit == "acre" else "ha"


def _conv(v: float, area_unit: str) -> float:
    """Engine values are per hectare; show per acre when the farmer works in acres."""
    return economics.cost_per_ha_to_per_acre(v) if area_unit == "acre" else v


def _water(mm: float, area_unit: str) -> tuple[float, str]:
    """Water depth in inches for farmers working in acres, millimetres otherwise."""
    return (mm / MM_PER_INCH, "inches") if area_unit == "acre" else (mm, "mm")


def money(per_ha: float, currency: str, area_unit: str) -> str:
    v = _conv(per_ha, area_unit)
    return f"{'-' if v < 0 else ''}{currency} {abs(v):,.0f}"


def same_plan(a: dict, b: dict) -> bool:
    return a["crops"] == b["crops"] and a["cover_crops"] == b["cover_crops"]


def years_html(rot: dict) -> str:
    cells = []
    for i, yr in enumerate(rot["crops"]):
        name = " then ".join(crop_label(c) for c in yr) + (" + cover crop" if rot["cover_crops"][i] else "")
        cells.append(f'<div class="rl-year"><b>Year {i + 1}</b><span>{html.escape(name)}</span></div>')
    return '<div class="rl-years">' + "".join(cells) + "</div>"


def plain_summary(rot: dict, current: dict, currency: str, area_unit: str) -> str:
    """One or two sentences against what the farmer grows today, in their units. Built only from computed numbers."""
    if same_plan(rot, current):
        return "This is the plan you grow today."
    d, u = rot["deltas_vs_current"], _unit(area_unit)

    def amount(v, fmt="{:,.0f}"):
        return fmt.format(abs(v))
    dm, dw = _conv(d["mean_profit"], area_unit), _conv(d["worst10_profit"], area_unit)
    part = []
    part.append(f"about {currency} {amount(dm)} {'more' if dm > 0 else 'less'} per {u} in an average year" if abs(dm) >= 0.5 else "about the same in an average year")
    part.append(f"{currency} {amount(dw)} {'more' if dw > 0 else 'less'} in a bad year" if abs(dw) >= 0.5 else "the same in a bad year")
    s1 = f"Compared with what you grow today, this plan earns {part[0]} and {part[1]}."
    ds = d["soil_score"]
    wv, wu = _water(d["total_water_mm"], area_unit)
    soil = f"scores {amount(ds)} points {'higher' if ds > 0 else 'lower'} for soil health" if abs(ds) >= 0.5 else "scores the same for soil health"
    small = 0.05 if wu == "inches" else 0.5
    water = f"uses {amount(wv, '{:,.1f}' if wu == 'inches' else '{:,.0f}')} {wu} {'more' if wv > 0 else 'less'} water a year" if abs(wv) >= small else "uses about the same water"
    return s1 + f" It {soil} and {water}."


def compare_table(rot: dict, current: dict, currency: str, area_unit: str) -> str:
    u, d = _unit(area_unit), rot["deltas_vs_current"]
    wv, wu = _water(rot["total_water_mm"], area_unit)
    wc, _ = _water(current["total_water_mm"], area_unit)
    wd, _ = _water(d["total_water_mm"], area_unit)
    wf = "{:,.1f}" if wu == "inches" else "{:,.0f}"
    food = lambda r: _conv(r, area_unit) / 1e6
    rows = [
        (f"Average profit ({currency} per {u} a year)", f"{_conv(rot['mean_profit'], area_unit):,.0f}", f"{_conv(current['mean_profit'], area_unit):,.0f}",
         delta_html(_conv(d["mean_profit"], area_unit), "{:,.0f}", "", True)),
        (f"Profit in a bad year ({currency} per {u})", f"{_conv(rot['worst10_profit'], area_unit):,.0f}", f"{_conv(current['worst10_profit'], area_unit):,.0f}",
         delta_html(_conv(d["worst10_profit"], area_unit), "{:,.0f}", "", True)),
        ("Soil Health Score (0 to 100)", f"{rot['soil_score']:.0f}", f"{current['soil_score']:.0f}", delta_html(d["soil_score"], "{:,.0f}", "", True)),
        (f"Water the crops use ({wu} a year)", wf.format(wv), wf.format(wc),
         _water_delta(wd) if wu == "inches" else delta_html(wd, "{:,.0f}", "", False)),
        (f"Food grown (million calories per {u})", f"{food(rot['calories']):,.1f}", f"{food(current['calories']):,.1f}", _small_delta(food(d["calories"]))),
    ]
    head = "<tr><th></th><th>This plan</th><th>Your plan today</th><th>Difference</th></tr>"
    body = "".join(f"<tr><td>{html.escape(a)}</td><td>{b}</td><td>{c}</td><td>{e}</td></tr>" for a, b, c, e in rows)
    return f'<div class="rl-tblwrap"><table class="rl-t">{head}{body}</table></div>'


def _water_delta(inches: float) -> str:
    if abs(inches) < 0.05:
        return '<span class="rl-delta">same</span>'
    return f'<span class="rl-delta {"dn" if inches > 0 else "up"}">{"+" if inches > 0 else "-"}{abs(inches):,.1f}</span>'


def _small_delta(v: float) -> str:
    if abs(v) < 0.05:
        return '<span class="rl-delta">same</span>'
    return f'<span class="rl-delta {"up" if v > 0 else "dn"}">{"+" if v > 0 else "-"}{abs(v):,.1f}</span>'


def pick_card(name: str, rot: dict | None, current: dict, currency: str, area_unit: str, big: bool, example: bool) -> None:
    title, ex = PICK_TITLES[name], (" " + badge("example") if example else "")
    cls = "rl-panel lead" if big else "rl-panel"
    if rot is None:
        md(f'<div class="{cls}"><h4>{title}{ex}</h4><p class="rl-say"><b>No plan fits your profit limit.</b> Every other plan earns less on average than '
           f'what you grow today. Allow a small drop in profit under "Change what matters to you", or look at the two plans below.</p></div>')
        return
    u = _unit(area_unit)
    md(f'<div class="{cls}"><h4>{title}{ex}</h4><p class="rl-bigsub" style="margin-top:-.3rem">{PICK_WHY[name]}</p>{years_html(rot)}'
       f'<div class="rl-big">{money(rot["mean_profit"], currency, area_unit)}</div>'
       f'<p class="rl-bigsub">average profit per {u} each year {badge("estimated")}</p>'
       f'<p class="rl-say">{html.escape(plain_summary(rot, current, currency, area_unit))}</p>'
       + ("" if same_plan(rot, current) else compare_table(rot, current, currency, area_unit)) + "</div>")


def tradeoff_chart(result: dict, currency: str, area_unit: str):
    """Profit against Soil Health Score for every plan; the three picks and the current plan are marked."""
    allr = result["all_results"]
    names = [" > ".join(crop_label(yr[0]) for yr in r["crops"]) for r in allr]
    fig = go.Figure(go.Scatter(
        x=[_conv(r["mean_profit"], area_unit) for r in allr], y=[r["soil_score"] for r in allr], mode="markers", name="Every other plan",
        marker=dict(size=8, color=T["line"], line=dict(width=1, color=T["ash"])), text=names,
        hovertemplate="%{text}<br>Average profit %{x:,.0f}<br>Soil Health Score %{y:.0f}<extra></extra>"))
    marks = [("Your plan today", result["current_plan_result"], "circle", T["ink"])]
    for k, sym, col in (("headline", "star", T["accent"]), ("highest_profit", "diamond", T["jowar"]), ("best_soil", "square", T["pigeonpea"])):
        if result.get(k) is not None:
            marks.append((PICK_TITLES[k], result[k], sym, col))
    for label, r, sym, col in marks:
        fig.add_trace(go.Scatter(x=[_conv(r["mean_profit"], area_unit)], y=[r["soil_score"]], mode="markers", name=label,
                                 marker=dict(symbol=sym, size=17, color=col, line=dict(width=2, color=T["ink"])),
                                 text=[" > ".join(crop_label(yr[0]) for yr in r["crops"])],
                                 hovertemplate=label + "<br>%{text}<br>Average profit %{x:,.0f}<br>Soil Health Score %{y:.0f}<extra></extra>"))
    font = dict(family='"Source Sans 3", system-ui, sans-serif', size=15, color=T["ink"])
    fig.update_layout(height=430, margin=dict(l=10, r=10, t=16, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=font,
                      legend=dict(orientation="h", y=-0.22, x=0, font=dict(size=14)), hoverlabel=dict(font=font, bgcolor=T["surface"]))
    ax = dict(gridcolor=T["line"], zeroline=False, linecolor=T["line"], tickfont=dict(size=13, color=T["ink2"]))
    fig.update_xaxes(title=f"Average profit ({currency} per {_unit(area_unit)} a year)", **ax)
    fig.update_yaxes(title="Soil Health Score", range=[0, 100], **ax)
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
    st.caption("Move a slider and the three plans above update. Left means it matters less to you, right means it matters more.")
    c1, c2 = st.columns(2)
    with c1:
        bad = st.slider("Plan for an average year  or  protect me in bad years", 0, 100, 30, key=f"{key}_bad",
                        help="All the way left picks the highest average profit. All the way right picks the best profit in the worst 1 year in 10.")
        soil = st.slider("How much do you care about soil health?", 0, 100, 50, key=f"{key}_soil",
                         help="All the way left ranks plans by profit only. All the way right ranks them by Soil Health Score.")
    with c2:
        water = st.slider("How much do you care about saving water?", 0, 100, 0, key=f"{key}_water")
        tol = st.slider("How much average profit could you give up? (percent)", 0, 25, 0, key=f"{key}_tol",
                        help="The first plan never earns less on average than what you grow today, minus this much.")
    shift = st.radio("Which weather should the plans be tested against?", list(SHIFT_LABELS), format_func=SHIFT_LABELS.get, horizontal=True, key=f"{key}_shift")
    st.caption("These are what-if settings applied to real past years. They are not forecasts.")
    return {"bad_year": bad / 100.0, "soil": soil / 100.0, "water": water / 100.0, "profit_tolerance_pct": float(tol), "climate_shift": shift}


def render(site, inputs, currency: str = "USD", area_unit: str = "ha", key: str = "rec", simulate=None, scenarios=None,
           crops=None, recommend_fn=None) -> dict | None:
    st.header("Your best crop plans")
    st.caption(DISCLAIMER)
    answer = st.container()                                   # the plans are shown first, the controls sit under them
    with st.expander("Change what matters to you", expanded=False):
        sliders = read_sliders(key)
        most_food = st.toggle("Show the plan that grows the most food instead of the most profit (second card)", value=False, key=f"{key}_food")
    with answer:
        with st.spinner("Testing every crop plan against past weather. This can take a moment."):
            if recommend_fn is not None:
                result = recommend_fn(sliders, most_food)
            else:
                bundle = _scored_bundle(_site_key(site, inputs, cache_extra(crops, simulate, scenarios)), site, inputs, crops, simulate, scenarios)
                result = opt.assemble_recommendation(bundle, sliders, most_food, explain_text=False)
        if "input_needed" in result:
            need = "; ".join(f"your {n['field']} for {crop_label(n['crop'])}" for n in result["input_needed"])
            st.warning(f"Input needed. Enter {need} before money numbers can be shown. Nothing is filled in for you.")
            return result
        if "current_plan_problem" in result:
            st.warning(f"Your current plan could not be simulated here: {result['current_plan_problem']}. Check the crops and the site, then try again.")
            return result
        ex, cur, head = bool(result.get("example")), result["current_plan_result"], result["headline"]
        if ex:
            st.warning("EXAMPLE DATA. The crop simulation is not connected yet, so these results come from a stand-in. Do not use them for decisions.")
        if head is not None and same_plan(head, cur):
            st.info("What you grow today is already the best match for your priorities. No other plan keeps your average profit and scores higher.")
        pick_card("headline", head, cur, currency, area_unit, True, ex)
        a, b = st.columns(2)
        with a:
            pick_card("highest_profit", result["highest_profit"], cur, currency, area_unit, False, ex)
        with b:
            pick_card("best_soil", result["best_soil"], cur, currency, area_unit, False, ex)
        if result.get("excluded_crops"):
            st.caption("Left out until you enter them: " + ", ".join(f"{crop_label(x['crop'])} (needs your {x['field']})" for x in result["excluded_crops"]) + ".")
        if result.get("cover_crop_note"):
            st.caption("Cover crops are not offered until you enter what the seed and planting cost you.")
    st.subheader("Every plan we tested")
    st.caption("Each dot is one four-year plan. Further right earns more. Higher up is better for your soil. "
               "The marked dots are the three plans above and what you grow today.")
    st.plotly_chart(tradeoff_chart(result, currency, area_unit), width="stretch", key=f"{key}_chart", config={"displayModeBar": False})
    st.markdown(badge("assumption"), unsafe_allow_html=True)
    st.caption(f"{SOIL_LABEL} Profit uses the prices and costs you entered or official figures, held the same every year. "
               "A bad year means the average of the worst 1 in 10 weather sequences.")
    return result
