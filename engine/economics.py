# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Economics (engine-decision). Rupees per acre. The ONLY place kg/ha is converted to per-acre.

Build Spec v3 section 5.7:
  Profit_year = Ya * MSP - operating_cost - N_cost_adjustment      (N adjustment = saving after pigeon pea)
There is NO irrigation or water charge in profit. Saving water is handled only by the water slider (section 7).
Rice: district statistics report MILLED rice, while the MSP is paid per quintal of PADDY. The sold quantity is
therefore yield / milled_rice_per_paddy (config/prices_india.yaml, 0.66 from the ICRISAT documentation).
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
    "soil_test_cost_rs": None,
    "water_measure_cost_rs": None,
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
    badges = {}
    price = _crop_dict(_find(raw, PRICE_KEYS))
    op_node = _find(raw, OPCOST_KEYS) or {}
    op = _crop_dict(op_node)
    out = {"price_rs_per_quintal": {}, "operating_cost_rs_per_acre": {}}
    for c in CROPS:
        if c not in PLACEHOLDER["price_rs_per_quintal"] and c not in price:
            continue          # e.g. ragi: only usable if the YAML provides it (no invented fallback)
        if c in price:
            out["price_rs_per_quintal"][c], badges[f"price_{c}"] = price[c], "observed"
        else:
            out["price_rs_per_quintal"][c], badges[f"price_{c}"] = PLACEHOLDER["price_rs_per_quintal"][c], "placeholder"
        if c in op:
            meta = next((op_node[n] for n in ALIASES[c] if n in op_node), {})
            out["operating_cost_rs_per_acre"][c], badges[f"opcost_{c}"] = op[c], meta.get("badge", "assumption") if isinstance(meta, dict) else "assumption"
        elif c not in PLACEHOLDER["operating_cost_rs_per_acre"] and c not in price:
            continue
        else:
            out["operating_cost_rs_per_acre"][c], badges[f"opcost_{c}"] = PLACEHOLDER["operating_cost_rs_per_acre"].get(c, PLACEHOLDER["operating_cost_rs_per_acre"]["bajra"]), "placeholder"
    for k, alts in {"n_cost_rs_per_kg": ("n_cost_rs_per_kg", "nitrogen_cost_rs_per_kg"),
                    "soil_test_cost_rs": ("soil_test_cost_rs",),
                    "water_measure_cost_rs": ("water_measure_cost_rs", "borewell_or_tank_capacity_measurement_cost_rs")}.items():
        v = _num(_find(raw, alts))
        if v is not None:
            out[k], badges[k] = v, "assumption"
        else:
            out[k], badges[k] = PLACEHOLDER[k], "placeholder"
    # badge and source of each operating cost come from the YAML entry itself when it has them
    opnode = _find(raw, OPCOST_KEYS) or {}
    out["operating_cost_source"] = {}
    for c in list(out["operating_cost_rs_per_acre"]):
        e = next((opnode[n] for n in ALIASES[c] if isinstance(opnode, dict) and isinstance(opnode.get(n), dict)), None)
        if e and e.get("value") is not None:
            badges[f"opcost_{c}"] = e.get("badge", "assumption")
            out["operating_cost_source"][c] = e.get("source", "config/prices_india.yaml")
        else:
            out["operating_cost_source"][c] = PLACEHOLDER_NOTE
    conv = _find(raw, ("milled_rice_per_paddy",))
    f = _num(conv)
    out["milled_rice_per_paddy"] = f if f else 1.0
    badges["milled_rice_per_paddy"] = (conv.get("badge", "observed") if isinstance(conv, dict) and f else "placeholder")
    out["sold_kg_per_yield_kg"] = {c: (1.0 / out["milled_rice_per_paddy"] if c == "rice" else 1.0) for c in CROPS}
    out["badges"] = badges
    farm_path = ROOT / "config/farm.yaml"
    if farm_path.exists():
        acres = (yaml.safe_load(farm_path.read_text()) or {}).get("farm", {}).get("acres")
        if acres is not None:
            out["farm_area_acres"], badges["farm_area_acres"] = float(acres), "local"
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
    yld = np.asarray(sim["yield_kg_ha"], float)                       # [S,4] kg/ha (rice: milled rice)
    sold = np.array([prices.get("sold_kg_per_yield_kg", {}).get(c, 1.0) for c in plan])   # rice is sold as paddy
    price_kg = np.array([prices["price_rs_per_quintal"][c] / 100.0 for c in plan]) * price_mult   # Rs/kg
    op = np.array([prices["operating_cost_rs_per_acre"][c] for c in plan])
    kg_acre = yld * sold[None, :] * HA_PER_ACRE                       # the single kg/ha -> per-acre conversion
    revenue = kg_acre * price_kg[None, :]
    credit = n_credit_kg_ha(plan) if n_credit is None else np.asarray(n_credit, float)
    n_saving = np.broadcast_to(credit * HA_PER_ACRE * prices["n_cost_rs_per_kg"], yld.shape)
    profit_year = revenue - op[None, :] + n_saving
    return {"profit_year": profit_year, "profit": profit_year.sum(1), "revenue": revenue,
            "op_cost": np.broadcast_to(op, yld.shape), "n_saving": n_saving, "sold_kg_acre": kg_acre,
            "badges": economics_badges(prices)}


def kg_ha_to_quintal_acre(kg_ha):
    """Unit conversion used for display: 1 quintal = 100 kg, 1 acre = 0.404686 ha."""
    return np.asarray(kg_ha, float) * HA_PER_ACRE / 100.0


def rs_ha_to_rs_acre(rs_ha):
    return np.asarray(rs_ha, float) * HA_PER_ACRE


def economics_badges(prices: dict) -> dict:
    b = prices["badges"]
    costs = [v for k, v in b.items() if k.startswith("opcost_")]
    return {"profit": "modeled",
            "prices": "placeholder" if any(v == "placeholder" for k, v in b.items() if k.startswith("price_")) else "observed",
            "operating_cost": "placeholder" if "placeholder" in costs else "local" if costs and all(v == "local" for v in costs) else "assumption",
            "n_cost": b["n_cost_rs_per_kg"]}


# =====================================================================================================
# Build Spec v4 / v5 (Feature 3): generic profit per hectare for any pin. Everything above this line is the
# v3 India module and is left untouched. Parameters live in config/assumptions/recommend.yaml (units section).
# The engine is metric: yield kg/ha, price currency per tonne, cost currency per ha. US units are for display
# and for US data only.
# =====================================================================================================
import yaml as _yaml

_RECOMMEND_YAML = ROOT / "config" / "assumptions" / "recommend.yaml"


class InputNeeded(ValueError):
    """A money number cannot be computed because the farmer has not given a price or cost and no source has one.
    Never replaced by a default: the UI shows a prompt for `crop` and `field` ("price" or "cost")."""

    def __init__(self, crop: str, field: str):
        super().__init__(f"input needed: {field} for {crop}")
        self.crop, self.field = crop, field


def _units() -> dict:
    return _yaml.safe_load(_RECOMMEND_YAML.read_text())["units"]


def _u(name: str) -> float:
    return float(_units()[name]["value"])


def acres_to_ha(acres: float) -> float:
    return acres * _u("ha_per_acre")


def ha_to_acres(ha: float) -> float:
    return ha / _u("ha_per_acre")


def kg_per_bushel(crop: str) -> float:
    b = _units()["bushel_lb"].get(crop)
    if b is None:
        raise KeyError(f"no bushel weight for {crop}; enter yield and price in kg/ha and per tonne")
    return float(b["value"]) * _u("kg_per_lb")


def bu_ac_to_kg_ha(bu_per_acre: float, crop: str) -> float:
    return bu_per_acre * kg_per_bushel(crop) / _u("ha_per_acre")


def kg_ha_to_bu_ac(kg_per_ha: float, crop: str) -> float:
    return kg_per_ha * _u("ha_per_acre") / kg_per_bushel(crop)


def price_per_bu_to_per_tonne(price_per_bu: float, crop: str) -> float:
    return price_per_bu / kg_per_bushel(crop) * _u("kg_per_tonne")


def price_per_tonne_to_per_bu(price_per_tonne: float, crop: str) -> float:
    return price_per_tonne * kg_per_bushel(crop) / _u("kg_per_tonne")


def cost_per_acre_to_per_ha(cost_per_acre: float) -> float:
    return cost_per_acre / _u("ha_per_acre")


def cost_per_ha_to_per_acre(cost_per_ha: float) -> float:
    return cost_per_ha * _u("ha_per_acre")


def _pick(obj, name):
    if obj is None:
        return None
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def crop_economics(crop: str, us_defaults=None, crop_overrides: dict | None = None) -> dict:
    """Price and cost for one crop: the farmer's entry first, then US data, otherwise raise InputNeeded.
    Returns {"price_per_t", "cost_per_ha", "price_badge", "cost_badge"}; badges are your_input or observed."""
    ov = (crop_overrides or {}).get(crop) or {}
    out = {}
    for field, key, bucket in (("price", "price", "prices"), ("cost", "cost", "costs")):
        v, badge = ov.get(key), "your_input"
        if v is None:
            v = (_pick(us_defaults, bucket) or {}).get(crop)
            badge = "observed"
        if v is None:
            raise InputNeeded(crop, field)
        out[f"{field}_per_t" if field == "price" else "cost_per_ha"] = float(v)
        out[f"{field}_badge"] = badge
    return out


def profit_per_ha(yield_kg_ha, price_per_tonne: float, cost_per_ha: float):
    """Profit per hectare = yield (kg/ha) / 1000 * price per tonne - cost per ha. Works on numbers or numpy arrays.
    Yields are never negative; a zero yield loses the whole cost."""
    y = np.maximum(np.asarray(yield_kg_ha, dtype=float), 0.0)
    return y / _u("kg_per_tonne") * price_per_tonne - cost_per_ha
