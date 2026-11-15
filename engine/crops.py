# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Crop parameters and assumption lookup. Reads config/assumptions.yaml (nothing hard-coded here)."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
ASSUMPTIONS_PATH = ROOT / "config" / "assumptions.yaml"
PRICES_PATH = ROOT / "config" / "prices_india.yaml"
CROP_IDS = ("rice", "jowar", "bajra", "ragi", "pigeonpea")
MILLETS = ("jowar", "bajra", "ragi")


def load_assumptions() -> dict:
    return _read_assumptions(ASSUMPTIONS_PATH.stat().st_mtime_ns)


@lru_cache(maxsize=2)
def _read_assumptions(version) -> dict:
    """Flat dict: dotted name -> leaf dict(value, range, unit, source, badge)."""
    raw = yaml.safe_load(ASSUMPTIONS_PATH.read_text())
    flat = {}

    def walk(node, prefix):
        for k, v in node.items():
            name = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict) and "value" in v:
                flat[name] = v
            elif isinstance(v, dict):
                walk(v, name)

    walk(raw, "")
    return flat


def A(params: dict | None, name: str):
    """Assumption value with optional override: params[dotted name] wins, then params[leaf name]."""
    if params:
        if name in params:
            return params[name]
        leaf = name.rsplit(".", 1)[-1]
        if leaf in params and not name.startswith(("crops.", "heat.tmax_c.", "heat.flowering_days.", "soil_cover.score.")):
            return params[leaf]
    return load_assumptions()[name]["value"]


@dataclass
class CropParams:
    id: str
    kc_ini: float
    kc_mid: float
    kc_end: float
    stages_days: tuple
    root_depth_m: float
    p: float
    ky: float
    sowing_doy: int
    ym_kg_ha: float
    badges: dict = field(default_factory=dict)

    @property
    def season_days(self) -> int:
        return int(sum(self.stages_days))

    def kc_curve(self) -> np.ndarray:
        """FAO-56 piecewise Kc over the season (ch.6 Fig. 34): flat ini, linear dev, flat mid, linear late."""
        ini, dev, mid, late = self.stages_days
        kc = np.empty(self.season_days)
        kc[:ini] = self.kc_ini
        kc[ini:ini + dev] = np.linspace(self.kc_ini, self.kc_mid, dev + 1)[1:]
        kc[ini + dev:ini + dev + mid] = self.kc_mid
        kc[ini + dev + mid:] = np.linspace(self.kc_mid, self.kc_end, late + 1)[1:]
        return kc


@lru_cache(maxsize=1)
def _prices_yaml() -> dict:
    return (yaml.safe_load(PRICES_PATH.read_text()) or {}) if PRICES_PATH.exists() else {}


def _ym_from_prices(crop: str):
    if not PRICES_PATH.exists():
        return None, None
    d = _prices_data(PRICES_PATH.stat().st_mtime_ns)
    y = d.get("potential_yield_kg_ha")
    if not isinstance(y, dict) or crop not in y:
        return None, None
    v = y[crop]
    badge = "observed"
    if isinstance(v, dict):
        badge = v.get("badge", "observed")
        v = v.get("value")
    return (None, None) if v is None else (float(v), badge)


@lru_cache(maxsize=2)
def _prices_data(version):
    return yaml.safe_load(PRICES_PATH.read_text()) or {}


def load_crops(params: dict | None = None) -> dict[str, CropParams]:
    out = {}
    for c in CROP_IDS:
        g = lambda k: A(params, f"crops.{c}.{k}")
        ym, ym_badge = _ym_from_prices(c)
        meta = (_prices_data(PRICES_PATH.stat().st_mtime_ns).get("potential_yield_kg_ha") or {}).get(c, {})
        ym_badge = meta.get("badge", "modeled") if isinstance(meta, dict) else "modeled"
        if ym is None:
            ym, ym_badge = float(A(params, f"ym_kg_ha.{c}")), "placeholder"
        if params and f"ym_kg_ha.{c}" in params:
            ym = float(params[f"ym_kg_ha.{c}"])
        badges = {k: load_assumptions()[f"crops.{c}.{k}"]["badge"] for k in
                  ("kc_ini", "kc_mid", "kc_end", "stages_days", "root_depth_m", "p", "ky", "sowing_doy")}
        badges["ym_kg_ha"] = ym_badge
        out[c] = CropParams(c, float(g("kc_ini")), float(g("kc_mid")), float(g("kc_end")),
                            tuple(int(x) for x in g("stages_days")), float(g("root_depth_m")),
                            float(g("p")), float(g("ky")), int(g("sowing_doy")), ym, badges)
        item = out[c]
        if len(item.stages_days) != 4 or any(n <= 0 for n in item.stages_days) or item.season_days > 365:
            raise ValueError(f"{c}: use four positive crop-stage lengths totaling at most 365 days")
        values = [item.kc_ini, item.kc_mid, item.kc_end, item.root_depth_m, item.p, item.ky, item.ym_kg_ha]
        if not np.isfinite(values).all() or min(values) < 0 or item.root_depth_m <= 0 or not 0 < item.p < 1 or not 1 <= item.sowing_doy <= 365:
            raise ValueError(f"{c}: invalid crop coefficients, root depth, depletion fraction or calendar")
    return out
