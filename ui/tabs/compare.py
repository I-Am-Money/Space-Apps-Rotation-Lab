import html

import pandas as pd
import streamlit as st

from ui import charts, data
from ui.components import badge, bullets, fmt_rs, legend, md, ribbon, section, tab_head
from ui.data import ROT_NAME, humanize

from ui.theme import T
T_ACC, T_RICE = T["accent_soft"], T["rice"]
IDS = ("current", "A", "B", "C")


def render():
    p = data.params()
    cmp = data.compare(IDS, p)
    rec = data.recommend(p)
    rots = cmp["rotations"]
    b = "placeholder" if data.is_mock() else "modeled"
    tab_head("Compare Futures", f"Your current rotation against A, B and C, each run through {cmp['n_scenarios']:,} possible four-year weather sequences drawn from the real record.")

    cols = st.columns(4, gap="small")
    for col, (rid, r) in zip(cols, rots.items()):
        with col:
            md(f'<div class="rl-panel" style="padding:.8rem .9rem"><div style="font-weight:700;margin-bottom:.35rem">{html.escape(ROT_NAME[rid])}</div>{ribbon(r["plan"], True)}</div>')

    legend([(charts.NAMES[k], charts.ROT_COLOR[k]) for k in rots])
    section("Plan profit across weather sequences", b, "Each box spans the middle half of outcomes; the dashed line is the mean. Dots beyond the whiskers are unusual sequences.")
    charts.show(charts.profit_dist(rots), "profit")

    c1, c2 = st.columns(2, gap="large")
    with c1:
        section("Yield by year", b)
        charts.show(charts.yearly_yield(rots), "yy")
    with c2:
        section("Soil cover trend", b, "Higher means more crop growth left on the soil. This is a proxy, not a measured residue amount.")
        charts.show(charts.residue_lines(rots), "res")

    section("Water use", b, "Rain and irrigation over the four-year plan, average sequence. Irrigation alone is on the right.")
    fig, irr, names = charts.water_bars(rots)
    legend([("Rain", T_ACC), ("Irrigation", T_RICE)])
    c1, c2 = st.columns([1.5, 1], gap="large")
    with c1:
        charts.show(fig, "wb")
    with c2:
        charts.show(charts.irrigation_only(names, irr), "wi")

    section("Stress tests", b, "A named bad-weather case, placed in a plan year with typical weather in the other years.")
    tests = {}
    for rid, r in rots.items():
        for t in r["stress_tests"]:
            tests.setdefault(t["test"], dict(label=t["label"], by={}))["by"][rid] = t["profit"]
    for name, t in tests.items():
        lines = " ".join(f"{ROT_NAME[rid]} earns {fmt_rs(v)}." for rid, v in t["by"].items())
        md(f'<p style="margin:.5rem 0;max-width:85ch"><strong>In a repeat of the {html.escape(t["label"])}:</strong> {html.escape(lines)} (per acre, 4 years) {badge(b)}</p>')
    with st.expander("Show stress tests as a table"):
        st.dataframe(pd.DataFrame([{"Case": t["label"], **{ROT_NAME[k]: round(v) for k, v in t["by"].items()}} for t in tests.values()]), hide_index=True, use_container_width=True)

    section("The case for and against each rotation")
    reps = rec["three_strategy_report"]
    top_id = rec["top"]["id"]
    keys = [k for k in IDS if k in reps]
    for i in range(0, len(keys), 2):
        cols = st.columns(2, gap="large")
        for col, k in zip(cols, keys[i:i + 2]):
            r = reps[k]
            ev = r["evidence"]
            ev_lines = [f"Ranks {ev['rank_of_256']} of 256 for your priorities.",
                        f"Average {fmt_rs(ev['mean_profit_rs_acre'])} per acre; worst 10% {fmt_rs(ev['worst10_profit_rs_acre'])}.",
                        f"Water stress {ev['water_stress_mm']:,.0f} mm; irrigation {ev['irrigation_mm']:,.0f} mm over the plan."]
            with col:
                top = ' <span class="rl-badge" style="background:var(--ink);color:#fff">Model favourite</span>' if r["id"] == top_id else ""
                md(f'<div class="rl-panel"><h4>{html.escape(ROT_NAME[k])}{top}</h4>{ribbon(r["plan"], True)}'
                   f'<p style="margin:.4rem 0">{html.escape(humanize(r["why"]))} {badge(b)}</p>'
                   + bullets("Evidence", ev_lines) + bullets("Benefits", r["benefits"])
                   + bullets("What we do not know", r["info_gaps"]) + bullets("Needs local review", r["risks_for_local_review"]) + "</div>")
