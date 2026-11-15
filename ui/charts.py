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
SHORT = {"A": "A today", "B": "B", "C": "C", "current": "Yours"}
NAMES = {"A": "A: our farm today (all rice)", "B": "B: rice and millet", "C": "C: rice, pigeon pea, millet", "current": "Your rotation"}


def _layout(fig, h=380, xt=None, yt=None, legend=True):
    fig.update_layout(
        height=h, margin=dict(l=8, r=14, t=14, b=18), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=14, color=T["ink"]),
        hoverlabel=dict(bgcolor=T["surface"], bordercolor=T["line"], font=dict(family=FONT, size=14, color=T["ink"])),
        showlegend=legend, legend=dict(orientation="h", y=-0.2, x=0, font=dict(size=13)),
    )
    ax = dict(gridcolor=T["line"], zeroline=False, linecolor=T["line"], tickfont=dict(size=12, color=T["ink2"]), automargin=True)
    fig.update_xaxes(title=dict(text=xt, font=dict(size=13, color=T["ink2"])) if xt else None, **ax)
    fig.update_yaxes(title=dict(text=yt, font=dict(size=13, color=T["ink2"])) if yt else None, **ax)
    return fig


def show(fig, key):
    st.plotly_chart(fig, width="stretch", config=CONFIG, key=key)


def offline_map(region):
    import json
    from pathlib import Path
    outline = json.loads((Path(__file__).resolve().parents[1] / "assets/nalgonda_outline.json").read_text())
    fig = go.Figure()
    for ring in outline["outlines"]:
        xy = np.asarray(ring)
        fig.add_scatter(x=xy[:, 0], y=xy[:, 1], mode="lines", fill="toself", fillcolor=T["accent_soft"],
                        line=dict(color=T["accent"], width=2), hoverinfo="skip", showlegend=False)
    fig.add_scatter(x=[region["lon"]], y=[region["lat"]], mode="markers+text", text=["NASA POWER district point"],
                    textposition="top center", marker=dict(size=12, color=T["rice"]), showlegend=False,
                    hovertemplate="Nalgonda district centroid<br>%{y:.3f} N, %{x:.3f} E<extra></extra>")
    _layout(fig, 400, xt="Longitude", yt="Latitude", legend=False)
    fig.update_yaxes(scaleanchor="x", scaleratio=1)
    return fig


def yield_history(df):
    fig = go.Figure()
    xmax = int(df.year.max())
    for c in ("rice", "jowar", "bajra", "ragi", "pigeonpea"):
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
    if "A" in rots:
        base = float(np.mean(rots["A"]["profit"]))
        fig.add_hline(y=base, line=dict(color=T["ink"], width=1.5, dash="dot"))
        fig.add_annotation(x=1, xref="paper", xanchor="right", y=base, yanchor="bottom", text="Our farm today, mean", showarrow=False, font=dict(size=12, color=T["ink2"]))
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


WELL = oklch(0.58, 0.10, 195)


def water_bars(rots):
    names = [SHORT.get(k, k) for k in rots]
    split = all("irrigation_canal_mm" in r for r in rots.values())
    irr = [r["irrigation_mm"] for r in rots.values()]
    rain = [max(0.0, r["total_water_mm"] - r["irrigation_mm"]) for r in rots.values()]
    canal = [r.get("irrigation_canal_mm", 0.0) for r in rots.values()]
    well = [r.get("irrigation_well_mm", 0.0) for r in rots.values()]
    fig = go.Figure()
    fig.add_bar(y=names, x=rain, orientation="h", name="Rain", marker=dict(color=T["accent_soft"], line=dict(color=T["accent"], width=1.5)), hovertemplate="%{x:,.0f} mm rain<extra>%{y}</extra>")
    if split:
        fig.add_bar(y=names, x=canal, orientation="h", name="Canal", marker=dict(color=T["rice"]), hovertemplate="%{x:,.0f} mm canal water<extra>%{y}</extra>")
        fig.add_bar(y=names, x=well, orientation="h", name="Well", marker=dict(color=WELL), hovertemplate="%{x:,.0f} mm well water<extra>%{y}</extra>")
    else:
        fig.add_bar(y=names, x=irr, orientation="h", name="Irrigation", marker=dict(color=T["rice"]), hovertemplate="%{x:,.0f} mm irrigation<extra>%{y}</extra>")
    _layout(fig, 300, xt="Water over the 4-year plan (mm)", legend=False)
    fig.update_layout(barmode="stack", bargap=0.35)
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)")
    return fig, (canal, well) if split else None, names


def irrigation_only(names, irr, split=None):
    fig = go.Figure()
    if split:
        canal, well = split
        fig.add_bar(y=names, x=canal, orientation="h", name="Canal", marker=dict(color=T["rice"]), hovertemplate="%{x:,.0f} mm canal<extra>%{y}</extra>")
        fig.add_bar(y=names, x=well, orientation="h", name="Well", marker=dict(color=WELL), hovertemplate="%{x:,.0f} mm well<extra>%{y}</extra>",
                    text=[f"{c + w:,.0f} mm" for c, w in zip(canal, well)], textposition="outside", cliponaxis=False)
        fig.update_layout(barmode="stack")
        mx = max(c + w for c, w in zip(canal, well))
    else:
        fig.add_bar(y=names, x=irr, orientation="h", marker=dict(color=T["rice"]), text=[f"{v:,.0f} mm" for v in irr], textposition="outside", cliponaxis=False,
                    hovertemplate="%{x:,.0f} mm<extra>%{y}</extra>")
        mx = max(irr + [1])
    _layout(fig, 300, xt="Irrigation water by source (mm)", legend=False)
    fig.update_yaxes(autorange="reversed", showticklabels=False, gridcolor="rgba(0,0,0,0)")
    fig.update_xaxes(range=[0, max(mx, 1) * 1.3])
    return fig


def residue_lines(rots):
    fig = go.Figure()
    for rid, r in rots.items():
        fig.add_scatter(x=[f"Year {i+1}" for i in range(4)], y=list(r["residue_index"]), mode="lines+markers", name=NAMES.get(rid, rid),
                        line=dict(color=ROT_COLOR.get(rid, T["mixed"]), width=2.5), marker=dict(size=8, line=dict(color=T["surface"], width=2)),
                        hovertemplate="%{y:.2f}<extra>" + NAMES.get(rid, rid) + "</extra>")
    _layout(fig, 320, yt="Soil cover proxy (1 = best modeled yield for that crop)", legend=False)
    return fig


def pareto(df, top_id, base_id="rice-rice-rice-rice"):
    fig = go.Figure()
    fig.add_scatter(x=df.mean_profit, y=df.worst10_profit, mode="markers", showlegend=False,
                    marker=dict(size=8, color=df.irrigation_mm, colorscale=[[0, "#dfe8de"], [1, T["rice"]]], opacity=0.9, line=dict(color=T["surface"], width=1),
                                colorbar=dict(title=dict(text="Irrigation, mm", side="top", font=dict(size=12)), thickness=12, len=0.8, tickfont=dict(size=12), x=1.0, xpad=6)),
                    text=[plan_label(p) for p in df.plan], customdata=df.irrigation_mm,
                    hovertemplate="%{text}<br>Average: Rs %{x:,.0f}<br>Bad years: Rs %{y:,.0f}<br>Irrigation: %{customdata:,.0f} mm<extra></extra>")
    fr = df[df.on_frontier].sort_values("mean_profit")
    fig.add_scatter(x=fr.mean_profit, y=fr.worst10_profit, mode="lines", name="Best trade-offs", line=dict(color=T["ink"], width=2, dash="dot"), hoverinfo="skip")
    t = df[df.id == top_id].iloc[0]
    fig.add_scatter(x=[t.mean_profit], y=[t.worst10_profit], mode="markers+text", name="Recommended", text=["Recommended"], textposition="top left",
                    textfont=dict(size=14, color=T["ink"]), marker=dict(size=17, color=T["jowar"], line=dict(color=T["ink"], width=2.5), symbol="diamond"),
                    hovertemplate=plan_label(t.plan) + "<extra>Recommended</extra>")
    b = df[df.id == base_id]
    if len(b):
        b = b.iloc[0]
        fig.add_scatter(x=[b.mean_profit], y=[b.worst10_profit], mode="markers+text", name="Our farm today", text=["Our farm today"], textposition="bottom right",
                        textfont=dict(size=14, color=T["ink"]), marker=dict(size=15, color="#ffffff", line=dict(color=T["ink"], width=3)),
                        hovertemplate="Our farm today (rice every year)<extra></extra>")
    _layout(fig, 460, xt="Average plan profit over 4 years (Rs per acre)", yt="Profit in the worst 10% of weather sequences (Rs per acre)", legend=False)
    return fig


def winner_colors(ids):
    """Colour a plan by its dominant crop (non-rice crops win ties), the crop palette used everywhere else.
    Plans sharing a dominant crop get small lightness steps; the legend spells out each full plan."""
    out, seen = {}, {}
    def dom(pid):
        crops = pid.split("-")
        counts = {c: crops.count(c) for c in set(crops)}
        return sorted(counts, key=lambda c: (-counts[c], c == "rice", c))[0]
    for i in sorted(ids, key=lambda s: (dom(s), -s.split("-").count("rice"), s)):
        d = dom(i)
        k = seen.get(d, 0); seen[d] = k + 1
        base = CROP_COLOR[d]
        out[i] = base if k == 0 else _shift(base, 0.09 * ((k + 1) // 2) * (1 if k % 2 else -1))
    return out


def _shift(hexcol, dl):
    """Lighten or darken a hex colour in sRGB by a small amount (used only to tell sibling plans apart)."""
    r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    f = lambda v: max(0, min(255, round(v + dl * 255)))
    return "#%02x%02x%02x" % (f(r), f(g), f(b))


def plan_colors(tp):
    """One colour per plan id, shared by every chart on the Tipping Points tab."""
    ids = {w for row in tp["grid"]["winner"] for w in row}
    ids |= {w for row in (tp.get("grid_upstream_local") or {}).get("winner", []) for w in row}
    for c in tp["rainfall_crossover"].get("crossovers", []):
        ids |= {c["from"], c["to"]}
    ids |= set(tp["rainfall_crossover"].get("winner", [])[:1]) | set(tp["late_monsoon"]["rotations"])
    return winner_colors(ids)


def tipping_grid(g, irr_now, colors, xkey="rain_mult", ykey="irrigation_mm", xt="Monsoon rainfall compared with usual (1.0 = usual)", yt="Irrigation water available (mm per season)", farm=None, hov=None):
    ids = sorted({w for row in g["winner"] for w in row}, key=lambda s: (-s.split("-").count("rice"), s))
    idx = {k: i for i, k in enumerate(ids)}
    n = max(1, len(ids))
    z = [[idx[w] for w in row] for row in g["winner"]]
    cs = []
    for i, k in enumerate(ids):
        cs += [[i / n, colors[k]], [(i + 1) / n, colors[k]]]
    text = [[plan_label(w) for w in row] for row in g["winner"]]
    fig = go.Figure(go.Heatmap(x=g[xkey], y=g[ykey], z=z, colorscale=cs, zmin=-0.5, zmax=n - 0.5, showscale=False, xgap=2, ygap=2, text=text,
                               hovertemplate=(hov or "Rain %{x:.2f} times usual<br>%{y:,.0f} mm irrigation water<br>Best: %{text}<extra></extra>")))
    thr_l = g.get("rice_shift_threshold_mm") or []
    xs = [m for m, t in zip(g[xkey], thr_l) if t is not None]
    ys = [t for t in thr_l if t is not None]
    if xs:
        fig.add_scatter(x=xs, y=ys, mode="lines+markers", name="Shift to rice", line=dict(color=T["ink"], width=2.5, dash="dash", shape="hv"),
                        marker=dict(size=6, color=T["ink"]), hovertemplate="Rice-majority wins above %{y:,.0f} mm<extra></extra>", showlegend=False)
    band = g.get("boundary_band")
    if band:
        fig.add_scatter(x=g[xkey], y=band["p90"], mode="lines", line=dict(width=0), hoverinfo="skip", showlegend=False)
        fig.add_scatter(x=g[xkey], y=band["p10"], mode="lines", line=dict(width=0), fill="tonexty",
                        fillcolor="rgba(22,38,43,0.15)", name="Boundary, 10th-90th percentile", showlegend=False,
                        hovertemplate="Bootstrap lower boundary: %{y:,.0f} mm<extra></extra>")
    fx, fy = farm if farm else (1.0, irr_now)
    fig.add_scatter(x=[fx], y=[fy], mode="markers",
                    marker=dict(size=18, color="#ffffff", line=dict(color=T["ink"], width=3.5)), hovertemplate="Our farm today<extra></extra>", showlegend=False)
    fig.add_annotation(x=fx, y=fy, text="Our farm today", showarrow=True, ax=0, ay=-34, arrowcolor=T["ink"], arrowwidth=1.5, arrowhead=0,
                       bgcolor="#ffffff", bordercolor=T["ink"], borderwidth=1, borderpad=4, font=dict(size=14, color=T["ink"]))
    _layout(fig, 520 if ykey == "irrigation_mm" else 440, xt=xt, yt=yt, legend=False)
    fig.update_xaxes(gridcolor="rgba(0,0,0,0)", tickmode="array", tickvals=g[xkey], tickformat=".2f" if xkey != "rain_mult" else None); fig.update_yaxes(gridcolor="rgba(0,0,0,0)")
    return fig, [(plan_label(k), colors[k]) for k in ids]


def crossover(xo, colors):
    fig = go.Figure()
    band = xo.get("band") or {}
    if band.get("p10") is not None and band.get("p90") is not None:
        fig.add_vrect(x0=band["p10"], x1=band["p90"], fillcolor=T["accent"], opacity=0.14, line_width=0, annotation_text="10th to 90th percentile", annotation_position="top left", annotation_font=dict(size=12, color=T["ink2"]))
    names = xo["candidates"]
    P = np.array(xo["J"])
    show = ["rice-rice-rice-rice"] if "rice-rice-rice-rice" in names else []
    for c in xo.get("crossovers", []):
        for k in (c["from"], c["to"]):
            if k not in show:
                show.append(k)
    if xo["winner"][0] not in show:
        show.append(xo["winner"][0])
    show = show[:5]
    cols = {k: colors[k] for k in show}
    for k in show:
        fig.add_scatter(x=xo["rain_mult"], y=P[:, names.index(k)], mode="lines", name=plan_label(k), line=dict(color=cols[k], width=3),
                        hovertemplate="Rain %{x:.2f} times usual: Rs %{y:,.0f}<extra>" + plan_label(k) + "</extra>")
    if xo.get("crossovers"):
        c0 = xo["crossovers"][0]["rain_mult"]
        fig.add_vline(x=c0, line=dict(color=T["ink"], dash="dash", width=2), annotation_text=f"Switch near {c0:.2f}", annotation_position="bottom right", annotation_font=dict(size=14))
    _layout(fig, 380, xt="Monsoon rainfall compared with usual (1.0 = usual)", yt="Priority score, J (Rs per acre)", legend=False)
    return fig, [(plan_label(k), cols[k]) for k in show]


def late_monsoon(lm, colors):
    fig = go.Figure()
    items = []
    for i, (k, r) in enumerate(lm["rotations"].items()):
        items.append((plan_label(k), colors[k]))
        fig.add_scatter(x=lm["days"], y=r["J"], mode="lines+markers", name=plan_label(k), line=dict(width=2.5, color=colors[k]),
                        marker=dict(size=8, line=dict(color=T["surface"], width=2)), hovertemplate="%{x} days late: Rs %{y:,.0f}<extra>" + plan_label(k) + "</extra>")
    _layout(fig, 320, xt="Days onset and sowing are delayed", yt="Priority score, J (Rs per acre)", legend=False)
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


def validation_history(d, crop, farm=None):
    """Untransformed yield histories; farm observations are never fabricated anomalies."""
    import pandas as pd
    fig = go.Figure()
    fig.add_scatter(x=d["years"], y=d["observed"], mode="lines+markers", name="District observed", line=dict(color=T["ink"], width=2))
    fig.add_scatter(x=d["years"], y=d["modeled"], mode="lines", name="Model", line=dict(color=CROP_COLOR[crop], width=2.5))
    if farm and farm.get("rows"):
        rows = pd.DataFrame(farm["rows"])
        rows = rows[rows.crop == crop]
        if not rows.empty:
            totals = rows.groupby("year")[["yield_quintals", "area_acres"]].sum()
            values = totals.yield_quintals * 100 / (totals.area_acres * .404686)
            fig.add_scatter(x=values.index, y=values, mode="markers", name="Farm records (local input)",
                            marker=dict(symbol="diamond", size=12, color=T["jowar"], line=dict(color=T["ink"], width=1)))
    if d.get("heldout_years"):
        fig.add_vrect(x0=min(d["heldout_years"]) - .5, x1=max(d["heldout_years"]) + .5, fillcolor=T["accent"], opacity=.08, line_width=0)
    return _layout(fig, 340, xt="Year (shaded years held out)", yt="Yield (kg per hectare)")
