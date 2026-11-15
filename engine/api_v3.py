# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Decision API (engine-decision) exactly as in engine/CONTRACT.md.

Scenario set for optimisation: 500 bootstrap plans of 4 random real years (seed 42).
Historical 4-year blocks are returned separately in compare(). Boundaries use the same set unless
BOUNDARY_N_SCEN trims it (stated in outputs).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from engine import boundaries as bd
from engine import economics, hindcast as hc
from engine import optimize as opt
from engine import scenarios as sc
from engine.cache import ArrayCache
from engine.configuration import version as configuration_version

IS_MOCK = False
ROOT = Path(__file__).resolve().parent.parent
N_SCEN = sc.N_BOOT
BOUNDARY_N_SCEN = 150
_ANNUAL = None          # tests may inject via set_annual()
_ANNUAL_REV = 0
_TIPPING_CACHE = ArrayCache(16 * 1024 * 1024)
_AWC_FALLBACK = 140.0   # mm/m, UNVERIFIED dev placeholder used only if no soil data / assumptions value
_IRR_FALLBACK = 500.0   # mm per season, UNVERIFIED dev placeholder if assumptions.yaml has no value


def set_annual(annual):
    global _ANNUAL, _ANNUAL_REV
    _ANNUAL = annual
    _ANNUAL_REV += 1
    _TIPPING_CACHE.clear()
    _scensets.clear(); opt.clear_cache()


_scensets: dict = {}


def annual() -> dict:
    return _ANNUAL if _ANNUAL is not None else sc.load_annual()


def boot_set(n=None) -> sc.ScenSet:
    n = n or N_SCEN
    k = ("boot", n, configuration_version(include_data=True), _ANNUAL_REV)
    if k not in _scensets:
        _scensets[k] = sc.bootstrap_plans(annual(), n)
    return _scensets[k]


def hist_set() -> sc.ScenSet:
    key = ("hist", configuration_version(include_data=True), _ANNUAL_REV)
    if key not in _scensets:
        _scensets[key] = sc.historical_blocks(annual())
    return _scensets[key]


# ---------------------------------------------------------------- params
_YAML: dict = {}


def _yaml(name):
    p = ROOT / "config" / name
    if not p.exists():
        return {}
    k = (name, p.stat().st_mtime)
    if k not in _YAML:
        _YAML[k] = yaml.safe_load(open(p)) or {}
    return _YAML[k]


def _dfs(d, names):
    if isinstance(d, dict):
        for n in names:
            if n in d:
                v = d[n]
                if isinstance(v, dict) and "value" in v:
                    v = v["value"]
                if isinstance(v, (int, float)):
                    return float(v)
        for v in d.values():
            r = _dfs(v, names)
            if r is not None:
                return r
    return None


_SOIL = None


def soil_info() -> dict:
    """Soil at the configured point from engine.fetch_soil.get_soil (own badge/source), else flagged fallback."""
    global _SOIL
    if _SOIL is None:
        reg = _yaml("region.yaml")
        try:
            from engine import fetch_soil
            _SOIL = fetch_soil.get_soil(float(reg.get("lat", 17.5)), float(reg.get("lon", 78.5)))
        except Exception:
            v = _dfs(_yaml("assumptions.yaml"), ("awc_mm_per_m",))
            _SOIL = {"awc_mm_per_m": v if v is not None else _AWC_FALLBACK, "badge": "placeholder",
                     "awc_low": None, "awc_high": None, "source": "fetch_soil unavailable; unverified placeholder"}
    return _SOIL


def default_awc():
    s = soil_info()
    return float(s["awc_mm_per_m"]), s.get("badge", "assumption")


def default_irrigation(ws=None):
    if ws == "canal_and_well":
        try:
            return _assump("base_canal") + _assump("base_well"), "assumption"
        except Exception:
            pass
    v = _dfs(_yaml("assumptions.yaml"), ("base_available_irrigation_mm", "irrigation_available_mm", "base_available_mm"))
    return (v, "assumption") if v is not None else (_IRR_FALLBACK, "placeholder")


def norm_params(params=None) -> dict:
    p = dict(params or {})
    opt.configure()
    def number(name, default, low, high):
        value = default if p.get(name) is None else p[name]
        value = float(value)
        if not np.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{name} must be between {low} and {high}")
        return value
    for key, limits in {"lam": (0, 1), "w": (0, 1), "irrigation_mm": (0, 10000),
                        "awc_mm_per_m": (1, 1000), "canal_supply_mm": (0, 10000), "well_supply_mm": (0, 10000),
                        "price_mult": (0, 10), "water_value_rs_m3": (0, 10), "recharge_exponent_k": (0, 3), "canal_release_factor": (0, 3)}.items():
        if p.get(key) is not None:
            number(key, 0, *limits)
    if p.get("water_source") not in (None, *WATER_SOURCE_LABEL):
        raise ValueError("Choose a supported rice water source")
    current = p.get("current_rotation") or opt.REF["A"]
    if len(current) != 4 or any(c not in opt.CROPS for c in current):
        raise ValueError("Choose four crops from the configured candidate set")
    overrides = {}
    for crop, value in (p.get("operating_costs") or {}).items():
        if crop not in opt.CROPS or not np.isfinite(float(value)) or float(value) < 0:
            raise ValueError("Cultivation costs must be nonnegative and use selected crops")
        overrides[f"cost.{crop}"] = float(value)
    for key in ("soil_test_cost_rs", "water_measure_cost_rs"):
        if p.get(key) is not None:
            overrides[key] = number(key, 0, 0, 1e7)
    soil_mode = p.get("soil_mode") or "farm_black_soil"
    soil_mode = {"farm": "farm_black_soil", "district": "district_soilgrids"}.get(soil_mode, soil_mode)
    if soil_mode not in ("farm_black_soil", "district_soilgrids"):
        raise ValueError(f"Unknown soil mode: {soil_mode!r}")
    soil = active_soil({"soil_mode": soil_mode})
    awc_d = soil["awc"]
    ws = p.get("water_source") or _yaml("region.yaml").get("water_source") or "unset"
    cs, wsup = p.get("canal_supply_mm"), p.get("well_supply_mm")
    requested = ws
    try:
        no_up = ws == "canal_and_well" and annual().get("upstream") is None
    except Exception:
        no_up = False
    if no_up:      # physics needs upstream rain for this mode; degrade visibly to the local-rainfall proxy
        ws = "unset"
    irr_default = default_irrigation(ws)[0]
    if ws == "canal_and_well":
        irr_default = (_assump("base_canal") if cs is None else float(cs)) + (_assump("base_well") if wsup is None else min(float(wsup), _assump("max_well")))
    return {"water_source": ws, "water_source_requested": requested, "soil_mode": soil["mode"], "soil_mode_requested": soil_mode, "canal_supply_mm": None if cs is None else float(cs),
            "well_supply_mm": None if wsup is None else float(wsup), "lam": float(p.get("lam", 0.3)), "w": float(p.get("w", 0.1)),
            "irrigation_mm": float(p["irrigation_mm"]) if p.get("irrigation_mm") is not None else irr_default,
            "awc_mm_per_m": p.get("awc_mm_per_m"), "soil": soil, "awc": float(p["awc_mm_per_m"]) if p.get("awc_mm_per_m") is not None else awc_d,
            "current_rotation": list(p.get("current_rotation") or opt.REF["A"]),
            "price_mult": float(p.get("price_mult", 1.0)),
            "irrigation_badge": "local" if p.get("irrigation_mm") is not None else default_irrigation(ws)[1],
            "recharge_exponent_k": p.get("recharge_exponent_k"),
            "canal_release_factor": p.get("canal_release_factor"),
            "heat_enabled": bool(p.get("heat_enabled", True)), "economic_overrides": overrides,
            "water_value_rs_m3": number("water_value_rs_m3", opt.water_price_proxy_rs_per_mm_acre() / economics.M3_PER_MM_ACRE, 0, 10),
            "boundary_scenarios": int(number("boundary_scenarios", BOUNDARY_N_SCEN, 10, 1000))}


def _assump(name: str) -> float:
    from engine import crops
    return float(crops.A(None, f"rice_irrigation.{name}"))


def _assump_any(name: str):
    from engine import crops
    return crops.A(None, name)


def soil_cover_trend(plan) -> dict:
    """v3 section 5.6: residue / soil-cover index (0 to 1) from a simple per-crop rule in assumptions.yaml.
    index[y] = carry * index[y-1] + (1 - carry) * score(crop in year y); year 0 = rice (our farm today).
    Soil organic carbon is reported as a direction only."""
    carry = float(_assump_any("soil_cover.carry"))
    start = float(_assump_any("soil_cover.score.rice"))
    idx, out = start, []
    for c in plan:
        idx = carry * idx + (1.0 - carry) * float(_assump_any(f"soil_cover.score.{c}"))
        out.append(float(idx))
    d = out[-1] - start
    arrow = "up" if d > 1e-9 else ("down" if d < -1e-9 else "flat")
    return {"index": out, "start": start, "change_vs_rice_only": d, "soc_direction": arrow,
            "soc_note": "direction only; too slow to quantify over 4 years", "badge": "assumption",
            "rule": "cover index = carry x last year's index + (1 - carry) x the crop's cover score (assumptions.yaml soil_cover)"}


def _median_rain() -> float:
    """Median rice-season rain of the BASE (un-adjusted) bootstrap set; fixed so rainfall what-ifs
    reduce irrigation availability instead of rescaling the median with them."""
    return float(np.median(annual()["precip"][:, 151:304].sum(1)))


def _apply_sim_params(p):
    opt.set_economic_params(p.get("economic_overrides"))
    med = _median_rain()
    split = None
    if p["water_source"] == "canal_and_well":
        split = {"base_canal": _assump("base_canal") if p.get("canal_supply_mm") is None else p["canal_supply_mm"],
                 "base_well": _assump("base_well") if p.get("well_supply_mm") is None else p["well_supply_mm"]}
        if sum(split.values()) <= 0:
            split = {"base_canal": _assump("base_canal"), "base_well": _assump("base_well")}
    opt.set_sim_params(split=split, water_source=p["water_source"], median_season_rain_mm=med, median_local_rain=med,
                       median_upstream_rain=None if annual().get("upstream") is None else float(np.median(annual()["upstream"])),
                       canal_supply_mm=p.get("canal_supply_mm"), well_supply_mm=p.get("well_supply_mm"),
                       recharge_exponent_k=p.get("recharge_exponent_k"),
                       canal_release_factor=p.get("canal_release_factor"),
                       **{"heat.enabled": p.get("heat_enabled", True)})


WATER_SOURCE_LABEL = {
    "canal_and_well": "Canal plus well: canal is a proxy for canal releases based on upstream monsoon rain (actual releases depend on reservoir operations); wells are a simplified recharge proxy. Canal is used first, wells cover the shortfall.",
    "unset": "Rice water source not chosen: confirm your rice water source (borewell, tank or canal). Showing the local-rainfall recharge proxy.",
    "borewell": "Borewell: local-rainfall recharge proxy for water availability (simplified, team to verify).",
    "tank": "Tank: local-rainfall recharge proxy for water availability (simplified, team to verify).",
    "canal": "Canal: proxy for canal water availability (Nagarjuna Sagar releases, not local rain); base_available and exponent are editable assumptions.",
}


def _supply_params() -> dict:
    return {n: {"value": _assump(n), "badge": "assumption", "note": "team to verify"}
            for n in ("base_canal", "k_canal", "base_well", "k_well", "max_well")}


def _water_flag(p) -> dict:
    ws = p["water_source"]
    up = annual().get("upstream") is not None
    fb = None
    if p.get("water_source_requested") not in (None, ws):
        fb = (f"water source {p['water_source_requested']} needs upstream rain data (engine.fetch_upstream), which is not available; "
              f"showing the local-rainfall proxy instead")
    return {"water_source": ws, "fallback_reason": fb, "label": WATER_SOURCE_LABEL.get(ws, ws), "confirm_required": ws == "unset",
            "upstream_data_available": up, "upstream_note": annual().get("upstream_note"),
            "supply_params": _supply_params() if ws == "canal_and_well" else None,
            "irrigation_slider_note": ("the irrigation slider is the total base supply (mm); it scales base_canal and base_well in their assumption ratio"
                                       if ws == "canal_and_well" else None),
            "canal_supply_override_mm": p.get("canal_supply_mm"), "well_supply_override_mm": p.get("well_supply_mm"),
            "flag": "confirm your rice water source" if ws == "unset" else None, "badge": "assumption"}


def _badges(p):
    prices = opt.current_prices()
    return {"profit": "modeled", "prices": economics.economics_badges(prices)["prices"],
            "water": "modeled", "weather": "observed", "irrigation_mm": p["irrigation_badge"],
            "water_supply_params": "assumption",
            "awc": p["soil"]["badge"] if p["awc_mm_per_m"] is None else "local",
            "rotation_effects": "assumption", "econ_detail": economics.economics_badges(prices)}


def _table(p, n=None, extra=()):
    """Metrics table over the offered rotations, plus (not offered, never recommended) the user's current rotation
    and any `extra` rotation that the team rule blocks, so they can still be compared."""
    opt.configure()
    _apply_sim_params(p)
    ss = boot_set(n)
    df = opt.evaluate_table(ss, p["awc"], p["irrigation_mm"], p["lam"], p["w"], p["price_mult"], extra=[p["current_rotation"], *extra])
    return ss, opt.rescore(df, p["lam"], p["w"], p["water_value_rs_m3"] * economics.M3_PER_MM_ACRE)


def _resolve(rid, p):
    if isinstance(rid, (list, tuple)):
        return list(rid)
    if rid == "current":
        return list(p["current_rotation"])
    if rid in opt.REF:
        return list(opt.REF[rid])
    return rid.split("-")


# ------------------------------------------------------------ farm facts
def farm_info() -> dict:
    """config/farm.yaml (lead-owned, read-only): acres, soil, unit conversion. Never hardcoded here."""
    f = _yaml("farm.yaml")
    acres = float((f.get("farm") or {}).get("acres"))
    m3 = float((f.get("units") or {}).get("m3_per_acre_per_mm", economics.M3_PER_MM_ACRE))
    return {"acres": acres, "acres_badge": (f.get("farm") or {}).get("acres_badge", "local"), "m3_per_acre_per_mm": m3,
            "label": (f.get("farm") or {}).get("label"), "soil": f.get("soil") or {}}


def farm_soil_info():
    """Farm black soil via fetch_soil.farm_soil() when it exists and has an AWC; else None."""
    try:
        from engine import fetch_soil
        d = fetch_soil.farm_soil()
        if d and d.get("awc_mid") is not None:
            return d
    except Exception:
        pass
    return None


SOIL_MODE_ALIASES = {"farm": "farm_black_soil", "district": "district_soilgrids"}      # names the UI uses


def active_soil(p) -> dict:
    """Soil used for AWC: farm black soil (default) if available, else the district SoilGrids estimate."""
    mode = SOIL_MODE_ALIASES.get(p.get("soil_mode") or "farm_black_soil", p.get("soil_mode") or "farm_black_soil")
    if mode == "farm_black_soil":
        fs = farm_soil_info()
        if fs:
            return {"mode": mode, "awc": float(fs["awc_mid"]), "low": fs.get("awc_low"), "high": fs.get("awc_high"),
                    "badge": fs.get("badge", "local"), "display_name": fs.get("display_name", "Black soil (farm input)"),
                    "source": fs.get("source") or fs.get("awc_source"), "fallback_reason": None}
        si = soil_info()
        return {"mode": "district_soilgrids", "awc": float(si["awc_mm_per_m"]), "low": si.get("awc_low_pm25"), "high": si.get("awc_high_pm25"),
                "badge": si.get("badge", "assumption"), "display_name": "District soil (SoilGrids estimate)", "source": si.get("source"),
                "fallback_reason": "farm black-soil AWC is not filled in config/farm.yaml yet (team to verify); using the district SoilGrids estimate"}
    si = soil_info()
    return {"mode": "district_soilgrids", "awc": float(si["awc_mm_per_m"]), "low": si.get("awc_low_pm25"), "high": si.get("awc_high_pm25"),
            "badge": si.get("badge", "assumption"), "display_name": "District soil (SoilGrids estimate)", "source": si.get("source"),
            "fallback_reason": None}


def farm_totals(per_acre: dict, farm=None) -> dict:
    """Farm totals from per-acre metrics (profit over the plan in Rs, water in mm -> m3)."""
    farm = farm or farm_info()
    a, k = farm["acres"], farm["m3_per_acre_per_mm"]
    def m3(x):
        return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x) * a * k
    return {"acres": a, "total_profit_mean": float(per_acre["mean_profit"]) * a,
            "total_profit_worst10": float(per_acre["worst10_profit"]) * a,
            "total_irrigation_m3": m3(per_acre["irrigation_mm"]), "irrigation_canal_m3": m3(per_acre.get("irrigation_canal_mm")),
            "irrigation_well_m3": m3(per_acre.get("irrigation_well_mm")), "total_water_m3": m3(per_acre["total_water_mm"]),
            "badge": "modeled", "acres_badge": farm["acres_badge"]}


def _add_farm_cols(df, farm):
    a, k = farm["acres"], farm["m3_per_acre_per_mm"]
    df = df.copy()
    df["total_profit_mean"] = df.mean_profit * a
    df["total_profit_worst10"] = df.worst10_profit * a
    df["total_irrigation_m3"] = df.irrigation_mm * a * k
    df["irrigation_canal_m3"] = df.irrigation_canal_mm * a * k
    df["irrigation_well_m3"] = df.irrigation_well_mm * a * k
    df["total_water_m3"] = df.total_water_mm * a * k
    df["d_total_profit_mean"] = df.d_mean_profit * a
    df["d_total_profit_worst10"] = df.d_worst10_profit * a
    df["d_total_irrigation_m3"] = df.d_irrigation_mm * a * k
    df["d_total_water_m3"] = df.d_total_water_mm * a * k
    return df


# ------------------------------------------------------------------- API
def get_field_summary() -> dict:
    reg = _yaml("region.yaml")
    a = annual()
    yrs = a["years"]
    mr = sc.monsoon_rain(a)
    from engine import monsoon
    monsoon_data = monsoon.summary(a)
    onset = np.asarray(monsoon_data["onset_doy"])
    out = {"region": reg, "dev_placeholder": bool(reg.get("dev_placeholder", False)),
           "climate": {"first_year": int(yrs[0]), "last_year": int(yrs[-1]), "annual_rain_mm": float(a["precip"].sum(1).mean()),
                       "monsoon_rain_mm": float(mr.mean()), "monsoon_rain_p10_mm": float(np.percentile(mr, 10)),
                       "annual_et0_mm": float(a["et0"].sum(1).mean()), "badge": "observed",
                       "note": "NASA POWER regional estimate (~0.5 degree grid), not your field"}}
    mon = np.cumsum([0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])
    out["climate"]["monthly_rain_mm"] = [float(a["precip"][:, mon[i]:mon[i + 1]].sum(1).mean()) for i in range(12)]
    out["climate"]["monthly_tmax_c"] = [float(a["tmax"][:, mon[i]:mon[i + 1]].mean()) for i in range(12)]
    out["climate"]["monthly_et0_mm"] = [float(a["et0"][:, mon[i]:mon[i + 1]].sum(1).mean()) for i in range(12)]
    out["soil"] = dict(soil_info())
    out["climate"]["onset"] = {"years": yrs.tolist(), "doy": onset.tolist(),
        "median_doy": monsoon_data["median_doy"],
        "no_onset_years": monsoon_data["no_clean_onset_years"], "badge": "modeled",
        "note": "Wet-window / dry-spell planning rule applied to NASA POWER rainfall; sowing follows onset. Not an official IMD onset date."}
    out["monsoon_onset"] = monsoon_data
    obs = hc.load_observed()
    out["yield_history"] = None if obs is None else obs.to_dict("records")
    fr = hc.load_farm_records()
    out["farm_records"] = None if fr is None else {"badge": "local", "rows": fr.to_dict("records")}
    return out


def list_rotations() -> list[dict]:
    opt.configure()
    rows = [{"id": k, "plan": list(v), "label": f"{k}: " + ", ".join(v) + (" (our farm today, baseline)" if k == "A" else "")} for k, v in opt.REF.items()]
    rows.append({"id": "current", "plan": None, "label": "Your current rotation (defaults to A)"})
    rows += [{"id": opt.plan_id(p), "plan": list(p), "label": ", ".join(p)} for p in opt.ALL_PLANS]
    return rows


def _stress_rows(plan, p, stress, base_rows=None):
    rows = []
    for name, t in stress.items():
        tss = sc.ScenSet(t["key"], t["scen"])
        at = opt.rotation_arrays(plan, tss, p["awc"], p["irrigation_mm"], p["price_mult"])
        rows.append({"test": name, "label": t["label"], "source_year": t["source_year"], "description": t["description"],
                     "profit": float(at["profit"][0]), "yield_kg_ha": at["yield"][0].tolist(),
                     "water_stress_mm": float(at["stress"][0]), "irrigation_mm": float(at["irrig"][0]),
                     "hot_days": None if at.get("hot_days") is None else at["hot_days"][0].tolist(),
                     "sowing_doy": None if at.get("sowing_doy") is None else at["sowing_doy"][0].tolist(),
                     "plan_year": t.get("plan_year"), "total_water_mm": float(at["total"][0])})
    if p["water_source"] == "canal":      # x0.5 what-if only for the older canal mode; canal_and_well uses the real low-upstream year
        ms = sc.median_year_scenario(annual())
        f = sc.CANAL_LOW_RELEASE_FACTOR
        at = opt.rotation_arrays(plan, ms, p["awc"], p["irrigation_mm"] * f, p["price_mult"])
        rows.append({"test": "low canal release year",
                     "label": f"low canal release year (what-if: available irrigation x{f:g}, no release record used)",
                     "source_year": None, "badge": "assumption",
                     "description": f"Median real weather year ({ms.scen['labels'][0]}) with available irrigation scaled by {f:g}. "
                                    f"The {f:g} factor is an assumption, team to verify; no Nagarjuna Sagar release data is used.",
                     "profit": float(at["profit"][0]), "yield_kg_ha": at["yield"][0].tolist(),
                     "water_stress_mm": float(at["stress"][0]), "irrigation_mm": float(at["irrig"][0]),
                     "total_water_mm": float(at["total"][0])})
    if base_rows is not None:
        for r, b in zip(rows, base_rows):
            r["delta_profit_vs_baseline"] = r["profit"] - b["profit"]
            r["delta_irrigation_vs_baseline"] = r["irrigation_mm"] - b["irrigation_mm"]
            r["delta_water_vs_baseline"] = r["total_water_mm"] - b["total_water_mm"]
    return rows


def compare(rotation_ids: list, params=None) -> dict:
    p = norm_params(params)
    ss, df = _table(p, extra=[_resolve(r, p) for r in rotation_ids])
    hist = hist_set()
    prices = opt.current_prices()
    stress = {k: v for k, v in sc.stress_tests(annual()).items()
              if k != "low canal release year" or p["water_source"] == "canal_and_well"}
    base_plan = list(opt.REF["A"])
    base_st = _stress_rows(base_plan, p, stress)
    out = {"params": p, "badges": _badges(p), "n_scenarios": ss.n, "scenario_note": ss.note,
           "baseline_id": opt.BASELINE_ID, "baseline_label": "A: rice x4, our farm today", "water_source": _water_flag(p),
           "farm": {"acres": farm_info()["acres"], "badge": farm_info()["acres_badge"], "m3_per_acre_per_mm": farm_info()["m3_per_acre_per_mm"]},
           "crop_selection": {"millets": list(opt.MILLETS), "source": opt.SELECTION_SOURCE},
           "fixed_prices_note": prices["fixed_prices_note"], "rotations": {}}
    for rid in rotation_ids:
        plan = _resolve(rid, p)
        a = opt.rotation_arrays(plan, ss, p["awc"], p["irrigation_mm"], p["price_mult"])
        m = opt.metrics(a)
        ah = opt.rotation_arrays(plan, hist, p["awc"], p["irrigation_mm"], p["price_mult"])
        cover = soil_cover_trend(plan)
        row = df[df.id == opt.plan_id(plan)].iloc[0]
        out["rotations"][rid] = {"plan": plan, "profit": a["profit"], "yield_kg_ha": a["yield"], "yield_mean": a["yield"].mean(0),
            "profit_year_mean": a["profit_year"].mean(0), **m, "J": float(row.J), "offered": bool(row.offered),
            "delta_vs_baseline": opt.delta_vs_baseline(row),
            "farm_totals": farm_totals({**m, "irrigation_canal_mm": None if a["irrig_canal"] is None else float(a["irrig_canal"].mean()),
                                        "irrigation_well_mm": None if a["irrig_well"] is None else float(a["irrig_well"].mean())}),
            "farm_total_profit_distribution": a["profit"] * farm_info()["acres"],
            "irrigation_canal_mm": None if a["irrig_canal"] is None else float(a["irrig_canal"].mean()),
            "irrigation_well_mm": None if a["irrig_well"] is None else float(a["irrig_well"].mean()),
            "irrigation_source_note": "canal = proxy for canal releases from upstream monsoon rain; wells = simplified recharge proxy",
            "profit_delta_distribution": a["profit"] - opt.rotation_arrays(base_plan, ss, p["awc"], p["irrigation_mm"], p["price_mult"])["profit"],
            "residue_index": cover["index"], "residue_index_note": cover["rule"], "soil_cover": cover,
            "yield_quintal_acre_mean": (economics.kg_ha_to_quintal_acre(a["yield"].mean(0))
                                        * np.array([prices["sold_kg_per_yield_kg"].get(c, 1.0) for c in plan])).tolist(),
            "yield_unit_note": "quintals per acre as sold: rice as paddy (milled rice / 0.66), other crops as grain",
            "hot_days_mean": None if a.get("hot_days") is None else a["hot_days"].mean(0).tolist(),
            "historical_blocks": {"labels": hist.scen["labels"], "profit": ah["profit"]},
            "stress_tests": _stress_rows(plan, p, stress, base_st), "badges": {"profit": "modeled", "water": "modeled", "yield": "modeled"}}
    return out


def land_split(alt_id, params=None) -> dict:
    """Farm total when k acres follow rotation A (rice x4, baseline) and the rest follow `alt_id`, k = 0..acres.
    Worst-10% is computed on the combined per-scenario total (not by mixing the two worst cases)."""
    p = norm_params(params)
    ss, df = _table(p)
    farm = farm_info()
    N = int(round(farm["acres"]))
    k_m3 = farm["m3_per_acre_per_mm"]
    base_plan, alt_plan = list(opt.REF["A"]), _resolve(alt_id, p)
    aA = opt.rotation_arrays(base_plan, ss, p["awc"], p["irrigation_mm"], p["price_mult"])
    aB = opt.rotation_arrays(alt_plan, ss, p["awc"], p["irrigation_mm"], p["price_mult"])
    k = np.arange(N + 1, dtype=float)[:, None]               # acres in rice
    w_rice, w_alt = k, (N - k)
    profit = opt.combine_profit(aA["profit"], aB["profit"], N)   # farm total over the plan, Rs [N+1, S]
    S = profit.shape[1]
    nw = max(1, int(np.ceil(0.1 * S)))
    mean = profit.mean(1)
    worst10 = np.sort(profit, axis=1)[:, :nw].mean(1)
    def lin(key):
        if aA.get(key) is None or aB.get(key) is None:
            return None
        return (w_rice[:, 0] * aA[key].mean() + w_alt[:, 0] * aB[key].mean()) * k_m3
    irr_m3, canal_m3, well_m3, water_m3 = lin("irrig"), lin("irrig_canal"), lin("irrig_well"), lin("total")
    irrigation_acre_mm = w_rice[:, 0] * aA["irrig"].mean() + w_alt[:, 0] * aB["irrig"].mean()
    scale = df.attrs["scale"]
    J = opt.objective(mean, worst10, irrigation_acre_mm, p["lam"], p["w"], scale)
    b = N   # baseline index: all acres in rice
    def d(x):
        return None if x is None else (x - x[b]).tolist()
    best = int(np.argmax(J))
    text = (f"{N} of {N} acres in rice is the baseline (our farm today). With {best} acres in rice and {N - best} in {opt.plan_id(alt_plan)}, "
            f"mean total profit over the plan changes by {mean[best] - mean[b]:+,.0f} Rs and worst-10% by {worst10[best] - worst10[b]:+,.0f} Rs"
            + (f"; irrigation water changes by {irr_m3[best] - irr_m3[b]:+,.0f} m3" if irr_m3 is not None else "")
            + f". Best split at these slider settings: {best} acres in rice (highest J).")
    return {"alt_id": alt_id, "alt_plan": alt_plan, "baseline_id": opt.BASELINE_ID, "acres_total": N,
            "acres_rice": k[:, 0].astype(int).tolist(), "baseline_index": b,
            "total_profit_mean": mean.tolist(), "total_profit_worst10": worst10.tolist(),
            "total_irrigation_m3": None if irr_m3 is None else irr_m3.tolist(),
            "irrigation_canal_m3": None if canal_m3 is None else canal_m3.tolist(),
            "irrigation_well_m3": None if well_m3 is None else well_m3.tolist(),
            "total_water_m3": None if water_m3 is None else water_m3.tolist(),
            "J_total": J.tolist(), "best_acres_rice": best,
            "delta_vs_baseline": {"total_profit_mean": d(mean), "total_profit_worst10": d(worst10),
                                  "total_irrigation_m3": d(irr_m3), "irrigation_canal_m3": d(canal_m3),
                                  "irrigation_well_m3": d(well_m3), "total_water_m3": d(water_m3)},
            "text": text, "badges": {"profit": "modeled", "acres": farm["acres_badge"]}, "n_scenarios": S,
            "water_source": _water_flag(p), "fixed_prices_note": economics.load_prices()["fixed_prices_note"]}


def recommend(params=None) -> dict:
    p = norm_params(params)
    ss, df = _table(p)
    farm = farm_info()
    df = _add_farm_cols(df, farm)
    r = opt.recommend_from_table(df)
    strategies = {"A": opt.REF["A"], "B": opt.REF["B"], "C": opt.REF["C"]}
    if opt.plan_id(p["current_rotation"]) != opt.plan_id(opt.REF["A"]):
        strategies["current"] = p["current_rotation"]
    rep = opt.three_strategy_report(df, ss, p["awc"], p["irrigation_mm"], p, strategies, p["price_mult"])
    for v in rep.values():
        row = df[df.id == v["id"]].iloc[0]
        v["evidence"]["farm_totals"] = farm_totals(row.to_dict(), farm)
    cols = ["id", "offered", "mean_profit", "worst10_profit", "water_stress_mm", "irrigation_mm", "total_water_mm", "J", "rank", "on_frontier"] + list(opt.DELTA_FIELDS.values()) + [
        "irrigation_canal_mm", "irrigation_well_mm", "total_profit_mean", "total_profit_worst10", "total_irrigation_m3",
        "irrigation_canal_m3", "irrigation_well_m3", "total_water_m3", "d_total_profit_mean", "d_total_profit_worst10",
        "d_total_irrigation_m3", "d_total_water_m3"]
    pts = df[cols]
    be = opt.breakeven_shortfall(r["top"]["plan"], ss, p["awc"], p["irrigation_mm"], p["lam"], p["w"], p["price_mult"], df.attrs["scale"])
    nofx = opt.without_rotation_effects(r["top"]["plan"], ss, p["awc"], p["irrigation_mm"], p["price_mult"])
    if nofx is not None:
        nofx["effects"] = {k: _assump_any(f"rotation.{k}") for k in ("rice_after_rice", "rice_after_pigeonpea", "millet_after_pigeonpea",
                                                                      "millet_after_millet", "n_credit_after_pigeonpea")}
    return {"params": p, "top": r["top"], "runner_up": r["runner_up"], "metrics": df, "pareto": pts, "breakeven": be,
            "no_rotation_effects": nofx,
            "baseline_id": opt.BASELINE_ID, "baseline_label": "A: rice x4, our farm today",
            "farm": {"acres": farm["acres"], "badge": farm["acres_badge"], "label": farm["label"],
                     "m3_per_acre_per_mm": farm["m3_per_acre_per_mm"], "soil": p["soil"]},
            "top_delta_vs_baseline": opt.delta_vs_baseline(r["top"]), "runner_up_delta_vs_baseline": opt.delta_vs_baseline(r["runner_up"]),
            "water_source": _water_flag(p), "crop_selection": {"millets": list(opt.MILLETS), "source": opt.SELECTION_SOURCE},
            "three_strategy_report": rep, "badges": _badges(p), "n_scenarios": ss.n,
            "scale_rs_per_mm": df.attrs["scale"],
            "water_price_proxy": {"value_rs_per_mm_ha": p["water_value_rs_m3"] * 10, "badge": "assumption", "note": "Planning preference, never a charge deducted from profit"},
            "objective": "J = (1-lam)*mean + lam*worst10 - w*scale*irrigation_mm",
            "fixed_prices_note": economics.load_prices()["fixed_prices_note"]}


def tipping_points(params=None) -> dict:
    p = norm_params(params)
    cache_key = (json.dumps(p, sort_keys=True), configuration_version(include_data=True), N_SCEN, BOUNDARY_N_SCEN, _ANNUAL_REV, id(opt._SIM))
    cached = _TIPPING_CACHE.get(cache_key)
    if cached is not None:
        return copy.deepcopy(cached)
    ss, df = _table(p)
    count = min(p["boundary_scenarios"], ss.n)
    bs = boot_set(count) if count < ss.n else ss
    scale = df.attrs["scale"]
    cands = bd.candidate_plans(df)
    prices = opt.current_prices()
    awc, irr = p["awc"], p["irrigation_mm"]
    farm = farm_info()
    out = {"params": p, "farm": {"acres": farm["acres"], "badge": farm["acres_badge"], "m3_per_acre_per_mm": farm["m3_per_acre_per_mm"]},
           "badges": _badges(p), "n_scenarios": bs.n, "frame": bd.FRAME, "baseline_id": opt.BASELINE_ID,
           "water_source": _water_flag(p), "crop_selection": {"millets": list(opt.MILLETS), "source": opt.SELECTION_SOURCE}}
    out["rainfall_crossover"] = bd.rainfall_crossover(bs, awc, irr, p, scale, cands)
    irr_levels = np.round(np.linspace(0, max(2 * irr, 1500.0), 9), 1)
    g = bd.decision_grid(bs, awc, p, scale, cands, irr_levels)
    out["grid"] = {"rain_mult": g["rain_mult"], "irrigation_mm": g["irrigation_mm"], "winner": g["winner"],
                   "boundary_band": g["boundary_band"], "rice_years": g["rice_years"], "current_irrigation_mm": irr,
                   "rice_shift_threshold_mm": g["rice_shift_threshold_mm"], "baseline_id": opt.BASELINE_ID,
                   "delta_mean_profit_vs_baseline": g["delta_mean_profit_vs_baseline"], "text": g["text"], "badge": "modeled"}
    out["late_monsoon"] = bd.late_monsoon_curve(bs, awc, irr, p, scale, cands)
    out["heat"] = bd.heat_curve(bs, awc, irr, p, scale, cands)
    si = soil_info()
    sa = p["soil"]
    lo, hi = si.get("awc_low_pm25"), si.get("awc_high_pm25")
    if sa["mode"] == "farm_black_soil" and sa.get("low") and sa.get("high") and sa["high"] > sa["low"] > 0:
        awc_vals = np.linspace(sa["low"], sa["high"], 9)
        awc_note = (f"{sa['display_name']}: AWC range {sa['low']:.0f}-{sa['high']:.0f} mm/m ({sa['badge']}); source: {sa.get('source') or 'team to verify'}")
    elif lo and hi and hi > lo > 0:
        # fetch_soil's SoilGrids 5-95% band is unphysically wide here (awc_low 0, awc_high 342 mm/m), so use its
        # +-25% band (assumption, flagged by fetch_soil) and say so.
        awc_vals = np.linspace(lo, hi, 9)
        awc_note = (f"AWC range {lo:.0f}-{hi:.0f} mm/m = +-25% of the SoilGrids value (fetch_soil awc_low_pm25/high_pm25, assumption); "
                    f"the raw SoilGrids 5-95% band ({si.get('awc_low')}-{si.get('awc_high')} mm/m) is too wide to be physical.")
    else:
        awc_vals = np.linspace(0.7 * awc, 1.3 * awc, 9)
        awc_note = "AWC uncertainty range +-30% of the base value, assumption, team to verify"
    e1 = bd.evpi(bs, p, scale, cands, "awc", awc_vals, awc, irr,
                 None if prices["soil_test_cost_rs"] is None else prices["soil_test_cost_rs"] / farm["acres"], prices["badges"]["soil_test_cost_rs"], "soil water capacity")
    e1["range_note"] = awc_note
    e1["text"] = bd.evpi_text_awc(e1)
    irr_vals = np.linspace(0.5 * irr, 1.5 * irr, 9)     # +-50% range: ASSUMPTION
    e2 = bd.evpi(bs, p, scale, cands, "irr", irr_vals, awc, irr,
                 None if prices["water_measure_cost_rs"] is None else prices["water_measure_cost_rs"] / farm["acres"], prices["badges"]["water_measure_cost_rs"], "available irrigation water")
    e2["range_note"] = "irrigation uncertainty range +-50% of the input, assumption, team to verify"
    e2["text"] = bd.evpi_text_irr(e2, p["water_source"])
    out["evpi_awc"], out["evpi_irrigation"] = e1, e2
    out["grid_upstream_local"] = bd.upstream_local_grid(bs, awc, irr, p, scale, cands, n_scen=bs.n)
    a_ = farm["acres"]
    out["rainfall_crossover"]["delta_total_profit_vs_baseline"] = [x * a_ for x in out["rainfall_crossover"]["delta_vs_baseline"]]
    out["grid"]["delta_total_profit_vs_baseline"] = [[x * a_ for x in r] for r in g["delta_mean_profit_vs_baseline"]]
    if out["grid_upstream_local"].get("available"):
        out["grid_upstream_local"]["delta_total_profit_vs_baseline"] = [[x * a_ for x in r] for r in out["grid_upstream_local"]["delta_mean_profit_vs_baseline"]]
    _TIPPING_CACHE[cache_key] = copy.deepcopy(out)
    return out


def hindcast(params=None) -> dict:
    p = norm_params(params)
    ss, df = _table(p)
    farm = None
    if (params or {}).get("farm_records"):
        from engine.records import validate_records
        farm = validate_records(params["farm_records"])
    h = hc.hindcast(annual(), p["awc"], p["irrigation_mm"], farm=farm)
    h["baseline"] = hc.baseline_table(df, ss, p["awc"], p["irrigation_mm"], p)
    h["note"] = h.get("note") or ("Single-season model vs district yield, linearly detrended. District rice yields mix irrigated and rainfed fields, "
                                  "and are reported as milled rice (paddy x 0.66).")
    return h


def assumptions_table(params=None) -> pd.DataFrame:
    rows = []
    def walk(d, prefix=""):
        for k, v in (d or {}).items():
            if isinstance(v, dict) and ("value" in v or "range" in v):
                rows.append({"name": prefix + k, "value": v.get("value"), "range": v.get("range"), "unit": v.get("unit"),
                             "source": v.get("source", "team to verify"), "badge": v.get("badge", "assumption")})
            elif isinstance(v, dict):
                walk(v, prefix + k + ".")
    walk(_yaml("assumptions.yaml"))
    pr = economics.load_prices()
    for c in economics.CROPS:
        price_badge = pr["badges"].get(f"price_{c}", "placeholder")
        cost_badge = pr["badges"].get(f"opcost_{c}", "placeholder")
        rows.append({"name": f"price.{c}", "value": pr["price_rs_per_quintal"].get(c), "range": None, "unit": "Rs/quintal",
                     "source": "config/prices_india.yaml" if price_badge != "placeholder" else "unverified placeholder, team to verify",
                     "badge": price_badge})
        rows.append({"name": f"operating_cost.{c}", "value": pr["operating_cost_rs_per_acre"].get(c), "range": None, "unit": "Rs/acre",
                     "source": "config/prices_india.yaml" if cost_badge != "placeholder" else "unverified placeholder, team to verify",
                     "badge": cost_badge})
    for k in ("n_cost_rs_per_kg", "soil_test_cost_rs", "water_measure_cost_rs", "farm_area_acres"):
        rows.append({"name": k, "value": pr[k], "range": None, "unit": k.split("_rs_")[-1] if "_rs_" in k else "", "source": "config/prices_india.yaml"
                     if pr["badges"][k] != "placeholder" else "unverified placeholder, team to verify", "badge": pr["badges"][k]})
    rows[-1]["source"] = "config/farm.yaml (farm area supplied locally)"
    if params:
        current = norm_params(params)
        for name, value in current["economic_overrides"].items():
            rows.append({"name": "current." + name, "value": value, "range": None, "unit": "Rs/acre" if name.startswith("cost.") else "Rs/m3" if name == "irrigation_cost_rs_per_m3" else "Rs per farm",
                         "source": "Current session override; replaces the configured default above", "badge": "local"})
        for name, unit in (("awc_mm_per_m", "mm/m"), ("canal_supply_mm", "mm/season"), ("well_supply_mm", "mm/season"), ("irrigation_mm", "mm/season")):
            if params.get(name) is not None:
                rows.append({"name": "current." + name, "value": params[name], "range": None, "unit": unit,
                             "source": "Current session input; replaces the configured default above", "badge": "local"})
    rows += [{"name": "et0_per_degC", "value": sc.ET0_PER_DEGC, "range": "0.02-0.05", "unit": "fraction per degC", "source": "team to verify", "badge": "assumption"},
             {"name": "awc_uncertainty_range", "value": 0.3, "range": None, "unit": "fraction", "source": "team to verify", "badge": "assumption"},
             {"name": "irrigation_uncertainty_range", "value": 0.5, "range": None, "unit": "fraction", "source": "team to verify", "badge": "assumption"},
             {"name": "scenario_seed", "value": sc.SEED, "range": None, "unit": "", "source": "project rule", "badge": "assumption"}]
    df = pd.DataFrame(rows)
    df["in_use"] = [_in_use(n) for n in df["name"]]
    return df


def _in_use(name: str) -> bool:
    """False for table rows the current run does not read: parameters of crops that are not in the crop list, and
    the fallback potential yields that config/prices_india.yaml overrides."""
    crops_all = ("rice", "jowar", "bajra", "ragi", "pigeonpea")
    used = set(opt.CROPS)
    parts = name.split(".")
    crop = next((x for x in parts if x in crops_all), None)
    if crop is not None and crop not in used:
        return False
    if parts[0] == "monsoon":
        return False  # legacy standalone absolute-onset compatibility, not the app onset rule
    if parts[0] == "ym_kg_ha":
        pot = ((_yaml("prices_india.yaml").get("potential_yield_kg_ha")) or {}).get(parts[-1]) or {}
        return pot.get("value") is None
    return True
