import html

import streamlit as st

from engine import explain
from ui import charts, data
from ui.data import plan_label
from ui.tabs import _farm
from ui.components import delta_html, srcline, badge, fmt_rs, md, ribbon, section, stat, stats, tab_head


def explain_inputs(rec, tp, p):
    t, r = rec["top"], rec["runner_up"]
    d = dict(top_rotation=plan_label(t["plan"]), runner_up=plan_label(r["plan"]), top_mean_profit=round(t["mean_profit"]),
             top_worst10_profit=round(t["worst10_profit"]), top_water_stress_mm=round(t["water_stress_mm"]),
             runner_up_mean_profit=round(r["mean_profit"]), runner_up_worst10_profit=round(r["worst10_profit"]),
             bad_year_weight=p["lam"], water_stress_weight=p["w"], irrigation_input_mm=p["irrigation_mm"])
    if tp:
        co = tp["rainfall_crossover"].get("crossovers") or []
        d["rain_crossover"] = co[0]["rain_mult"] if co else None
        thr = tp["grid"]["rice_shift_threshold_mm"]; rm = tp["grid"]["rain_mult"]
        d["irrigation_shift_mm"] = thr[min(range(len(rm)), key=lambda i: abs(rm[i] - 1.0))]
        d["evpi_irrigation_rs"] = round(tp["evpi_irrigation"]["value"])
        d["evpi_soil_rs"] = round(tp["evpi_awc"]["value"])
    return {k: v for k, v in d.items() if v is not None}


def render():
    tab_head("My Priorities", "Say what matters to you. The recommendation moves with the sliders.")
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.slider("What matters more to you?", 0, 100, value=data.V()["lam"], format="%d", **data.bind("lam"),
                  help="Left: maximise the average result. Right: care most about the worst seasons.")
        md('<div style="display:flex;justify-content:space-between;font-size:.86rem;color:var(--ink2);margin-top:-.6rem"><span>Plan for an average year</span><span>Protect me in bad years</span></div>')
    with c2:
        st.slider("How much do you care about water stress?", 0, 100, value=data.V()["w"], format="%d", **data.bind("w"))
        md('<div style="display:flex;justify-content:space-between;font-size:.86rem;color:var(--ink2);margin-top:-.6rem"><span>Not much</span><span>A lot</span></div>')

    p = data.params()
    with st.spinner(data.MSG["recommend"]):
        rec = data.recommend(p)
    mdf = rec["metrics"]
    base = mdf[mdf.id == "rice-rice-rice-rice"].iloc[0]
    t = rec["top"]
    b = "placeholder" if data.is_mock() else "modeled"
    ex = explain.explain(explain_inputs(rec, None, p))
    src = "Written by Claude from the numbers above." if ex["source"] == "model" else "Written from a fixed template using the numbers above."
    md(f'<div class="rl-hero"><p style="margin:0;font-size:.9rem;opacity:.85">Recommended for these priorities {badge(b)}</p>'
       f'<h4>{html.escape(plan_label(t["plan"]))}</h4>{ribbon(t["plan"])}<p style="margin:.7rem 0 .3rem">{html.escape(ex["text"])}</p>'
       f'<p style="margin:0;font-size:.82rem;opacity:.8">{src} Modeled estimate, for planning only.</p></div>')
    stats([
        stat("Average over 4 years", fmt_rs(t["mean_profit"]), "per acre", b, delta_html(t["mean_profit"] - base.mean_profit, "Rs {:,.0f}") + " per acre against our farm today. " + _farm.per_farm_note(t["mean_profit"])),
        stat("Worst 10% of seasons", fmt_rs(t["worst10_profit"]), "per acre", b, delta_html(t["worst10_profit"] - base.worst10_profit, "Rs {:,.0f}") + " per acre against our farm today. " + _farm.per_farm_note(t["worst10_profit"])),
        stat("Water shortfall", f'{t["water_stress_mm"]:,.0f}', "mm", b, delta_html(t["water_stress_mm"] - base.water_stress_mm, "{:,.0f} mm", good_when_up=False) + " against our farm today"),
    ])

    section("Every possible rotation, plotted", b,
            "Each dot is one of the 256 ways to fill four years. Higher and further right is better. Darker blue means more water stress.")
    charts.show(charts.pareto(rec["metrics"], t["id"]), "pareto")
    _farm.land_split_panel(t["id"], data.plan_label(t["plan"]), "pri", p)
    srcline(f"Model output for all {len(mdf)} rotations over {rec['n_scenarios']:,} resampled weather sequences.", "Source")
    md('<p class="rl-note">The white circle is our farm today. The diamond is the recommended rotation. The dotted line joins the rotations where you cannot raise the average without lowering the bad-year result.</p>')
