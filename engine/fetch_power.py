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
        "latitude": lat, "start": start, "end": end, "format": "JSON"}, timeout=180)
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
