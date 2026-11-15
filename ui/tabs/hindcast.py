# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
import html
from pathlib import Path

import pandas as pd
import streamlit as st

from ui import charts, data
from ui.components import srcline, badge, md, section, tab_head
from ui.data import CROP_LABEL, humanize, plan_label

LIMITS_FILE = Path(__file__).resolve().parents[2] / "LIMITATIONS.md"

SOURCES = [
    ("Minimum support prices, kharif 2026-27 (Press Information Bureau, Government of India)", "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2260617&reg=3&lang=1", "Read by the team: prices and all-India cost per quintal for paddy, bajra, jowar and tur. Cached copy in data/raw."),
    ("Cost of cultivation of principal crops, Telangana (PJTSAU page, source Directorate of Economics and Statistics)", "https://www.pjtau.edu.in/Cost_Cultivation_Crops.html", "Read 2026-11-15: A2+FL cost per hectare and per quintal for paddy and red gram, 2018-19 to 2020-21."),
    ("District yields: panel built from ICRISAT district data (Mendeley Data)", "https://doi.org/10.17632/ywp3y5j9vv.1", "Historical fallback panel. The active source is the apportioned World Bank archive below."),
    ("ICRISAT VDSA documentation (rice is reported as milled rice, paddy times 0.66)", "https://vdsa.icrisat.org/Include/document/all-apportioned-web-document.pdf", "Read 2026-11-15."),
    ("SoilGrids (ISRIC), district soil estimate", "https://soilgrids.org", "Used for the district soil estimate only; the farm soil is the farmer's input."),
    ("NASA POWER, daily weather", "https://power.larc.nasa.gov/docs/", "Opened in a browser: the project is the Prediction Of Worldwide Energy Resources."),
    ("NASA GIBS, imagery services", "https://www.earthdata.nasa.gov/engage/open-data-services-software/earthdata-developer-portal/gibs-api", "Opened in a browser: provides global satellite imagery through web map services."),
    ("NASA SMAP mission", "https://smap.jpl.nasa.gov/", "Opened in a browser."),
    ("NASA Earth Observatory, NDVI", "https://science.nasa.gov/earth/earth-observatory/measuring-vegetation-ndvi-evi/", "Opened in a browser: NDVI is the most common satellite measure of the density of plant growth."),
    ("FAO Paper 56, evapotranspiration", "https://www.fao.org/4/x0490e/x0490e04.htm", "Opened in a browser: evapotranspiration is water lost from soil by evaporation plus from the crop by transpiration."),
    ("ICRISAT/TCI district crop table, World Bank archive", "https://reproducibility.worldbank.org/catalog/409", "Apportioned Nalgonda, code 59: 1966-2017. All selected crops have 52 positive-yield years. Source member checksum is recorded in the cache."),
    ("Government kharif MSP and national A2+FL unit costs, 2026-27", "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2260617&reg=3&lang=1", "Prices are observed official figures. Converting national unit costs to per-acre crop budgets is an explicit model assumption, not a measured Telangana cost."),
]


def render():
    p = data.params()
    with st.spinner(data.MSG["hindcast"]):
        h = data.hindcast(p)
    b = "placeholder" if data.is_mock() else "modeled"
    tab_head("How Good Is This?", "A check of the model against what the district actually harvested, plus every assumption and limit in one place.")
    if h.get("note"):
        md(f'<div class="rl-callout"><p>{html.escape(humanize(h["note"]))} {badge(b)}</p></div>')
    pc = {c: d for c, d in h.get("per_crop", {}).items() if "pearson_r" in d}
    if not h.get("available") or not pc:
        md(f'<p>{badge("placeholder")} District yield data is not loaded, so the comparison is skipped. Nothing has been made up.</p>')
    else:
        missing = [c for c in data.CROPS + ["ragi"] if c in h.get("per_crop", {}) and c not in pc]
        if missing:
            md('<div class="rl-nodata"><strong>No validation data</strong> for ' + ", ".join(CROP_LABEL.get(c, c.title()) for c in missing) + ". The Nalgonda yield record for these crops is missing or too short, so the model is not checked against them.</div>")
        crop = st.segmented_control("Crop", list(pc), format_func=CROP_LABEL.get, default=list(pc)[0], key="hc_crop") or list(pc)[0]
        d = pc[crop]
        c1, c2 = st.columns([1.5, 1], gap="large")
        with c1:
            section("Model against district yields", b, "Each dot is a year, with the long-run trend removed from both. On the dotted line the model matches the district.")
            charts.show(charts.hindcast_scatter(d, crop), "hc")
            srcline("ICRISAT/TCI apportioned district yields, archived by the World Bank, against single-season model output. District rice mixes farms, irrigation regimes and seasons.", "Data source")
            charts.show(charts.validation_history(d, crop, h.get("farm_records")), "validation_history")
            st.caption(d.get("level_note", ""))
            if h.get("farm_records"):
                md(f'{badge("local")} Your farm records were provided and are listed below.')
                st.dataframe(pd.DataFrame(h["farm_records"]["rows"]), hide_index=True, width="stretch")
            else:
                md('<p class="rl-note">No farm records were provided, so only district data is shown.</p>')
        with c2:
            section("Scores", b)
            r, ho = d.get("pearson_r"), d.get("heldout_r")
            nh = len(d.get("heldout_years") or [])
            rows = [("Correlation, all years", f"{r:.2f}" if r is not None else "n/a", ""),
                    (f"Correlation, latest {nh} years held out" if nh else "Correlation, latest years held out", f"{ho:.2f}" if ho is not None else "n/a", ""),
                    ("Average error", f"{d['mae_kg_ha']:,.0f}", "kg per ha")]
            for l, v, u in rows:
                md(f'<div class="rl-stat" style="padding-left:0;border-bottom:1px solid var(--line)"><div class="l">{l}</div><div class="v">{v}<span class="u">{u}</span></div><div class="b">{badge(b)}</div></div>')
            md(f'<p class="rl-note">{html.escape(d.get("text", ""))}</p>')
            if d.get("weak_reason"):
                md(f'<p class="rl-note"><strong>Why the match is weak:</strong> {html.escape(d["weak_reason"])}</p>')

    section("The recommendation next to simple baselines", b, "Rice every year, and the plan picked on average profit alone, next to the plan picked for your priorities.")
    bt = pd.DataFrame(h.get("baseline", []))
    if not bt.empty:
        bt["id"] = bt["id"].map(lambda i: plan_label(i) if "-" in str(i) else i)
        bt = bt.rename(columns=dict(strategy="Strategy", id="Rotation", mean_profit="Average profit (Rs per acre)", worst10_profit="Worst 10% (Rs per acre)",
                                    irrigation_mm="Irrigation over 4 years (mm)"))
        num = [c for c in bt.columns if c not in ("Strategy", "Rotation")]
        bt[num] = bt[num].round(0).astype(int)
        st.dataframe(bt, hide_index=True, width="stretch")

    section("Every assumption", None, "Each row says where its value comes from. Rows marked team to verify have no confirmed source yet.")
    try:
        a = data.assumptions(p).copy()
        a["value"] = a["value"].astype(str); a["range"] = a["range"].astype(str).replace({"None": ""})
        st.dataframe(a.rename(columns=str.title), hide_index=True, width="stretch")
        st.download_button("Download assumptions and sources (CSV)", a.to_csv(index=False).encode(), "rotationlab-assumptions.csv", "text/csv")
    except Exception as e:  # engine output changing under us: say so, never crash the page
        md(f'<div class="rl-nodata">{badge("placeholder")} The assumptions table could not be built by the engine ({html.escape(type(e).__name__)}: {html.escape(str(e))}). The values are in <code>config/assumptions.yaml</code> and <code>config/prices_india.yaml</code>.</div>')

    section("Limitations")
    try:
        txt = LIMITS_FILE.read_text()
    except Exception:
        txt = ""
    if txt:
        with st.expander("Read the full limitations", expanded=True):
            st.markdown("\n".join(l for i, l in enumerate(txt.splitlines()) if not (i == 0 and l.startswith("# "))))
    else:
        md(f'<p>{badge("placeholder")} LIMITATIONS.md is not written yet. It will appear here.</p>')

    section("How AI was used")
    md('<p style="max-width:80ch">This tool was built with AI assistance. Claude (Anthropic), through Claude Code, wrote most of the code, the tests and the documentation under the team\'s direction; the team chose the problem, the farm, the data sources and the decisions. '
       'Inside the app, the short explanation on the Our Priorities tab can be written by Claude from the computed numbers only; with no API key it comes from a fixed template. '
       'No AI-generated images, video or audio are used, and no NASA logo or mission identifier is used. Details are in <code>AI_USE.md</code>.</p>')

    section("Data sources")
    md('<ul class="rl-src">' + "".join(f'<li><a href="{u}" target="_blank" rel="noopener">{html.escape(n)}</a><div class="st">{html.escape(s)}</div></li>' for n, u, s in SOURCES) + "</ul>")
    section("AI use")
    st.markdown((LIMITS_FILE.parent / "AI_USE.md").read_text().split("\n", 2)[-1])
