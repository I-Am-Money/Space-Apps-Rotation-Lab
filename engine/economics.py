"""Economics (engine-decision). Rupees per acre. The ONLY place kg/ha is converted to per-acre.

profit/acre/year = yield * price - operating cost + N-credit fertiliser saving - irrigation cost
Plan profit = sum of the 4 yearly profits, undiscounted.
Prices are FIXED across scenarios (no price model); the price multiplier slider scales them uniformly.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
HA_PER_ACRE = 0.404686
ACRE_PER_HA = 1.0 / HA_PER_ACRE
M3_PER_MM_ACRE = 4.04686     # 1 mm over 1 acre = 4.04686 m3
PRICES_PATH = ROOT / "config" / "prices_india.yaml"
CROPS = ("rice", "jowar", "bajra", "ragi", "pigeonpea")

ALIASES = {"rice": ("rice", "paddy", "paddy_common"), "jowar": ("jowar", "sorghum", "sorghum_hybrid", "jowar_hybrid"),
           "bajra": ("bajra", "pearl_millet", "pearlmillet", "millet"),
           "ragi": ("ragi", "finger_millet", "mandua"),
           "pigeonpea": ("pigeonpea", "pigeon_pea", "tur", "arhar", "redgram")}
PRICE_KEYS = ("msp_rs_per_quintal", "price_rs_per_quintal", "msp", "prices_rs_per_quintal", "prices")
OPCOST_KEYS = ("operating_cost_rs_per_acre", "operating_cost", "cost_of_cultivation_rs_per_acre")

# Fallbacks used ONLY so code runs when config/prices_india.yaml lacks the value. These are UNVERIFIED dev
# placeholders with no source (not MSP, not cost-of-cultivation data). Every use carries badge "placeholder".
PLACEHOLDER = {
    "price_rs_per_quintal": {"rice": 2369.0, "jowar": 3699.0, "bajra": 2775.0, "pigeonpea": 8000.0},
    "operating_cost_rs_per_acre": {"rice": 28000.0, "jowar": 11000.0, "bajra": 9000.0, "pigeonpea": 13000.0},
    "n_cost_rs_per_kg": 13.0,
    "irrigation_cost_rs_per_m3": 3.0,
    "soil_test_cost_rs": 300.0,
    "water_measure_cost_rs": 1500.0,
    "farm_area_acres": 5.0,
}
PLACEHOLDER_NOTE = "unverified dev placeholder, no source; team to verify / replace via config/prices_india.yaml"


def _num(x):
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    if isinstance(x, dict):
        for k in ("value", "msp_rs_per_quintal", "rs_per_quintal", "rs", "price"):
            if k in x and isinstance(x[k], (int, float)):
                return float(x[k])
    return None


def _find(d, names):
    if not isinstance(d, dict):
        return None
    for n in names:
        if n in d:
            return d[n]
    for v in d.values():
        r = _find(v, names)
        if r is not None:
            return r
    return None


def _crop_dict(node) -> dict:
    out = {}
    if isinstance(node, dict):
        for c, names in ALIASES.items():
            for n in names:
                if n in node and _num(node[n]) is not None:
                    out[c] = _num(node[n])
                    break
    return out


_PRICE_CACHE: dict = {}


def load_prices(path=None) -> dict:
    """Cached by file mtime (re-reads when config/prices_india.yaml changes)."""
    path = Path(path or PRICES_PATH)
    key = (str(path), path.stat().st_mtime if path.exists() else None)
    if key not in _PRICE_CACHE:
        _PRICE_CACHE.clear()
        _PRICE_CACHE[key] = _load_prices(path)
    return _PRICE_CACHE[key]


def _load_prices(path) -> dict:
    """Read config/prices_india.yaml tolerantly. Missing values fall back to flagged placeholders."""
    import yaml
    path = Path(path or PRICES_PATH)
    raw = {}
    if path.exists():
        raw = yaml.safe_load(open(path)) or {}
    badges, src = {}, {}
    price = _crop_dict(_find(raw, PRICE_KEYS))
    op = _crop_dict(_find(raw, OPCOST_KEYS))
    out = {"price_rs_per_quintal": {}, "operating_cost_rs_per_acre": {}}
    for c in CROPS:
        if c not in PLACEHOLDER["price_rs_per_quintal"] and c not in price:
            continue          # e.g. ragi: only usable if the YAML provides it (no invented fallback)
        if c in price:
            out["price_rs_per_quintal"][c], badges[f"price_{c}"] = price[c], "observed"
        else:
            out["price_rs_per_quintal"][c], badges[f"price_{c}"] = PLACEHOLDER["price_rs_per_quintal"][c], "placeholder"
        if c in op:
            out["operating_cost_rs_per_acre"][c], badges[f"opcost_{c}"] = op[c], "assumption"
        elif c not in PLACEHOLDER["operating_cost_rs_per_acre"] and c not in price:
            continue
        else:
            out["operating_cost_rs_per_acre"][c], badges[f"opcost_{c}"] = PLACEHOLDER["operating_cost_rs_per_acre"].get(c, PLACEHOLDER["operating_cost_rs_per_acre"]["bajra"]), "placeholder"
    for k, alts in {"n_cost_rs_per_kg": ("n_cost_rs_per_kg", "nitrogen_cost_rs_per_kg"),
                    "irrigation_cost_rs_per_m3": ("irrigation_cost_rs_per_m3",),
                    "soil_test_cost_rs": ("soil_test_cost_rs",),
                    "water_measure_cost_rs": ("water_measure_cost_rs", "borewell_or_tank_capacity_measurement_cost_rs"),
                    "farm_area_acres": ("farm_area_acres",)}.items():
        v = _num(_find(raw, alts))
        if v is not None:
            out[k], badges[k] = v, "assumption"
        else:
            out[k], badges[k] = PLACEHOLDER[k], "placeholder"
    out["badges"] = badges
    out["fixed_prices_note"] = "Prices are fixed across all scenarios (no price model); the price slider scales all crops together."
    out["source_file_found"] = path.exists()
    return out


def n_credit_kg_ha(plan) -> np.ndarray:
    try:
        from engine.yieldmodel import nitrogen_credit_kg_ha
        return np.asarray(nitrogen_credit_kg_ha(list(plan)), float)
    except Exception:
        return np.zeros(len(plan))


def plan_economics(plan, sim: dict, price_mult: float = 1.0, prices: dict | None = None,
                   n_credit=None) -> dict:
    """sim = PlanResult. Returns per-year arrays [S,4] in rupees/acre and the plan profit [S]."""
    prices = prices or load_prices()
    yld = np.asarray(sim["yield_kg_ha"], float)                       # [S,4] kg/ha
    irr = np.asarray(sim["irrig_mm"], float)                          # [S,4] mm
    S = yld.shape[0]
    price_kg = np.array([prices["price_rs_per_quintal"][c] / 100.0 for c in plan]) * price_mult   # Rs/kg
    op = np.array([prices["operating_cost_rs_per_acre"][c] for c in plan])
    kg_acre = yld * HA_PER_ACRE                                       # the single kg/ha -> per-acre conversion
    revenue = kg_acre * price_kg[None, :]
    credit = n_credit_kg_ha(plan) if n_credit is None else np.asarray(n_credit, float)
    n_saving = np.broadcast_to(credit * HA_PER_ACRE * prices["n_cost_rs_per_kg"], yld.shape)
    irr_cost = irr * M3_PER_MM_ACRE * prices["irrigation_cost_rs_per_m3"]
    profit_year = revenue - op[None, :] + n_saving - irr_cost
    return {"profit_year": profit_year, "profit": profit_year.sum(1), "revenue": revenue,
            "op_cost": np.broadcast_to(op, yld.shape), "n_saving": n_saving, "irrig_cost": irr_cost,
            "badges": economics_badges(prices)}


def economics_badges(prices: dict) -> dict:
    b = prices["badges"]
    return {"profit": "modeled",
            "prices": "placeholder" if any(v == "placeholder" for k, v in b.items() if k.startswith("price_")) else "observed",
            "operating_cost": "placeholder" if any(v == "placeholder" for k, v in b.items() if k.startswith("opcost_")) else "assumption",
            "irrigation_cost": b["irrigation_cost_rs_per_m3"], "n_cost": b["n_cost_rs_per_kg"]}
