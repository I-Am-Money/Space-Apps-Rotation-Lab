# AI use: this file was written by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""USDA NASS Quick Stats for US pins (Build Spec v4, A3 and R2). Owner: Person 3.

What it gives the engine, per county (5-digit FIPS):
  county_yields(fips, crop)      DataFrame [year, yield_kg_ha, level]  (hindcast and default yields)
  prices_received(state_fips, crop)  {"usd_per_t", "year", "level"}    (state, else national)
  crops_grown(fips)              list of engine crop ids with harvested area in the county
  irrigated_share(fips)          0..1 from the latest Census of Agriculture, or None
  us_defaults(fips)              everything above in the shape of api.USDefaults (called by get_site())

Rules:
  * Suppressed county values ((D) withheld etc.) or no county series -> the state series, labelled
    level="state" with the note "State average: county data withheld or not published by NASS" (R2).
  * Key: environment variable NASS_API_KEY. It is never written to disk, logs or cache metadata.
  * Caching: engine.cache.fetch_cached(kind="nass"), 7-day expiry. Without a key (or offline) cached and
    pre-cached copies are still used; with no copy at all a NassUnavailable error is raised and
    us_defaults() returns empty values with badge "missing" so the UI asks the farmer. Nothing is invented.
Units out: kg/ha and US dollars per tonne (engine units are metric).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import pandas as pd
import requests
import yaml

from engine import cache

ROOT = Path(__file__).resolve().parent.parent
ASSUMPTIONS = ROOT / "config" / "assumptions" / "us_data.yaml"
SOURCE = "USDA NASS Quick Stats"
LB_KG = 0.45359237
ACRE_HA = 0.40468564224
STATE_NOTE = "State average: county data withheld or not published by NASS"

# US state FIPS -> postal code (ANSI/FIPS 5-2 state codes).
STATE_FIPS = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "11": "DC",
    "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT",
    "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY"}


_PRECACHE = False      # True only inside precache_county(): answers go to the committed data/precache/


class NassUnavailable(RuntimeError):
    """No NASS key or network, and nothing cached for this query."""


@lru_cache(maxsize=1)
def config() -> dict:
    return yaml.safe_load(ASSUMPTIONS.read_text())


def crop_spec(crop: str) -> dict:
    return config()["crops"][crop]


def known_crops() -> list[str]:
    return list(config()["crops"])


def kg_ha_per_unit(crop: str) -> float:
    return float(crop_spec(crop)["lb_per_unit"]) * LB_KG / ACRE_HA


def usd_per_t_per_unit(crop: str) -> float:
    """Multiply a NASS price ($ per bushel / cwt / lb) by this to get $ per tonne."""
    return 1000.0 / (float(crop_spec(crop)["price_lb_per_unit"]) * LB_KG)


def has_key() -> bool:
    return bool(os.environ.get("NASS_API_KEY", "").strip())


def split_fips(fips: str) -> tuple[str, str]:
    f = str(fips).strip().zfill(5)
    return f[:2], f[2:]


def parse_value(v):
    """NASS 'Value' string -> float, or None when suppressed / not available ('(D)', '(Z)', ...)."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in set(config()["nass"]["suppressed_codes"]["value"]) or s.startswith("("):
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


# ------------------------------------------------------------------------------------------- raw query

def _get(params: dict) -> list[dict]:
    """One Quick Stats call. Returns the list of records ([] when NASS has no matching rows)."""
    key = os.environ.get("NASS_API_KEY", "").strip()
    if not key:
        raise NassUnavailable("NASS_API_KEY is not set")
    r = requests.get(config()["nass"]["api_url"]["value"], params={**params, "key": key, "format": "JSON"},
                     timeout=60)
    if r.status_code == 400 and "invalid query" in r.text.lower():
        return []                         # NASS answers 400 "bad request - invalid query" when nothing matches
    r.raise_for_status()
    data = r.json().get("data", [])
    keep = ("year", "Value", "commodity_desc", "class_desc", "util_practice_desc", "prodn_practice_desc",
            "statisticcat_desc", "unit_desc", "short_desc", "reference_period_desc", "agg_level_desc",
            "state_fips_code", "county_code", "source_desc", "freq_desc")
    return [{k: d.get(k) for k in keep} for d in data]


def query(kind_key: str, params: dict, refresh: str = "auto") -> tuple[list[dict], dict]:
    """Cached Quick Stats query. Returns (records, meta with data_as_of / stale / from_cache)."""
    try:
        return cache.fetch_cached("nass", kind_key, lambda: _get(params), SOURCE,
                                  url="https://quickstats.nass.usda.gov/api", refresh=refresh,
                                  precache=_PRECACHE)
    except cache.DataUnavailable as e:
        raise NassUnavailable(str(e)) from e


# ------------------------------------------------------------------------------------------- yields

def _county_records(fips: str, stat: str) -> tuple[list[dict], dict]:
    st, co = split_fips(fips)
    return query(f"county_{stat.lower().replace(' ', '_')}_{st}{co}",
                 {"source_desc": "SURVEY", "agg_level_desc": "COUNTY", "statisticcat_desc": stat,
                  "state_fips_code": st, "county_code": co})


def _state_records(state_fips: str, stat: str, commodity: str) -> tuple[list[dict], dict]:
    return query(f"state_{stat.lower().replace(' ', '_')}_{state_fips}_{commodity.lower()}",
                 {"source_desc": "SURVEY", "agg_level_desc": "STATE", "statisticcat_desc": stat,
                  "state_fips_code": state_fips, "commodity_desc": commodity})


def _match(rec: dict, crop: str, practice: str | None = None, unit_key: str = "yield_unit") -> bool:
    s = crop_spec(crop)
    if rec.get("commodity_desc") != s["commodity_desc"]:
        return False
    if s.get("class_desc") and unit_key == "yield_unit" and rec.get("class_desc") != s["class_desc"]:
        return False
    if s.get("util_practice_desc") and rec.get("util_practice_desc") not in (s["util_practice_desc"], None, ""):
        return False
    if unit_key and rec.get("unit_desc") != s[unit_key]:
        return False
    want = practice or "ALL PRODUCTION PRACTICES"
    if rec.get("prodn_practice_desc") not in (want, None, ""):
        return False
    return str(rec.get("reference_period_desc", "YEAR")).upper() == "YEAR"


def yield_series(records: list[dict], crop: str, practice: str | None = None) -> pd.Series:
    """Year -> kg/ha from Quick Stats yield records (suppressed values dropped)."""
    out = {}
    k = kg_ha_per_unit(crop)
    for r in records:
        if _match(r, crop, practice):
            v = parse_value(r.get("Value"))
            if v is not None:
                out[int(r["year"])] = v * k
    return pd.Series(out, dtype=float).sort_index()


def county_yields(fips: str, crop: str, practice: str | None = None, allow_state: bool = False) -> pd.DataFrame:
    """NASS county yield history [year, yield_kg_ha, level]. Empty if none.

    allow_state=True falls back to the state series (level="state") when the county has none. The hindcast
    keeps allow_state=False: validating a county model against a state number would overstate skill."""
    recs, _ = _county_records(fips, "YIELD")
    s = yield_series(recs, crop, practice)
    level = "county"
    if s.empty and allow_state:
        st, _co = split_fips(fips)
        srecs, _ = _state_records(st, "YIELD", crop_spec(crop)["commodity_desc"])
        s, level = yield_series(srecs, crop, practice), "state"
    return pd.DataFrame({"year": s.index.astype(int), "yield_kg_ha": s.to_numpy(float), "level": level})


def default_yield(fips: str, crop: str, n_years: int | None = None) -> dict | None:
    """Mean of the latest n county yields (state if the county is suppressed). None if NASS has neither."""
    n = int(n_years or config()["nass"]["default_years_for_mean"]["value"])
    df = county_yields(fips, crop, allow_state=True)
    if df.empty:
        return None
    last = df.sort_values("year").tail(n)
    level = str(last["level"].iloc[0])
    return {"yield_kg_ha": round(float(last["yield_kg_ha"].mean()), 1), "years": [int(y) for y in last["year"]],
            "level": level, "badge": "observed" if level == "county" else "estimated",
            "note": None if level == "county" else STATE_NOTE}


# ------------------------------------------------------------------------------------------- prices

def prices_received(state_fips: str, crop: str) -> dict | None:
    """Latest marketing-year price received in $/t: state, else national (labelled). None if neither."""
    s = crop_spec(crop)
    params = {"source_desc": "SURVEY", "statisticcat_desc": "PRICE RECEIVED", "commodity_desc": s["commodity_desc"],
              "freq_desc": "ANNUAL", "reference_period_desc": "MARKETING YEAR"}
    for level, extra in (("state", {"agg_level_desc": "STATE", "state_fips_code": state_fips}),
                         ("national", {"agg_level_desc": "NATIONAL"})):
        key = f"price_{level}_{state_fips if level == 'state' else 'us'}_{s['commodity_desc'].lower()}"
        recs, meta = query(key, {**params, **extra})
        best = None
        for r in recs:
            if r.get("unit_desc") != s["price_unit"]:
                continue
            if s.get("price_class_desc") and r.get("class_desc") not in (s["price_class_desc"], None, ""):
                continue
            if not s.get("price_class_desc") and s.get("class_desc") and r.get("class_desc") not in (s["class_desc"], "ALL CLASSES", None, ""):
                continue
            v = parse_value(r.get("Value"))
            if v is not None and (best is None or int(r["year"]) > best[0]):
                best = (int(r["year"]), v)
        if best:
            return {"usd_per_t": round(best[1] * usd_per_t_per_unit(crop), 2), "year": best[0], "level": level,
                    "badge": "observed" if level == "state" else "estimated", "data_as_of": meta.get("data_as_of"),
                    "note": None if level == "state" else "National price: no state price published by NASS"}
    return None


# ------------------------------------------------------------------------------------------- crops, irrigation

def crops_grown(fips: str, recent_years: int = 5) -> list[str]:
    """Engine crop ids with harvested area reported in the county in the latest few survey years.
    Suppressed (D) area still counts as grown: NASS withholds it only when there are few operations."""
    recs, _ = _county_records(fips, "AREA HARVESTED")
    if not recs:
        return []
    last = max(int(r["year"]) for r in recs)
    grown = []
    for crop in known_crops():
        s = crop_spec(crop)
        for r in recs:
            if int(r["year"]) <= last - recent_years or r.get("commodity_desc") != s["commodity_desc"]:
                continue
            if s.get("class_desc") and r.get("class_desc") not in (s["class_desc"],):
                continue
            v = parse_value(r.get("Value"))
            if v is None or v > 0:
                grown.append(crop)
                break
    return grown


def irrigated_share(fips: str) -> float | None:
    """Irrigated acres / cropland acres from the latest Census of Agriculture year with both. None if missing."""
    cfg = config()["irrigated_share"]
    st, co = split_fips(fips)
    recs, _ = query(f"census_irrigation_{st}{co}",
                    {"source_desc": cfg["source_desc"]["value"], "agg_level_desc": "COUNTY",
                     "state_fips_code": st, "county_code": co, "commodity_desc": "AG LAND",
                     "domain_desc": "TOTAL"})
    by_year: dict[int, dict] = {}
    for r in recs:
        v = parse_value(r.get("Value"))
        if v is None:
            continue
        if r.get("short_desc") == cfg["irrigated_short_desc"]["value"]:
            by_year.setdefault(int(r["year"]), {})["irr"] = v
        elif r.get("short_desc") == cfg["cropland_short_desc"]["value"]:
            by_year.setdefault(int(r["year"]), {})["crop"] = v
    for y in sorted(by_year, reverse=True):
        d = by_year[y]
        if "irr" in d and d.get("crop"):
            return round(min(1.0, d["irr"] / d["crop"]), 3)
    return None


# ------------------------------------------------------------------------------------------- one call for get_site()

def us_defaults(fips: str) -> dict:
    """Everything get_site() needs for a US county, shaped like api.USDefaults (as a dict).

    Keys: crops, yields (kg/ha), prices ($/t), costs ($/ha, from fetch_ers), irrigated_share, level
    ("county" or "state" if any value fell back), badges, notes, data_as_of, available (False when NASS
    could not be reached and nothing is cached: the UI must then ask the farmer for every value)."""
    from engine import fetch_ers

    st, _co = split_fips(fips)
    out = {"crops": [], "yields": {}, "prices": {}, "costs": {}, "irrigated_share": None, "level": "county",
           "badges": {}, "notes": {}, "data_as_of": None, "available": True, "source": SOURCE}
    try:
        _recs, meta = _county_records(fips, "YIELD")
        out["data_as_of"] = meta.get("data_as_of")
        grown = crops_grown(fips)
        out["crops"] = grown
        for crop in grown:
            y = default_yield(fips, crop)
            if y:
                out["yields"][crop] = y["yield_kg_ha"]
                out["badges"][f"yield:{crop}"] = y["badge"]
                if y["level"] == "state":
                    out["level"] = "state"
                    out["notes"][f"yield:{crop}"] = STATE_NOTE
            p = prices_received(st, crop)
            if p:
                out["prices"][crop] = p["usd_per_t"]
                out["badges"][f"price:{crop}"] = p["badge"]
                if p["note"]:
                    out["notes"][f"price:{crop}"] = p["note"]
        out["irrigated_share"] = irrigated_share(fips)
        out["badges"]["irrigated_share"] = "observed" if out["irrigated_share"] is not None else "missing"
    except NassUnavailable as e:
        out["available"] = False
        out["notes"]["nass"] = f"NASS data unavailable ({e}). Enter yields and prices yourself."
        out["badges"]["nass"] = "missing"
    for crop in out["crops"] or known_crops():
        c = fetch_ers.cost_for_county(fips, crop)
        if c:
            out["costs"][crop] = c["usd_per_ha"]
            out["badges"][f"cost:{crop}"] = "estimated"
            out["notes"][f"cost:{crop}"] = c["note"]
    return out


def precache_county(fips: str, crops=None) -> dict:
    """Fetch every NASS query a county needs and write it to the committed pre-cache (needs NASS_API_KEY)."""
    global _PRECACHE
    _PRECACHE = True
    try:
        d = us_defaults(fips)
        for crop in crops or []:
            county_yields(fips, crop)
        return d
    finally:
        _PRECACHE = False


if __name__ == "__main__":
    import sys

    if "--precache-validation" in sys.argv:
        from engine import hindcast as _hc

        for site in _hc.validation_sites():
            try:
                d = precache_county(site["fips"], site["crops"])
                print(site["id"], "ok" if d["available"] else d["notes"].get("nass"))
            except NassUnavailable as err:
                print(site["id"], "NASS unavailable:", err)
