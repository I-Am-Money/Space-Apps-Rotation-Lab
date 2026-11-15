# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Tab 3, Our Priorities (Build Spec v3 section 9): the two sliders, the Pareto chart and the recommendation card."""
import html

import streamlit as st

from engine import explain
from ui import charts, data
from ui.data import plan_label
from ui.tabs import _farm
from ui.components import delta_html, srcline, badge, fmt_rs, md, ribbon, section, stat, stats, tab_head


CLOSE_CALL_RS = 500   # Rs per acre over 4 years; a smaller gap between the top two plans is shown as a tie

def explain_inputs(rec, tp, p):
    """Only computed numbers go to the explanation (v3 section 10): top rotation, baseline A, differences,
    crossover thresholds and EVPI when the tipping points are already computed."""
    t, r = rec["top"], rec["runner_up"]
    mdf = rec["metrics"]
    a = mdf[mdf.id == "rice-rice-rice-rice"].iloc[0]
    d = dict(top_rotation=plan_label(t["plan"]), runner_up=plan_label(r["plan"]),
             top_mean_profit=round(t["mean_profit"]), top_worst10_profit=round(t["worst10_profit"]),
             top_irrigation_mm=round(t["irrigation_mm"]),
             baseline_rotation="Rice every year (our farm today)", baseline_mean_profit=round(a.mean_profit),
             baseline_worst10_profit=round(a.worst10_profit), baseline_irrigation_mm=round(a.irrigation_mm),
             diff_mean_profit=round(t["mean_profit"] - a.mean_profit), diff_worst10_profit=round(t["worst10_profit"] - a.worst10_profit),
             diff_irrigation_mm=round(t["irrigation_mm"] - a.irrigation_mm),
             same_as_today=bool(t["id"] == "rice-rice-rice-rice"),
             bad_year_weight=p["lam"], water_saving_weight=p["w"])
    nofx, be = rec.get("no_rotation_effects"), rec.get("breakeven")
    if nofx:
        d["diff_mean_profit_if_no_rotation_effects"] = round(nofx["d_mean_profit"])
    if be and be.get("shortfall") is not None:
        d["new_crop_income_shortfall_pct_that_flips_the_advice"] = round(be["shortfall"] * 100)
    if tp:
        co = tp["rainfall_crossover"].get("crossovers") or []
        d["rain_crossover"] = co[0]["rain_mult"] if co else None
        thr = tp["grid"]["rice_shift_threshold_mm"]; rm = tp["grid"]["rain_mult"]
        d["irrigation_shift_mm"] = thr[min(range(len(rm)), key=lambda i: abs(rm[i] - 1.0))]
        d["evpi_irrigation_rs"] = round(tp["evpi_irrigation"]["value"])
        d["evpi_soil_rs"] = round(tp["evpi_awc"]["value"])
    return {k: v for k, v in d.items() if v is not None}


def render():
    tab_head("Our Priorities", "Say what matters to the farm. The recommendation moves with the two sliders.")
    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.slider("What matters more to you?", 0, 100, value=data.V()["lam"], format="%d", **data.bind("lam"),
                  help="Left: the best result in an average run of years. Right: the best result in the worst tenth of weather sequences.")
        md('<div style="display:flex;justify-content:space-between;font-size:.86rem;color:var(--ink2);margin-top:-.6rem"><span>Plan for an average year</span><span>Protect me in bad years</span></div>')
    with c2:
        st.slider("How much do you want to save irrigation water?", 0, 100, value=data.V()["w"], format="%d", **data.bind("w"),
                  help="Left: water saving does not count. Right: every millimetre of irrigation water saved counts at the full water value set in the assumptions.")
        md('<div style="display:flex;justify-content:space-between;font-size:.86rem;color:var(--ink2);margin-top:-.6rem"><span>Not at all</span><span>As much as possible</span></div>')

    p = data.params()
    with st.spinner(data.MSG["recommend"]):
        rec = data.recommend(p)
    mdf = rec["metrics"]
    n_rot = int(mdf["offered"].sum()) if "offered" in mdf else len(mdf)
    base = mdf[mdf.id == "rice-rice-rice-rice"].iloc[0]
    t = rec["top"]
    b = "placeholder" if data.is_mock() else "modeled"
    tp_key, tp_seen = st.session_state.get("_tp") or (None, None)      # only when Tipping Points was already opened for these inputs
    ex = explain.explain(explain_inputs(rec, tp_seen if tp_key == repr(sorted(p.items(), key=str)) else None, p))
    src = "Written by Claude from the numbers on this page." if ex["source"] == "model" else "Written from a fixed template using the numbers on this page."
    same = t["id"] == "rice-rice-rice-rice"
    md(f'<div class="rl-hero"><p style="margin:0;font-size:.9rem;opacity:.85">{"Recommended for these priorities: stay with rice every year" if same else "Recommended for these priorities"} {badge(b)}</p>'
       f'<h4>{html.escape(plan_label(t["plan"]))}</h4>{ribbon(t["plan"])}<p style="margin:.7rem 0 .3rem">{html.escape(ex["text"])}</p>'
       f'<p style="margin:0;font-size:.82rem;opacity:.8">{src} Modeled estimate, for planning only.</p></div>')
    stats([
        stat("Average over 4 years", fmt_rs(t["mean_profit"]), "per acre", b, delta_html(t["mean_profit"] - base.mean_profit, "Rs {:,.0f}") + " per acre against our farm today. " + _farm.per_farm_note(t["mean_profit"])),
        stat("Worst 10% of weather sequences", fmt_rs(t["worst10_profit"]), "per acre", b, delta_html(t["worst10_profit"] - base.worst10_profit, "Rs {:,.0f}") + " per acre against our farm today. " + _farm.per_farm_note(t["worst10_profit"])),
        stat("Irrigation water over 4 years", f'{t["irrigation_mm"]:,.0f}', "mm", b, delta_html(t["irrigation_mm"] - base.irrigation_mm, "{:,.0f} mm", good_when_up=False) + " against our farm today"
             + (f' ({data.m3(t["irrigation_mm"] - base.irrigation_mm):+,.0f} m3 on the farm)' if data.m3(1) else "")),
    ])
    ru = rec.get("runner_up") or {}
    if ru and ru.get("J") is not None and t.get("J") is not None:
        gap = float(t["J"]) - float(ru["J"])
        if gap < CLOSE_CALL_RS:
            md(f'<p class="rl-note"><strong>Close call.</strong> The second plan, {html.escape(plan_label(ru["plan"]))}, scores only Rs {gap:,.0f} per acre lower over four years. '
               f'We treat any gap under Rs {CLOSE_CALL_RS:,} as a tie (a rule of thumb, not a statistical test), so choose between the two on what suits the farm.</p>')
    be, nofx = rec.get("breakeven"), rec.get("no_rotation_effects")
    if not same and (be or nofx):
        items = []
        if nofx:
            fx = nofx.get("effects") or {}
            def pct(v):
                return f"{abs(float(v) - 1) * 100:.0f}% {'more' if float(v) >= 1 else 'less'}"
            d0, d1 = nofx["d_mean_profit"], nofx["d_mean_profit_with_effects"]
            def vs(d):
                return "the same as" if abs(d) < 0.5 else f"{fmt_rs(abs(d))} per acre {'more' if d > 0 else 'less'} than"
            items.append(f"<strong>It leans on rotation benefits that nobody has measured here.</strong> The model assumes rice yields {pct(fx.get('rice_after_pigeonpea', 1))} "
                         f"after pigeon pea and {pct(fx.get('rice_after_rice', 1))} after rice. Those are starting values from the build spec with no source yet {badge('assumption')}. "
                         f"With every rotation effect set to zero, this plan would earn {vs(d0)} rice every year, instead of {vs(d1)} it. "
                         f"The water saving does not depend on them.")
        if be:
            crops = " and ".join(data.CROP_LABEL.get(c, c).lower() for c in be["crops"])
            if be.get("shortfall") is None:
                room = f"Even with no income at all from {crops}, this plan still scores higher than rice every year for these priorities, because of the weight put on saving water."
            else:
                room = (f"If {crops} brings in {be['shortfall'] * 100:.0f}% less money than assumed (a lower price or a lower yield), "
                        f"rice every year scores higher than this plan for these priorities.")
            items.append(f"<strong>Room for error on the new crops.</strong> {room} The model values {crops} at the full support price"
                         f"{', and pigeon pea has no district yield record' if 'pigeonpea' in be['crops'] else ''}.")
        md('<div class="rl-note" style="max-width:95ch"><p style="margin:.2rem 0 .3rem"><strong>How solid is this?</strong> Check these locally before acting.</p><ul style="margin:.2rem 0 0 1.1rem">'
           + "".join(f"<li style='margin-bottom:.35rem'>{i}</li>" for i in items) + "</ul></div>")
    wp = rec.get("water_price_proxy") or {}
    if wp.get("value_rs_per_mm_ha") is not None:
        md(f'<p class="rl-note">How the score works: average profit and worst-10% profit are mixed by the first slider. The second slider then subtracts '
           f'a value for the irrigation water a plan uses, up to Rs {wp["value_rs_per_mm_ha"]:g} per mm per hectare at the far right {badge("assumption")}. '
           f'That value is a preference, not a bill: it is never taken off the profit shown.</p>')

    section("Every rotation, plotted", b,
            f"Each dot is one of the {n_rot} four-year rotations. Further right is a better average, higher is a better bad-year result. Darker blue uses more irrigation water.")
    charts.show(charts.pareto(rec["metrics"], t["id"]), "pareto")
    srcline(f"Model output for all {n_rot} rotations over {rec['n_scenarios']:,} resampled weather sequences. Plans that grow the same non-rice crop in all four years are not offered (team rule).", "Source")
    md('<p class="rl-note">The white circle is our farm today. The diamond is the recommended rotation. The dotted line joins the rotations where you cannot raise the average without lowering the bad-year result.</p>')
    if not same:
        _farm.land_split_panel(t["id"], data.plan_label(t["plan"]), "pri", p)
