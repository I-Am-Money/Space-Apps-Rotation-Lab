# AI use: legacy code used Claude Code; v4 economics and input validation revised with OpenAI Codex. See AI_USE.md.
"""Economics: v4 metric interface plus the preserved v3 rupees-per-acre interface. The ONLY place kg/ha is converted to per-acre.

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
from engine.cache import ArrayCache

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

# Optional measurement quotes remain unknown until entered. Missing economic
# inputs never receive invented prices, budgets or nitrogen costs.
PLACEHOLDER = {"n_cost_rs_per_kg": None, "soil_test_cost_rs": None,
               "water_measure_cost_rs": None}
PLACEHOLDER_NOTE = "Input needed: no usable configured value; enter a farmer input."


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


_PRICE_CACHE = ArrayCache(2 * 1024 * 1024)


def load_prices(path=None) -> dict:
    """Cached by file mtime (re-reads when config/prices_india.yaml changes)."""
    path = Path(path or PRICES_PATH)
    key = (str(path), path.stat().st_mtime if path.exists() else None)
    if key not in _PRICE_CACHE:
        _PRICE_CACHE.clear()
        _PRICE_CACHE[key] = _load_prices(path)
    return _PRICE_CACHE[key]


def _load_prices(path) -> dict:
    """Read legacy config. Missing price/cost stays None; profit requires explicit input."""
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
        if c in price:
            out["price_rs_per_quintal"][c], badges[f"price_{c}"] = price[c], "observed"
        else:
            out["price_rs_per_quintal"][c], badges[f"price_{c}"] = None, "input_needed"
        if c in op:
            meta = next((op_node[n] for n in ALIASES[c] if n in op_node), {})
            out["operating_cost_rs_per_acre"][c], badges[f"opcost_{c}"] = op[c], meta.get("badge", "assumption") if isinstance(meta, dict) else "assumption"
        else:
            out["operating_cost_rs_per_acre"][c], badges[f"opcost_{c}"] = None, "input_needed"
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
    for crop in plan:
        for field in ('price_rs_per_quintal', 'operating_cost_rs_per_acre'):
            value = prices.get(field, {}).get(crop)
            _nonnegative(value, f'{field} for {crop}')
    yld = np.asarray(sim["yield_kg_ha"], float)                       # [S,4] kg/ha (rice: milled rice)
    _nonnegative(yld, 'yield (kg/ha)')
    _nonnegative(price_mult, 'price multiplier')
    sold = np.array([prices.get("sold_kg_per_yield_kg", {}).get(c, 1.0) for c in plan])   # rice is sold as paddy
    price_kg = np.array([prices["price_rs_per_quintal"][c] / 100.0 for c in plan]) * price_mult   # Rs/kg
    op = np.array([prices["operating_cost_rs_per_acre"][c] for c in plan])
    kg_acre = yld * sold[None, :] * HA_PER_ACRE                       # the single kg/ha -> per-acre conversion
    revenue = kg_acre * price_kg[None, :]
    credit = n_credit_kg_ha(plan) if n_credit is None else np.asarray(n_credit, float)
    nitrogen_cost = prices.get("n_cost_rs_per_kg")
    if nitrogen_cost is None:
        if np.any(credit != 0):
            raise InputNeededError('Input needed: enter nitrogen cost before applying a nitrogen credit.')
        nitrogen_cost = 0.0  # zero credit contributes exactly zero; no cost is assumed
    _nonnegative(nitrogen_cost, 'nitrogen cost')
    n_saving = np.broadcast_to(credit * HA_PER_ACRE * nitrogen_cost, yld.shape)
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
            "prices": "input_needed" if any(v == "input_needed" for k, v in b.items() if k.startswith("price_")) else "placeholder" if any(v == "placeholder" for k, v in b.items() if k.startswith("price_")) else "observed",
            "operating_cost": "input_needed" if "input_needed" in costs else "placeholder" if "placeholder" in costs else "local" if costs and all(v == "local" for v in costs) else "assumption",
            "n_cost": b["n_cost_rs_per_kg"]}


# v4 interface: metric throughout, no guessed prices or budgets.
# Exact international acre (1 acre = 43,560 international square feet).
HECTARES_PER_ACRE = 0.40468564224
POUNDS_TO_KG = 0.45359237
BUSHEL_WEIGHT_LB = {'maize': 56, 'corn': 56, 'sorghum': 56, 'jowar': 56,
                    'soybean': 60, 'soybeans': 60, 'wheat': 60,
                    'wheat_winter': 60, 'wheat_spring': 60}
CONVERSION_SOURCE = 'https://www.ers.usda.gov/media/7780/ah-697.pdf (Tables 3 and 6)'


class InputNeededError(ValueError):
    """A farmer-supplied economic input is required before displaying money."""


def _nonnegative(value, name):
    if value is None:
        raise InputNeededError(f'Input needed: enter {name}.')
    try:
        arr = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise InputNeededError(f'Input needed: {name} must be numeric.') from exc
    if np.any(~np.isfinite(arr)) or np.any(arr < 0):
        raise InputNeededError(f'Input needed: {name} must be finite and nonnegative.')
    return arr


def profit_per_hectare(yield_kg_ha, price_per_kg=None, cost_per_ha=None):
    """Currency/ha = harvested kg/ha × same-currency/kg − same-currency/ha.

    Broadcasts over scenario/season arrays. Yield must be the commodity as sold;
    this function does not assume rice processing factors or exchange rates.
    """
    y = _nonnegative(yield_kg_ha, 'yield (kg/ha)')
    p = _nonnegative(price_per_kg, 'price (currency/kg)')
    c = _nonnegative(cost_per_ha, 'cost (currency/ha)')
    try:
        with np.errstate(over='raise', invalid='raise'):
            return y * p - c
    except FloatingPointError as exc:
        raise InputNeededError('Input needed: economic inputs exceed the supported numeric range.') from exc
    except ValueError as exc:
        raise ValueError('Yield, price and cost must have compatible scenario/season shapes.') from exc


def currency_ha_to_acre(value):
    """Any currency/ha → that same currency/acre, including negative profits."""
    arr = np.asarray(value, dtype=float)
    if np.any(~np.isfinite(arr)):
        raise ValueError('Currency values must be finite.')
    return arr * HECTARES_PER_ACRE


def kg_ha_to_quintals_per_acre(value):
    """Exact v4 conversion; the older singular-name helper retains v3 rounding."""
    return _nonnegative(value, 'yield (kg/ha)') * HECTARES_PER_ACRE / 100


def kg_ha_to_bushels_acre(value, crop):
    crop = str(crop).lower().strip()
    if crop not in BUSHEL_WEIGHT_LB:
        raise InputNeededError(f'Input needed: no verified bushel weight for {crop}; display kg or quintals instead.')
    return _nonnegative(value, 'yield (kg/ha)') * HECTARES_PER_ACRE / (BUSHEL_WEIGHT_LB[crop] * POUNDS_TO_KG)


def bushels_acre_to_kg_ha(value, crop):
    crop = str(crop).lower().strip()
    if crop not in BUSHEL_WEIGHT_LB:
        raise InputNeededError(f'Input needed: no verified bushel weight for {crop}.')
    return _nonnegative(value, 'yield (bushels/acre)') * BUSHEL_WEIGHT_LB[crop] * POUNDS_TO_KG / HECTARES_PER_ACRE


def resolve_crop_economics(crop, country, defaults=None, overrides=None):
    """Resolve already-normalized US defaults or explicit farmer inputs.

    Fetching NASS and ERS is owned by Person 3; this function never fetches them.
    defaults: {yields: {crop: kg/ha}, prices: {crop: currency/kg},
               costs: {crop: currency/ha}}. Values may be metadata dictionaries.
    overrides: {crop: {yield, price, cost}}. A zero input is explicit, not missing.
    Outside the US all three fields must be farmer-supplied.
    """
    us = str(country).strip().upper() in ('US', 'USA', 'UNITED STATES', 'UNITED STATES OF AMERICA')
    defaults = defaults or {}
    override = (overrides or {}).get(crop) or {}
    result, badges, sources = {}, {}, {}
    for field, bucket in (('yield', 'yields'), ('price', 'prices'), ('cost', 'costs')):
        user = field in override and override[field] is not None
        raw = override[field] if user else (defaults.get(bucket) or {}).get(crop) if us else None
        meta = raw if isinstance(raw, dict) else {}
        value = meta.get('value') if isinstance(raw, dict) else raw
        arr = _nonnegative(value, f'{field} for {crop}')
        if arr.ndim != 0:
            raise InputNeededError(f'Input needed: enter one typical {field} for {crop}.')
        if not user and any(flag in str(meta.get('badge', '')).lower() for flag in ('placeholder', 'example', 'stub', 'input_needed')):
            raise InputNeededError(f'Input needed: replace the unverified {field} for {crop}.')
        result[field] = float(arr)
        badges[field] = 'Your input' if user else meta.get('badge', 'Estimated')
        sources[field] = 'Farmer input' if user else meta.get('source', 'US default supplied by site API')
    return {**result, 'badges': badges, 'sources': sources,
            'units': {'yield': 'kg/ha', 'price': 'currency/kg', 'cost': 'currency/ha'}}

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


import functools as _functools


@_functools.lru_cache(maxsize=2)
def _units_read(version) -> dict:
    return _yaml.safe_load(_RECOMMEND_YAML.read_text())["units"]


def _units() -> dict:
    """Parsed `units` section of recommend.yaml; re-read only when the file changes."""
    return _units_read(_RECOMMEND_YAML.stat().st_mtime_ns)


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
            badge = (_pick(us_defaults, "badges") or {}).get(f"{field}:{crop}", "observed")
        try:
            valid = v is not None and not isinstance(v, bool) and np.isfinite(float(v)) and float(v) >= 0
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise InputNeeded(crop, field)
        out[f"{field}_per_t" if field == "price" else "cost_per_ha"] = float(v)
        out[f"{field}_badge"] = badge
    return out


def profit_per_ha(yield_kg_ha, price_per_tonne: float, cost_per_ha: float):
    """Profit per hectare = yield (kg/ha) / 1000 * price per tonne - cost per ha. Works on numbers or numpy arrays.
    Yields are never negative; a zero yield loses the whole cost."""
    y = np.maximum(np.asarray(yield_kg_ha, dtype=float), 0.0)
    return profit_per_hectare(y, _nonnegative(price_per_tonne, 'price (currency/tonne)') / _u("kg_per_tonne"), cost_per_ha)
