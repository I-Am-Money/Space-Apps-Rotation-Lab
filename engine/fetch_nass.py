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
  * No key: the pre-cache command (and any run with NASS_PUBLIC_CSV=1) downloads the same Quick Stats records
    through the public Quick Stats website's own spreadsheet download, which needs no key. That route is not
    a documented API, so the app itself does not use it unless NASS_PUBLIC_CSV=1 is set.
  * Caching: engine.cache.fetch_cached(kind="nass"), 7-day expiry. Without a key (or offline) cached and
    pre-cached copies are still used; with no copy at all a NassUnavailable error is raised and
    us_defaults() returns empty values with badge "missing" so the UI asks the farmer. Nothing is invented.
Units out: kg/ha and US dollars per tonne (engine units are metric).
"""
from __future__ import annotations

import csv
import io
import os
import math
import re
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

import pandas as pd
import requests
import yaml

from engine import cache

ROOT = Path(__file__).resolve().parent.parent
ASSUMPTIONS = ROOT / "config" / "assumptions" / "us_data.yaml"
SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"
SOURCE = "USDA NASS Quick Stats"
LB_KG = 0.45359237
ACRE_HA = 0.40468564224
PUBLIC_URL = "https://quickstats.nass.usda.gov (website spreadsheet export, no key)"
STATE_NOTE = "State average: county data withheld or not published by NASS"

# US state FIPS -> postal code (ANSI/FIPS 5-2 state codes).
STATE_FIPS = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "11": "DC",
    "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT",
    "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY"}


_PRECACHE = ContextVar("nass_precache", default=False)  # isolated per request/thread


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


def _api_key() -> str:
    # Respect an explicitly empty environment value (tests/disabled service).
    if "NASS_API_KEY" in os.environ:
        return os.environ["NASS_API_KEY"].strip()
    import tomllib
    try:
        with SECRETS_PATH.open('rb') as stream:
            value = tomllib.load(stream).get('NASS_API_KEY', '')
        return value.strip() if isinstance(value, str) else ''
    except (OSError, ValueError):
        return ''


def has_key() -> bool:
    return bool(_api_key())


def split_fips(fips: str) -> tuple[str, str]:
    f = str(fips).strip().zfill(5)
    if not re.fullmatch(r"[0-9]{5}", f) or f[:2] not in STATE_FIPS or f[2:] == "000":
        raise ValueError("County FIPS must contain a valid two-digit state and three-digit county code")
    return f[:2], f[2:]


def parse_value(v):
    """NASS 'Value' string -> float, or None when suppressed / not available ('(D)', '(Z)', ...)."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in set(config()["nass"]["suppressed_codes"]["value"]) or s.startswith("("):
        return None
    try:
        value = float(s.replace(",", ""))
        return value if math.isfinite(value) and value >= 0 else None
    except ValueError:
        return None


# ------------------------------------------------------------------------------------------- public CSV route
# The Quick Stats website (https://quickstats.nass.usda.gov) lets anyone download a query as a spreadsheet
# without a key: the page posts the query to /uuid/encode and downloads /data/spreadsheet/<id>.csv. The rows
# are the same Quick Stats records as the API returns, but class, utilization, practice and unit are only
# inside the "Data Item" text, so they are parsed back out here. The two word lists below are parsing
# vocabulary (NASS names), not model parameters.

_PRACTICE_START = ("IRRIGATED", "NON-IRRIGATED", "ORGANIC", "FOLLOWING", "NOT FOLLOWING", "CONTINUOUS")
_UTIL_WORDS = {"GRAIN", "SILAGE", "FORAGE", "SEED", "HAY", "HAYLAGE", "SUGAR", "SYRUP", "PROCESSING",
               "FRESH MARKET", "HAY & HAYLAGE", "GREENCHOP", "OIL"}


def public_csv_allowed() -> bool:
    """The key-free website route is used only while pre-caching, or when NASS_PUBLIC_CSV=1 is set."""
    return _PRECACHE.get() or os.environ.get("NASS_PUBLIC_CSV", "").strip().lower() in ("1", "true", "yes")


def parse_data_item(item: str, commodity: str) -> dict:
    """Split a Quick Stats "Data Item" (short_desc) into class, utilization, practice, statistic and unit.

    "CORN, GRAIN, NON-IRRIGATED - YIELD, MEASURED IN BU / ACRE" ->
      class ALL CLASSES, util GRAIN, practice NON-IRRIGATED, statistic YIELD, unit BU / ACRE."""
    left, _, right = str(item).partition(" - ")
    stat, _, unit = right.partition(", MEASURED IN ")
    rest = left[len(commodity):] if commodity and left.startswith(commodity) else ""
    tokens = [t.strip() for t in rest.split(",") if t.strip()]
    util = [t for t in tokens if t in _UTIL_WORDS]
    tokens = [t for t in tokens if t not in _UTIL_WORDS]
    cut = next((i for i, t in enumerate(tokens) if t.startswith(_PRACTICE_START)), len(tokens))
    return {"class_desc": ", ".join(tokens[:cut]) or "ALL CLASSES",
            "util_practice_desc": ", ".join(util) or "ALL UTILIZATION PRACTICES",
            "prodn_practice_desc": ", ".join(tokens[cut:]) or "ALL PRODUCTION PRACTICES",
            "statisticcat_desc": stat.strip(), "unit_desc": unit.strip() or stat.strip()}


def records_from_csv(text: str) -> list[dict]:
    """Quick Stats website spreadsheet (CSV text) -> records shaped like the API's."""
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        item, commodity = row.get("Data Item") or "", row.get("Commodity") or ""
        if not item:
            continue
        out.append({"year": row.get("Year"), "Value": row.get("Value"), "commodity_desc": commodity,
                    **parse_data_item(item, commodity), "short_desc": item,
                    "reference_period_desc": row.get("Period"), "agg_level_desc": row.get("Geo Level"),
                    "state_fips_code": row.get("State ANSI"), "county_code": row.get("County ANSI"),
                    "source_desc": row.get("Program"), "freq_desc": None})
    return out


def _get_public_csv(params: dict) -> list[dict]:
    """The same query through the Quick Stats website's spreadsheet download (no key)."""
    cfg = config()["nass"]
    r = requests.post(cfg["public_encode_url"]["value"], data=params, timeout=60)
    r.raise_for_status()
    query_id = str(r.json()).strip()
    r = requests.get(cfg["public_csv_url"]["value"].format(id=query_id), timeout=180)
    r.raise_for_status()
    return records_from_csv(r.text)


# ------------------------------------------------------------------------------------------- raw query

def _get(params: dict) -> list[dict]:
    """One Quick Stats call. Returns the list of records ([] when NASS has no matching rows)."""
    key = _api_key()
    if not key:
        if public_csv_allowed():
            return _get_public_csv(params)
        raise NassUnavailable("NASS_API_KEY is not set")
    try:
        r = requests.get(config()["nass"]["api_url"]["value"], params={**params, "key": key, "format": "JSON"},
                         timeout=(5, 45))
        if r.status_code == 400 and "invalid query" in r.text.lower():
            return []  # Quick Stats uses this response for an empty selection too.
        if r.status_code in (401, 403):
            raise NassUnavailable("NASS authentication failed; check NASS_API_KEY in server secrets")
        if r.status_code >= 400:
            raise NassUnavailable(f"NASS service returned HTTP {r.status_code}; retry or use cached data")
        body = r.json()
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise NassUnavailable("NASS returned an invalid response; retry or use cached data")
        data = body["data"]
        if any(not isinstance(row, dict) for row in data):
            raise NassUnavailable("NASS returned invalid records; retry or use cached data")
    except (requests.RequestException, ValueError):
        # requests exceptions contain the prepared URL, including the API key.
        # Do not chain or return those errors to the UI/cache/logs.
        raise NassUnavailable("NASS request failed; retry or use cached data") from None
    keep = ("year", "Value", "commodity_desc", "class_desc", "util_practice_desc", "prodn_practice_desc",
            "statisticcat_desc", "unit_desc", "short_desc", "reference_period_desc", "agg_level_desc",
            "state_fips_code", "county_code", "source_desc", "freq_desc", "domain_desc", "domaincat_desc")
    return [{k: d.get(k) for k in keep} for d in data]


def check_connection() -> dict:
    """Small uncached authenticated probe. Never returns the credential or request URL."""
    rows = _get({'commodity_desc': 'CORN', 'statisticcat_desc': 'YIELD', 'agg_level_desc': 'COUNTY',
                 'state_fips_code': '19', 'county_code': '169', 'year': 2023,
                 'domain_desc': 'TOTAL', 'freq_desc': 'ANNUAL'})
    if not rows:
        raise NassUnavailable('The NASS probe returned no data; authentication and source availability are unverified')
    return {'authenticated': True, 'records': len(rows), 'source': SOURCE}


def query(kind_key: str, params: dict, refresh: str = "auto") -> tuple[list[dict], dict]:
    """Cached Quick Stats query. Returns (records, meta with data_as_of / stale / from_cache)."""
    try:
        url = PUBLIC_URL if (not has_key() and public_csv_allowed()) else "https://quickstats.nass.usda.gov/api"
        return cache.fetch_cached("nass", kind_key, lambda: _get(params), SOURCE, url=url, refresh=refresh,
                                  precache=_PRECACHE.get())
    except cache.DataUnavailable as e:
        raise NassUnavailable(str(e)) from e


# ------------------------------------------------------------------------------------------- yields

def _county_records(fips: str, stat: str) -> tuple[list[dict], dict]:
    st, co = split_fips(fips)
    return query(f"county_{stat.lower().replace(' ', '_')}_{st}{co}",
                 {"source_desc": "SURVEY", "agg_level_desc": "COUNTY", "statisticcat_desc": stat,
                  "state_fips_code": st, "county_code": co, "sector_desc": "CROPS",
                  "group_desc": "FIELD CROPS", "freq_desc": "ANNUAL", "domain_desc": "TOTAL"})


def _state_records(state_fips: str, stat: str, commodity: str) -> tuple[list[dict], dict]:
    return query(f"state_{stat.lower().replace(' ', '_')}_{state_fips}_{commodity.lower()}",
                 {"source_desc": "SURVEY", "agg_level_desc": "STATE", "statisticcat_desc": stat,
                  "state_fips_code": state_fips, "commodity_desc": commodity, "freq_desc": "ANNUAL", "domain_desc": "TOTAL"})


def _match(rec: dict, crop: str, practice: str | None = None, unit_key: str = "yield_unit") -> bool:
    s = crop_spec(crop)
    if rec.get("domain_desc") not in (None, "", "TOTAL"):
        return False
    if rec.get("commodity_desc") != s["commodity_desc"]:
        return False
    if s.get("class_desc") and unit_key == "yield_unit" and rec.get("class_desc") != s["class_desc"]:
        return False
    if not s.get("class_desc") and unit_key == "yield_unit" and rec.get("class_desc") not in ("ALL CLASSES", None, ""):
        return False                      # e.g. "RICE, LONG GRAIN" must not overwrite the all-rice yield
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
    recs, meta = _county_records(fips, "YIELD")
    s = yield_series(recs, crop, practice)
    level = "county"
    if s.empty and allow_state:
        st, _co = split_fips(fips)
        srecs, meta = _state_records(st, "YIELD", crop_spec(crop)["commodity_desc"])
        s, level = yield_series(srecs, crop, practice), "state"
    result = pd.DataFrame({"year": s.index.astype(int), "yield_kg_ha": s.to_numpy(float), "level": level})
    result.attrs.update(meta)
    return result


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
              "freq_desc": "ANNUAL", "reference_period_desc": "MARKETING YEAR", "domain_desc": "TOTAL"}
    for level, extra in (("state", {"agg_level_desc": "STATE", "state_fips_code": state_fips}),
                         ("national", {"agg_level_desc": "NATIONAL"})):
        key = f"price_{level}_{state_fips if level == 'state' else 'us'}_{s['commodity_desc'].lower()}"
        recs, meta = query(key, {**params, **extra})
        best = None
        for r in recs:
            if r.get("domain_desc") not in (None, "", "TOTAL"):
                continue
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
            if r.get("domain_desc") not in (None, "", "TOTAL"):
                continue
            if s.get("util_practice_desc") and r.get("util_practice_desc") not in (s["util_practice_desc"], None, ""):
                continue
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
    """Fetch every NASS query a county needs and write it to the committed pre-cache. Uses NASS_API_KEY when
    set, otherwise the public Quick Stats website download."""
    token = _PRECACHE.set(True)
    try:
        d = us_defaults(fips)
        histories = {}
        for crop in crops or []:
            df = county_yields(fips, crop)
            histories[crop] = {"years": len(df), "level": "county", "available": not df.empty, "stored": bool(df.attrs.get("stored"))}
        d["historical_yields"] = histories
        d["historical_complete"] = bool(histories) and all(row["available"] and row["stored"] for row in histories.values())
        return d
    finally:
        _PRECACHE.reset(token)


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
