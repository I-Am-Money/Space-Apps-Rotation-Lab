# AI use: this file was written by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""How Good Is This? page (Build Spec v4, A1 step 10, R20-R22). Owner: Person 3.

Sections: validation table and site map, assumptions (every config/assumptions/*.yaml plus the shared
config/assumptions.yaml), limitations, data sources, AI use. Also the "Not validated here" banner (R21) that
every results page can show: `banner_for_site(site)` / `render_banner(site)`.

The logic functions are pure (no Streamlit) so they are unit-tested; render() draws the page.
Data reaches this page only through engine/api.py (validation_summary). Until the v4 api.py on main has it,
it falls back to engine.correction.validation_summary (same owner, same table).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
ASSUMPTION_FILES = [ROOT / "config" / "assumptions.yaml", *sorted((ROOT / "config" / "assumptions").glob("*.yaml"))]
DOCS = {"Limitations": ROOT / "LIMITATIONS.md", "Data sources": ROOT / "DATA_SOURCES.md", "AI use": ROOT / "AI_USE.md"}
NOT_VALIDATED = ("Not validated here: there are no local yield records for this location to check the model "
                 "against, so these are model estimates only.")
NEAR_DEG = 0.5      # team choice: about one NASA POWER cell; a district is roughly this size. Team to verify.
VERIFY_WORDS = ("team to verify", "placeholder", "unverified", "tbd")

# Team UI rule (2026-11-15): plain Streamlit defaults only, no custom colors, CSS or styling. Data labels go
# through badge() from ui/components.py only. Until its basic (plain-text) version is on main, this file uses a
# minimal local fallback with the same call shape. The shared one is used automatically once it returns plain
# text (no HTML).
_FALLBACK_LABELS = {"observed": "Observed", "estimated": "Estimated", "your_input": "Your input",
                    "assumption": "Assumption", "placeholder": "Placeholder (team to verify)",
                    "example": "EXAMPLE DATA", "missing": "Missing"}


def _local_badge(kind: str) -> str:
    return _FALLBACK_LABELS.get(str(kind or "placeholder").lower(), _FALLBACK_LABELS["placeholder"])


def badge(kind: str) -> str:
    """Plain-text label for a badge kind: ui.components.badge when it is the plain version, else the fallback."""
    try:
        from ui.components import badge as shared
        out = shared(kind)
        if isinstance(out, str) and "<" not in out:
            return out
    except Exception:
        pass
    return _local_badge(kind)


# ------------------------------------------------------------------------------------------- validation data

def load_validation():
    """ValidationSummary(table, sites) from api.validation_summary(), falling back to engine.correction."""
    try:
        from engine import api
        fn = getattr(api, "validation_summary", None)
        if callable(fn):
            return fn()
    except Exception:
        pass
    from engine import correction
    return correction.validation_summary()


def _table_df(summary) -> pd.DataFrame:
    t = getattr(summary, "table", None)
    if isinstance(t, pd.DataFrame):
        return t.copy()
    return pd.DataFrame(list(t or []))


def _fmt(v, nd=2) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "n/a"
    return "n/a" if f != f else f"{f:.{nd}f}"


def _s(v) -> str:
    """Text cell: '' for None/NaN (CSV round-trips turn empty cells into NaN, which is truthy)."""
    return "" if v is None or (isinstance(v, float) and v != v) else str(v)


def validation_rows(summary) -> list[dict]:
    """Display rows: county, crop, held-out r and MAE (t/ha) with and without the correction, status."""
    df = _table_df(summary)
    rows = []
    for r in df.to_dict("records"):
        status = r.get("status") or "unknown"
        ok = status == "ok"
        mae = lambda k: _fmt(float(r[k]) / 1000.0) if ok and pd.notna(r.get(k)) else "n/a"
        rows.append({
            "County": f"{_s(r.get('county')) or _s(r.get('site'))}, {_s(r.get('state'))}".strip(", "),
            "Country": "US" if _s(r.get("fips")) else "India" if "India" in _s(r.get("region")) else "",
            "ERS region": _s(r.get("ers_region")) or _s(r.get("region")),
            "Crop": _s(r.get("crop")), "Water": _s(r.get("water")),
            "r (held out)": _fmt(r.get("r")) if ok else "n/a", "MAE t/ha": mae("mae"),
            "r corrected": _fmt(r.get("r_corrected")) if ok else "n/a", "MAE corrected t/ha": mae("mae_corrected"),
            "Years train/test": f"{int(r['n_train'])}/{int(r['n_test'])}" if ok else "",
            "Status": "validated" if ok else status, "Label": badge("estimated" if ok else "missing"),
            "Model": "stand-in" if "stand-in" in _s(r.get("badge")) else _s(r.get("badge"))})
    return rows


def validated_fips(summary) -> set[str]:
    df = _table_df(summary)
    if df.empty or "status" not in df:
        return set()
    return {str(f).zfill(5) for f in df.loc[df["status"] == "ok", "fips"].dropna()}


# ------------------------------------------------------------------------------------------- R21 banner

def banner_for_site(site=None, summary=None, crop: str | None = None) -> dict:
    """{"show": bool, "text": str}. The banner shows unless the pin's US county has hindcast results
    (status ok) for the crop (or any crop if crop is None). Non-US pins always show it."""
    get = (lambda k: site.get(k)) if isinstance(site, dict) else (lambda k: getattr(site, k, None))
    fips = (get("us_county_fips") or get("fips")) if site is not None else None
    lat, lon = (get("lat"), get("lon")) if site is not None else (None, None)
    if not fips and (lat is None or lon is None):
        return {"show": True, "text": NOT_VALIDATED}
    summary = load_validation() if summary is None else summary
    df = _table_df(summary)
    if df.empty or "status" not in df:
        return {"show": True, "text": NOT_VALIDATED}
    ok = df[df["status"] == "ok"]
    if fips and "fips" in ok:
        here = ok[ok["fips"].astype(str).str.zfill(5) == str(fips).zfill(5)]
    elif not fips and {"lat", "lon"} <= set(ok.columns):
        # outside the US: validated districts (no FIPS) count for pins within NEAR_DEG of their centroid
        nofips = ok[ok["fips"].isna()] if "fips" in ok else ok
        here = nofips[((nofips["lat"] - float(lat)).abs() <= NEAR_DEG) & ((nofips["lon"] - float(lon)).abs() <= NEAR_DEG)]
    else:
        here = ok.iloc[0:0]
    if crop is not None:
        here = here[here["crop"] == crop]
    if here.empty:
        return {"show": True, "text": NOT_VALIDATED}
    r = here.iloc[0]
    return {"show": False, "text": f"Checked against {'NASS county' if fips else 'district'} yields here ({r['crop']}): held-out r = "
                                   f"{_fmt(r.get('r'))}. See How Good Is This?"}


# ------------------------------------------------------------------------------------------- assumptions

def _walk(node, path, file_label, out):
    if isinstance(node, dict) and "value" in node:
        src = node.get("source") or node.get("note") or ""
        val = node["value"]
        text = str(src).lower()
        out.append({"File": file_label, "Parameter": ".".join(path), "Value": val if not isinstance(val, (dict, list))
                    else yaml.safe_dump(val, default_flow_style=True, width=10_000).strip(),
                    "Unit": node.get("unit", ""), "Range": node.get("range", ""), "Source": str(src).strip(),
                    "Badge": "placeholder" if (not src or any(w in text for w in VERIFY_WORDS)) else
                             (node.get("badge") or "assumption")})
        return
    if isinstance(node, dict):
        for k, v in node.items():
            _walk(v, path + [str(k)], file_label, out)


def assumption_rows(files=None) -> list[dict]:
    """Every parameter that carries a `value` in the assumption files, with source, range and badge.
    Unsourced or 'team to verify' values get the Placeholder badge."""
    out: list[dict] = []
    for f in files or ASSUMPTION_FILES:
        if not Path(f).exists():
            continue
        try:
            doc = yaml.safe_load(Path(f).read_text()) or {}
        except yaml.YAMLError:
            continue
        _walk(doc, [], str(Path(f).relative_to(ROOT)) if str(f).startswith(str(ROOT)) else Path(f).name, out)
    return out


def doc_text(name: str) -> str:
    p = DOCS[name]
    return p.read_text() if p.exists() else f"{p.name} is missing."


# ------------------------------------------------------------------------------------------- Streamlit

def render_banner(site=None, crop=None) -> None:
    import streamlit as st
    b = banner_for_site(site, crop=crop)
    (st.warning if b["show"] else st.caption)(b["text"])


def site_points(summary) -> pd.DataFrame:
    """One row per validation site with lat/lon (for st.map)."""
    df = _table_df(summary)
    if df.empty or not {"lat", "lon"} <= set(df.columns):
        return pd.DataFrame(columns=["site", "lat", "lon"])
    return df.dropna(subset=["lat", "lon"]).drop_duplicates("site")[["site", "lat", "lon"]].reset_index(drop=True)


def render() -> None:
    import streamlit as st

    st.header("How good is this?")
    st.write("We re-ran the crop model on past NASA weather in US counties with long USDA yield records, "
             "then compared it with what farmers actually harvested. The latest 8 years were never used to tune "
             "anything, so those numbers show how the model does on years it has not seen.")
    summary = load_validation()
    rows = validation_rows(summary)
    st.subheader("Validation (hindcast)")
    us_ok = [r for r in rows if r["Status"] == "validated" and r["Country"] == "US"]
    if not us_ok:
        st.warning("US counties are not validated yet: NASS county yields are not cached (they need a NASS API "
                   "key). The US counties below are the ones that will be checked.")
    st.caption("r: correlation of year-to-year ups and downs after removing the long-term trend (1 = perfect). "
               "MAE: average miss in tonnes per hectare. 'Corrected' adds the small bias correction (R12), fitted on "
               "training years only.")
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    pts = site_points(summary)
    if len(pts):
        st.caption("Validation sites")
        st.map(pts)

    st.subheader("Assumptions")
    a = pd.DataFrame(assumption_rows())
    if not a.empty:
        n_ph = int((a["Badge"] == "placeholder").sum())
        st.caption(f"{len(a)} parameters. {n_ph} are marked Placeholder (team to verify or no source yet).")
        for col in ("Value", "Range", "Unit"):
            a[col] = a[col].map(lambda v: "" if v is None else str(v))
        a["Badge"] = a["Badge"].map(badge)
        st.dataframe(a, hide_index=True)
    for name in DOCS:
        with st.expander(name, expanded=(name == "Limitations")):
            st.markdown(doc_text(name))


if __name__ == "__main__":
    render()
