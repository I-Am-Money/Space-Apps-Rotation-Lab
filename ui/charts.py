"""Plotly figures in the RotationLab style. Every function draws engine output; no numbers are made up here."""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from ui.data import CROP_LABEL, ROT_NAME, plan_label
from ui.theme import CROP_COLOR, T, oklch

FONT = '"Source Sans 3", system-ui, sans-serif'
CONFIG = {"displayModeBar": False, "responsive": True}
ROT_COLOR = {"A": T["rice"], "B": T["jowar"], "C": T["pigeonpea"], "current": T["bajra"]}
SHORT = {"A": "A", "B": "B", "C": "C", "current": "Yours"}
NAMES = {"A": "A: all rice", "B": "B: rice and jowar", "C": "C: rice, pigeon pea, jowar", "current": "Your current rotation"}


def _layout(fig, h=380, xt=None, yt=None, legend=True):
    fig.update_layout(
        height=h, margin=dict(l=8, r=12, t=10, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=14, color=T["ink"]),
        hoverlabel=dict(bgcolor=T["surface"], bordercolor=T["line"], font=dict(family=FONT, size=14, color=T["ink"])),
        showlegend=legend, legend=dict(orientation="h", y=-0.2, x=0, font=dict(size=13)),
    )
    ax = dict(gridcolor=T["line"], zeroline=False, linecolor=T["line"], tickfont=dict(size=13, color=T["ink2"]), automargin=True)
    fig.update_xaxes(title=dict(text=xt, font=dict(size=13, color=T["ink2"])) if xt else None, **ax)
    fig.update_yaxes(title=dict(text=yt, font=dict(size=13, color=T["ink2"])) if yt else None, **ax)
    return fig


def show(fig, key):
    st.plotly_chart(fig, use_container_width=True, config=CONFIG, key=key)


def yield_history(df):
    fig = go.Figure()
    xmax = int(df.year.max())
    for c in ("rice", "jowar", "bajra", "pigeonpea"):
        d = df[df.crop == c].sort_values("year")
        if d.empty:
            continue
        fig.add_scatter(x=d.year, y=d.yield_kg_ha, mode="lines", name=CROP_LABEL[c], line=dict(color=CROP_COLOR[c], width=2.5),
                        hovertemplate="%{x}: %{y:,.0f} kg per ha<extra>" + CROP_LABEL[c] + "</extra>")
        fig.add_annotation(x=d.year.iloc[-1], y=d.yield_kg_ha.iloc[-1], text=CROP_LABEL[c], showarrow=False, xanchor="left", xshift=6, font=dict(size=13, color=T["ink"]))
    _layout(fig, 340, yt="District yield (kg per hectare)", legend=False)
    fig.update_xaxes(range=[int(df.year.min()), xmax + 5])
    return fig


def profit_dist(rots):
    fig = go.Figure()
    for rid, r in rots.items():
        col = ROT_COLOR.get(rid, T["mixed"])
        fig.add_trace(go.Box(y=r["profit"], name=NAMES.get(rid, rid), marker_color=col, line=dict(color=col, width=2), fillcolor="rgba(0,0,0,0)",
                             boxpoints="outliers", boxmean=True, marker_size=5,
                             hovertemplate="Rs %{y:,.0f} per acre over 4 years<extra>" + NAMES.get(rid, rid) + "</extra>"))
    _layout(fig, 400, yt="Plan profit over 4 years (Rs per acre)", legend=False)
    return fig


def yearly_yield(rots):
    fig = go.Figure()
    for rid, r in rots.items():
        fig.add_bar(x=[f"Year {i+1}" for i in range(4)], y=list(r["yield_mean"]), name=NAMES.get(rid, rid), marker=dict(color=ROT_COLOR.get(rid, T["mixed"]), cornerradius=4),
                    customdata=[CROP_LABEL[c] for c in r["plan"]], hovertemplate="%{customdata}: %{y:,.0f} kg per ha<extra>" + NAMES.get(rid, rid) + "</extra>")
    _layout(fig, 360, yt="Average yield (kg per hectare)", legend=False)
    fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.08)
    return fig


def water_bars(rots):
    names = [SHORT.get(k, k) for k in rots]
    irr = [r["irrigation_mm"] for r in rots.values()]
    rain = [max(0.0, r["total_water_mm"] - r["irrigation_mm"]) for r in rots.values()]
    fig = go.Figure()
    fig.add_bar(y=names, x=rain, orientation="h", name="Rain", marker=dict(color=T["accent_soft"], line=dict(color=T["accent"], width=1.5)), hovertemplate="%{x:,.0f} mm rain<extra>%{y}</extra>")
    fig.add_bar(y=names, x=irr, orientation="h", name="Irrigation", marker=dict(color=T["rice"]), hovertemplate="%{x:,.0f} mm irrigation<extra>%{y}</extra>")
    _layout(fig, 300, xt="Water over the 4-year plan (mm)", legend=False)
    fig.update_layout(barmode="stack", bargap=0.35)
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
    return fig, irr, names


def irrigation_only(names, irr):
    fig = go.Figure(go.Bar(y=names, x=irr, orientation="h", marker=dict(color=T["rice"]), text=[f"{v:,.0f} mm" for v in irr],
                           textposition="outside", cliponaxis=False, hovertemplate="%{x:,.0f} mm<extra>%{y}</extra>"))
    _layout(fig, 300, xt="Irrigation water only (mm)", legend=False)
    fig.update_yaxes(autorange="reversed", showticklabels=False, gridcolor="rgba(0,0,0,0)")
    fig.update_xaxes(range=[0, max(irr + [1]) * 1.3])
    return fig


def residue_lines(rots):
    fig = go.Figure()
    for rid, r in rots.items():
        fig.add_scatter(x=[f"Year {i+1}" for i in range(4)], y=list(r["residue_index"]), mode="lines+markers", name=NAMES.get(rid, rid),
                        line=dict(color=ROT_COLOR.get(rid, T["mixed"]), width=2.5), marker=dict(size=8, line=dict(color=T["surface"], width=2)),
                        hovertemplate="%{y:.2f}<extra>" + NAMES.get(rid, rid) + "</extra>")
    _layout(fig, 320, yt="Soil cover proxy (1 = best modeled yield for that crop)", legend=False)
    return fig


def pareto(df, top_id):
    fig = go.Figure()
    fig.add_scatter(x=df.mean_profit, y=df.worst10_profit, mode="markers", showlegend=False,
                    marker=dict(size=8, color=df.water_stress_mm, colorscale=[[0, "#dfe8de"], [1, T["rice"]]], opacity=0.9, line=dict(color=T["surface"], width=1),
                                colorbar=dict(title=dict(text="Water stress (mm)", side="top", font=dict(size=12)), thickness=12, len=0.8, tickfont=dict(size=12), x=1.0, xpad=6)),
                    text=[plan_label(p) for p in df.plan], customdata=df.water_stress_mm,
                    hovertemplate="%{text}<br>Average: Rs %{x:,.0f}<br>Bad years: Rs %{y:,.0f}<br>Water stress: %{customdata:,.0f} mm<extra></extra>")
    fr = df[df.on_frontier].sort_values("mean_profit")
    fig.add_scatter(x=fr.mean_profit, y=fr.worst10_profit, mode="lines", name="Best trade-offs", line=dict(color=T["ink"], width=2, dash="dot"), hoverinfo="skip")
    t = df[df.id == top_id].iloc[0]
    fig.add_scatter(x=[t.mean_profit], y=[t.worst10_profit], mode="markers+text", name="Recommended", text=["Recommended"], textposition="top left",
                    textfont=dict(size=14, color=T["ink"]), marker=dict(size=17, color=T["jowar"], line=dict(color=T["ink"], width=2.5), symbol="diamond"),
                    hovertemplate=plan_label(t.plan) + "<extra>Recommended</extra>")
    _layout(fig, 460, xt="Average plan profit over 4 years (Rs per acre)", yt="Profit in the worst 10% of seasons (Rs per acre)", legend=False)
    return fig


_RICE_STEPS = {4: (0.46, 0.10, 240), 3: (0.56, 0.09, 205), 2: (0.66, 0.10, 160), 1: (0.74, 0.13, 115), 0: (0.78, 0.15, 85)}


def winner_colors(ids):
    """Colour by rice share (4 rice years = water blue ... 0 = ochre), with small lightness steps when several winners share a count."""
    out, seen = {}, {}
    for i in sorted(ids, key=lambda s: (-s.split("-").count("rice"), s)):
        n = i.split("-").count("rice")
        k = seen.get(n, 0); seen[n] = k + 1
        L, C, H = _RICE_STEPS[n]
        out[i] = oklch(min(0.9, L + 0.07 * k), C, H)
    return out


def plan_colors(tp):
    """One colour per plan id, shared by every chart on the Tipping Points tab."""
    ids = {w for row in tp["grid"]["winner"] for w in row}
    for c in tp["rainfall_crossover"].get("crossovers", []):
        ids |= {c["from"], c["to"]}
    ids |= set(tp["rainfall_crossover"].get("winner", [])[:1]) | set(tp["late_monsoon"]["rotations"])
    return winner_colors(ids)


def tipping_grid(g, irr_now, colors):
    ids = sorted({w for row in g["winner"] for w in row}, key=lambda s: (-s.split("-").count("rice"), s))
    idx = {k: i for i, k in enumerate(ids)}
    n = max(1, len(ids))
    z = [[idx[w] for w in row] for row in g["winner"]]
    cs = []
    for i, k in enumerate(ids):
        cs += [[i / n, colors[k]], [(i + 1) / n, colors[k]]]
    text = [[plan_label(w) for w in row] for row in g["winner"]]
    fig = go.Figure(go.Heatmap(x=g["rain_mult"], y=g["irrigation_mm"], z=z, colorscale=cs, zmin=-0.5, zmax=n - 0.5, showscale=False, xgap=2, ygap=2, text=text,
                               hovertemplate="Rain %{x:.2f} times usual<br>%{y:,.0f} mm irrigation water<br>Best: %{text}<extra></extra>"))
    xs = [m for m, t in zip(g["rain_mult"], g["rice_shift_threshold_mm"]) if t is not None]
    ys = [t for t in g["rice_shift_threshold_mm"] if t is not None]
    if xs:
        fig.add_scatter(x=xs, y=ys, mode="lines+markers", name="Shift to rice", line=dict(color=T["ink"], width=2.5, dash="dash", shape="hv"),
                        marker=dict(size=6, color=T["ink"]), hovertemplate="Rice-majority wins above %{y:,.0f} mm<extra></extra>", showlegend=False)
    fig.add_scatter(x=[1.0], y=[irr_now], mode="markers+text", text=["Your farm"], textposition="top right", textfont=dict(size=15, color=T["ink"]),
                    marker=dict(size=18, color="#ffffff", line=dict(color=T["ink"], width=3.5)), hovertemplate="Your farm: usual rain, %{y:,.0f} mm irrigation<extra></extra>", showlegend=False)
    _layout(fig, 520, xt="Monsoon rainfall compared with usual (1.0 = usual)", yt="Irrigation water available (mm per season)", legend=False)
    fig.update_xaxes(gridcolor="rgba(0,0,0,0)", tickmode="array", tickvals=g["rain_mult"]); fig.update_yaxes(gridcolor="rgba(0,0,0,0)")
    return fig, [(plan_label(k), colors[k]) for k in ids]


def crossover(xo, colors):
    fig = go.Figure()
    band = xo.get("band") or {}
    if band.get("p10") is not None and band.get("p90") is not None:
        fig.add_vrect(x0=band["p10"], x1=band["p90"], fillcolor=T["accent"], opacity=0.14, line_width=0, annotation_text="10th to 90th percentile", annotation_position="top left", annotation_font=dict(size=12, color=T["ink2"]))
    names = xo["candidates"]
    P = np.array(xo["mean_profit"])
    show = []
    for c in xo.get("crossovers", []):
        for k in (c["from"], c["to"]):
            if k not in show:
                show.append(k)
    show = show[:4] or [xo["winner"][0]]
    cols = {k: colors[k] for k in show}
    for k in show:
        fig.add_scatter(x=xo["rain_mult"], y=P[:, names.index(k)], mode="lines", name=plan_label(k), line=dict(color=cols[k], width=3),
                        hovertemplate="Rain %{x:.2f} times usual: Rs %{y:,.0f}<extra>" + plan_label(k) + "</extra>")
    if xo.get("crossovers"):
        c0 = xo["crossovers"][0]["rain_mult"]
        fig.add_vline(x=c0, line=dict(color=T["ink"], dash="dash", width=2), annotation_text=f"Switch near {c0:.2f}", annotation_position="bottom right", annotation_font=dict(size=14))
    _layout(fig, 380, xt="Monsoon rainfall compared with usual (1.0 = usual)", yt="Mean plan profit (Rs per acre)", legend=False)
    return fig, [(plan_label(k), cols[k]) for k in show]


def late_monsoon(lm, colors):
    fig = go.Figure()
    items = []
    for i, (k, r) in enumerate(lm["rotations"].items()):
        items.append((plan_label(k), colors[k]))
        fig.add_scatter(x=lm["days"], y=r["mean_profit"], mode="lines+markers", name=plan_label(k), line=dict(width=2.5, color=colors[k]),
                        marker=dict(size=8, line=dict(color=T["surface"], width=2)), hovertemplate="%{x} days late: Rs %{y:,.0f}<extra>" + plan_label(k) + "</extra>")
    _layout(fig, 320, xt="Days the early monsoon rain arrives late", yt="Mean plan profit (Rs per acre)", legend=False)
    return fig, items


def hindcast_scatter(d, crop, farm=None):
    fig = go.Figure()
    fig.add_scatter(x=d["observed_anomaly"], y=d["modeled_anomaly"], mode="markers", text=d["years"], name="District years",
                    marker=dict(size=10, color=CROP_COLOR[crop], line=dict(color=T["surface"], width=2)), hovertemplate="%{text}<br>District: %{x:+,.0f}<br>Model: %{y:+,.0f}<extra></extra>")
    lim = max(max(abs(v) for v in d["observed_anomaly"]), max(abs(v) for v in d["modeled_anomaly"])) * 1.1
    fig.add_scatter(x=[-lim, lim], y=[-lim, lim], mode="lines", line=dict(color=T["ash"], dash="dot", width=1.5), name="Perfect match", hoverinfo="skip")
    _layout(fig, 400, xt="District yield, change from trend (kg per ha)", yt="Model yield, change from trend (kg per ha)")
    fig.update_yaxes(scaleanchor="x", scaleratio=1)
    return fig
