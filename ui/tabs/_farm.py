"""Farm-wide totals and the land-split control, shared by Compare Futures and My Priorities."""
import html

import plotly.graph_objects as go
import streamlit as st

from ui import charts, data
from ui.components import badge, delta_html, fmt_rs, md, section, srcline, stat, stats
from ui.theme import T


def per_farm_note(per_acre: float, unit: str = "Rs") -> str:
    """'Rs 40,00,000 for the farm' text under a per-acre figure."""
    t = data.farm_total(per_acre)
    return "" if t is None else f"{fmt_rs(t)} for {data.ACRES:,.0f} acres"


def land_split_panel(alt_id: str, alt_name: str, key: str, p: dict) -> None:
    b = "placeholder" if data.is_mock() else "modeled"
    with st.spinner("Splitting the land between rice and the alternative."):
        ls = data.land_split(alt_id, p)
    xs = list(ls["acres_rice"])
    total = float(ls.get("acres_total") or data.ACRES or max(xs))
    section(f"Split the land between rice and {alt_name}", b,
            f"Move the slider to put some of the {total:,.0f} acres in the alternative. The rest stays in rice. Totals are for the whole farm over four years.")
    x = st.slider(f"Acres in rice, out of {total:,.0f}", int(min(xs)), int(max(xs)), value=int(max(xs)), step=1, key=f"split_{key}")
    i = xs.index(x) if x in xs else len(xs) - 1
    j = xs.index(max(xs))  # all-rice baseline
    def row(k):
        return ls[k][i], ls[k][i] - ls[k][j]
    m, dm = row("total_profit_mean"); w, dw = row("total_profit_worst10"); irr, di = row("total_irrigation_m3")
    stats([
        stat("Total profit, average", fmt_rs(m), "", b, delta_html(dm, "Rs {:,.0f}") + " against all rice"),
        stat("Total profit, worst 10% of seasons", fmt_rs(w), "", b, delta_html(dw, "Rs {:,.0f}") + " against all rice"),
        stat("Total irrigation water", f"{irr:,.0f}", "m3", b, delta_html(di, "{:,.0f} m3", good_when_up=False) + " against all rice"),
    ])
    fig = go.Figure()
    fig.add_scatter(x=xs, y=ls["total_profit_mean"], mode="lines", name="Average", line=dict(color=T["rice"], width=3), hovertemplate="%{x:.0f} acres in rice: Rs %{y:,.0f}<extra>Average</extra>")
    fig.add_scatter(x=xs, y=ls["total_profit_worst10"], mode="lines", name="Worst 10%", line=dict(color=T["bajra"], width=3), hovertemplate="%{x:.0f} acres in rice: Rs %{y:,.0f}<extra>Worst 10%</extra>")
    fig.add_vline(x=x, line=dict(color=T["ink"], width=2, dash="dash"))
    fig.add_annotation(x=max(xs), y=ls["total_profit_mean"][j], text="All rice (our farm today)", showarrow=False, xanchor="right", yanchor="bottom", font=dict(size=12, color=T["ink2"]))
    charts._layout(fig, 320, xt=f"Acres in rice (of {total:,.0f})", yt="Total profit over 4 years (Rs)", legend=False)
    charts.show(fig, f"split_chart_{key}")
    srcline("Model output for the whole farm. Blue is the average, clay red is the worst 10% of seasons.", "Source")
