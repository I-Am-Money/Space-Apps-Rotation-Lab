# AI use: this file was written by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Monsoon onset (Build Spec v3 section 6.2) and the sowing rule that follows it.

Onset rule (one simple, documented rule; every number lives in config/assumptions.yaml, block `monsoon_onset`):
  the first day on or after `start_doy` (1 June) when rain over `window_days` consecutive days reaches
  `threshold_mm`, and which is NOT followed, within the next `dry_search_days`, by a dry spell of
  `dry_spell_days` consecutive days with less than `dry_spell_mm` of rain in total.
If no day qualifies before `last_doy`, onset is `last_doy` (the year is flagged as "no clean onset").

Sowing rule: every crop's `sowing_doy` in assumptions.yaml is its sowing (rice: transplanting) date in a year with
the MEDIAN onset of the weather record. In any other year sowing moves by the same number of days as onset:
  sowing(year, crop) = crop.sowing_doy + (onset(year) - median_onset) + what-if delay
clipped so the season still ends inside the calendar year (stated in LIMITATIONS.md).

Day-of-year values here are 1-based (1 = 1 January) on a 365-day year (29 February dropped).
"""
from __future__ import annotations

import numpy as np

from engine.crops import A

NDAY = 365


def onset_params(params: dict | None = None) -> dict:
    g = lambda k: A(params, f"monsoon_onset.{k}")
    return {"start_doy": int(g("start_doy")), "window_days": int(g("window_days")), "threshold_mm": float(g("threshold_mm")),
            "dry_spell_days": int(g("dry_spell_days")), "dry_spell_mm": float(g("dry_spell_mm")),
            "dry_search_days": int(g("dry_search_days")), "last_doy": int(g("last_doy"))}


def onset_doy(precip_year, params: dict | None = None) -> int:
    """Onset day-of-year (1-based) for one year of daily rain [365]."""
    return int(onset_doy_years(np.asarray(precip_year, float)[None, :], params)[0])


def onset_doy_years(precip, params: dict | None = None) -> np.ndarray:
    """Onset day-of-year (1-based) for each row of daily rain [Y, 365]. Returns int array [Y]."""
    q = onset_params(params)
    p = np.asarray(precip, float)
    Y = p.shape[0]
    c = np.concatenate([np.zeros((Y, 1)), np.cumsum(p, axis=1)], axis=1)        # c[:, d] = rain before day index d
    win, dry, look = q["window_days"], q["dry_spell_days"], q["dry_search_days"]
    out = np.full(Y, q["last_doy"], int)
    for i in range(Y):
        for d in range(q["start_doy"] - 1, q["last_doy"] - 1):                  # d = 0-based day index
            if d + win > NDAY or c[i, d + win] - c[i, d] < q["threshold_mm"]:
                continue
            ok = True
            for s in range(d + win, min(d + win + look - dry + 1, NDAY - dry + 1)):
                if c[i, s + dry] - c[i, s] < q["dry_spell_mm"]:
                    ok = False
                    break
            if ok:
                out[i] = d + 1
                break
    return out


def sowing_doy(base_sowing_doy: int, season_days: int, onset, median_onset: float, delay_days=0):
    """Sowing day-of-year (1-based) per scenario-year. `onset` any shape; returns an int array of that shape.
    Capped so that sowing + season length stays inside the 365-day year; never before 1 January."""
    shift = np.rint(np.asarray(onset, float) - float(median_onset)).astype(int) + np.asarray(delay_days, int)
    s = int(base_sowing_doy) + shift
    return np.clip(s, 1, NDAY - int(season_days) + 1)


def summary(annual: dict, params: dict | None = None) -> dict:
    """Onset statistics of the weather record for the Our Farm tab (observed rain, modeled rule)."""
    on = annual["onset"] if annual.get("onset") is not None else onset_doy_years(annual["precip"], params)
    q = onset_params(params)
    yrs = np.asarray(annual["years"])
    return {"onset_doy": [int(x) for x in on], "years": [int(y) for y in yrs],
            "median_doy": float(np.median(on)), "earliest_doy": int(on.min()), "latest_doy": int(on.max()),
            "earliest_year": int(yrs[int(on.argmin())]), "latest_year": int(yrs[int(on.argmax())]),
            "no_clean_onset_years": [int(y) for y, o in zip(yrs, on) if o >= q["last_doy"]],
            "rule": (f"first day on or after day {q['start_doy']} (1 June) with at least {q['threshold_mm']:g} mm in "
                     f"{q['window_days']} days, not followed within {q['dry_search_days']} days by "
                     f"{q['dry_spell_days']} days with under {q['dry_spell_mm']:g} mm"),
            "badge": "modeled", "rain_badge": "observed"}


def detect_onset(rain, params=None):
    """First wet window after June 1 without a following long dry spell.

    Returns the END of the wet window. A year with no qualifying window returns
    365 (no planting). Works on any leading dimensions, so scenarios stay vectorized.
    The thresholds describe a planning assumption, not an official IMD onset date.
    """
    rain = np.asarray(rain, dtype=float)
    if rain.shape[-1] != 365 or not np.isfinite(rain).all() or (rain < 0).any():
        raise ValueError("Onset requires 365 finite, nonnegative daily rain values")
    start = int(A(params, "monsoon.search_start_doy")) - 1
    end = int(A(params, "monsoon.search_end_doy")) - 1
    window = int(A(params, "monsoon.wet_window_days"))
    threshold = float(A(params, "monsoon.wet_window_mm"))
    look = int(A(params, "monsoon.followup_days"))
    dry_len = int(A(params, "monsoon.max_dry_spell_days"))
    dry_mm = float(A(params, "monsoon.dry_day_mm"))
    csum = np.concatenate([np.zeros(rain.shape[:-1] + (1,)), rain.cumsum(-1)], axis=-1)
    dry = rain < dry_mm
    dc = np.concatenate([np.zeros(rain.shape[:-1] + (1,)), dry.cumsum(-1)], axis=-1)
    out = np.full(rain.shape[:-1], 365, dtype=np.int64)
    for day in range(start + window - 1, min(end + 1, 365 - look)):
        wet = csum[..., day + 1] - csum[..., day + 1 - window] >= threshold
        long_dry = np.zeros(rain.shape[:-1], dtype=bool)
        for after in range(day + 1, day + look - dry_len + 2):
            long_dry |= dc[..., after + dry_len] - dc[..., after] >= dry_len
        select = (out == 365) & wet & ~long_dry
        out[select] = day
    return out
