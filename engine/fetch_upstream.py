"""Upstream (upper Krishna basin) Jun-Oct rainfall from NASA POWER points listed in config/region.yaml.

The mean of a few ~0.5 degree grid points is a PROXY for basin rainfall, not catchment inflow.
Uses engine.fetch_power for download, -999 handling, caching (data/raw/power_<lat>_<lon>.json).
Window: 1984-2025 (same as load_weather default).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from engine import fetch_power

ROOT = Path(__file__).resolve().parent.parent
SEASON_MONTHS = (6, 7, 8, 9, 10)


def upstream_points() -> list[dict]:
    reg = yaml.safe_load((ROOT / "config" / "region.yaml").read_text())
    pts = reg.get("upstream_points") or []
    if not 3 <= len(pts) <= 5:
        raise ValueError(f"expected 3-5 upstream_points, found {len(pts)}")
    return pts


def load_upstream_season_rain() -> pd.DataFrame:
    """DataFrame[year, mean_season_rain_mm, <one column per point name>], Jun-Oct totals, 1984-2025."""
    cols = {}
    for p in upstream_points():
        w = fetch_power.load_weather(p["lat"], p["lon"])  # raises on gaps; cached; 1984-2025
        s = w.loc[w.index.month.isin(SEASON_MONTHS), "precip"]
        cols[p["name"]] = s.groupby(s.index.year).sum()
    df = pd.DataFrame(cols)
    df.index.name = "year"
    df.insert(0, "mean_season_rain_mm", df.mean(axis=1))
    return df.reset_index()


def lowest_upstream_year(df: pd.DataFrame | None = None) -> tuple[int, float]:
    """(year, mean upstream Jun-Oct rain mm) of the real driest upstream season."""
    df = load_upstream_season_rain() if df is None else df
    i = df["mean_season_rain_mm"].idxmin()
    return int(df.loc[i, "year"]), float(df.loc[i, "mean_season_rain_mm"])


if __name__ == "__main__":
    d = load_upstream_season_rain()
    print(d.round(0).to_string(index=False))
    print("median", d.mean_season_rain_mm.median(), "lowest", lowest_upstream_year(d))
