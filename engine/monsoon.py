"""Transparent rainfall-onset rule. Day indices are zero-based, with Feb 29 removed."""
import numpy as np

from engine.crops import A


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
