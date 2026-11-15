# AI use: this file was written by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""USDA ERS Commodity Costs and Returns by Farm Resource Region (Build Spec v4, A3 and R2). Owner: Person 3.

  region_for_county(fips)        -> {"id": 1..9, "name": "Heartland"} or None
  cost_for_county(fips, crop)    -> {"usd_per_ha", "usd_per_acre", "year", "region", "level", "basis", "note"}
                                    or None (crop has no ERS cost: the farmer must enter one, R2)
  has_ers_cost(crop)             -> bool

Data: two official ERS downloads, stored with engine.cache (kind "costs" and "geo", 1-year expiry). Copies
downloaded on 2026-11-15 are committed under data/precache/ so the app needs no network:
  * one CSV per crop from https://www.ers.usda.gov/data-products/commodity-costs-and-returns
    (dollars per planted acre, latest year 2025 in the 2026-11-15 download);
  * reglink.xls, ERS county FIPS -> Farm Resource Region 1-9.
A crop that ERS covers but not in the county's region uses the ERS U.S. total, labelled (level "us").
Rice (ERS uses its own rice areas) also uses the U.S. total; peanut sub-regions are matched by state.
Refresh: python -m engine.fetch_ers --precache   (needs network; xlrd for the .xls)
"""
from __future__ import annotations

import io
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd
import requests
import yaml

from engine import cache

ROOT = Path(__file__).resolve().parent.parent
ASSUMPTIONS = ROOT / "config" / "assumptions" / "us_data.yaml"
SOURCE = "USDA ERS Commodity Costs and Returns"
REGION_SOURCE = "USDA ERS Farm Resource Regions (reglink.xls)"
ACRE_HA = 0.40468564224
ITEMS = {"operating": "Total, operating costs", "total_listed": "Total, costs listed"}
REGION_NAMES = {1: "Heartland", 2: "Northern Crescent", 3: "Northern Great Plains", 4: "Prairie Gateway",
                5: "Eastern Uplands", 6: "Southern Seaboard", 7: "Fruitful Rim", 8: "Basin and Range",
                9: "Mississippi Portal"}
# ERS spells region 9 "Mississippian Portal" in some files and "Mississippi Portal" in the cost CSVs.
_ALIASES = {"mississippian portal": "Mississippi Portal"}


@lru_cache(maxsize=1)
def config() -> dict:
    return yaml.safe_load(ASSUMPTIONS.read_text())["ers"]


def csv_urls() -> dict:
    return config()["csv_urls"]["value"]


def has_ers_cost(crop: str) -> bool:
    return crop in csv_urls()


def _norm_region(name: str) -> str:
    n = str(name).strip()
    return _ALIASES.get(n.lower(), n)


# ------------------------------------------------------------------------------------------- builders

def build_costs(csv_text: str) -> dict:
    """ERS crop CSV -> {region: {year: {"operating": $/acre, "total_listed": $/acre}}} (compact payload)."""
    d = pd.read_csv(io.StringIO(csv_text))
    d = d[d["Item"].isin(ITEMS.values()) & (d["Units"] == "dollars per planted acre")]
    out: dict = {}
    for row in d.itertuples(index=False):
        basis = next(k for k, v in ITEMS.items() if v == row.Item)
        out.setdefault(_norm_region(row.Region), {}).setdefault(str(int(row.Year)), {})[basis] = float(row.Value)
    return out


def build_regions(xls_bytes: bytes) -> dict:
    """reglink.xls -> {"05111": 9, ...} (county FIPS -> region id). Needs xlrd (only for a refresh)."""
    import xlrd   # optional dependency, only needed to rebuild the pre-cache

    sh = xlrd.open_workbook(file_contents=xls_bytes).sheet_by_index(0)
    out = {}
    for r in range(sh.nrows):
        a, b = sh.cell_value(r, 0), sh.cell_value(r, 1)
        if isinstance(a, float) and isinstance(b, float) and 1 <= b <= 9:
            out[f"{int(a):05d}"] = int(b)
    return out


def _download(url: str) -> requests.Response:
    r = requests.get(url, timeout=90)
    r.raise_for_status()
    return r


def _file_key(url: str) -> str:
    return "ers_" + re.sub(r"\W", "_", url.rsplit("/", 1)[-1].split("?")[0].rsplit(".", 1)[0])


# ------------------------------------------------------------------------------------------- loaders

def costs_table(crop: str, refresh: str = "never") -> tuple[dict, dict]:
    """(payload, cache meta) for a crop's ERS cost table. refresh="never" = use the committed copy."""
    url = csv_urls()[crop]
    return cache.fetch_cached("costs", _file_key(url), lambda: build_costs(_download(url).text), SOURCE,
                              url=url, refresh=refresh)


def regions_table(refresh: str = "never") -> tuple[dict, dict]:
    url = config()["region_url"]["value"]
    return cache.fetch_cached("geo", "ers_farm_resource_regions", lambda: build_regions(_download(url).content),
                              REGION_SOURCE, url=url, refresh=refresh)


def region_for_county(fips: str) -> dict | None:
    try:
        table, _ = regions_table()
    except cache.DataUnavailable:
        return None
    rid = table.get(str(fips).strip().zfill(5))
    return None if rid is None else {"id": int(rid), "name": REGION_NAMES[int(rid)]}


def _pick_region(table: dict, region: str | None, state: str | None) -> tuple[str, str]:
    """(table key, level) for a county's region; falls back to 'U.S. total'."""
    if region:
        if region in table:
            return region, "region"
        for key in table:                     # e.g. peanuts: "Southern Seaboard (AL, GA)"
            m = re.match(r"(.+?)\s*\(([^)]*)\)$", key)
            if m and m.group(1) == region and state and state in [s.strip() for s in m.group(2).split(",")]:
                return key, "region"
    return "U.S. total", "us"


def cost_for_county(fips: str, crop: str, basis: str | None = None) -> dict | None:
    """Latest ERS cost per hectare for this crop in the county's Farm Resource Region. None: farmer enters cost."""
    if not has_ers_cost(crop):
        return None
    basis = basis or config()["cost_basis"]["value"]
    try:
        table, meta = costs_table(crop)
    except cache.DataUnavailable:
        return None
    from engine.fetch_nass import STATE_FIPS

    reg = region_for_county(fips)
    state = STATE_FIPS.get(str(fips).zfill(5)[:2])
    key, level = _pick_region(table, reg["name"] if reg else None, state)
    years = table.get(key) or {}
    usable = [y for y, v in years.items() if basis in v]
    if not usable:
        return None
    year = max(usable, key=int)
    per_acre = years[year][basis]
    where = f"ERS {key} region" if level == "region" else "ERS U.S. average (this region not surveyed for this crop)"
    return {"usd_per_acre": round(per_acre, 2), "usd_per_ha": round(per_acre / ACRE_HA, 2), "year": int(year),
            "region": key, "level": level, "basis": basis, "data_as_of": meta.get("data_as_of"),
            "badge": "estimated", "note": f"{ITEMS[basis]}, {year}, {where}"}


def precache_all() -> None:
    """Download every ERS file and write it to the committed pre-cache (data/precache/)."""
    for crop in sorted(set(csv_urls())):
        url = csv_urls()[crop]
        cache.write("costs", _file_key(url), build_costs(_download(url).text), SOURCE, url, precache=True)
    url = config()["region_url"]["value"]
    cache.write("geo", "ers_farm_resource_regions", build_regions(_download(url).content), REGION_SOURCE, url,
                precache=True)


if __name__ == "__main__":
    import sys

    if "--precache" in sys.argv:
        precache_all()
        print("ERS pre-cache written to data/precache/")
