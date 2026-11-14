import html

import streamlit as st

from ui import charts, data
from ui.components import badge, fmt_rs, legend, md, section, stat, stats, tab_head
from ui.data import humanize


def render():
    p = data.params()
    tp = data.tipping(p)
    g, xo = tp["grid"], tp["rainfall_crossover"]
    b = "placeholder" if data.is_mock() else "modeled"
    tab_head("Tipping Points", "At what water level should land move from rice to millets? This is where the answer changes.")

    colors = charts.plan_colors(tp)
    rm, thr = g["rain_mult"], g["rice_shift_threshold_mm"]
    j1 = min(range(len(rm)), key=lambda i: abs(rm[i] - 1.0))
    top_irr = max(g["irrigation_mm"])
    co = xo.get("crossovers") or []
    stats([
        stat("Water level where rice-majority plans start to win, usual rain",
             f"{thr[j1]:,.0f}" if thr[j1] is not None else "None", "mm" if thr[j1] is not None else f"up to {top_irr:,.0f} mm", b),
        stat("Irrigation water you entered", f'{p["irrigation_mm"]:,.0f}', "mm", "local"),
        stat("Rainfall where the best rotation switches", f'{co[0]["rain_mult"]:.2f}' if co else "None", "times usual" if co else f"in {rm[0]:.2f} to {rm[-1]:.2f} times usual", b),
    ])
    md(f'<div class="rl-callout"><p>{html.escape(humanize(g["text"]))}</p></div>')
    section("Which rotation wins, for each rainfall and water supply", b,
            "Each square is a different season. Read across for rainfall, up for irrigation water. The dashed line is where rice-majority plans start to win. The white circle is your farm in a usual year.")
    fig, items = charts.tipping_grid(g, p["irrigation_mm"], colors)
    legend(items)
    charts.show(fig, "grid")

    section("Where rainfall alone tips the choice", b, "Mean profit of the rotations involved in the switch. The shaded band is the 10th to 90th percentile of where the switch lands when the weather record is resampled.")
    md(f'<div class="rl-callout"><p>{html.escape(humanize(xo["text"]))}</p></div>')
    fig, items = charts.crossover(xo, colors)
    legend(items)
    charts.show(fig, "cross")

    section("If the early monsoon rain arrives late", b)
    md(f'<p style="max-width:75ch">{html.escape(humanize(tp["late_monsoon"]["text"]))}</p>')
    fig, items = charts.late_monsoon(tp["late_monsoon"], colors)
    legend(items)
    charts.show(fig, "late")

    section("Is it worth measuring before you decide?", b, "How much a better decision is worth if one unknown is pinned down first. It is an upper limit on what any real test could add.")
    c1, c2 = st.columns(2, gap="large")
    for col, key, q in ((c1, "evpi_irrigation", "Is it worth measuring your borewell or tank capacity before deciding?"),
                        (c2, "evpi_awc", "Is it worth testing your soil's water holding capacity before deciding?")):
        e = tp[key]
        verdict = ("Above the test cost, so measuring could pay." if e.get("worth_measuring") else "Not above the test cost, so measuring is unlikely to pay.")
        with col:
            md(f'<div class="rl-panel"><div class="rl-q">{q}</div><div class="rl-evpi">{fmt_rs(e["value"])}<span style="font-size:.95rem;font-family:var(--sans);color:var(--ink2)"> per acre, 4 years</span></div>'
               f'<p style="margin:.5rem 0 .3rem"><strong>Test cost {fmt_rs(e["test_cost"])} per acre</strong> {badge(e.get("test_cost_badge", "placeholder"))}</p>'
               f'<p style="margin:0 0 .4rem">{verdict}</p>'
               f'<details><summary style="cursor:pointer;font-weight:600">Full model note</summary><p style="margin-top:.4rem">{html.escape(humanize(e["text"]))} {badge(e.get("badge", b))}</p></details></div>')
