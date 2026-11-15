# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
import html
import json
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from ui import charts, data
from ui.components import REGIONAL, badge, fmt_rs, md, section, srcline, stat, stats, tab_head
from ui.data import CROP_LABEL

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
    tab_head("Our Farm", "A rice farm in Nalgonda, Telangana. It grows rice every year today. Set the water you can count on, then see what else could work.")
    with st.spinner(data.MSG["get_field_summary"]):
        fs = data.field_summary()
    reg, cl, soil = fs["region"], fs["climate"], fs["soil"]
    V = data.V()

    # --- baseline card: rotation A, rice every year (v3 section 9, tab 1)
    p = data.params()
    with st.spinner(data.MSG["recommend"]):
        rec = data.recommend(p)
    mb = "placeholder" if data.is_mock() else "modeled"
    mdf = rec["metrics"]
    a = mdf[mdf.id == "rice-rice-rice-rice"]
    if len(a):
        a = a.iloc[0]
        section("Our farm today: rice every year (Rotation A)", mb, "This is the baseline. Every other plan in the tool is shown as a difference from it.")
        stats([
            stat("Average profit over 4 years", fmt_rs(a.mean_profit), "per acre", mb, f"{fmt_rs(data.farm_total(a.mean_profit))} for {data.ACRES:,.0f} acres" if data.ACRES else ""),
            stat("In the worst 10% of weather sequences", fmt_rs(a.worst10_profit), "per acre", mb, f"{fmt_rs(data.farm_total(a.worst10_profit))} for {data.ACRES:,.0f} acres" if data.ACRES else ""),
            stat("Irrigation water over 4 years", f"{a.irrigation_mm:,.0f}", "mm", mb, f"{data.m3(a.irrigation_mm):,.0f} m3 on the farm" if data.m3(1) else ""),
        ])
        md('<p class="rl-note">District-scale estimate from regional weather, district yields and state cost surveys. It is not a measurement of this farm. Prices are this season\'s minimum support prices and do not change between years.</p>')

    # --- rice irrigation supply: canal plus well
    section("Rice irrigation water", "assumption", "Rice gets canal water first. Wells cover what the canal does not, up to their limit. By default the model works both out from rainfall. Override either one with your own figure.")
    def source_box(col, key, title, label, base):
        with col:
            md(f'<div class="rl-q" style="font-size:1.05rem">{title}</div><p class="rl-note" style="margin:.1rem 0 .5rem">{label}</p>')
            st.checkbox(f"I know my {title.split()[0].lower()} supply", value=V[f"{key}_override"], **data.bind(f"{key}_override"))
            if V[f"{key}_override"]:
                st.number_input(f"{title} (mm per season)", 0, 3000, step=50, value=int(V[f"{key}_supply"] if V[f"{key}_supply"] is not None else (base or 500)), **data.bind(f"{key}_supply"))
                md(badge("local"))
            else:
                bs = f"Model default: base {base:,.0f} mm per season, scaled by rainfall. " if base is not None else "Model default: worked out from rainfall. "
                md(f'<span style="font-size:.92rem;color:var(--ink2)">{bs}</span>{badge("assumption")} <span style="font-size:.86rem;color:var(--ink2)">team to verify</span>')
    c1, c2 = st.columns(2, gap="large")
    source_box(c1, "canal", "Canal supply (mm)", data.CANAL_LABEL, data.BASE_CANAL)
    source_box(c2, "well", "Well supply (mm)", data.WELL_LABEL, data.BASE_WELL)

    section("Soil", "local", "The farm soil is what you told us. SoilGrids is a satellite-derived estimate for the whole district.")
    fs_ = data.FARM
    rng = fs_["awc_range"]
    if isinstance(rng, (list, tuple)) and len(rng) == 2:
        awc_txt = f'{rng[0]:g} to {rng[1]:g}'
        awc_note = f'{badge("assumption")} <details style="margin-top:.4rem"><summary style="cursor:pointer;font-weight:600">Source for this range</summary><p style="margin:.3rem 0 0;font-size:.9rem">{html.escape(str(fs_["awc_source"] or "not stated"))}</p></details>'
    else:
        awc_txt = "Not set"
        awc_note = f'The black-soil water holding range has no cited source yet. {badge("assumption")} team to verify'
    try:
        from engine import fetch_soil
        fsoil = fetch_soil.farm_soil()
    except Exception:
        fsoil = None
    s1, s2 = st.columns(2, gap="large")
    with s1:
        stats([stat(html.escape(fs_["soil_name"]), awc_txt, "mm per metre" if isinstance(rng, (list, tuple)) else "", "local", "Water holding capacity range")])
        md(f'<p class="rl-note">{awc_note}</p>')
    with s2:
        stats([stat("SoilGrids, district estimate", f'{soil["awc_mm_per_m"]:.0f}', "mm per metre", soil.get("badge", "placeholder"), "Regional default")])
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            lo, hi = rng
            rel = "inside" if lo <= soil["awc_mm_per_m"] <= hi else ("below" if soil["awc_mm_per_m"] < lo else "above")
            md(f'<p class="rl-note">The district estimate of {soil["awc_mm_per_m"]:.0f} mm per metre is {rel} the black-soil range of {lo:g} to {hi:g}.</p>')
        else:
            md('<p class="rl-note">There is no black-soil range to compare with yet, so the two are shown side by side only.</p>')
    st.segmented_control("Soil used by the model", ["farm", "district"], format_func=lambda k: {"farm": "Farm soil (black soil)", "district": "District estimate (SoilGrids)"}[k],
                         default=V["soil_mode"], key="w_soil_mode", on_change=lambda: V.update(soil_mode=st.session_state.get("w_soil_mode") or "farm"))

    c2, c3 = st.columns([1, 1.2], gap="large")
    with c2:
        st.checkbox("I have a soil test for water holding capacity", value=V["use_soil_test"], **data.bind("use_soil_test"))
        if V["use_soil_test"]:
            st.number_input("Soil water holding capacity (mm per metre)", 40, 300, step=5, value=int(V["soil_awc"]), **data.bind("soil_awc"))
            md(badge("local"))
    with c3:
        st.markdown("**Rotation to compare with today** (one crop per year)")
        cols = st.columns(4)
        for i, col in enumerate(cols):
            with col:
                st.selectbox(f"Year {i+1}", data.CROPS, index=data.CROPS.index(V[f"rot{i}"]), format_func=CROP_LABEL.get, **data.bind(f"rot{i}"))
        md(f'{badge("local")} <span style="font-size:.86rem;color:var(--ink2)">Starts as rice every year, our farm today (Rotation A). Rotations B and C are always shown.</span>')

    with st.expander("Older single-source water model (advanced)"):
        st.segmented_control("Rice water source", list(data.SOURCE_LABELS), format_func=data.SOURCE_LABELS.get, default=V["water_source"], selection_mode="single",
                             key="w_water_source", on_change=lambda: V.update(water_source=st.session_state.get("w_water_source") or "canal_and_well"))
        st.slider("Water available per season (mm), single-source modes only", 0, 3000, step=50, value=int(V["irrigation_mm"]), **data.bind("irrigation_mm"))
        md(f'{badge("assumption")} Used only when a single-source mode is selected. Canal and well is the default.')
        st.number_input("Recharge exponent k (single-source modes)", 0.0, 1.0, step=0.1, value=float(V["recharge_k"]), **data.bind("recharge_k"))

    left, right = st.columns([1.45, 1], gap="large")
    with left:
        section("Where the model is looking")
        m = folium.Map(location=[reg["lat"], reg["lon"]], zoom_start=8, tiles="OpenStreetMap", control_scale=True)
        layers = _gibs_layers()
        if layers:
            pick = st.radio("NASA satellite layer", ["No satellite layer"] + [l["label"] for l in layers], horizontal=True, key="gibs_pick")
            for l in layers:
                if l["label"] == pick:
                    folium.TileLayer(tiles=l["url"], attr="NASA GIBS", name=l["label"], overlay=True, opacity=0.75, max_native_zoom=l["zoom"], max_zoom=12).add_to(m)
                    md(f'{badge("observed")} <span style="font-size:.9rem">{html.escape(l["title"])}, image dated {l["date"]}. Layer id {l["id"]}.</span>')
        else:
            md(f'{badge("placeholder")} <span style="font-size:.92rem">Satellite layers are unavailable: <code>data/gibs_layers.json</code> could not be read. The model does not depend on them.</span>')
        dev = reg.get("dev_placeholder") or reg.get("district") in (None, "TEAM_TO_FILL")
        folium.Marker([reg["lat"], reg["lon"]], tooltip="Demo point" if dev else f'{reg.get("district", "District")} centroid',
                      icon=folium.Icon(color="darkblue", icon="circle", prefix="fa")).add_to(m)
        st_folium(m, height=400, use_container_width=True, returned_objects=[], key="map")
        if dev:
            md(f'<p class="rl-note">{badge("placeholder")} The pin is a demo point ({reg["lat"]}, {reg["lon"]}), not the district centroid yet.</p>')
        else:
            md(f'<p class="rl-note">The pin marks the {html.escape(str(reg["district"]))} district centroid. No village location is used.</p>')
        md(f'<p class="rl-note">{REGIONAL}</p>')
    with right:
        section("What the record shows")
        n_yrs = int(cl["last_year"]) - int(cl["first_year"]) + 1
        yrs = f'Regional estimate, mean of {n_yrs} years, {cl["first_year"]} to {cl["last_year"]}'
        stats([
            stat("Rain in a typical year", f'{cl["annual_rain_mm"]:,.0f}', "mm", cl.get("badge", "observed"), yrs),
            stat("Of which June to September", f'{cl["monsoon_rain_mm"]:,.0f}', "mm", cl.get("badge", "observed"), "Regional estimate"),
        ])
        stats([stat("Soil water held per metre", f'{soil["awc_mm_per_m"]:.0f}', "mm", soil.get("badge", "placeholder"), "District estimate (SoilGrids). The model uses the farm soil unless you switch it.")])
        if cl.get("note"):
            md(f'<p class="rl-note">{html.escape(cl["note"])}. {badge(cl.get("badge", "observed"))}</p>')

    mon = fs.get("monsoon_onset")
    if mon:
        section("When the monsoon arrives", mon.get("badge", "modeled"),
                "Every crop is sown when the monsoon arrives, so a late monsoon means late sowing. The onset date of each year is worked out from the daily rain record with one fixed rule.")
        stats([
            stat("Usual onset (median)", charts.doy_label(mon["median_doy"]), "", mon.get("badge", "modeled"), f'{len(mon["years"])} years of daily rain'),
            stat("Earliest", charts.doy_label(mon["earliest_doy"]), "", mon.get("badge", "modeled"), f'in {mon["earliest_year"]}'),
            stat("Latest", charts.doy_label(mon["latest_doy"]), "", mon.get("badge", "modeled"), f'in {mon["latest_year"]}'),
        ])
        charts.show(charts.onset_history(mon), "onset_hist")
        nc = mon.get("no_clean_onset_years") or []
        srcline(f'Daily rain from NASA POWER (regional estimate). Onset rule: {mon["rule"]}.'
                + (f' No clean onset was found in {", ".join(str(y) for y in nc)}; 1 September is used for those years.' if nc else "")
                + " The numbers in the rule are assumptions, team to verify.", "Source")

    yh = fs.get("yield_history")
    if yh:
        yh = pd.DataFrame(yh)
        section("District yield history", "placeholder" if data.is_mock() else "observed",
                "Average yields for the district, all farms together. Rice is reported as milled rice (paddy times 0.66) and mixes irrigated and rainfed fields.")
        charts.show(charts.yield_history(yh), "yh")
        srcline("District yields from a third-party panel built from ICRISAT data (Mendeley Data, doi 10.17632/ywp3y5j9vv.1), 1990 to 2015. The ICRISAT district tables themselves could not be downloaded. Crops with no district record are not drawn.", "Data source")
        with st.expander("Show these numbers as a table"):
            t = yh.pivot_table(index="year", columns="crop", values="yield_kg_ha").rename(columns=CROP_LABEL).round(0).reset_index().rename(columns={"year": "Year"})
            st.dataframe(t, hide_index=True, use_container_width=True)
    else:
        section("District yield history")
        md(f'<div class="rl-nodata">{badge("placeholder")} No district yield data is loaded yet, so nothing is drawn. Nothing has been made up.</div>')

    fr = fs.get("farm_records")
    section("Farm records", "local")
    if fr and fr.get("rows"):
        md('<p class="rl-note">Your own harvest records, as entered in data/raw/farm_records.csv.</p>')
        st.dataframe(pd.DataFrame(fr["rows"]), hide_index=True, use_container_width=True)
    else:
        md('<p class="rl-note">No farm records have been added yet. Put past harvests in <code>data/raw/farm_records.csv</code> (year, crop, area_acres, yield_quintals) and they will show here and on the How Good Is This? tab as Local input.</p>')
