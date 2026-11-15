# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
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
    export = pd.DataFrame([{"rotation": rid, "plan": data.plan_label(r["plan"]),
        "mean_profit_rs_acre": r["mean_profit"], "worst10_profit_rs_acre": r["worst10_profit"],
        "irrigation_mm": r["irrigation_mm"], "total_water_mm": r["total_water_mm"],
        "farm_mean_profit_rs": data.farm_total(r["mean_profit"]), "farm_irrigation_m3": data.m3(r["irrigation_mm"])} for rid, r in rots.items()])
    st.download_button("Download this comparison (CSV)", export.to_csv(index=False).encode(), "rotationlab-comparison.csv", "text/csv")
    b = "placeholder" if data.is_mock() else "modeled"
    tab_head("Compare Futures", f"Rotations B and C against our farm today (A, rice every year), each run through {cmp['n_scenarios']:,} four-year weather sequences drawn from the real record. Every result is shown as a difference from A.")

    cols = st.columns(max(len(rots), 3), gap="small")
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
    table(["Rotation", "Average profit", "Worst 10% of weather sequences", "Total water", "Irrigation water"], rows)
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
        section("Yield by year", b, "Quintals per acre as the crop is sold: rice as paddy, the others as grain.")
        charts.show(charts.yearly_yield(rots), "yy")
        hot = [(ROT_NAME[k], sum(r["hot_days_mean"])) for k, r in rots.items() if r.get("hot_days_mean")]
        srcline("Model output, average over weather sequences. District-scale estimate, not a field measurement."
                + (" Hot days at flowering over the plan, on average: " + "; ".join(f"{n} {v:.1f}" for n, v in hot) + "." if hot else ""), "Source")
    with c2:
        section("Soil cover trend", "assumption", "A simple index from 0 to 1 of how much residue and ground cover each crop leaves. It is a ranking rule, not a measurement.")
        charts.show(charts.residue_lines(rots), "res")
        arrow = {"up": "&#8593; up", "down": "&#8595; down", "flat": "&#8594; no change"}
        soc = [f'{html.escape(ROT_NAME[k])}: <strong>{arrow.get(r["soil_cover"]["soc_direction"], "n/a")}</strong>' for k, r in rots.items() if r.get("soil_cover")]
        if soc:
            md('<p class="rl-note" style="margin:.2rem 0"><strong>Soil organic carbon, direction only</strong> (too slow to quantify over 4 years): ' + "; ".join(soc) + f'. {badge("assumption")}</p>')
        srcline(rots[next(iter(rots))].get("residue_index_note", "Proxy, not measured."), "Rule")

    section("Water use", b, "Rain received during crop seasons plus irrigation, averaged over the four-year plan. This is not whole-year precipitation or crop evapotranspiration. Irrigation alone is on the right.")
    fig, split, names = charts.water_bars(rots)
    irr = [r["irrigation_mm"] for r in rots.values()]
    legend([("Rain", T_ACC), ("Canal water", T_RICE), ("Well water", charts.WELL)] if split else [("Rain", T_ACC), ("Irrigation", T_RICE)])
    c1, c2 = st.columns([1.5, 1], gap="large")
    with c1:
        charts.show(fig, "wb")
    with c2:
        charts.show(charts.irrigation_only(names, irr, split), "wi")
    srcline("Model output. Canal water is a proxy based on upstream monsoon rain; well water is a simplified recharge proxy. Canal is used first, wells cover the shortfall.", "Note")

    section("Stress tests", b, "Each test takes one real bad year from the record and places it in one year of the plan, with a typical year in the other three.")
    tests = {}
    for rid, r in rots.items():
        for t in r["stress_tests"]:
            tests.setdefault(t["test"], dict(label=t["label"], desc=t.get("description", ""), year=t.get("source_year"), badge=t.get("badge"), by={}))["by"][rid] = t["profit"]
    for name, t in tests.items():
        base_v = t["by"].get("A")
        lines = " ".join(f"{ROT_NAME[rid]} earns {fmt_rs(v)}" + ("" if rid == "A" or base_v is None else f" ({'+' if v - base_v >= 0 else '-'}Rs {abs(v - base_v):,.0f} against A)") + "." for rid, v in t["by"].items())
        yr = t.get("year")
        if yr and " in year " in name:
            head = f"In a repeat of {yr}, the {name.replace(' in year ', ', placed in year ')} of the plan"
        elif yr:
            head = f"In a repeat of {yr}, the {name}"
        else:
            head = f"In a {t['label']}"
        md(f'<p style="margin:.5rem 0;max-width:85ch"><strong>{html.escape(head)}:</strong> {html.escape(lines)} (per acre, 4 years) {badge(t.get("badge") or b)}</p>' + (f'<p class="rl-note" style="margin:-.3rem 0 .6rem">{html.escape(t["desc"])}</p>' if t["desc"] else ""))
    yrs_used = [t["year"] for t in tests.values() if t.get("year")]
    if len(yrs_used) != len(set(yrs_used)):
        md('<p class="rl-note">Some tests use the same year because one year of the record was the worst on more than one measure.</p>')
    with st.expander("Show stress tests as a table"):
        st.dataframe(pd.DataFrame([{"Case": t["label"], **{ROT_NAME[k]: round(v) for k, v in t["by"].items()}} for t in tests.values()]), hide_index=True, width="stretch")

    section("The case for and against each rotation")
    reps = rec["three_strategy_report"]
    top_id = rec["top"]["id"]
    keys = [k for k in ("A", "B", "C", "current") if k in reps]
    for i in range(0, len(keys), 2):
        cols = st.columns(2, gap="large")
        for col, k in zip(cols, keys[i:i + 2]):
            r = reps[k]
            ev = r["evidence"]
            ev_lines = [f"Ranks {ev['rank_of_256']} of {len(rec['metrics'])} for your priorities.",
                        f"Average {fmt_rs(ev['mean_profit_rs_acre'])} per acre; worst 10% {fmt_rs(ev['worst10_profit_rs_acre'])}.",
                        f"Irrigation {ev['irrigation_mm']:,.0f} mm and total water {ev['total_water_mm']:,.0f} mm over the plan."]
            with col:
                top = ' <span class="rl-badge" style="background:var(--ink);color:#fff">Model favourite</span>' if r["id"] == top_id else ""
                md(f'<div class="rl-panel"><h4>{html.escape(ROT_NAME[k])}{top}</h4>{ribbon(r["plan"], True)}'
                   f'<p style="margin:.4rem 0">{html.escape(humanize(r["why"]))} {badge(b)}</p>'
                   + bullets("Evidence", ev_lines) + bullets("Benefits", r["benefits"])
                   + bullets("What we do not know", r["info_gaps"]) + bullets("Needs local review", r["risks_for_local_review"]) + "</div>")
