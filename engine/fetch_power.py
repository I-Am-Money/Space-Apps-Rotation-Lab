# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
# TODO (Person 2 handoff, 2026-11-15 12:56 PM): the v4 section at the bottom (load_site_weather) works live (tested for
# Iowa: 1981 to 2026-11-12, no NaN, ET0 included) but has NO unit tests yet. The v3 load_weather above is unchanged.
"""NASA POWER daily point data (community AG) -> contract DataFrame.

load_weather(lat, lon) -> DataFrame indexed by daily date 1981-01-01..2025-12-31,
columns tmax,tmin,tmean,rh,wind2,precip,srad. No NaN, no -999.
Default returns 1984-01-01..2025-12-31 (srad record start); see srad_leading_gap.

Known property of the source (verified in the downloaded JSON, header v2.10.3):
ALLSKY_SFC_SW_DWN (srad) is -999 for all of 1981-01-01..1983-12-31 (1095 days);
POWER solar data start 1984-01-01. That gap is far longer than 3 days so it is
never interpolated. Policy (`srad_leading_gap`):
  "trim" (default): drop 1981-01-01..1983-12-31 and return 1984-01-01..2025-12-31
        (15,341 days, 42 years). No invented values. Trim recorded in df.attrs["trimmed_range"].
  "doy_climatology" (explicit opt-in, off by default): fill that block with the
        1984-2025 day-of-year mean srad; labelled in df.attrs (badge: assumption).
  "raise": fail loudly (strict).
Any other gap > 3 days, in any variable, always raises.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
API = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMS = ["T2M_MAX", "T2M_MIN", "T2M", "RH2M", "WS2M", "PRECTOTCORR", "ALLSKY_SFC_SW_DWN"]
RENAME = {"T2M_MAX": "tmax", "T2M_MIN": "tmin", "T2M": "tmean", "RH2M": "rh",
          "WS2M": "wind2", "PRECTOTCORR": "precip", "ALLSKY_SFC_SW_DWN": "srad"}
START, END = "1981-01-01", "2025-12-31"
MAX_INTERP_GAP = 3


def cache_path(lat: float, lon: float) -> Path:
    return RAW / f"power_{lat}_{lon}.json"


def _request(lat, lon, start, end):
    r = requests.get(API, params={
        "parameters": ",".join(PARAMS), "community": "AG", "longitude": lon,
        "latitude": lat, "start": start, "end": end, "format": "JSON"}, timeout=(5, 30))
    r.raise_for_status()
    return r.json()


def fetch_raw(lat: float, lon: float, force: bool = False) -> dict:
    """Return raw POWER JSON, from cache if present. Chunks by decade if full range fails."""
    p = cache_path(lat, lon)
    if p.exists() and not force:
        return json.loads(p.read_text())
    RAW.mkdir(parents=True, exist_ok=True)
    try:
        data = _request(lat, lon, START.replace("-", ""), END.replace("-", ""))
    except Exception:
        data = None
        for y0 in range(1981, 2026, 5):
            part = _request(lat, lon, f"{y0}0101", f"{min(y0 + 4, 2025)}1231")
            if data is None:
                data = part
            else:
                for k, v in part["properties"]["parameter"].items():
                    data["properties"]["parameter"][k].update(v)
    p.write_text(json.dumps(data))
    return data


def _fill_gaps(s: pd.Series, name: str) -> pd.Series:
    """Interpolate NaN runs of <= 3 days; raise on longer runs."""
    isn = s.isna()
    if not isn.any():
        return s
    run_id = (isn != isn.shift()).cumsum()
    for _, grp in s[isn].groupby(run_id[isn]):
        if len(grp) > MAX_INTERP_GAP:
            raise ValueError(f"POWER {name}: gap of {len(grp)} days "
                             f"({grp.index[0].date()}..{grp.index[-1].date()}) exceeds {MAX_INTERP_GAP}")
    return s.interpolate(limit=MAX_INTERP_GAP, limit_area="inside")


def load_weather(lat: float, lon: float, srad_leading_gap: str = "trim") -> pd.DataFrame:
    raw = fetch_raw(lat, lon)
    par = raw["properties"]["parameter"]
    df = pd.DataFrame({RENAME[k]: pd.Series(par[k]) for k in PARAMS})
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df.index.name = "date"
    df = df.replace(-999, np.nan).replace(-999.0, np.nan).astype(float)
    df = df.reindex(pd.date_range(START, END, freq="D"))
    df.index.name = "date"

    # Structural leading srad gap (POWER solar record starts 1984).
    lead = df["srad"].isna()
    filled = trimmed = None
    if lead.any():
        first_valid = df["srad"].first_valid_index()
        block = df.index[(df.index < first_valid) & lead]
        if len(block) > MAX_INTERP_GAP and len(block) == int(lead[: len(block)].sum()) and block[0] == df.index[0]:
            if srad_leading_gap == "raise":
                raise ValueError(f"POWER srad missing {block[0].date()}..{block[-1].date()} "
                                 f"({len(block)} days); solar record starts {first_valid.date()}")
            rng = (str(block[0].date()), str(block[-1].date()))
            if srad_leading_gap == "trim":
                df = df.loc[first_valid:]
                trimmed = rng
            elif srad_leading_gap == "doy_climatology":
                clim = df["srad"].groupby(df.index.day_of_year).mean()
                df.loc[block, "srad"] = block.day_of_year.map(clim).to_numpy()
                filled = rng
            else:
                raise ValueError(f"unknown srad_leading_gap {srad_leading_gap!r}")
    for c in df.columns:
        df[c] = _fill_gaps(df[c], c)
    assert not df.isna().any().any()
    df.attrs["srad_filled_range"] = filled
    df.attrs["trimmed_range"] = trimmed
    df.attrs["srad_fill_method"] = ("1984-2025 day-of-year mean (POWER solar record starts 1984); "
                                    "badge: assumption" if filled else None)
    df.attrs["lat"], df.attrs["lon"] = lat, lon
    df.attrs["elevation_m"] = raw["geometry"]["coordinates"][2]
    df.attrs["power_api_version"] = raw.get("header", {}).get("api", {}).get("version")
    return df


def describe(df: pd.DataFrame) -> dict:
    """Record length plus annual and Jun-Oct monsoon rainfall statistics."""
    annual = df["precip"].groupby(df.index.year).sum()
    mons = df.loc[df.index.month.isin([6, 7, 8, 9, 10]), "precip"]
    mons = mons.groupby(mons.index.year).sum()

    def st(s):
        return {"mean": float(s.mean()), "median": float(s.median()), "std": float(s.std()),
                "min": float(s.min()), "max": float(s.max()),
                "p10": float(s.quantile(.1)), "p90": float(s.quantile(.9))}
    return {"n_days": int(len(df)), "n_years": int(annual.size),
            "start": str(df.index[0].date()), "end": str(df.index[-1].date()),
            "annual_rain_mm": st(annual), "monsoon_JunOct_rain_mm": st(mons),
            "monsoon_share_of_annual": float(mons.sum() / annual.sum()),
            "elevation_m": df.attrs.get("elevation_m"),
            "srad_filled_range": df.attrs.get("srad_filled_range"),
            "trimmed_range": df.attrs.get("trimmed_range")}


def _region_point():
    import yaml
    r = yaml.safe_load((ROOT / "config" / "region.yaml").read_text())
    return r["lat"], r["lon"]


if __name__ == "__main__":
    import sys
    la, lo = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 else _region_point()
    print(json.dumps(describe(load_weather(la, lo)), indent=2))


# =====================================================================================================
# Build Spec v4 weather loader (Person 2, task 2): any point on Earth, 1981 to the latest day NASA has.
#
# load_site_weather(lat, lon) -> daily DataFrame, columns tmax, tmin, tmean, rh, wind2, precip, srad, et0,
# et0_hargreaves (True where ET0 came from the Hargreaves fallback) and filled (True where any input was
# gap-filled). No -999 and no NaN ever leaves this function (v4 test "no -999 or NaN reaches the engine").
#
# Missing values (POWER uses -999):
#   - trailing days NASA has not published yet are dropped (the record ends at the last complete day);
#   - gaps of up to 3 days are interpolated;
#   - longer gaps (in practice: solar radiation before 1984, when the POWER solar record starts) are filled
#     with that variable's day-of-year mean and flagged in the `filled` column and in df.attrs["filled_days"].
#     On those days ET0 uses the Hargreaves equation, which needs only Tmax and Tmin, so the filled solar,
#     humidity or wind values never drive the water balance.
# Cached through engine.cache (weather expires after 7 days; an expired copy is still served offline).
# =====================================================================================================
import datetime as _dt

from engine import cache as _cache

V4_START = "1981-01-01"
SOURCE_NAME = "NASA POWER daily point API (community AG)"


def _request_range(lat, lon, start: str, end: str) -> dict:
    try:
        return _request(lat, lon, start, end)
    except requests.HTTPError as exc:
        # Chunk only a rejected range/size request. Repeating timeouts or authentication/
        # rate-limit errors nine times makes an outage slower without improving coverage.
        if exc.response is None or exc.response.status_code not in (400, 413, 422):
            raise
        data = None
        y0, y1 = int(start[:4]), int(end[:4])
        for first in range(y0, y1 + 1, 5):
            part = _request(lat, lon, f"{first}0101" if first > y0 else start,
                            f"{min(first + 4, y1)}1231" if first + 4 < y1 else end)
            if data is None:
                data = part
            else:
                for key, values in part['properties']['parameter'].items():
                    data['properties']['parameter'][key].update(values)
        return data


def _fetch_payload(lat: float, lon: float) -> dict:
    end = (_dt.date.today() - _dt.timedelta(days=1)).strftime("%Y%m%d")
    raw = _request_range(lat, lon, V4_START.replace("-", ""), end)
    par = raw["properties"]["parameter"]
    days = sorted(par[PARAMS[0]])
    cols = {RENAME[k]: [None if (par[k].get(d) is None or par[k][d] <= -900) else par[k][d] for d in days]
            for k in PARAMS}
    return {"first_day": days[0], "last_day": days[-1], "n_days": len(days), "dates": days, "columns": cols,
            "elevation_m": raw["geometry"]["coordinates"][2],
            "grid_point": raw["geometry"]["coordinates"][:2],
            "api_version": raw.get("header", {}).get("api", {}).get("version")}


def _fill_series(s: pd.Series) -> tuple[pd.Series, pd.Series]:
    """(filled series, mask of every filled day). Short gaps are interpolated."""
    if not s.isna().any():
        return s, pd.Series(False, index=s.index)
    short = s.interpolate(limit=MAX_INTERP_GAP, limit_area="inside")
    isn = s.isna()
    run = (isn != isn.shift()).cumsum()
    run_len = isn.groupby(run).transform("sum")
    long_gap = isn & (run_len > MAX_INTERP_GAP)
    short[long_gap] = np.nan                                   # do not half-interpolate long gaps
    clim = s.groupby(s.index.day_of_year).mean()
    fill = pd.Series(s.index.day_of_year, index=s.index).map(clim)
    out = short.where(~short.isna(), fill)
    if out.isna().any():                                       # a day of year never observed: overall mean
        out = out.fillna(s.mean())
    return out, isn


def frame_from_payload(payload: dict, lat: float, lon: float, meta: dict | None = None) -> pd.DataFrame:
    """Build the clean daily frame (see module notes). Raises ValueError if NASA returned no usable days."""
    from engine import et0 as _et0

    idx = pd.to_datetime(payload["dates"], format="%Y%m%d") if payload.get("dates") else pd.date_range(pd.Timestamp(payload["first_day"]), periods=payload["n_days"], freq="D")
    df = pd.DataFrame({k: pd.array(v, dtype="float64") for k, v in payload["columns"].items()}, index=idx).astype(float)
    df.index.name = "date"
    if df.index.has_duplicates or not df.index.is_monotonic_increasing:
        raise ValueError("NASA POWER dates must be unique and increasing")
    df = df.reindex(pd.date_range(df.index.min(), df.index.max(), freq="D"))
    df = df.replace([np.inf, -np.inf], np.nan)
    for name in ("precip", "wind2", "srad"):
        df.loc[df[name] < 0, name] = np.nan
    df.loc[~df["rh"].between(0, 100), "rh"] = np.nan
    core = df[["tmax", "tmin", "precip"]].notna().all(axis=1)
    if not core.any():
        raise ValueError("NASA POWER returned no usable days for this point")
    df = df.loc[:core[core].index[-1]]                         # drop the not-yet-published tail
    missing = df.isna()
    filled_any = pd.Series(False, index=df.index)
    filled_days = {}
    for c in list(df.columns):
        df[c], m = _fill_series(df[c])
        filled_days[c] = int(m.sum())
        filled_any |= m
    if df.isna().any().any():
        raise ValueError("NASA POWER weather still has gaps after filling")
    if (df["tmax"] < df["tmin"]).any():
        raise ValueError("NASA POWER contains maximum temperatures below minimum temperatures")
    df["tmean"] = np.where(missing["tmean"], (df["tmax"] + df["tmin"]) / 2, df["tmean"])
    elev = float(payload.get("elevation_m") or 0.0)
    doy = df.index.day_of_year.to_numpy()
    es = (_et0._sat_vp(df["tmax"].to_numpy()) + _et0._sat_vp(df["tmin"].to_numpy())) / 2
    ea = np.clip(df["rh"].to_numpy(), 1, 100) / 100 * es
    pm = _et0.et0_penman_monteith(df["tmax"], df["tmin"], df["srad"], np.maximum(df["wind2"], 0.5), ea, lat, doy, elev)
    hg = _et0.et0_hargreaves(df["tmax"], df["tmin"], lat, doy)
    use_hg = (missing[["rh", "wind2", "srad"]].any(axis=1) | filled_any).to_numpy()
    df["et0"] = np.where(use_hg, hg, pm)
    df["et0_hargreaves"] = use_hg
    df["filled"] = filled_any.to_numpy()
    df.attrs.update(lat=float(lat), lon=float(lon), elevation_m=elev, source=SOURCE_NAME, url=API,
                    power_api_version=payload.get("api_version"), filled_days=filled_days,
                    hargreaves_days=int(use_hg.sum()), first_day=str(df.index[0].date()),
                    last_day=str(df.index[-1].date()),
                    last_full_year=int(df.index[-1].year if (df.index[-1].month, df.index[-1].day) == (12, 31)
                                       else df.index[-1].year - 1),
                    data_as_of=(meta or {}).get("data_as_of"), stale=bool((meta or {}).get("stale", False)),
                    badge="Observed")
    return df


def load_site_weather(lat: float, lon: float, refresh: str = "auto", precache: bool = False) -> pd.DataFrame:
    """Clean daily weather for any point, 1981 to the latest published day, with ET0. See module notes.

    refresh: "auto" (7-day expiry), "never" (use any cached copy, for instant demo sites), "force".
    Raises engine.cache.DataUnavailable when there is no cached copy and NASA POWER cannot be reached.
    """
    lat, lon = float(lat), float(lon)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("latitude must be -90..90 and longitude -180..180")
    key = _cache.location_key(lat, lon)
    payload, meta = _cache.fetch_cached("weather", key, lambda: _fetch_payload(lat, lon), SOURCE_NAME, API,
                                        refresh=refresh, precache=precache)
    return frame_from_payload(payload, lat, lon, meta)


def full_years(weather: pd.DataFrame) -> pd.DataFrame:
    """The frame cut to complete calendar years (what scenarios should sample from)."""
    return weather.loc[:f"{int(weather.attrs.get('last_full_year', weather.index[-1].year - 1))}-12-31"]
