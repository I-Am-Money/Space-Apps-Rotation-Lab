import html
import json

import pandas as pd

import streamlit as st

from ui import charts, data
from ui.components import srcline, badge, fmt_rs, legend, md, section, stat, stats, tab_head
from ui.data import humanize


def render():
    st.checkbox("Use all 500 weather sequences for tipping points (slower)", value=data.V()["full_tipping"], **data.bind("full_tipping"))
    st.caption("Interactive mode uses 150 seeded weather sequences and 200 bootstrap resamples. Recommendations always use 500. Enable the full run for a final review.")
    p = data.params()
    with st.spinner(data.MSG["tipping_points"]):
        tp = data.tipping(p)
    p = tp.get("params", p)
    if p.get("irrigation_mm") is None:  # placeholder engine has no normalized params
        p = dict(p, irrigation_mm=data.BASE_IRR)
    g, xo = tp["grid"], tp["rainfall_crossover"]
    st.download_button("Download this tipping analysis (JSON)", json.dumps(tp, default=str, allow_nan=False).encode(),
                       "rotationlab-tipping-analysis.json", "application/json")
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
        stat("Base irrigation supply", f'{p["irrigation_mm"]:,.0f}', "mm", tp.get("badges", {}).get("irrigation_mm", "assumption")),
        stat("Rainfall where the best rotation switches", f'{co[0]["rain_mult"]:.2f}' if co else "None", "times usual" if co else f"in {rm[0]:.2f} to {rm[-1]:.2f} times usual", b),
    ])
    winners = {w for row in g["winner"] for w in row}
    single = len(winners) == 1
    if single:
        only = data.plan_label(next(iter(winners)))
        md(f'<div class="rl-callout"><p><strong>No shift point at these inputs.</strong> {html.escape(only)} wins every square, so there is no boundary to draw. {html.escape(humanize(g["text"]))} Try another water source, a different amount of water, or the rainfall crossover below.</p></div>')
    else:
        md(f'<div class="rl-callout"><p>{html.escape(humanize(g["text"]))}</p></div>')
    section("Which rotation wins, for each rainfall and water supply", b,
            ("One colour fills the grid because one rotation is best everywhere tested. " if single else "") + "Each square is a different season. Read across for rainfall, up for irrigation water. " + ("" if single else "The dashed line is where rice-majority plans start to win. ") + "The white circle is our farm today in a usual year.")
    fig, items = charts.tipping_grid(g, p["irrigation_mm"], colors)
    legend(items)
    charts.show(fig, "grid")
    with st.expander("Read the decision map as a table"):
        table = pd.DataFrame([[data.plan_label(plan) for plan in row] for row in g["winner"]],
            index=[f"{water:,.0f} mm" for water in g["irrigation_mm"]], columns=[f"{rain:.2f}x rain" for rain in g["rain_mult"]])
        st.dataframe(table, width="stretch")
    srcline(f"Model output over {tp['n_scenarios']:,} resampled weather sequences. {html.escape(humanize(tp.get('frame', '')))}", "Source")

    gu = tp.get("grid_upstream_local")
    if gu and gu.get("available", False):
        w2 = {w for row in gu["winner"] for w in row}
        single2 = len(w2) == 1
        section("Which rotation wins when canal rain and local rain differ", b,
                ("One colour fills the grid because one rotation is best everywhere tested. " if single2 else "")
                + "Across is the monsoon rain upstream of Nagarjuna Sagar, which feeds the canal proxy. Up is local rain on the farm, which feeds the well proxy and the crop. 1.0 means a usual year.")
        if single2:
            md(f'<div class="rl-callout"><p><strong>No boundary at these inputs.</strong> {html.escape(data.plan_label(next(iter(w2))))} wins every square, so upstream and local rain do not change the choice here. {html.escape(humanize(gu.get("text", "")))}</p></div>')
        elif gu.get("text"):
            md(f'<div class="rl-callout"><p>{html.escape(humanize(gu["text"]))}</p></div>')
        fig2, items2 = charts.tipping_grid(dict(gu, winner=gu["winner"]), None, colors, xkey="upstream_mult", ykey="local_mult",
                                           xt="Upstream rainfall compared with usual (1.0 = usual)", yt="Local rainfall compared with usual (1.0 = usual)", farm=(1.0, 1.0),
                                           hov="Upstream rain %{x:.2f} times usual<br>Local rain %{y:.2f} times usual<br>Best: %{text}<extra></extra>")
        legend(items2)
        charts.show(fig2, "grid2")
        srcline("Model output. Upstream rain is the NASA POWER season rainfall averaged over points upstream of Nagarjuna Sagar; actual canal releases depend on reservoir operations.", "Source")

    section("Where rainfall alone tips the choice", b, "Priority score balances average profit, bad-year profit and saving irrigation. The band is the 10th to 90th percentile of the switch across 200 resamples.")
    md(f'<div class="rl-callout"><p>{html.escape(humanize(xo["text"]))}</p></div>')
    fig, items = charts.crossover(xo, colors)
    legend(items)
    charts.show(fig, "cross")
    srcline("Model output. The shaded band comes from resampling the weather record.", "Source")

    section("If the early monsoon rain arrives late", b)
    md(f'<p style="max-width:75ch">{html.escape(humanize(tp["late_monsoon"]["text"]))}</p>')
    fig, items = charts.late_monsoon(tp["late_monsoon"], colors)
    legend(items)
    charts.show(fig, "late")
    srcline("Model output. Early rain moves later with its total conserved, and planting follows the delayed onset. A crop that cannot mature within the modeled year has no harvest.", "Source")

    section("Is it worth measuring before you decide?", b, "How much a better decision is worth if one unknown is pinned down first. It is an upper limit on what any real test could add.")
    c1, c2 = st.columns(2, gap="large")
    for col, key, q in ((c1, "evpi_irrigation", "Is it worth measuring your borewell or tank capacity before deciding?"),
                        (c2, "evpi_awc", "Is it worth testing your soil's water holding capacity before deciding?")):
        e = tp[key]
        verdict = ("Enter a real measurement quote to compare it with this upper bound." if e.get("test_cost") is None else "Above the test cost, so measuring could pay." if e.get("worth_measuring") else "Not above the test cost, so measuring is unlikely to pay.")
        with col:
            md(f'<div class="rl-panel"><div class="rl-q">{q}</div><div class="rl-evpi">{fmt_rs(e["value"])}<span style="font-size:.95rem;font-family:var(--sans);color:var(--ink2)"> per acre, 4 years</span></div>'
               f'<p style="margin:.5rem 0 .3rem"><strong>Test cost {fmt_rs(e["test_cost"])} per acre</strong> {badge(e.get("test_cost_badge", "placeholder"))}</p>'
               f'<p style="margin:0 0 .4rem">{verdict}</p>'
               f'<details><summary style="cursor:pointer;font-weight:600">Full model note</summary><p style="margin-top:.4rem">{html.escape(humanize(e["text"]))} {badge(e.get("badge", b))}</p></details></div>')
