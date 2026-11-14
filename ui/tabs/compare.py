import html

import pandas as pd
import streamlit as st

from ui import charts, data
from ui.tabs import _farm
from ui.components import badge, bullets, delta_html, fmt_rs, legend, md, ribbon, section, srcline, table, tab_head
from ui.data import ROT_NAME, humanize

from ui.theme import T
T_ACC, T_RICE = T["accent_soft"], T["rice"]


def render():
    p = data.params()
    with st.spinner(data.MSG["compare"]):
        cmp = data.compare(data.compare_ids(p), p)
    with st.spinner(data.MSG["recommend"]):
        rec = data.recommend(p)
    rots = cmp["rotations"]
    b = "placeholder" if data.is_mock() else "modeled"
    tab_head("Compare Futures", f"Rotations B and C against our farm today (A, rice every year), each run through {cmp['n_scenarios']:,} possible four-year weather sequences drawn from the real record.")

    cols = st.columns(4, gap="small")
    for col, (rid, r) in zip(cols, rots.items()):
        with col:
            md(f'<div class="rl-panel" style="padding:.8rem .9rem"><div style="font-weight:700;margin-bottom:.35rem">{html.escape(ROT_NAME[rid])}</div>{ribbon(r["plan"], True)}</div>')

    legend([(charts.NAMES[k], charts.ROT_COLOR[k]) for k in rots])
    section("Difference from our farm today", b, "Every number below is the change compared with Rotation A, rice every year. Plus is higher.")
    rows = []
    for rid in rots:
        if rid == "A":
            continue
        rows.append([html.escape(ROT_NAME[rid]) + f'<br><span style="font-size:.8rem;color:var(--ash)">{html.escape(data.plan_label(rots[rid]["plan"]))}</span>',
                     delta_html(data.delta(rots, rid, "mean_profit"), "Rs {:,.0f}"),
                     delta_html(data.delta(rots, rid, "worst10_profit"), "Rs {:,.0f}"),
                     delta_html(data.delta(rots, rid, "total_water_mm"), "{:,.0f} mm", good_when_up=False),
                     delta_html(data.delta(rots, rid, "irrigation_mm"), "{:,.0f} mm", good_when_up=False)])
    table(["Rotation", "Average profit", "Worst 10% of seasons", "Total water", "Irrigation water"], rows)
    srcline(f"Model output over {cmp['n_scenarios']:,} resampled weather sequences. Profit is rupees per acre over four years. Less water is shown as good, more profit is shown as good.", "Note")
    section("Totals for the whole farm", b, f"Each figure is for all {data.ACRES:,.0f} acres over four years, with the per-acre number under it. Water is in cubic metres.")
    rows = []
    for rid, r in rots.items():
        canal, well = r.get("irrigation_canal_mm"), r.get("irrigation_well_mm")
        wcell = (f'{data.m3(canal):,.0f} canal<br>{data.m3(well):,.0f} well' if canal is not None and well is not None else f'{data.m3(r["irrigation_mm"]):,.0f}')
        rows.append([html.escape(ROT_NAME[rid]),
                     f'{fmt_rs(data.farm_total(r["mean_profit"]))}<br><span style="font-size:.8rem;color:var(--ash)">{fmt_rs(r["mean_profit"])} per acre</span>',
                     f'{fmt_rs(data.farm_total(r["worst10_profit"]))}<br><span style="font-size:.8rem;color:var(--ash)">{fmt_rs(r["worst10_profit"])} per acre</span>',
                     wcell + f'<br><span style="font-size:.8rem;color:var(--ash)">{r["irrigation_mm"]:,.0f} mm per acre</span>',
                     f'{data.m3(r["total_water_mm"]):,.0f}<br><span style="font-size:.8rem;color:var(--ash)">{r["total_water_mm"]:,.0f} mm per acre</span>'])
    table(["Rotation", "Total profit, average", "Total profit, worst 10%", "Irrigation water (m3)", "Total water, rain and irrigation (m3)"], rows)
    srcline("Model output. Farm totals are per-acre values times the acres in config/farm.yaml; cubic metres use 1 mm over 1 acre from the same file.", "Note")

    alts = [k for k in rots if k != "A"]
    if alts:
        pick = st.segmented_control("Alternative to split with", alts, format_func=lambda k: ROT_NAME[k], default=alts[0], key="split_alt") or alts[0]
        _farm.land_split_panel(pick, ROT_NAME[pick] + " (" + data.plan_label(rots[pick]["plan"]) + ")", "cmp", p)

    section("Plan profit across weather sequences", b, "Each box spans the middle half of outcomes; the dashed line is the mean. Dots beyond the whiskers are unusual sequences.")
    charts.show(charts.profit_dist(rots), "profit")
    srcline(f"Model output, {cmp['n_scenarios']:,} weather sequences resampled from the NASA POWER record. The dotted line is the mean for our farm today.", "Source")

    c1, c2 = st.columns(2, gap="large")
    with c1:
        section("Yield by year", b)
        charts.show(charts.yearly_yield(rots), "yy")
        srcline("Model output, average over weather sequences.", "Source")
    with c2:
        section("Soil cover trend", b, "Higher means more crop growth left on the soil. This is a proxy, not a measured residue amount.")
        charts.show(charts.residue_lines(rots), "res")
        srcline(rots[next(iter(rots))].get("residue_index_note", "Proxy, not measured."), "Note")

    section("Water use", b, "Rain and irrigation over the four-year plan, average sequence. Irrigation alone is on the right.")
    fig, split, names = charts.water_bars(rots)
    irr = [r["irrigation_mm"] for r in rots.values()]
    legend([("Rain", T_ACC), ("Canal water", T_RICE), ("Well water", charts.WELL)] if split else [("Rain", T_ACC), ("Irrigation", T_RICE)])
    c1, c2 = st.columns([1.5, 1], gap="large")
    with c1:
        charts.show(fig, "wb")
    with c2:
        charts.show(charts.irrigation_only(names, irr, split), "wi")
    srcline("Model output. Canal water is a proxy based on upstream monsoon rain; well water is a simplified recharge proxy. Canal is used first, wells cover the shortfall.", "Note")

    section("Stress tests", b, "A named bad-weather case, placed in a plan year with typical weather in the other years.")
    tests = {}
    for rid, r in rots.items():
        for t in r["stress_tests"]:
            tests.setdefault(t["test"], dict(label=t["label"], desc=t.get("description", ""), by={}))["by"][rid] = t["profit"]
    for name, t in tests.items():
        base_v = t["by"].get("A")
        lines = " ".join(f"{ROT_NAME[rid]} earns {fmt_rs(v)}" + ("" if rid == "A" or base_v is None else f" ({'+' if v - base_v >= 0 else '-'}Rs {abs(v - base_v):,.0f} against A)") + "." for rid, v in t["by"].items())
        md(f'<p style="margin:.5rem 0;max-width:85ch"><strong>In a repeat of the {html.escape(t["label"])}:</strong> {html.escape(lines)} (per acre, 4 years) {badge(b)}</p>' + (f'<p class="rl-note" style="margin:-.3rem 0 .6rem">{html.escape(t["desc"])}</p>' if t["desc"] else ""))
    with st.expander("Show stress tests as a table"):
        st.dataframe(pd.DataFrame([{"Case": t["label"], **{ROT_NAME[k]: round(v) for k, v in t["by"].items()}} for t in tests.values()]), hide_index=True, use_container_width=True)

    section("The case for and against each rotation")
    reps = rec["three_strategy_report"]
    top_id = rec["top"]["id"]
    keys = [k for k in ("A", "B", "C", "current") if k in reps]
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
