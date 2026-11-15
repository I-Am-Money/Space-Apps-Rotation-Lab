# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""What was grown at a spot, year by year, anywhere in the contiguous United States: USDA NASS Cropland Data Layer.

    crop_history(lat, lon) -> [{"year", "category", "crop", "supported", "note"}, ...]   (oldest first)
    suggest_plan(history)  -> {"plan": [crop or None x4], "years": [...], "complete": bool, "messages": [...]}

Source: USDA NASS Cropland Data Layer (30 m, annual), read through the CropScape web service
https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLValue (x, y in EPSG:5070, NAD83 / Conus Albers).
The CDL is a satellite-based classification, not a farm record: a pixel can be misclassified, so the farmer confirms it.
It covers the lower 48 states only. Nothing is stored; results live in this process's memory.
"""
from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import requests

SERVICE = "https://nassgeodata.gmu.edu/axis2/services/CDLService/GetCDLValue"
LATEST_YEAR = 2025          # the newest CDL year this service answered with on 2026-11-15
YEARS_SHOWN = 5
READ_TIMEOUT = 8       # seconds to wait for one answer before retrying
ATTEMPTS = 3

# CDL category name -> crop id used by engine/crops.py. Anything not listed is "not supported" (pasture, forest, urban, ...).
CROP_MAP = {
    "Corn": "maize", "Soybeans": "soybean", "Winter Wheat": "wheat_winter", "Spring Wheat": "wheat_spring",
    "Durum Wheat": "wheat_spring", "Sorghum": "sorghum", "Cotton": "cotton", "Rice": "rice", "Peanuts": "peanut",
    "Barley": "barley", "Oats": "oats", "Canola": "canola", "Sunflower": "sunflower", "Potatoes": "potato",
    "Sugarbeets": "sugarbeet", "Dry Beans": "dry_bean", "Chick Peas": "chickpea", "Lentils": "lentil", "Peas": "pea",
    "Dbl Crop WinWht/Soybeans": "wheat_winter",
}
DOUBLE_CROP_NOTE = {"Dbl Crop WinWht/Soybeans": "double cropped: winter wheat then soybeans; shown as winter wheat"}

# EPSG:5070 (NAD83 / Conus Albers): Albers equal-area conic on GRS80, standard parallels 29.5 and 45.5, origin 23 N 96 W.
_A, _F = 6378137.0, 1 / 298.257222101
_E2 = 2 * _F - _F * _F
_E = math.sqrt(_E2)
_P1, _P2, _P0, _L0 = (math.radians(v) for v in (29.5, 45.5, 23.0, -96.0))


def _q(phi):
    s = math.sin(phi)
    return (1 - _E2) * (s / (1 - _E2 * s * s) - (1 / (2 * _E)) * math.log((1 - _E * s) / (1 + _E * s)))


def _m(phi):
    return math.cos(phi) / math.sqrt(1 - _E2 * math.sin(phi) ** 2)


_N = (_m(_P1) ** 2 - _m(_P2) ** 2) / (_q(_P2) - _q(_P1))
_C = _m(_P1) ** 2 + _N * _q(_P1)
_RHO0 = _A * math.sqrt(_C - _N * _q(_P0)) / _N


def to_albers(lon: float, lat: float) -> tuple[float, float]:
    """Longitude and latitude (degrees) to EPSG:5070 easting and northing (metres)."""
    phi, lam = math.radians(lat), math.radians(lon)
    rho = _A * math.sqrt(_C - _N * _q(phi)) / _N
    th = _N * (lam - _L0)
    return rho * math.sin(th), _RHO0 - rho * math.cos(th)


def from_albers(x: float, y: float) -> tuple[float, float]:
    """EPSG:5070 easting and northing (metres) back to (longitude, latitude) in degrees."""
    rho = math.hypot(x, _RHO0 - y)
    theta = math.atan2(x, _RHO0 - y)
    q = (_C - (rho * _N / _A) ** 2) / _N
    phi = math.asin(max(-1.0, min(1.0, q / 2)))
    for _ in range(15):
        s_ = math.sin(phi)
        d = (1 - _E2 * s_ * s_) ** 2 / (2 * math.cos(phi)) * (q / (1 - _E2) - s_ / (1 - _E2 * s_ * s_) + (1 / (2 * _E)) * math.log((1 - _E * s_) / (1 + _E * s_)))
        phi += d
        if abs(d) < 1e-14:
            break
    return math.degrees(_L0 + theta / _N), math.degrees(phi)


def in_conus(lat: float, lon: float) -> bool:
    return 24.0 <= lat <= 50.0 and -125.5 <= lon <= -66.0


def classify(category: str | None) -> dict:
    cat = (category or "").strip()
    crop = CROP_MAP.get(cat)
    return {"category": cat, "crop": crop, "supported": crop is not None, "note": DOUBLE_CROP_NOTE.get(cat, "")}


_PAT = re.compile(r'value:\s*(\d+),\s*category:\s*"([^"]*)"')


def _fetch(year: int, x: float, y: float) -> dict:
    """One value request. The service usually answers in about 3 seconds but some requests hang, so use a short
    timeout and retry a few times instead of waiting a minute."""
    for _ in range(ATTEMPTS):
        try:
            r = requests.get(SERVICE, params={"year": year, "x": f"{x:.1f}", "y": f"{y:.1f}"}, timeout=(5, READ_TIMEOUT),
                             headers={"User-Agent": "RotationLab/1.0"})
            r.raise_for_status()
            m = _PAT.search(r.text)
            if not m:
                return {"year": year, "category": None, "crop": None, "supported": False, "note": "no value returned for this year"}
            return {"year": year, **classify(m.group(2))}
        except requests.RequestException:
            continue
    return {"year": year, "category": None, "crop": None, "supported": False, "note": "the crop service did not answer for this year"}


@lru_cache(maxsize=64)
def _history(lat5: float, lon5: float, years: tuple) -> tuple:
    x, y = to_albers(lon5, lat5)
    with ThreadPoolExecutor(max_workers=len(years)) as ex:
        rows = list(ex.map(lambda yr: _fetch(yr, x, y), years))
    return tuple(sorted(rows, key=lambda r: r["year"]))


def crop_history(lat: float, lon: float, years: tuple | None = None) -> list[dict]:
    """Crop at this spot for each of the last few years, oldest first. Raises ValueError outside the lower 48 states."""
    if not in_conus(lat, lon):
        raise ValueError("Crop history covers the lower 48 United States only. Enter your crops by hand.")
    yrs = tuple(years) if years else tuple(range(LATEST_YEAR - YEARS_SHOWN + 1, LATEST_YEAR + 1))
    return [dict(r) for r in _history(round(lat, 5), round(lon, 5), yrs)]


def suggest_plan(history: list[dict], n: int = 4) -> dict:
    """A four-year current plan from the most recent years: oldest of the four first. Years that were not a
    supported crop (pasture, fallow, a failed lookup) are left blank for the farmer to fill in."""
    rows = [r for r in history if r.get("category") is not None or r.get("note")][-n:]
    plan = [r["crop"] for r in rows]
    msgs = []
    for r in rows:
        if r["crop"] is None:
            msgs.append(f"{r['year']}: {r['category'] or 'no data'} is not a crop this tool plans, so that year is left blank.")
        elif r["note"]:
            msgs.append(f"{r['year']}: {r['note']}.")
    while len(plan) < n:
        plan.insert(0, None)
    return {"plan": plan, "years": [r["year"] for r in rows], "complete": all(plan), "messages": msgs}


_DIRS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]


def nearest_cropland(lat: float, lon: float, year: int = LATEST_YEAR, radii: tuple = (60, 120, 200, 300, 450),
                     bearings: int = 8) -> dict | None:
    """A street address usually lands on the farmhouse, where the satellite record says "Developed". Look in rings
    around the point (latest year only) for the nearest spot classified as a crop this tool plans.
    Returns {"lat", "lon", "distance_m", "direction", "category", "crop"} or None if there is none within the largest ring."""
    x0, y0 = to_albers(lon, lat)
    pts = [(r, b, x0 + r * math.sin(math.radians(b)), y0 + r * math.cos(math.radians(b)))
           for r in radii for b in range(0, 360, 360 // bearings)]
    with ThreadPoolExecutor(max_workers=16) as ex:
        res = list(ex.map(lambda p: (p, _fetch(year, p[2], p[3])), pts))
    for r in radii:
        hits = [(p, row) for p, row in res if p[0] == r and row["supported"]]
        if hits:
            top = max({row["crop"] for _, row in hits}, key=lambda c: sum(1 for _, row in hits if row["crop"] == c))
            p, row = next((p, row) for p, row in hits if row["crop"] == top)
            lo, la = from_albers(p[2], p[3])
            return {"lat": la, "lon": lo, "distance_m": r, "direction": _DIRS[int(round(p[1] / 45)) % 8], "category": row["category"], "crop": row["crop"]}
    return None
