"""Soil available water capacity (AWC), texture, hydrologic group for a lat/lon.

Source: ISRIC SoilGrids 2.0 REST API (https://rest.isric.org/soilgrids/v2.0/properties/query),
250 m grid, layers wv0033 (water content at 33 kPa), wv1500 (at 1500 kPa), sand, silt, clay,
depths 0-100 cm. AWC = wv0033 - wv1500 (field capacity minus wilting point), summed over
the layers weighted by thickness. Mapped units are (10^-2 cm3/cm3)*10 for wv, g/kg for
texture (API field unit_measure.d_factor = 10), so value/10 = percent by volume or mass.

The 5-95 percent band comes from the API quantiles (Q0.05, Q0.95): the two layers'
half-widths are combined in quadrature (assumes independent errors; flagged).
Hydrologic group is NOT in SoilGrids: it is an ASSUMPTION mapped from USDA texture class.
Urban/water/masked pixels return null: the nearest valid pixel within ~3 km is used and
reported in `pixel_offset_km`. Fallback: FAO-56 Table 19 typical TAW by texture, badge
assumption (+-25 percent).
"""
from __future__ import annotations
import json
import math
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
DEPTHS = [("0-5cm", 50), ("5-15cm", 100), ("15-30cm", 150), ("30-60cm", 300), ("60-100cm", 400)]  # mm thick
PROPS = ["wv0033", "wv1500", "sand", "silt", "clay"]
STAT = ["mean", "Q0.05", "Q0.95"]
# FAO-56 Table 19 (Allen et al. 1998, Chapter 7, https://www.fao.org/4/x0490e/x0490e0c.htm,
# read 2026-11-14): theta_FC - theta_WP ranges (m3/m3) -> mm per m is x1000; values below are the
# range MID-POINTS. Table 19 lists: sand .05-.11, loamy sand .06-.12, sandy loam .11-.15,
# loam .13-.18, silt loam .13-.19, silt .16-.20, silt clay loam .13-.18, silty clay .13-.19,
# clay .12-.20. Classes not in the table (sandy clay, clay loam, sandy clay loam) use the nearest
# listed class (assumption).
FAO56_AWC_MM_PER_M = {"sand": 80, "loamy sand": 90, "sandy loam": 130, "loam": 155,
                      "silt loam": 160, "silt": 180, "silty clay loam": 155, "silty clay": 160,
                      "clay": 160, "clay loam": 155, "sandy clay loam": 130, "sandy clay": 140}
HSG = {"sand": "A", "loamy sand": "A", "sandy loam": "B", "loam": "B", "silt loam": "B", "silt": "B",
       "sandy clay loam": "C", "clay loam": "C", "silty clay loam": "C", "sandy clay": "D",
       "silty clay": "D", "clay": "D"}


def usda_texture(sand: float, silt: float, clay: float) -> str:
    """USDA texture class from percent sand/silt/clay (standard triangle rules)."""
    if silt + 1.5 * clay < 15:
        return "sand"
    if silt + 1.5 * clay >= 15 and silt + 2 * clay < 30:
        return "loamy sand"
    if (7 <= clay < 20 and sand > 52 and silt + 2 * clay >= 30) or (clay < 7 and silt < 50 and silt + 2 * clay >= 30):
        return "sandy loam"
    if 7 <= clay < 27 and 28 <= silt < 50 and sand <= 52:
        return "loam"
    if (silt >= 50 and 12 <= clay < 27) or (50 <= silt < 80 and clay < 12):
        return "silt loam"
    if silt >= 80 and clay < 12:
        return "silt"
    if 20 <= clay < 35 and silt < 28 and sand > 45:
        return "sandy clay loam"
    if 27 <= clay < 40 and sand <= 20:
        return "silty clay loam"
    if 27 <= clay < 40 and 20 < sand <= 45:
        return "clay loam"
    if clay >= 35 and sand > 45:
        return "sandy clay"
    if clay >= 40 and silt >= 40:
        return "silty clay"
    return "clay"


def _query(lat: float, lon: float, timeout: int = 60) -> dict | None:
    params = [("lat", lat), ("lon", lon)] + [("property", p) for p in PROPS] + \
             [("depth", d) for d, _ in DEPTHS] + [("value", v) for v in STAT]
    r = requests.get(URL, params=params, timeout=timeout)
    r.raise_for_status()
    js = r.json()
    lay = {l["name"]: {d["label"]: d["values"] for d in l["depths"]} for l in js["properties"]["layers"]}
    return lay if lay["wv0033"]["0-5cm"]["mean"] is not None else None


def _cached(lat: float, lon: float) -> tuple[dict, float]:
    """Return (layers, offset_km) from cache or API, searching nearby pixels if masked."""
    RAW.mkdir(parents=True, exist_ok=True)
    f = RAW / f"soil_{lat}_{lon}.json"
    if f.exists():
        d = json.loads(f.read_text())
        return d["layers"], d["offset_km"]
    for k in range(0, 4):  # 0, then rings of 0.01 deg (~1.1 km) up to ~3.3 km
        ring = [(0, 0)] if k == 0 else [(i, j) for i in range(-k, k + 1) for j in range(-k, k + 1)
                                       if max(abs(i), abs(j)) == k]
        for i, j in ring:
            la, lo = lat + i * 0.01, lon + j * 0.01
            lay = _query(la, lo)
            if lay is not None:
                off = math.hypot(i * 1.11, j * 1.11 * math.cos(math.radians(lat)))
                f.write_text(json.dumps(dict(lat=lat, lon=lon, queried=[la, lo], offset_km=round(off, 2),
                                             layers=lay, source=URL)))
                return lay, off
    raise LookupError("no valid SoilGrids pixel within ~3 km")


def _fallback(texture: str = "loam", why: str = "") -> dict:
    awc = FAO56_AWC_MM_PER_M[texture]
    return dict(awc_mm_per_m=awc, awc_low=awc * 0.75, awc_high=awc * 1.25, texture=texture,
                hydrologic_group=HSG[texture], badge="assumption",
                source=f"FAO-56 Table 19 typical TAW for {texture} (+-25% assumed), {why}")


def get_soil(lat: float, lon: float) -> dict:
    """{awc_mm_per_m, awc_low, awc_high, texture, hydrologic_group, source, badge, ...}"""
    try:
        lay, off = _cached(round(lat, 4), round(lon, 4))
    except Exception as e:
        return _fallback(why=f"SoilGrids unavailable ({type(e).__name__}), texture assumed loam")
    tot = sum(t for _, t in DEPTHS)

    def w(prop, stat):
        return sum(lay[prop][d][stat] * t for d, t in DEPTHS) / tot / 10.0  # percent

    fc, wp = w("wv0033", "mean"), w("wv1500", "mean")
    awc = (fc - wp) * 10.0  # percent vol * 10 = mm per m
    # quadrature of the two layers' 5-95% half-widths (assumes independent errors)
    dlo = math.hypot(fc - w("wv0033", "Q0.05"), w("wv1500", "Q0.95") - wp) * 10.0
    dhi = math.hypot(w("wv0033", "Q0.95") - fc, wp - w("wv1500", "Q0.05")) * 10.0
    low, high = max(0.0, awc - dlo), awc + dhi
    sand, silt, clay = w("sand", "mean"), w("silt", "mean"), w("clay", "mean")
    tex = usda_texture(sand, silt, clay)
    return dict(awc_mm_per_m=round(awc, 1), awc_low=round(low, 1), awc_high=round(high, 1),
                texture=tex, hydrologic_group=HSG[tex], badge="local",
                source="ISRIC SoilGrids 2.0 (wv0033-wv1500, 0-100 cm thickness-weighted, Q0.05/Q0.95 band); "
                       "hydrologic group assumed from texture class",
                sand_pct=round(sand, 1), silt_pct=round(silt, 1), clay_pct=round(clay, 1),
                field_capacity_pct=round(fc, 1), wilting_point_pct=round(wp, 1),
                pixel_offset_km=round(off, 2),
                awc_low_pm25=round(awc * 0.75, 1), awc_high_pm25=round(awc * 1.25, 1),
                band_note="awc_low/high are the (very wide) SoilGrids 5-95% prediction band; awc_*_pm25 is a +-25% assumption alternative")


def farm_soil(lat: float | None = None, lon: float | None = None) -> dict:
    """The farm's own soil (farmer input: black soil / vertisol) with a cited AWC range from
    config/farm.yaml, plus a note comparing it with SoilGrids at the district centroid.
    No place or person names are stored or returned."""
    import yaml
    cfg = yaml.safe_load((ROOT / "config" / "farm.yaml").read_text())["soil"]
    rng = cfg.get("awc_range_mm_per_m")
    out = dict(display_name=cfg.get("display_name", "Black soil (farm input)"))
    if not rng:
        out.update(awc_low=None, awc_mid=None, awc_high=None, badge="assumption",
                   source="team to verify (no AWC range in config/farm.yaml)")
        return out
    lo, hi = float(rng[0]), float(rng[1])
    src = str(cfg.get("awc_source") or "team to verify")
    out.update(awc_low=lo, awc_high=hi, awc_mid=round((lo + hi) / 2, 1), source=src,
               badge="local" if "team to verify" not in src.lower() else "assumption",
               awc_note="soil type is a farmer input (local); the AWC range is literature, not measured on the farm",
               fao56_clay_range_mm_per_m=[120, 200])
    if lat is None:
        try:
            r = yaml.safe_load((ROOT / "config" / "region.yaml").read_text())
            lat, lon = r["lat"], r["lon"]
        except Exception:
            return out
    sg = get_soil(lat, lon)
    clay = sg.get("clay_pct")
    clayey = (clay is not None and clay >= 35) or sg["hydrologic_group"] in ("C", "D")
    in_rng = lo <= sg["awc_mm_per_m"] <= hi
    if clayey and in_rng:
        verdict = "agrees"
    elif clayey:
        verdict = "agrees on texture, AWC below the vertisol range"
    else:
        verdict = "disagrees strongly"
    out["soilgrids_comparison"] = dict(
        verdict=verdict, soilgrids_texture=sg["texture"], soilgrids_clay_pct=clay,
        soilgrids_hydrologic_group=sg["hydrologic_group"], soilgrids_awc_mm_per_m=sg["awc_mm_per_m"],
        note=(f"SoilGrids at the district centroid: {sg['texture']}, clay {clay}%, group "
              f"{sg['hydrologic_group']}, AWC {sg['awc_mm_per_m']} mm/m (district estimate, 250 m model). "
              f"Black soil (cracking clay) AWC range {lo:.0f}-{hi:.0f} mm/m: {verdict}. "
              "Keep SoilGrids as the district estimate; the farm soil is shown separately."))
    return out


if __name__ == "__main__":
    print(json.dumps(get_soil(17.5, 78.5), indent=1))
