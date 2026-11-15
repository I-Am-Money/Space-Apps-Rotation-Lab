import html
import io
from datetime import datetime, timedelta
import json
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from ui import charts, data
from ui.components import REGIONAL, badge, md, section, srcline, stat, stats, tab_head
from ui.data import CROP_LABEL

GIBS_FILE = Path(__file__).resolve().parents[2] / "data" / "gibs_layers.json"


def _save_crop_cost(crop):
    costs = dict(data.V()["cost_values"])
    costs[crop] = st.session_state[f"local_cost_{crop}"]
    data.V()["cost_values"] = costs


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
    tab_head("My Field", "Our farm grows rice every year today. Set the water you can count on, then see what else could work.")
    with st.spinner(data.MSG["get_field_summary"]):
        fs = data.field_summary()
    reg, cl, soil = fs["region"], fs["climate"], fs["soil"]
    V = data.V()
    with st.expander("Import anonymous farm records"):
        st.caption("CSV columns: year, crop, area_acres, yield_quintals; optional costs_rupees. Use no names, contact details or village locations. Imports stay in this session.")
        uploaded = st.file_uploader("Farm harvest records (CSV, up to 2 MB)", type=["csv"], key="farm_csv")
        if uploaded is not None:
            try:
                if uploaded.size > 2 * 1024 * 1024:
                    raise ValueError("Please keep the CSV below 2 MB")
                from engine.records import validate_records
                records = validate_records(pd.read_csv(io.BytesIO(uploaded.getvalue())))
                st.session_state["farm_records"] = records.drop(columns="yield_kg_ha").to_dict("records")
                st.success(f"Loaded {len(records)} anonymous records. View them in How Good Is This?")
            except (ValueError, UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as error:
                st.error(str(error))
        if st.session_state.get("farm_records") and st.button("Clear imported records"):
            del st.session_state["farm_records"]
            st.rerun()
    with st.expander("Crop costs and heat sensitivity"):
        st.checkbox("Include flowering heat sensitivity", value=V["heat_enabled"], **data.bind("heat_enabled"))
        st.caption("A labeled sensitivity assumption: yield falls 1% per hot day in the flowering-window proxy. Thresholds are in the assumptions table.")
        st.checkbox("Use my cultivation and measurement costs", value=V["use_cost_overrides"], **data.bind("use_cost_overrides"))
        if V["use_cost_overrides"]:
            from engine.economics import load_prices
            prices = load_prices()
            costs = dict(V["cost_values"])
            for crop in data.CROPS:
                costs[crop] = st.number_input(f"{CROP_LABEL[crop]} operating cost (Rs per acre per season)",
                    min_value=0., value=float(costs.get(crop, prices["operating_cost_rs_per_acre"].get(crop, 0))),
                    step=500., key=f"local_cost_{crop}", on_change=_save_crop_cost, args=(crop,))
            V["cost_values"] = costs
            for key, label, source in (("irrigation_cost", "Additional irrigation cost (Rs per m3)", "irrigation_cost_rs_per_m3"),
                                       ("soil_test_cost", "Soil test quote for the farm (Rs)", "soil_test_cost_rs"),
                                       ("water_test_cost", "Water-supply measurement quote for the farm (Rs)", "water_measure_cost_rs")):
                V[key] = st.number_input(label, min_value=0., value=float((prices[source] or 0) if V[key] is None else V[key]), step=1., **data.bind(key))
            st.caption("Local inputs apply only to this session. Include only extra irrigation charges here if operating costs already include irrigation, to avoid double counting.")

    # --- rice irrigation supply: canal plus well
    section("Rice irrigation water", "assumption", "Rice gets canal water first. Wells cover what the canal does not, up to their limit. By default the model works both out from rainfall. Override either one with your own figure.")
    st.caption("Canal plus well is a regional planning scenario. The actual supply to this farm has not been measured or confirmed by public data.")
    def source_box(col, key, title, label, base):
        with col:
            md(f'<div class="rl-q" style="font-size:1.05rem">{title}</div><p class="rl-note" style="margin:.1rem 0 .5rem">{label}</p>')
            st.checkbox(f"I know my {title.split()[0].lower()} supply", value=V[f"{key}_override"], **data.bind(f"{key}_override"))
            if V[f"{key}_override"]:
                V[f"{key}_supply"] = st.number_input(f"{title} (mm per season)", 0, 3000, step=50, value=int(V[f"{key}_supply"] if V[f"{key}_supply"] is not None else (base or 500)), **data.bind(f"{key}_supply"))
                md(badge("local"))
            else:
                bs = f"Model default: base {base:,.0f} mm per season, scaled by rainfall. " if base is not None else "Model default: worked out from rainfall. "
                md(f'<span style="font-size:.92rem;color:var(--ink2)">{bs}</span>{badge("assumption")} <span style="font-size:.86rem;color:var(--ink2)">team to verify</span>')
    c1, c2 = st.columns(2, gap="large")
    source_box(c1, "canal", "Canal supply (mm)", data.CANAL_LABEL, data.BASE_CANAL)
    source_box(c2, "well", "Well supply (mm)", data.WELL_LABEL, data.BASE_WELL)

    section("Soil", "local", "The farm soil is what you told us. SoilGrids is a modeled district-point estimate, separate from the farm input.")
    fs_ = data.FARM
    rng = fs_["awc_range"]
    if isinstance(rng, (list, tuple)) and len(rng) == 2:
        awc_txt = f'{rng[0]:g} to {rng[1]:g}'
        awc_note = f'Source: {html.escape(str(fs_["awc_source"] or "not stated"))}. {badge("assumption")}'
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
        stats([stat(html.escape(fs_["soil_name"]), awc_txt, "mm per metre" if isinstance(rng, (list, tuple)) else "", "assumption", "Literature range; soil type supplied by the farm")])
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

    c1, c2, c3 = st.columns([1, 1, 1.2], gap="large")
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
        if V["water_source"] == "canal":
            st.slider("Canal release factor (1 = usual supply)", 0.0, 1.5, step=0.1,
                      value=float(V["canal_factor"]), **data.bind("canal_factor"))

    left, right = st.columns([1.45, 1], gap="large")
    with left:
        section("Where the model is looking")
        map_mode = st.radio("Map view", ["Offline district outline", "Online satellite map"], horizontal=True, key="map_mode")
        if map_mode == "Offline district outline":
            charts.show(charts.offline_map(reg), "offline_map")
            srcline("OpenStreetMap contributors, ODbL. Simplified cached district outline; not a field survey. NASA satellite layers are available in the online map.")
        else:
            _online_map(reg)
    with right:
        _climate_cards(cl, soil)

    _baseline_and_yields(fs)


def _online_map(reg):
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


def _climate_cards(cl, soil):
    section("What the record shows")
    yrs = f'Regional estimate, mean of {cl["first_year"]} to {cl["last_year"]}'
    stats([
        stat("Rain in a typical year", f'{cl["annual_rain_mm"]:,.0f}', "mm", cl.get("badge", "observed"), yrs),
        stat("Of which June to September", f'{cl["monsoon_rain_mm"]:,.0f}', "mm", cl.get("badge", "observed"), "Regional estimate"),
    ])
    stats([stat("Soil water held per metre", f'{soil["awc_mm_per_m"]:.0f}', "mm", soil.get("badge", "placeholder"), "Default until you enter a soil test")])
    onset = cl.get("onset") or {}
    if onset.get("median_doy"):
        date = datetime(2001, 1, 1) + timedelta(days=onset["median_doy"] - 1)
        stats([stat("Typical rainfall onset", date.strftime("%d %b"), "", "modeled", "Planning rule applied to NASA rainfall")])
        st.caption(onset["note"])
    if cl.get("note"):
        md(f'<p class="rl-note">{html.escape(cl["note"])}. {badge(cl.get("badge", "observed"))}</p>')


def _baseline_and_yields(fs):
    yh = fs.get("yield_history")
    section("Our farm today: rice every year", "modeled", "Baseline results for the current soil, water, cost and priority inputs. Profit totals cover four years.")
    base = data.recommend(data.params())["metrics"]
    base = base[base.id == "rice-rice-rice-rice"].iloc[0]
    stats([stat("Average profit", f'Rs {base.mean_profit:,.0f}', "per acre", "modeled"),
           stat("Bad-year profit, worst 10%", f'Rs {base.worst10_profit:,.0f}', "per acre", "modeled"),
           stat("Irrigation over four years", f'{base.irrigation_mm:,.0f}', "mm", "modeled")])
    if yh:
        yh = pd.DataFrame(yh)
        section("District yield history", "placeholder" if data.is_mock() else "observed",
                "Average yields for the district, all farms together. Rice here mixes irrigated and rainfed fields.")
        charts.show(charts.yield_history(yh), "yh")
        srcline("ICRISAT district-level yields as loaded by the app. Crops with no district record are not drawn.", "Data source")
        with st.expander("Show these numbers as a table"):
            t = yh.pivot_table(index="year", columns="crop", values="yield_kg_ha").rename(columns=CROP_LABEL).round(0).reset_index().rename(columns={"year": "Year"})
            st.dataframe(t, hide_index=True, width="stretch")
    else:
        section("District yield history")
        md(f'<div class="rl-nodata">{badge("placeholder")} No district yield data is loaded yet, so nothing is drawn. Nothing has been made up.</div>')
