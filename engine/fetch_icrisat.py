# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""ICRISAT District Level Database (DLD) loader: district yield (kg/ha) and area.

Primary source: ICRISAT/TCI DLD, http://data.icrisat.org/dld/src/crops.html
(1966 onward, apportioned; CC BY 4.0). From the build environment that host
timed out (TCP), so the primary files could NOT be downloaded programmatically.

Data actually used, in priority order:
 1. data/raw/icrisat_dld/*.csv  : DLD CSVs the team downloads by hand (see
    docs/INDIA_DATA.md, "Manual steps"). Any crop covered, 1966+.
 2. data/raw/icrisat_mendeley/  : FALLBACK, a published third-party panel built
    from ICRISAT DLD (unapportioned, 1990-2015, rice + pearl millet only):
    Mohapatra, Mendeley Data, doi:10.17632/ywp3y5j9vv.1, CC BY 4.0.
    Sorghum and pigeonpea are NOT in it, so they return no rows (never invented).

Nalgonda: pre-2016 (undivided) district; the Mendeley panel lists it under state "Telangana",
the DLD CSVs may list it under Andhra Pradesh (the loader accepts either).

Caveat: district rice yields mix irrigated and rainfed fields.
"""
from __future__ import annotations
import difflib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DLD_DIR = RAW / "icrisat_dld"
MENDELEY_XLS = RAW / "icrisat_mendeley" / "main_merge_1990_2015.xls"
MENDELEY_SLIM = RAW / "icrisat_mendeley" / "slim_rice_bajra.csv"
DLD_URL = "http://data.icrisat.org/dld/src/crops.html"
DEV_DISTRICT = "Nalgonda"  # used only when region.yaml has no district (district is now Nalgonda)

# DLD column crop label -> our crop id
CROP_LABELS = {"RICE": "rice", "KHARIF SORGHUM": "jowar", "SORGHUM": "jowar",
               "PEARL MILLET": "bajra", "FINGER MILLET": "ragi", "PIGEONPEA": "pigeonpea"}
COLS = ["year", "crop", "yield_kg_ha", "area"]  # area in hectares

# Current (2016+) Telangana district -> undivided (pre-2014) ICRISAT district.
# Administrative lineage, TEAM TO VERIFY against the Telangana district formation
# orders. Districts carved from several parents map to the main parent (flagged).
TELANGANA_TO_ICRISAT = {
    "Adilabad": "Adilabad", "Mancherial": "Adilabad", "Nirmal": "Adilabad",
    "Komaram Bheem Asifabad": "Adilabad", "Kumuram Bheem Asifabad": "Adilabad",
    "Karimnagar": "Karimnagar", "Jagtial": "Karimnagar", "Peddapalli": "Karimnagar",
    "Rajanna Sircilla": "Karimnagar",
    "Khammam": "Khammam", "Bhadradri Kothagudem": "Khammam",
    "Mahabubnagar": "Mahabubnagar", "Mahbubnagar": "Mahabubnagar", "Nagarkurnool": "Mahabubnagar",
    "Wanaparthy": "Mahabubnagar", "Jogulamba Gadwal": "Mahabubnagar", "Narayanpet": "Mahabubnagar",
    "Medak": "Medak", "Sangareddy": "Medak", "Siddipet": "Medak",
    "Nalgonda": "Nalgonda", "Suryapet": "Nalgonda", "Yadadri Bhuvanagiri": "Nalgonda",
    "Nizamabad": "Nizamabad", "Kamareddy": "Nizamabad",
    "Rangareddy": "Rangareddy", "Ranga Reddy": "Rangareddy", "Vikarabad": "Rangareddy",
    "Medchal-Malkajgiri": "Rangareddy", "Medchal Malkajgiri": "Rangareddy",
    "Hyderabad": "Hyderabad",
    "Warangal": "Warangal", "Hanumakonda": "Warangal", "Jangaon": "Warangal",
    "Mahabubabad": "Warangal", "Jayashankar Bhupalpally": "Warangal", "Mulugu": "Warangal",
}
MULTI_PARENT = {"Siddipet", "Kamareddy", "Yadadri Bhuvanagiri", "Medchal-Malkajgiri",
                "Medchal Malkajgiri", "Vikarabad", "Jagtial", "Mulugu", "Mahabubabad"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def _configured_district() -> str:
    try:
        cfg = yaml.safe_load((ROOT / "config" / "region.yaml").read_text())
    except Exception:
        cfg = {}
    for k in ("icrisat_district", "district"):
        v = cfg.get(k)
        if v and v != "TEAM_TO_FILL":
            return str(v)
    return DEV_DISTRICT


def match_district(name: str, known: list[str]) -> dict:
    """Map a current district name to an ICRISAT district present in `known`.
    Returns {input, matched, method, note, dev_placeholder?}."""
    nk = {_norm(k): k for k in known}
    if _norm(name) in nk:
        return dict(input=name, matched=nk[_norm(name)], method="exact", note="")
    for cur, old in TELANGANA_TO_ICRISAT.items():
        if _norm(cur) == _norm(name) and _norm(old) in nk:
            note = (f"{name} was formed in 2016 from undivided {old} (pre-2014 ICRISAT district)"
                    + ("; has more than one parent district, main parent used, team to verify"
                       if cur in MULTI_PARENT else ""))
            return dict(input=name, matched=nk[_norm(old)], method="telangana_lineage", note=note)
    close = difflib.get_close_matches(_norm(name), list(nk), n=1, cutoff=0.8)
    if close:
        return dict(input=name, matched=nk[close[0]], method="fuzzy",
                    note="fuzzy name match, team to verify")
    raise KeyError(f"no ICRISAT district for {name!r}; known: {sorted(known)[:10]}...")


def try_download(timeout: int = 20) -> dict:
    """Probe the DLD portal and log the result. Never raises."""
    import requests
    DLD_DIR.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(DLD_URL, timeout=timeout)
        status = dict(ok=r.ok, http=r.status_code, url=DLD_URL)
        if r.ok:
            (DLD_DIR / "crops.html").write_bytes(r.content)
    except Exception as e:  # network blocked / timed out
        status = dict(ok=False, error=type(e).__name__, url=DLD_URL)
    (DLD_DIR / "FETCH_STATUS.json").write_text(json.dumps(status, indent=1))
    return status


def _slim_mendeley() -> pd.DataFrame:
    if not MENDELEY_SLIM.exists():
        if not MENDELEY_XLS.exists():
            return pd.DataFrame()
        df = pd.read_excel(MENDELEY_XLS)
        keep = ["Dist Code", "Year", "State Code", "State Name", "Dist Name"] + [
            c for c in df.columns if c.startswith(("RICE ", "PEARL MILLET "))]
        df[keep].to_csv(MENDELEY_SLIM, index=False)
    return pd.read_csv(MENDELEY_SLIM)


def _tidy_wide(df: pd.DataFrame) -> pd.DataFrame:
    """Wide DLD-style frame (one column per crop x variable) -> long tidy frame
    with columns dist, state, year, crop, yield_kg_ha, area (ha)."""
    rows = []
    cols = {c.upper().strip(): c for c in df.columns}
    for label, crop in CROP_LABELS.items():
        yc = next((o for u, o in cols.items() if u.startswith(label + " YIELD")), None)
        ac = next((o for u, o in cols.items() if u.startswith(label + " AREA")), None)
        if yc is None:
            continue
        scale = 1000.0 if (ac and "1000" in ac) else 1.0
        sub = pd.DataFrame({
            "dist": df[cols["DIST NAME"]], "state": df[cols["STATE NAME"]],
            "year": pd.to_numeric(df[cols["YEAR"]], errors="coerce"), "crop": crop,
            "yield_kg_ha": pd.to_numeric(df[yc], errors="coerce"),
            "area": pd.to_numeric(df[ac], errors="coerce") * scale if ac else np.nan})
        rows.append(sub)
    if not rows:
        return pd.DataFrame(columns=["dist", "state", "year", "crop", "yield_kg_ha", "area"])
    out = pd.concat(rows, ignore_index=True)
    # DLD codes missing as -1 or 0: drop non-positive yields
    return out[out["yield_kg_ha"] > 0].dropna(subset=["year"])


def _load_all() -> tuple[pd.DataFrame, str]:
    frames, src = [], []
    for f in sorted(DLD_DIR.glob("*.csv")):
        d = _tidy_wide(pd.read_csv(f))
        if len(d):
            frames.append(d); src.append(f"DLD:{f.name}")
    if frames:
        return pd.concat(frames, ignore_index=True), "ICRISAT DLD manual CSV " + ",".join(src)
    m = _slim_mendeley()
    if len(m):
        return _tidy_wide(m), ("FALLBACK Mendeley doi:10.17632/ywp3y5j9vv.1 (ICRISAT DLD derived, "
                               "unapportioned, 1990-2015, rice+bajra only)")
    return pd.DataFrame(columns=["dist", "state", "year", "crop", "yield_kg_ha", "area"]), "none"


def load_district_yields(district: str | None = None, with_info: bool = False):
    """DataFrame[year, crop, yield_kg_ha, area] for one district (crop ids rice/jowar/
    bajra/pigeonpea). `district` = current name; default from config/region.yaml, else
    DEV district. Crops missing from the available files are absent (never invented).
    Attributes: df.attrs['match'], ['source'], ['badge'], ['dev_placeholder'].
    Note: district rice yields mix irrigated and rainfed fields."""
    allv, source = _load_all()
    dev = False
    if district is None:
        district = _configured_district()
        dev = _raw_cfg_district() in ("TEAM_TO_FILL", "None", "")
    if allv.empty:
        out = pd.DataFrame(columns=COLS)
        out.attrs.update(match=None, source=source, badge="placeholder", dev_placeholder=dev)
        return out
    tel = allv[allv["state"].isin(["Telangana", "Andhra Pradesh"])]
    match = match_district(district, sorted(tel["dist"].unique()))
    sub = tel[tel["dist"] == match["matched"]]
    out = sub[COLS].sort_values(["crop", "year"]).reset_index(drop=True)
    out["year"] = out["year"].astype(int)
    out.attrs.update(match=match, source=source, badge="observed", dev_placeholder=dev,
                     caveat="district rice yields mix irrigated and rainfed fields")
    return out


def _raw_cfg_district() -> str:
    try:
        return str(yaml.safe_load((ROOT / "config" / "region.yaml").read_text()).get("district"))
    except Exception:
        return ""


def year_counts(df: pd.DataFrame) -> dict:
    """Years of positive yield per crop id (0 = crop absent from the loaded files)."""
    return {c: int((df["crop"] == c).sum()) for c in ("rice", "jowar", "bajra", "ragi", "pigeonpea")}


def detrend(years: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Remove the linear trend, re-centred on the final year's trend level."""
    slope, icpt = np.polyfit(years, y, 1)
    return y - slope * (years - years.max())


def potential_yield(df: pd.DataFrame, crop: str):
    """P90 of detrended yields (kg/ha) or None when <10 years of data."""
    d = df[df["crop"] == crop]
    if len(d) < 10:
        return None
    return float(np.percentile(detrend(d["year"].to_numpy(float), d["yield_kg_ha"].to_numpy(float)), 90))


if __name__ == "__main__":
    d = load_district_yields()
    print(d.attrs); print(d.groupby("crop").agg(n=("year", "size"), y0=("year", "min"),
          y1=("year", "max"), mean=("yield_kg_ha", "mean")))
