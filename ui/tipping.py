# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Tipping Points page (Build Spec v4 R18). Feature 2.

    render(site=None, inputs=None, sliders=None, result=None)

Plain Streamlit only: default theme, default chart colors, no CSS. Data labels go through badge() from
ui/components.py (see _badge).

The page shows numbers from engine/tipping.py and computes nothing itself except display formatting.
If site, inputs or sliders are not passed, they are read from st.session_state under the same names.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

_WORDS = {"observed": "Observed", "estimated": "Estimated", "your_input": "Your input", "assumption": "Assumption",
          "example": "EXAMPLE DATA"}
_MODES = {"historical": "Historical", "recent": "Recent (last 20 years count double)",
          "trend": "Continuing trend (10 years ahead)"}


def _badge(kind: str) -> str:
    """A data label from the shared badge() in ui/components.py (a small HTML label with a hover note). If that
    cannot be loaded, the same word in code style."""
    try:
        from ui.components import badge as shared
        out = shared(kind)
        if isinstance(out, str) and out:
            return f"Data label: {out}"
    except Exception:
        pass
    return f"Data label: `{_WORDS.get(kind, str(kind))}`"


def _md(text: str) -> None:
    st.markdown(text, unsafe_allow_html=True)        # a shared badge() may return a small HTML label


def _cap(text: str) -> None:
    st.caption(text, unsafe_allow_html=True)


def _get(obj, key, default=None):
    if obj is None:
        return default
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _signature(site, inputs, sliders) -> str:
    """Changes whenever the farm, its answers or the climate setting change (the result is kept until then)."""
    w = _get(site, "weather")
    water = _get(inputs, "water")
    return repr((id(w), len(w) if w is not None else 0, _get(_get(site, "soil"), "awc_mm_per_m"),
                 _get(inputs, "current_plan"), _get(water, "mode"), _get(water, "normal_mm"), _get(water, "dry_mm"),
                 sorted((str(k), repr(v)) for k, v in (_get(inputs, "crop_overrides") or {}).items()),
                 [(k, _get(sliders, k)) for k in ("bad_year", "water", "soil", "profit_tolerance_pct", "climate_shift")]))


def compute(site, inputs, sliders) -> dict:
    """The tipping analysis for this farm, worked out once and kept in the session until an input changes."""
    from engine import api as tipping
    sig = _signature(site, inputs, sliders)
    kept = st.session_state.get("_tipping_result")
    if kept and kept[0] == sig:
        return kept[1]
    bar = st.progress(0.0, text="Checking what-if climates")

    def progress(done, total, text):
        bar.progress(min(done / max(total, 1), 1.0), text=f"{text} ({done} of {total})")
    result = tipping.tipping_points(site, inputs, sliders, progress=progress)
    bar.empty()
    st.session_state["_tipping_result"] = (sig, result)
    return result


ACRES_PER_HECTARE = 2.4710538147


def _area() -> tuple[str, float]:
    """The area unit the farmer picked in the app ('Metric units' switch), and the factor that turns a per-hectare
    value into it. Outside the app shell the engine's own unit (hectare) is shown. Display conversion only."""
    if st.session_state.get("v4_metric", True):
        return "hectare", 1.0
    return "acre", 1.0 / ACRES_PER_HECTARE


def _curve_frame(curve: dict, scale: float = 1.0) -> pd.DataFrame:
    k = scale if curve["metric"]["name"] == "profit" else 1.0     # only money is per area; yield shares stay as they are
    rows = []
    for name, mean in curve["series"].items():
        for i, x in enumerate(curve["x"]):
            rows.append({"x": x, "Plan": name, "Average": mean[i] * k, "Low (10th percentile)": curve["band"]["p10"][name][i] * k,
                         "High (90th percentile)": curve["band"]["p90"][name][i] * k, "Best plan here": curve["winner"][i]})
    return pd.DataFrame(rows)


def _curve_chart(curve: dict, unit: str = "hectare", scale: float = 1.0):
    df = _curve_frame(curve, scale)
    x = alt.X("x:Q", title=curve["x_label"], scale=alt.Scale(zero=False))
    tips = ["Plan", alt.Tooltip("x:Q", title=curve["x_label"]), alt.Tooltip("Average:Q", format=",.0f"),
            alt.Tooltip("Low (10th percentile):Q", format=",.0f"), alt.Tooltip("High (90th percentile):Q", format=",.0f"),
            "Best plan here"]
    y_title = f"Profit per {unit} per year" if curve["metric"]["name"] == "profit" else "Share of best possible yield (%)"
    legend = alt.Legend(orient="bottom", direction="vertical", labelLimit=600, title="Plan")
    band = alt.Chart(df).mark_area(opacity=0.2).encode(x=x, y=alt.Y("Low (10th percentile):Q", title=y_title),
                                                      y2="High (90th percentile):Q", color=alt.Color("Plan:N", legend=None))
    line = alt.Chart(df).mark_line(point=True).encode(x=x, y=alt.Y("Average:Q", title=y_title),
                                                      color=alt.Color("Plan:N", legend=legend), tooltip=tips)
    layers = [band, line]
    if curve.get("current_x") is not None:
        layers.append(alt.Chart(pd.DataFrame({"x": [curve["current_x"]], "label": ["your farm now"]}))
                      .mark_rule(strokeDash=[4, 4]).encode(x="x:Q", tooltip=["label"]))
    # the height covers the plot, the axis and the legend under it (one legend line per plan)
    return alt.layer(*layers).resolve_legend(color="independent").properties(height=380 + 24 * len(curve["series"]))


def _show_curve(title: str, curve: dict, lead: str, fmt, unit: str = "hectare", scale: float = 1.0) -> None:
    st.subheader(title)
    _cap(f"{lead} Line = average over 500 weather plans; shaded band = 10th to 90th percentile. "
               f"Dashed line = your farm now. {_badge('estimated')}")
    st.altair_chart(_curve_chart(curve, unit, scale), width="stretch")
    if curve["crossover_details"]:
        for d in curve["crossover_details"]:
            how = (f"10th to 90th percentile {fmt(d['p10'])} to {fmt(d['p90'])}" if d["by"] == "average"
                   else f"between {fmt(d['between'][0])} and {fmt(d['between'][1])}, set by your risk and soil settings")
            st.markdown(f"- **Tipping point near {fmt(d['at'])}** ({how}): below it **{d['from']}**, above it **{d['to']}**.")
    else:
        st.markdown("- No tipping point here: the best plan stays **" + curve["winner"][0] + "** across this whole range.")
    if curve.get("note"):
        st.caption(curve["note"])
    with st.expander("Numbers behind this chart"):
        st.dataframe(_curve_frame(curve, scale).rename(columns={"x": curve["x_label"]}), hide_index=True)


def _show_map(m: dict) -> None:
    st.subheader("Rainfall and water map")
    _cap(f"Each square is one what-if: a rainfall level (across) and a water supply (up). Its color is the plan "
               f"that comes out best there. {_badge('estimated')}")
    rows = [{"Rainfall": f"{r:.1f}x", "Water supply": f"{w:.0f} mm", "Best plan": m["winner"][i][j], "rain": r, "water": w}
            for i, w in enumerate(m["water_mm"]) for j, r in enumerate(m["rain_mult"])]
    df = pd.DataFrame(rows)
    x = alt.X("Rainfall:O", sort=[f"{r:.1f}x" for r in m["rain_mult"]], title="Rainfall (1.0x = the real record)", axis=alt.Axis(labelAngle=0))
    y = alt.Y("Water supply:O", sort=[f"{w:.0f} mm" for w in sorted(m["water_mm"], reverse=True)], title="Water supply a year")
    squares = alt.Chart(df).mark_rect().encode(x=x, y=y, tooltip=["Rainfall", "Water supply", "Best plan"],
                                               color=alt.Color("Best plan:N", legend=alt.Legend(orient="bottom", direction="vertical", labelLimit=600)))
    layers = [squares]
    cur = m["current"]
    if cur.get("row") is not None:
        here = pd.DataFrame({"Rainfall": [f"{m['rain_mult'][cur['col']]:.1f}x"], "Water supply": [f"{m['water_mm'][cur['row']]:.0f} mm"],
                             "label": ["◆ your farm"], "Best plan": [cur["winner"]]})
        layers.append(alt.Chart(here).mark_text(fontWeight="bold").encode(x=x, y=y, text="label", tooltip=["label", "Best plan"]))
    st.altair_chart(alt.layer(*layers).properties(height=380 + 24 * len(m["labels"])), width="stretch")
    if cur.get("row") is not None:
        st.markdown(f"**◆ Your farm now:** the real rainfall record, {cur['text']}. Best plan there: **{cur['winner']}**.")
    else:
        st.markdown(f"**Your farm now** is not on this map: {cur['text']}. Best plan for your farm: **{cur['winner']}**.")
    if m.get("note"):
        st.caption(m["note"])
    with st.expander("The map as a table"):
        table = pd.DataFrame(m["winner"], index=[f"{w:.0f} mm" for w in m["water_mm"]], columns=[f"{r:.1f}x rain" for r in m["rain_mult"]])
        st.dataframe(table.iloc[::-1])


def render(site=None, inputs=None, sliders=None, result=None) -> None:
    st.header("Tipping points")
    st.caption("Where would a different plan become the better choice? Each view changes one thing about your farm's "
               "weather or water and finds the best plan again. These are what-if changes to real weather years, "
               "not forecasts.")
    if result is None:
        site = site if site is not None else st.session_state.get("site")
        inputs = inputs if inputs is not None else st.session_state.get("inputs")
        sliders = sliders if sliders is not None else st.session_state.get("sliders")
        if site is None or inputs is None:
            st.info("Set up your farm first (location, current crop plan and water). Tipping points appear here after that.")
            return
        try:
            result = compute(site, inputs, sliders)
        except Exception as e:
            st.error(f"The tipping points could not be worked out for this farm: {e}")
            return
    if _get(result, "example"):
        st.error("EXAMPLE DATA. These tipping points are placeholder values, not computed for this farm.")

    for line in result.get("headlines", []):
        st.markdown(f"- {line}")
    climate = result.get("climate") or {}
    if climate:
        _cap(f"Climate setting: **{_MODES.get(climate.get('mode'), climate.get('label', ''))}**. {climate.get('text', '')} "
                   f"{_badge(climate.get('badge', 'assumption'))}")

    _show_map(result["map_2d"])
    money = result["metric"]["name"] == "profit"
    unit, scale = _area()
    what = f"average profit per {unit} per year, in the currency of your prices" if money else "share of the best possible yield"
    _show_curve("If rainfall changes", result["rainfall_curve"],
                f"Every day's rain is multiplied by the value on the bottom axis. The chart shows {what}.", lambda v: f"{v:.2f}x rain", unit, scale)
    _show_curve("If your water supply changes", result["water_curve"],
                f"Irrigation water available in a year. The chart shows {what}.", lambda v: f"{v:.0f} mm", unit, scale)
    _show_curve("If it gets hotter", result["heat_curve"],
                f"Degrees added to every day's maximum temperature. The chart shows {what}.", lambda v: f"+{v:.1f} degC", unit, scale)

    with st.expander("How this was worked out"):
        method = result.get("method") or {}
        _md(f"- Weather: real years from NASA POWER, re-drawn into {method.get('scenarios_bands', 500)} four-year "
                    f"plans (seed 42). {_badge('observed')}")
        _md(f"- Best plan at each point: {method.get('winner_source', 'not recorded')}. {_badge('estimated')}")
        _md(f"- Rainfall, heat and water levels tried are fixed what-if steps. {_badge('assumption')}")
        for note in result.get("notes", []):
            st.markdown(f"- {note}")
        st.markdown("- Planting dates and each crop's best possible yield stay as they are for your farm today; "
                    "only the weather and the water supply change.")
        if method.get("seconds") is not None:
            st.caption(f"Worked out in {method['seconds']:.0f} seconds.")
