# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Fake site, inputs and simulate() shared by the Feature 3 UI tests (hand-checkable numbers, no network)."""
import types

import numpy as np

F = np.linspace(0.2, 1.6, 10)
US = {"prices": {"maize": 200.0, "sorghum": 150.0, "soybean": 400.0}, "costs": {"maize": 300.0, "sorghum": 100.0, "soybean": 200.0}}
CROPS = ["maize", "sorghum", "soybean"]


def site(awc=150.0):
    return types.SimpleNamespace(lat=38.4, lon=-97.6, us_defaults=US, soil=types.SimpleNamespace(awc_mm_per_m=awc, organic_matter_pct=2.0))


def inputs(plan=("sorghum",) * 4, mode="rain", normal=None):
    return types.SimpleNamespace(current_plan=list(plan), crop_overrides={}, history=None,
                                 water=types.SimpleNamespace(mode=mode, normal_mm=normal, dry_mm=None))


def simulate(s, i, rotation, scenarios):
    cap = min(1.0, s.soil.awc_mm_per_m / 150.0)
    cols = [{"maize": 8000 * F * cap, "sorghum": 3500 + 500 * F, "soybean": 3000 * (0.7 + 0.3 * F)}[yr[0]] for yr in rotation["crops"]]
    y = np.stack(cols, axis=1)
    return {"yields_kg_ha": y, "irrigation_mm": np.zeros_like(y), "total_water_mm": np.full_like(y, 400.0)}
