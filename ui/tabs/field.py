import html
import json
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from ui import charts, data
from ui.components import REGIONAL, badge, md, section, stat, stats, tab_head
from ui.theme import CROP_LABEL

GIBS_FILE = Path(__file__).resolve().parents[2] / "data" / "gibs_layers.json"


def _gibs_layers():
    """Primary SMAP and NDVI layers from data/gibs_layers.json (written by the NASA data step)."""
    try:
        raw = json.loads(GIBS_FILE.read_text())
        out = []
        for group, kind in (("soil_moisture", "Soil moisture"), ("ndvi", "Vegetation greenness (NDVI)")):
            pid = raw.get("primary", {}).get(group)
            for l in raw["layers"].get(group, []):
                if l["id"] == pid and l.get("tile_url_template"):
                    zoom = int(l["tile_matrix_set"][0].rsplit("Level", 1)[1])
                    out.append(dict(label=kind, url=l["tile_url_template"], title=l.get("title", l["id"]), id=l["id"],
                                    date=(l.get("verified_tile") or {}).get("date") or l.get("last_date"), zoom=zoom))
        return out or None
    except Exception:
        return None


def render():
    tab_head("My Field", "Tell the tool about your land and water. Every other tab updates from these three inputs.")
    fs = data.field_summary()
    reg, cl, soil = fs["region"], fs["climate"], fs["soil"]

    c1, c2, c3 = st.columns([1, 1, 1.2], gap="large")
    with c1:
        st.slider("Irrigation water available per season (mm)", 0, 1500, step=50, value=data.V()["irrigation_mm"], **data.bind("irrigation_mm"),
                  help="Water you can count on from a borewell, tank or canal in a normal year, spread over one acre-season.")
        md(f'{badge("local" if data.V()["irrigation_mm"] != data.DEFAULTS["irrigation_mm"] else "assumption")} <span style="font-size:.86rem;color:var(--ink2)">Starting value until you enter your own figure.</span>')
    with c2:
        st.checkbox("I have a soil test for water holding capacity", value=data.V()["use_soil_test"], **data.bind("use_soil_test"))
        if data.V()["use_soil_test"]:
            st.number_input("Soil water holding capacity (mm per metre of soil)", 40, 300, step=5, value=int(data.V()["soil_awc"]), **data.bind("soil_awc"))
            md(badge("local"))
        else:
            md(f'<span style="font-size:.92rem;color:var(--ink2)">Using the regional soil default of {soil["awc_mm_per_m"]:.0f} mm per metre.</span> {badge(soil.get("badge", "placeholder"))}')
    with c3:
        st.markdown("**Your current rotation (one crop per year)**")
        cols = st.columns(4)
        for i, col in enumerate(cols):
            with col:
                st.selectbox(f"Year {i+1}", data.CROPS, index=data.CROPS.index(data.V()[f"rot{i}"]), format_func=CROP_LABEL.get, **data.bind(f"rot{i}"))
        md(f'{badge("local")} <span style="font-size:.86rem;color:var(--ink2)">Compared against rotations A, B and C.</span>')

    st.markdown("&nbsp;")
    left, right = st.columns([1.45, 1], gap="large")
    with left:
        section("Where the model is looking")
        m = folium.Map(location=[reg["lat"], reg["lon"]], zoom_start=8, tiles="OpenStreetMap", control_scale=True)
        layers = _gibs_layers()
        if layers:
            names = ["No satellite layer"] + [l["label"] for l in layers]
            pick = st.radio("NASA satellite layer", names, horizontal=True, key="gibs_pick")
            for l in layers:
                if l["label"] == pick:
                    folium.TileLayer(tiles=l["url"], attr="NASA GIBS", name=l["label"], overlay=True, opacity=0.75, max_native_zoom=l["zoom"], max_zoom=12).add_to(m)
                    md(f'{badge("observed")} <span style="font-size:.9rem">{html.escape(l["title"])}, image dated {l["date"]}. Layer id {l["id"]}.</span>')
        else:
            md(f'{badge("placeholder")} <span style="font-size:.92rem">Satellite layers are unavailable: <code>data/gibs_layers.json</code> could not be read. The model does not depend on them.</span>')
        folium.Marker([reg["lat"], reg["lon"]], tooltip="Demo location" if reg.get("dev_placeholder") else "Farm location",
                      icon=folium.Icon(color="darkblue", icon="circle", prefix="fa")).add_to(m)
        st_folium(m, height=400, use_container_width=True, returned_objects=[], key="map")
        if reg.get("dev_placeholder"):
            md(f'<p class="rl-note">{badge("placeholder")} The pin is a demo point ({reg["lat"]}, {reg["lon"]}), not the real farm. District: {reg["district"]}.</p>')
        md(f'<p class="rl-note">{REGIONAL}</p>')
    with right:
        section("What the record shows")
        yrs = f'Regional estimate, mean of {cl["first_year"]} to {cl["last_year"]}'
        stats([
            stat("Rain in a typical year", f'{cl["annual_rain_mm"]:,.0f}', "mm", cl.get("badge", "observed"), yrs),
            stat("Of which June to September", f'{cl["monsoon_rain_mm"]:,.0f}', "mm", cl.get("badge", "observed"), "Regional estimate"),
        ])
        stats([stat("Soil water held per metre", f'{soil["awc_mm_per_m"]:.0f}', "mm", soil.get("badge", "placeholder"), "Default until you enter a soil test")])
        if cl.get("note"):
            md(f'<p class="rl-note">{html.escape(cl["note"])}. {badge(cl.get("badge", "observed"))}</p>')

    yh = fs.get("yield_history")
    if yh:
        yh = pd.DataFrame(yh)
        section("District yield history", "placeholder" if data.is_mock() else "observed",
                "Average yields for the district, all farms together. Rice here mixes irrigated and rainfed fields.")
        charts.show(charts.yield_history(yh), "yh")
        with st.expander("Show these numbers as a table"):
            t = yh.pivot_table(index="year", columns="crop", values="yield_kg_ha").rename(columns=CROP_LABEL).round(0).reset_index().rename(columns={"year": "Year"})
            st.dataframe(t, hide_index=True, use_container_width=True)
    else:
        section("District yield history")
        md(f'<p>{badge("placeholder")} No district yield data is loaded yet, so nothing is shown. Nothing has been made up.</p>')
