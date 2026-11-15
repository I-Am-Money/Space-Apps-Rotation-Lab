# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
# Feature 1: wired into get_site; weighted-profile, invalid-data and fallback tests in test_ssurgo_v5.py.
"""US soil at a point from the USDA NRCS soil survey (Build Spec v4, Person 2 task 2).

Source: USDA NRCS Soil Data Access (SDA) REST service, https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest
  1. SSURGO (detailed survey): the map unit at the point, its largest component, and that component's horizons.
  2. STATSGO2 (general soil map) when SSURGO has no map unit or no usable horizons at the point (fallback).
  3. If both fail (outside the survey, water, network down with no cached copy): FAO-56 Table 19 typical value
     for loam, badge "Assumption". The caller sees which one it got in `source` and `badge`.

What is returned (all from the survey's representative "_r" values, nothing invented):
  awc_mm_per_m        available water capacity, thickness-weighted over 0-100 cm (awc_r is cm/cm; x1000 = mm/m)
  organic_matter_pct  organic matter, thickness-weighted over 0-30 cm (om_r, percent by weight)
  texture             surface horizon texture class (chtexturegrp.texdesc, representative)
  hydrologic_group    component hydrologic soil group (hydgrp; a dual group such as "B/D" keeps its first letter,
                      the drained condition)
Cached for 1 year through engine.cache (R24).
"""
from __future__ import annotations

import requests
import math

from engine import cache

SDA_URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
TOP_MM = 1000.0          # depth used for the AWC average
OM_TOP_CM = 30.0
SOURCE_SSURGO = "USDA NRCS SSURGO (Soil Data Access)"
SOURCE_STATSGO = "USDA NRCS STATSGO2 general soil map (Soil Data Access), used because SSURGO has no data here"

_COLUMNS = ("mu.mukey, mu.muname, c.cokey, c.compname, c.comppct_r, c.hydgrp, c.taxorder, h.hzdept_r, h.hzdepb_r, "
            "h.awc_r, h.om_r, h.sandtotal_r, h.silttotal_r, h.claytotal_r, h.ph1to1h2o_r, "
            "(SELECT TOP 1 tg.texdesc FROM chtexturegrp tg WHERE tg.chkey = h.chkey AND tg.rvindicator = 'Yes') AS texdesc")
_JOIN = ("FROM mapunit mu INNER JOIN component c ON c.mukey = mu.mukey AND c.cokey = "
         "(SELECT TOP 1 c2.cokey FROM component c2 WHERE c2.mukey = mu.mukey ORDER BY c2.comppct_r DESC, c2.cokey) "
         "LEFT JOIN chorizon h ON h.cokey = c.cokey ")


def _point(lat: float, lon: float) -> str:
    return f"point({float(lon):.6f} {float(lat):.6f})"


def ssurgo_query(lat: float, lon: float) -> str:
    return (f"SELECT {_COLUMNS} {_JOIN} WHERE mu.mukey IN (SELECT mukey FROM "
            f"SDA_Get_Mukey_from_intersection_with_WktWgs84('{_point(lat, lon)}')) ORDER BY h.hzdept_r")


def statsgo_query(lat: float, lon: float) -> str:
    return (f"SELECT {_COLUMNS} {_JOIN} WHERE mu.mukey IN (SELECT TOP 1 mukey FROM gsmmupolygon WHERE "
            f"mupolygongeo.STIntersects(geometry::STGeomFromText('{_point(lat, lon).upper()}', 4326)) = 1) "
            f"ORDER BY h.hzdept_r")


def run_query(sql: str, timeout: int = 60) -> list[dict]:
    """Rows of an SDA query as dicts (empty list when SDA returns no table)."""
    r = requests.post(SDA_URL, json={"query": sql, "format": "JSON+COLUMNNAME"}, timeout=timeout)
    r.raise_for_status()
    table = (r.json() or {}).get("Table") or []
    if len(table) < 2:
        return []
    return [dict(zip(table[0], row)) for row in table[1:]]


def _num(x):
    try:
        return None if x in (None, "") or not math.isfinite(float(x)) or float(x) <= -900 else float(x)
    except (TypeError, ValueError):
        return None


def _weighted(rows: list[dict], col: str, top_cm: float):
    """Thickness-weighted mean of a horizon value over 0..top_cm, using only horizons that have the value."""
    total, weight = 0.0, 0.0
    for h in rows:
        a, b, v = _num(h.get("hzdept_r")), _num(h.get("hzdepb_r")), _num(h.get(col))
        if a is None or b is None or v is None:
            continue
        thick = min(b, top_cm) - max(a, 0.0)
        if thick > 0:
            total, weight = total + v * thick, weight + thick
    return (total / weight, weight) if weight > 0 else (None, 0.0)


def summarize(rows: list[dict]) -> dict | None:
    """Soil summary from SDA horizon rows of one component, or None when no horizon has an AWC value."""
    awc, depth_cm = _weighted(rows, "awc_r", TOP_MM / 10.0)
    if awc is None or not 0 < awc <= 1:
        return None
    om, _ = _weighted(rows, "om_r", OM_TOP_CM)
    if om is not None and not 0 <= om <= 100:
        om = None
    sand, _ = _weighted(rows, "sandtotal_r", OM_TOP_CM)
    silt, _ = _weighted(rows, "silttotal_r", OM_TOP_CM)
    clay, _ = _weighted(rows, "claytotal_r", OM_TOP_CM)
    ph, _ = _weighted(rows, "ph1to1h2o_r", OM_TOP_CM)
    top = min((h for h in rows if _num(h.get("hzdept_r")) is not None and h.get("texdesc")),
              key=lambda h: _num(h["hzdept_r"]), default=None)
    first = rows[0]
    hyd = (first.get("hydgrp") or "").strip().upper()
    return {
        "texture": (top["texdesc"].strip().lower() if top else None),
        "awc_mm_per_m": round(awc * 1000.0, 1),
        "organic_matter_pct": None if om is None else round(om, 2),
        "hydrologic_group": hyd[:1] if hyd[:1] in ("A", "B", "C", "D") else None,
        "hydrologic_group_raw": hyd or None,
        "sand_pct": None if sand is None else round(sand, 1), "silt_pct": None if silt is None else round(silt, 1),
        "clay_pct": None if clay is None else round(clay, 1), "ph": None if ph is None else round(ph, 1),
        "awc_depth_cm": round(depth_cm, 0), "mukey": first.get("mukey"), "map_unit": first.get("muname"),
        "component": first.get("compname"), "component_pct": _num(first.get("comppct_r")),
    }


def _fetch(lat: float, lon: float) -> dict:
    rows = run_query(ssurgo_query(lat, lon))
    soil = summarize(rows) if rows else None
    if soil is not None:
        return dict(soil, source=SOURCE_SSURGO, dataset="SSURGO", badge="Observed")
    rows = run_query(statsgo_query(lat, lon))
    soil = summarize(rows) if rows else None
    if soil is not None:
        return dict(soil, source=SOURCE_STATSGO, dataset="STATSGO2", badge="Observed")
    return {"dataset": None}              # cached too: the point really has no survey data (water, outside the US)


def get_soil_us(lat: float, lon: float, refresh: str = "auto", precache: bool = False) -> dict | None:
    """Survey soil at a US point, or None when neither SSURGO nor STATSGO2 has data there.

    Keys: texture, awc_mm_per_m, organic_matter_pct, hydrologic_group, source, badge ("Observed"), dataset,
    map_unit, component, sand/silt/clay percent, ph, data_as_of, stale.
    Raises engine.cache.DataUnavailable when SDA cannot be reached and nothing is cached.
    """
    key = cache.location_key(lat, lon, 4)
    payload, meta = cache.fetch_cached("soil", "ssurgo_" + key, lambda: _fetch(lat, lon), SOURCE_SSURGO, SDA_URL,
                                       refresh=refresh, precache=precache)
    if not payload.get("dataset"):
        return None
    return dict(payload, url=SDA_URL, data_as_of=meta["data_as_of"], stale=bool(meta.get("stale")))
