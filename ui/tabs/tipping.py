# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Tab 4, Tipping Points (Build Spec v3 sections 8 and 9): the rainfall x irrigation map with the farm's dot,
the 1D crossover chart, the onset chart, the optional heat chart and the EVPI cards."""
import html

import streamlit as st

from ui import charts, data
from ui.components import srcline, badge, fmt_rs, legend, md, section, stat, stats, tab_head
from ui.data import humanize


def _evpi_card(e, question, what, b):
    """One 'is measuring worth it' card. With no sourced price for the test the card says so (yellow badge)
    instead of comparing against a made-up cost."""
    lead = e.get("text", "").split(": worth up to")[0].split(". Expected value")[0]
    if e.get("worth_measuring") is None:
        cost = (f'<p style="margin:.5rem 0 .3rem"><strong>Cost of {what}: no sourced price yet</strong> {badge("placeholder")}</p>'
                f'<p style="margin:0 0 .4rem">Get a local quote. If it is below {fmt_rs(e["value"])} per acre, measuring could pay; if it is above, it cannot.</p>')
    else:
        verdict = ("Above the cost, so measuring could pay." if e.get("worth_measuring") else "Not above the cost, so measuring is unlikely to pay.")
        cost = (f'<p style="margin:.5rem 0 .3rem"><strong>Cost of {what}: {fmt_rs(e["test_cost"])} per acre</strong> {badge(e.get("test_cost_badge", "placeholder"))}</p>'
                f'<p style="margin:0 0 .4rem">{verdict}</p>')
    md(f'<div class="rl-panel"><div class="rl-q">{question}</div>'
       f'<div class="rl-evpi">{fmt_rs(e["value"])}<span style="font-size:.95rem;font-family:var(--sans);color:var(--ink2)"> per acre over 4 years, at most</span></div>'
       f'<p style="margin:.5rem 0 .2rem">{html.escape(humanize(lead))}.</p>{cost}'
       f'<details><summary style="cursor:pointer;font-weight:600">Full model note</summary><p style="margin-top:.4rem">{html.escape(humanize(e.get("text", "")))} '
       f'{html.escape(e.get("range_note", ""))} {badge(e.get("badge", b))}</p></details></div>')


def render():
    p = data.params()
    with st.spinner(data.MSG["tipping_points"]):
        tp = data.tipping(p)
    g, xo = tp["grid"], tp["rainfall_crossover"]
    b = "placeholder" if data.is_mock() else "modeled"
    tab_head("Tipping Points", "At what water level should land move out of rice? This tab shows where the answer changes, and how sure the model is about that line.")

    colors = charts.plan_colors(tp)
    rm, thr = g["rain_mult"], g["rice_shift_threshold_mm"]
    j1 = min(range(len(rm)), key=lambda i: abs(rm[i] - 1.0))
    top_irr = max(g["irrigation_mm"])
    irr_now = g.get("current_irrigation_mm", p["irrigation_mm"])
    co = xo.get("crossovers") or []
    band = g.get("boundary_band") or {}
    lo, hi = (band.get("p10") or [None] * len(rm))[j1], (band.get("p90") or [None] * len(rm))[j1]
    note = f"10th to 90th percentile {lo:,.0f} to {hi:,.0f} mm" if lo is not None and hi is not None else ""
    stats([
        stat("Irrigation supply where plans with two or more rice years start to win, usual rain",
             f"{thr[j1]:,.0f}" if thr[j1] is not None else "None", "mm a season" if thr[j1] is not None else f"up to {top_irr:,.0f} mm", b, note),
        stat("Irrigation supply the model assumes for our farm", f"{irr_now:,.0f}", "mm a season", tp.get("badges", {}).get("irrigation", "assumption"),
             "Change it on the Our Farm tab"),
        stat("Rainfall where the number of rice years changes", f'{co[0]["rain_mult"]:.2f}' if co else "None", "times usual" if co else f"in {rm[0]:.2f} to {rm[-1]:.2f} times usual", b),
    ])
    ry = g.get("rice_years") or [[w.split("-").count("rice") for w in row] for row in g["winner"]]
    single = len({v for row in ry for v in row}) == 1
    md(f'<div class="rl-callout"><p>{"<strong>No shift point at these inputs.</strong> " if single else ""}{html.escape(humanize(g["text"]))}</p></div>')
    section("How many rice years the best plan has, for each rainfall and water supply", b,
            "Each square is one kind of season: read across for monsoon rainfall, up for irrigation water. Darker blue means more rice years in the best four-year plan. "
            + ("" if single else "The dashed line is where plans with two or more rice years start to win; the dotted lines show how far that line moves when the weather record is resampled. ")
            + "The white circle is our farm today in a usual year.")
    fig, items = charts.tipping_grid(g, irr_now)
    legend(items)
    charts.show(fig, "grid")
    srcline(f"Model output over {tp['n_scenarios']:,} resampled weather sequences (seed 42). Hover a square for the winning plan. {html.escape(humanize(tp.get('frame', '')))}.", "Source")
    md(f'<p class="rl-note">To stay fast this tab uses {tp["n_scenarios"]:,} of the resampled weather sequences. Plans that are nearly tied can therefore swap places with the Our Priorities tab; the number of rice years is the steady result.</p>')

    gu = tp.get("grid_upstream_local")
    if gu and gu.get("winner"):
        section("When canal rain and local rain differ", b,
                "Across is the monsoon rain upstream of Nagarjuna Sagar, which feeds the canal proxy. Up is local rain on the farm, which feeds the well proxy and the crop. 1.0 means a usual year.")
        if gu.get("text"):
            md(f'<div class="rl-callout"><p>{html.escape(humanize(gu["text"]))}</p></div>')
        fig2, items2 = charts.tipping_grid(gu, None, xkey="upstream_mult", ykey="local_mult",
                                           xt="Upstream rainfall compared with usual (1.0 = usual)", yt="Local rainfall compared with usual (1.0 = usual)", farm=(1.0, 1.0),
                                           hov="Upstream rain %{x:.2f} times usual<br>Local rain %{y:.2f} times usual<br>Best: %{text}<br>Rice years: %{customdata}<extra></extra>")
        legend(items2)
        charts.show(fig2, "grid2")
        srcline("Model output. Upstream rain is the NASA POWER season rainfall averaged over five points upstream of Nagarjuna Sagar; actual canal releases depend on reservoir operations.", "Source")

    section("Where rainfall alone tips the choice", b, "The score of each plan for your priorities as the monsoon gets weaker or stronger. The highest line is the best plan at that rainfall.")
    md(f'<div class="rl-callout"><p>{html.escape(humanize(xo["text"]))}</p></div>')
    fig, items = charts.crossover(xo, colors)
    legend(items)
    charts.show(fig, "cross")
    srcline("Model output. Dashed lines mark where the number of rice years in the best plan changes; the shaded band is the 10th to 90th percentile of the first change when the weather record is resampled.", "Source")

    lm = tp["late_monsoon"]
    section("If the monsoon starts late", b)
    md(f'<p style="max-width:75ch">{html.escape(humanize(lm["text"]))}</p>')
    fig, items = charts.late_monsoon(lm, colors, charts.curve_lines(lm))
    legend(items)
    charts.show(fig, "late")
    srcline("Model output. The monsoon starts later than it really did in every year: the rain of those first days is lost, and every crop is sown that many days later.", "Source")

    hc = tp.get("heat")
    if hc:
        section("If every season is hotter", b)
        md(f'<p style="max-width:75ch">{html.escape(humanize(hc["text"]))}</p>')
        fig, items = charts.heat(hc, colors, charts.curve_lines(hc))
        legend(items)
        charts.show(fig, "heat")
        srcline("Model output. Every day is made warmer by the same amount: crops need more water, and more days at flowering pass the heat limit. The heat limits are assumptions, team to verify.", "Source")

    section("Is it worth measuring before you decide?", b, "How much a better decision is worth if one unknown is pinned down first. It is the expected value of perfect information: an upper limit on what any real test could add.")
    c1, c2 = st.columns(2, gap="large")
    with c1:
        _evpi_card(tp["evpi_irrigation"], f"Is it worth measuring your {data.supply_words(p)} before deciding?", "a water-supply measurement", b)
    with c2:
        _evpi_card(tp["evpi_awc"], "Is it worth testing your soil's water holding capacity before deciding?", "a soil test", b)
