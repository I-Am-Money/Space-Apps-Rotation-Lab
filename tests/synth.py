"""Synthetic scenario arrays for physics tests (seed 42). Not data: only used to exercise the engine."""
import numpy as np


def make_scen(S=12, rain_mult=1.0, seed=42, et0_val=4.0, n_events=45):
    rng = np.random.default_rng(seed)
    rain = np.zeros((S, 4, 365))
    for s in range(S):
        for y in range(4):
            days = rng.choice(np.arange(150, 290), n_events, replace=False)   # monsoon-like window
            rain[s, y, days] = rng.gamma(2.0, 12.0, n_events) * (0.6 + 0.8 * s / max(S - 1, 1))
    et0 = np.full((S, 4, 365), et0_val)
    return dict(et0=et0, precip=rain * rain_mult, tmax=np.full((S, 4, 365), 32.0),
                labels=[f"s{i}" for i in range(S)])
