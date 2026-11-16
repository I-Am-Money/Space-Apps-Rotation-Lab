# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Best crop plans page (Build Spec v4 R13 to R16). Owner: Feature 3.

The answer comes first: three bordered plan cards (the headline is full width), each with the four years, st.metric cards
with the difference from today's plan, one plain sentence and a comparison table. The priority sliders sit in the side
panel and the chart of every plan has its own tab. Built-in Streamlit components only; data labels use badge() from
ui/components.py (through badge_md).
Every number comes from engine/optimize.py. Nothing here is computed except display formatting and unit conversion.

    render(site, inputs, currency="USD", area_unit="ha", key="rec", simulate=None, scenarios=None, crops=None,
           recommend_fn=None)

`recommend_fn(sliders_dict, most_food) -> result` lets the app shell plug in engine.api. The slow step is cached;
moving a control only re-runs the fast pick selection.
"""
from __future__ import annotations

import hashlib
import json
import os

import plotly.graph_objects as go
import streamlit as st

from engine import economics, optimize as opt
from ui.components import badge_md
from ui.theme import crop_name

DISCLAIMER = "Modeled estimates for planning. Not a guarantee of yield or profit."
SOIL_LABEL = "Rule-based score from NRCS soil health principles. Not a soil test."
SHIFT_LABELS = {"historical": "The weather as it has been", "recent": "The last 20 years count double", "trend": "The recent trend continues"}
PICK_TITLES = {"headline": "Best for soil and climate", "highest_profit": "Highest profit", "best_soil": "Best for your soil"}
PICK_WHY = {"headline": "The best balance of soil health, bad-year protection and profit, without earning less than you do today.",
            "highest_profit": "The plan that earns the most for the priorities you set.",
            "best_soil": "The plan with the highest Soil Health Score."}
MM_PER_INCH = 25.4


def show_badge(kind: str) -> None:
    """Display a data label: the shared badge() wording, drawn as a built-in Streamlit badge."""
    st.markdown("Data label: " + badge_md(kind))


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


def same_plan(a: dict | None, b: dict | None) -> bool:
    return a is not None and b is not None and a["crops"] == b["crops"] and a["cover_crops"] == b["cover_crops"]


def plan_words(rot: dict) -> str:
    """'Corn every year', or 'Corn, then soybeans, then corn, then soybeans'."""
    names = [" + ".join(crop_label(c) for c in yr) + (" with a cover crop" if cov else "") for yr, cov in zip(rot["crops"], rot["cover_crops"])]
    if len(set(names)) == 1:
        return f"{names[0]} every year"
    return ", then ".join([names[0]] + [n.lower() for n in names[1:]])


def years_table(rot: dict) -> str:
    """The four years as a small markdown table: Year 1 to Year 4 across, the crop under each."""
    names = [" then ".join(crop_label(c) for c in yr) + (" + cover crop" if rot["cover_crops"][i] else "") for i, yr in enumerate(rot["crops"])]
    head = "| " + " | ".join(f"Year {i + 1}" for i in range(len(names))) + " |"
    return "\n".join([head, "|" + " --- |" * len(names), "| " + " | ".join(f"**{n}**" for n in names) + " |"])


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


def _signed(v: float, fmt: str = "{:,.0f}", small: float = 0.5) -> str | None:
    """A difference from today's plan as '+12' or '-3'. None when it rounds to no difference."""
    if abs(v) < small:
        return None
    return ("+" if v > 0 else "-") + fmt.format(abs(v))


def plan_numbers(rot: dict, current: dict, currency: str, area_unit: str) -> list[dict]:
    """The five measures of a plan beside today's plan, in the farmer's units. Display formatting only.
    `good_up` says whether a higher number is the better one (water use is the exception)."""
    u, d = _unit(area_unit), rot["deltas_vs_current"]
    wv, wu = _water(rot["total_water_mm"], area_unit)
    wc, _ = _water(current["total_water_mm"], area_unit)
    wd, _ = _water(d["total_water_mm"], area_unit)
    wf = "{:,.1f}" if wu == "inches" else "{:,.0f}"
    food = lambda r: _conv(r, area_unit) / 1e6
    return [
        dict(name="profit", label=f"Average profit ({currency} per {u} a year)", short="Average profit",
             plan=f"{_conv(rot['mean_profit'], area_unit):,.0f}", today=f"{_conv(current['mean_profit'], area_unit):,.0f}",
             diff=_signed(_conv(d["mean_profit"], area_unit)), good_up=True, value=money(rot["mean_profit"], currency, area_unit)),
        dict(name="bad_year", label=f"Profit in a bad year ({currency} per {u})", short="Profit in a bad year",
             plan=f"{_conv(rot['worst10_profit'], area_unit):,.0f}", today=f"{_conv(current['worst10_profit'], area_unit):,.0f}",
             diff=_signed(_conv(d["worst10_profit"], area_unit)), good_up=True, value=money(rot["worst10_profit"], currency, area_unit)),
        dict(name="soil", label="Soil Health Score (0 to 100)", short="Soil Health Score", plan=f"{rot['soil_score']:.0f}",
             today=f"{current['soil_score']:.0f}", diff=_signed(d["soil_score"]), good_up=True, value=f"{rot['soil_score']:.0f}"),
        dict(name="water", label=f"Water the crops use ({wu} a year)", short="Water the crops use", plan=wf.format(wv),
             today=wf.format(wc), diff=_signed(wd, wf, 0.05 if wu == "inches" else 0.5), good_up=False, value=wf.format(wv)),
        dict(name="food", label=f"Food grown (million calories per {u})", short="Food grown",
             plan=f"{food(rot['calories']):,.1f}", today=f"{food(current['calories']):,.1f}",
             diff=_signed(food(d["calories"]), "{:,.1f}", 0.05), good_up=True, value=f"{food(rot['calories']):,.1f}"),
    ]


def compare_table(rot: dict, current: dict, currency: str, area_unit: str) -> str:
    """This plan beside today's plan as a markdown table. The sign is written out, so color is never the only cue."""
    rows = ["| | This plan | Your plan today | Difference |", "| --- | ---: | ---: | ---: |"]
    rows += [f"| {n['label']} | {n['plan']} | {n['today']} | {n['diff'] or 'same'} |" for n in plan_numbers(rot, current, currency, area_unit)]
    return "\n".join(rows)


def metric_cards(numbers: list[dict], names: tuple, per_row: int) -> None:
    """st.metric cards for the chosen measures, each with its difference from today's plan as the delta."""
    chosen = [n for n in numbers if n["name"] in names]
    for start in range(0, len(chosen), per_row):
        for col, n in zip(st.columns(per_row), chosen[start:start + per_row]):
            if n["diff"] is None:
                col.metric(n["short"], n["value"], "same as today", delta_color="off", delta_arrow="off", border=True)
            else:
                col.metric(n["short"], n["value"], n["diff"] + " vs today", delta_color="normal" if n["good_up"] else "inverse", border=True)


def summary_row(result: dict, current: dict, currency: str, area_unit: str) -> None:
    """The three recommendations side by side, one st.metric each: average profit, with the difference from today."""
    for col, name in zip(st.columns(3), PICK_TITLES):
        rot = result.get(name)
        if rot is None:
            col.metric(PICK_TITLES[name], "No plan fits", "see below", delta_color="off", delta_arrow="off", border=True)
            continue
        diff = _signed(_conv(rot["deltas_vs_current"]["mean_profit"], area_unit))
        if same_plan(rot, current) or diff is None:
            col.metric(PICK_TITLES[name], money(rot["mean_profit"], currency, area_unit), "same as today", delta_color="off", delta_arrow="off", border=True)
        else:
            col.metric(PICK_TITLES[name], money(rot["mean_profit"], currency, area_unit), diff + " vs today", border=True)
    st.caption(f"Average profit in {currency} per {_unit(area_unit)} each year. The small figure is the difference from what you grow today. "
               "Data label: " + badge_md("estimated"))


def pick_card(name: str, rot: dict | None, current: dict, currency: str, area_unit: str, big: bool, example: bool,
              same_as: str | None = None) -> None:
    """One recommended plan in a bordered card: its four years, five metric cards against today's plan, one plain
    sentence and the full comparison (open on the headline card, folded on the others)."""
    with st.container(border=True):
        st.subheader(PICK_TITLES[name])
        if example:
            st.markdown(badge_md("example"))
        if rot is None:
            st.info('**No plan fits your profit limit.** Every other plan earns less on average than what you grow today. Allow a small '
                    'drop in profit under "What matters to you" in the side panel, or look at the two plans below.')
            return
        st.caption(PICK_WHY[name])
        st.markdown(years_table(rot))
        if same_as is not None:                      # one plan won two categories: say so once instead of repeating the card
            st.write(f'This is the same plan as "{PICK_TITLES[same_as]}". It wins this category too.')
            return
        numbers = plan_numbers(rot, current, currency, area_unit)
        u, wu = _unit(area_unit), _water(0.0, area_unit)[1]
        units = f"Profit in {currency} per {u} each year. Soil Health Score out of 100."
        metric_cards(numbers, ("profit", "bad_year", "soil", "water", "food"), 5)
        units += f" Water in {wu} a year. Food in million calories per {u}."
        if not same_plan(rot, current):
            units += " The small figure under each number is the difference from what you grow today."
        st.caption(units + " Data label: " + badge_md("estimated"))
        st.write(plain_summary(rot, current, currency, area_unit))
        if not same_plan(rot, current):
            with st.expander("All the numbers beside your plan today", expanded=big):
                st.markdown(compare_table(rot, current, currency, area_unit))


def tradeoff_chart(result: dict, currency: str, area_unit: str):
    """Profit against Soil Health Score for every plan; the three picks and the current plan are marked by shape.
    Colors are left to the Streamlit chart theme."""
    allr = result["all_results"]
    names = [" > ".join(crop_label(yr[0]) for yr in r["crops"]) for r in allr]
    fig = go.Figure(go.Scatter(
        x=[_conv(r["mean_profit"], area_unit) for r in allr], y=[r["soil_score"] for r in allr], mode="markers", name="Every other plan",
        marker=dict(size=8, opacity=0.45), text=names,
        hovertemplate="%{text}<br>Average profit %{x:,.0f}<br>Soil Health Score %{y:.0f}<extra></extra>"))
    marks = [("Your plan today", result["current_plan_result"], "circle")]
    # the star is drawn last and smaller than the square, so it stays visible when one plan wins two categories
    for k, sym in (("best_soil", "square"), ("highest_profit", "diamond"), ("headline", "star")):
        if result.get(k) is not None:
            marks.append((PICK_TITLES[k], result[k], sym))
    for label, r, sym in marks:
        fig.add_trace(go.Scatter(x=[_conv(r["mean_profit"], area_unit)], y=[r["soil_score"]], mode="markers", name=label,
                                 marker=dict(symbol=sym, size=24 if sym == "square" else 17, line=dict(width=2)),
                                 text=[" > ".join(crop_label(yr[0]) for yr in r["crops"])],
                                 hovertemplate=label + "<br>%{text}<br>Average profit %{x:,.0f}<br>Soil Health Score %{y:.0f}<extra></extra>"))
    fig.update_layout(height=460, margin=dict(l=10, r=10, t=16, b=10), legend=dict(orientation="h", y=-0.22, x=0))
    fig.update_xaxes(title=f"Average profit ({currency} per {_unit(area_unit)} a year)", zeroline=False)
    fig.update_yaxes(title="Soil Health Score (0 to 100)", range=[0, 100], zeroline=False)
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
    st.caption("Move a slider and the plans update. Left means it matters less to you, right means it matters more.")
    bad = st.slider("Plan for an average year  or  protect me in bad years", 0, 100, 30, key=f"{key}_bad",
                    help="All the way left picks the highest average profit. All the way right picks the best profit in the worst 1 year in 10.")
    soil = st.slider("How much do you care about soil health?", 0, 100, 50, key=f"{key}_soil",
                     help="All the way left ranks plans by profit only. All the way right ranks them by Soil Health Score.")
    water = st.slider("How much do you care about saving water?", 0, 100, 0, key=f"{key}_water")
    tol = st.slider("How much average profit could you give up? (percent)", 0, 25, 0, key=f"{key}_tol",
                    help="The first plan never earns less on average than what you grow today, minus this much.")
    shift = st.radio("Which weather should the plans be tested against?", list(SHIFT_LABELS), format_func=SHIFT_LABELS.get, key=f"{key}_shift")
    st.caption("These are what-if settings applied to real past years. They are not forecasts.")
    return {"bad_year": bad / 100.0, "soil": soil / 100.0, "water": water / 100.0, "profit_tolerance_pct": float(tol), "climate_shift": shift}


def _extras(extra_tabs: dict | None, tabs=None) -> None:
    for i, draw in enumerate((extra_tabs or {}).values()):
        if tabs is None:
            draw()
        else:
            with tabs[i]:
                draw()


def render(site, inputs, currency: str = "USD", area_unit: str = "ha", key: str = "rec", simulate=None, scenarios=None,
           crops=None, recommend_fn=None, controls=None, extra_tabs: dict | None = None) -> dict | None:
    """`controls` is where the sliders are drawn (the side panel by default). `extra_tabs` maps a tab title to a
    function that draws it, so the app shell can add its own tab beside the plans and the chart."""
    st.header("Your best crop plans")
    st.caption(DISCLAIMER)
    st.caption("Year 1 is your next growing season, then Years 2, 3 and 4 follow it. Each plan was tested against hundreds of real past "
               "four-year stretches of weather (1981 to 2025), so no forecast is involved.")
    with (controls if controls is not None else st.sidebar):
        st.subheader("What matters to you")
        sliders = read_sliders(key)
        most_food = st.toggle("Show the plan that grows the most food instead of the most profit (second card)", value=False, key=f"{key}_food")
    with st.spinner("Testing every crop plan against past weather. This can take a moment."):
        if recommend_fn is not None:
            result = recommend_fn(sliders, most_food)
        else:
            bundle = _scored_bundle(_site_key(site, inputs, cache_extra(crops, simulate, scenarios)), site, inputs, crops, simulate, scenarios)
            result = opt.assemble_recommendation(bundle, sliders, most_food, explain_text=False)
    if "input_needed" in result:
        need = "; ".join(f"your {n['field']} for {crop_label(n['crop'])}" for n in result["input_needed"])
        st.warning(f"Input needed. Enter {need} before money numbers can be shown. Nothing is filled in for you.")
        _extras(extra_tabs)
        return result
    if "current_plan_problem" in result:
        st.warning(f"Your current plan could not be simulated here: {result['current_plan_problem']}. Check the crops and the site, then try again.")
        _extras(extra_tabs)
        return result
    ex, cur, head = bool(result.get("example")), result["current_plan_result"], result["headline"]
    if ex:
        st.warning("EXAMPLE DATA. The crop simulation is not connected yet, so these results come from a stand-in. Do not use them for decisions.")
    tabs = st.tabs(["Best plans", "Every plan we tested", *(extra_tabs or {})])
    with tabs[0]:
        if head is not None and same_plan(head, cur):
            st.info("What you grow today is already the best match for your priorities. No other plan keeps your average profit and scores higher.")
        with st.container(border=True):
            st.subheader("What you grow today")
            st.write(f"{plan_words(cur)}. It earns {money(cur['mean_profit'], currency, area_unit)} per {_unit(area_unit)} a year "
                     f"on average and {money(cur['worst10_profit'], currency, area_unit)} in a bad year, with a Soil Health Score of {cur['soil_score']:.0f} out of 100. "
                     "Each plan below is compared with this.")
        summary_row(result, cur, currency, area_unit)
        pick_card("headline", head, cur, currency, area_unit, True, ex)
        shown = [("headline", head)]
        for name in ("highest_profit", "best_soil"):
            pick = result[name]
            twin = next((other for other, r in shown if same_plan(pick, r)), None)
            pick_card(name, pick, cur, currency, area_unit, False, ex, same_as=twin)
            shown.append((name, pick))
        if result.get("excluded_crops"):
            st.caption("Left out until you enter them: " + ", ".join(f"{crop_label(x['crop'])} (needs your {x['field']})" for x in result["excluded_crops"]) + ".")
        if result.get("cover_crop_note"):
            st.caption("Cover crops are not offered until you enter what the seed and planting cost you.")
        if os.environ.get("ANTHROPIC_API_KEY") and result.get("headline") is not None and st.button("Explain the best plan in my own words", key=f"{key}_ai"):
            from engine import explain as ex_mod
            st.info(ex_mod.explain_pick(result["headline"], result["current_plan_result"], pick="headline", use_api=True))
    with tabs[1]:
        with st.container(border=True):
            st.subheader("Every plan we tested")
            st.caption("Each dot is one four-year plan. Further right earns more. Higher up is better for your soil. "
                       "The marked shapes are the three plans and what you grow today.")
            st.plotly_chart(tradeoff_chart(result, currency, area_unit), width="stretch", key=f"{key}_chart", config={"displayModeBar": False})
            st.caption("Data label: " + badge_md("assumption"))
            st.caption(f"{SOIL_LABEL} Profit uses the prices and costs you entered or official figures, held the same every year. "
                       "A bad year means the average of the worst 1 in 10 weather sequences.")
    _extras(extra_tabs, tabs[2:])
    return result
