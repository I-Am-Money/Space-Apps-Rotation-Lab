"""Validate anonymous farm records; never fabricate or persist uploaded rows."""
import numpy as np
import pandas as pd

from engine.economics import HA_PER_ACRE


def validate_records(frame):
    frame = pd.DataFrame(frame).copy()
    required = {"year", "crop", "area_acres", "yield_quintals"}
    if not required.issubset(frame.columns):
        raise ValueError("Farm CSV needs year, crop, area_acres and yield_quintals columns")
    if not 1 <= len(frame) <= 1000:
        raise ValueError("Use between 1 and 1000 farm-record rows")
    if "costs_inr" in frame and "costs_rupees" not in frame:
        frame = frame.rename(columns={"costs_inr": "costs_rupees"})
    frame = frame[[c for c in ("year", "crop", "area_acres", "yield_quintals", "costs_rupees") if c in frame]]
    aliases = {"paddy": "rice", "sorghum": "jowar", "pearl millet": "bajra", "finger millet": "ragi", "pigeon pea": "pigeonpea", "tur": "pigeonpea", "red gram": "pigeonpea"}
    frame["crop"] = frame.crop.astype(str).str.strip().str.lower().replace(aliases)
    if not frame.crop.isin(["rice", "jowar", "bajra", "ragi", "pigeonpea"]).all():
        raise ValueError("Farm crops must be rice, jowar, bajra, ragi or pigeonpea")
    for c in set(frame) - {"crop"}:
        frame[c] = pd.to_numeric(frame[c], errors="coerce")
        if not np.isfinite(frame[c]).all():
            raise ValueError(f"{c} must contain finite numbers")
    if not ((frame.year % 1 == 0) & frame.year.between(1900, 2100)).all():
        raise ValueError("Farm years must be whole calendar years")
    if (frame.area_acres <= 0).any() or (frame.yield_quintals < 0).any() or ("costs_rupees" in frame and (frame.costs_rupees < 0).any()):
        raise ValueError("Area must be positive; harvest and costs cannot be negative")
    frame["year"] = frame.year.astype(int)
    frame["yield_kg_ha"] = frame.yield_quintals * 100 / (frame.area_acres * HA_PER_ACRE)
    return frame
