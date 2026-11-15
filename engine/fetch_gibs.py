# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""NASA GIBS WMTS (EPSG:3857) layer discovery for map overlays (never used by the model).

Layer IDs are parsed from the real GetCapabilities document (cached in
data/raw/gibs_capabilities_epsg3857.xml), never typed from memory. Selection results
(tile matrix set, format, valid date ranges, verified date, tile HTTP check) are written
to data/gibs_layers.json by `python -m engine.fetch_gibs`.
"""
from __future__ import annotations

import datetime as dt
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CAPS_URL = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi?SERVICE=WMTS&request=GetCapabilities"
CAPS_FILE = ROOT / "data" / "raw" / "gibs_capabilities_epsg3857.xml"
OUT = ROOT / "data" / "gibs_layers.json"
NS = {"w": "http://www.opengis.net/wmts/1.0", "ows": "http://www.opengis.net/ows/1.1"}

# Candidate IDs; each is looked up in the capabilities XML and rejected if absent.
CANDIDATES = {
    "soil_moisture": ["SMAP_L4_Analyzed_Root_Zone_Soil_Moisture", "SMAP_L4_Analyzed_Surface_Soil_Moisture"],
    "ndvi": ["MODIS_Terra_L3_NDVI_16Day", "MODIS_Terra_L3_NDVI_Monthly"],
}
import math
import yaml

REGION = yaml.safe_load((ROOT / "config" / "region.yaml").read_text())
CENTER = (REGION["lat"], REGION["lon"])  # district centroid; map default centre


def lonlat_to_tile(lat, lon, z):
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return z, y, x


TEST_TILE = lonlat_to_tile(*CENTER, 5)  # overview tile covering the centroid


def get_capabilities(force=False) -> str:
    if CAPS_FILE.exists() and not force:
        return CAPS_FILE.read_text()
    CAPS_FILE.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(CAPS_URL, timeout=90)
    r.raise_for_status()
    CAPS_FILE.write_text(r.text)
    return r.text


def parse_layers(xml_text: str | None = None) -> dict:
    root = ET.fromstring(xml_text or get_capabilities())
    out = {}
    for lay in root.iter("{%s}Layer" % NS["w"]):
        ident = lay.findtext("ows:Identifier", namespaces=NS)
        dim = lay.find("w:Dimension", NS)
        ranges = [v.text for v in dim.findall("w:Value", NS)] if dim is not None else []
        out[ident] = {
            "title": lay.findtext("ows:Title", namespaces=NS),
            "format": lay.findtext("w:Format", namespaces=NS),
            "tile_matrix_set": [e.findtext("w:TileMatrixSet", namespaces=NS)
                                for e in lay.findall("w:TileMatrixSetLink", NS)],
            "time_ranges": ranges,
            "tile_template": next((r.get("template") for r in lay.findall("w:ResourceURL", NS)
                                   if r.get("resourceType") == "tile" and "{Time}" in r.get("template")), None),
        }
    return out


def _expand(ranges):
    """Yield (start, end, step_days) tuples from ISO8601 'a/b/P1D' strings."""
    for r in ranges:
        a, b, p = r.split("/")
        yield dt.date.fromisoformat(a), dt.date.fromisoformat(b), p


def candidate_dates(layer: dict, n=6):
    """Latest dates, newest first, that lie exactly on the layer's advertised time steps."""
    dates = []
    for a, b, p in _expand(layer["time_ranges"]):
        if p == "P1D":
            d = b
            for _ in range(n):
                if d >= a:
                    dates.append(d)
                d -= dt.timedelta(days=1)
        elif p.endswith("D"):
            step = int(p[1:-1]); d = b
            for _ in range(n):
                if d >= a:
                    dates.append(d)
                d -= dt.timedelta(days=step)
        else:  # P1M
            y, mo = b.year, b.month
            for _ in range(n):
                dates.append(dt.date(y, mo, a.day))
                mo -= 1
                if mo == 0:
                    y, mo = y - 1, 12
    return sorted(set(dates), reverse=True)[:n]


def tile_url_template(layer: str, date: str | dt.date, layers: dict | None = None) -> str:
    """Folium-ready XYZ URL ({z}/{y}/{x}) for a GIBS layer on a date. Built from the capabilities template."""
    layers = layers or parse_layers()
    L = layers[layer]
    t = L["tile_template"].replace("{Time}", str(date)).replace("{TileMatrixSet}", L["tile_matrix_set"][0])
    return t.replace("{TileMatrix}", "{z}").replace("{TileRow}", "{y}").replace("{TileCol}", "{x}")


def check_tile(layer: str, date, layers=None, tile=TEST_TILE) -> dict:
    z, y, x = tile
    url = tile_url_template(layer, date, layers).format(z=z, y=y, x=x)
    r = requests.get(url, timeout=30)
    return {"url": url, "status": r.status_code, "bytes": len(r.content),
            "content_type": r.headers.get("content-type")}


def main():
    layers = parse_layers()
    out = {"center": {"lat": CENTER[0], "lon": CENTER[1], "default_zoom": 8, "source": "config/region.yaml"},
           "test_tile_zyx": list(TEST_TILE), "capabilities_url": CAPS_URL, "retrieved": dt.date.today().isoformat(),
           "capabilities_default_time_note": "layer dates below come from the capabilities XML",
           "layers": {}}
    for key, cands in CANDIDATES.items():
        for cid in cands:
            if cid not in layers:
                continue
            L = layers[cid]
            verified = None
            for d in candidate_dates(L):
                chk = check_tile(cid, d, layers)
                if chk["status"] == 200 and chk["bytes"] > 0:
                    verified = {"date": str(d), **chk}
                    break
            out["layers"].setdefault(key, []).append({
                "id": cid, "title": L["title"], "format": L["format"],
                "tile_matrix_set": L["tile_matrix_set"], "time_ranges": L["time_ranges"],
                "first_date": L["time_ranges"][0].split("/")[0] if L["time_ranges"] else None,
                "last_date": L["time_ranges"][-1].split("/")[1] if L["time_ranges"] else None,
                "verified_tile": verified,
                "tile_url_template": tile_url_template(cid, verified["date"], layers) if verified else None})
    # primary choice = first candidate with a verified tile
    out["primary"] = {k: next((l["id"] for l in v if l["verified_tile"]), None) for k, v in out["layers"].items()}
    out["fallback"] = ("If a layer or date is unavailable: show a static Worldview screenshot labelled "
                       "with layer id and date; the model never depends on GIBS.")
    OUT.write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    o = main()
    print(json.dumps({k: [(l["id"], l["last_date"], l["verified_tile"] and l["verified_tile"]["date"],
                           l["verified_tile"] and l["verified_tile"]["status"]) for l in v]
                      for k, v in o["layers"].items()}, indent=1), o["primary"])
