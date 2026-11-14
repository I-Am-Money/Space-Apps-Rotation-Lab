"""Decision API (engine-decision) exactly as in engine/CONTRACT.md.

Scenario set for optimisation: 500 bootstrap plans of 4 random real years (seed 42).
Historical 4-year blocks are returned separately in compare(). Boundaries use the same set unless
BOUNDARY_N_SCEN trims it (stated in outputs).
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from engine import boundaries as bd
from engine import economics, hindcast as hc
from engine import optimize as opt
from engine import scenarios as sc

IS_MOCK = False
ROOT = Path(__file__).resolve().parent.parent
N_SCEN = sc.N_BOOT
BOUNDARY_N_SCEN = 500
_ANNUAL = None          # tests may inject via set_annual()
_AWC_FALLBACK = 140.0   # mm/m, UNVERIFIED dev placeholder used only if no soil data / assumptions value
_IRR_FALLBACK = 500.0   # mm per season, UNVERIFIED dev placeholder if assumptions.yaml has no value


def set_annual(annual):
    global _ANNUAL
    _ANNUAL = annual
    _scensets.clear(); opt.clear_cache()


_scensets: dict = {}


def annual() -> dict:
    return _ANNUAL if _ANNUAL is not None else sc.load_annual()


def boot_set(n=None) -> sc.ScenSet:
    n = n or N_SCEN
    k = ("boot", n)
    if k not in _scensets:
        _scensets[k] = sc.bootstrap_plans(annual(), n)
    return _scensets[k]


def hist_set() -> sc.ScenSet:
    if "hist" not in _scensets:
        _scensets["hist"] = sc.historical_blocks(annual())
    return _scensets["hist"]


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


def default_irrigation():
    v = _dfs(_yaml("assumptions.yaml"), ("base_available_irrigation_mm", "irrigation_available_mm", "base_available_mm"))
    return (v, "assumption") if v is not None else (_IRR_FALLBACK, "placeholder")


def norm_params(params=None) -> dict:
    p = dict(params or {})
    awc_d, _ = default_awc()
    return {"lam": float(p.get("lam", 0.5)), "w": float(p.get("w", 0.2)),
            "irrigation_mm": float(p["irrigation_mm"]) if p.get("irrigation_mm") is not None else default_irrigation()[0],
            "awc_mm_per_m": p.get("awc_mm_per_m"), "awc": float(p["awc_mm_per_m"]) if p.get("awc_mm_per_m") is not None else awc_d,
            "current_rotation": list(p.get("current_rotation") or opt.REF["A"]),
            "price_mult": float(p.get("price_mult", 1.0))}


def _badges(p):
    prices = economics.load_prices()
    return {"profit": "modeled", "prices": economics.economics_badges(prices)["prices"],
            "water": "modeled", "weather": "observed", "irrigation_mm": default_irrigation()[1] if p.get("irrigation_mm") is None else "local",
            "awc": default_awc()[1] if p["awc_mm_per_m"] is None else "local",
            "rotation_effects": "assumption", "econ_detail": economics.economics_badges(prices)}


def _table(p, n=None):
    ss = boot_set(n)
    return ss, opt.evaluate_table(ss, p["awc"], p["irrigation_mm"], p["lam"], p["w"], p["price_mult"])


def _resolve(rid, p):
    if isinstance(rid, (list, tuple)):
        return list(rid)
    if rid == "current":
        return list(p["current_rotation"])
    if rid in opt.REF:
        return list(opt.REF[rid])
    return rid.split("-")


# ------------------------------------------------------------------- API
def get_field_summary() -> dict:
    reg = _yaml("region.yaml")
    a = annual()
    yrs = a["years"]
    mr = sc.monsoon_rain(a)
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
    obs = hc.load_observed()
    out["yield_history"] = None if obs is None else obs.to_dict("records")
    fr = hc.load_farm_records()
    out["farm_records"] = None if fr is None else {"badge": "local", "rows": fr.to_dict("records")}
    return out


def list_rotations() -> list[dict]:
    rows = [{"id": k, "plan": list(v), "label": f"{k}: " + ", ".join(v)} for k, v in opt.REF.items()]
    rows.append({"id": "current", "plan": None, "label": "Your current rotation"})
    rows += [{"id": opt.plan_id(p), "plan": list(p), "label": ", ".join(p)} for p in opt.ALL_PLANS]
    return rows


def compare(rotation_ids: list, params=None) -> dict:
    p = norm_params(params)
    ss, df = _table(p)
    hist = hist_set()
    prices = economics.load_prices()
    stress = sc.stress_tests(annual())
    out = {"params": p, "badges": _badges(p), "n_scenarios": ss.n, "scenario_note": ss.note,
           "fixed_prices_note": prices["fixed_prices_note"], "rotations": {}}
    ym = {}
    for rid in rotation_ids:
        plan = _resolve(rid, p)
        a = opt.rotation_arrays(plan, ss, p["awc"], p["irrigation_mm"], p["price_mult"])
        m = opt.metrics(a)
        ah = opt.rotation_arrays(plan, hist, p["awc"], p["irrigation_mm"], p["price_mult"])
        # residue_index: PROXY = modeled yield / best modeled yield for that crop across the set (not measured residue)
        resid = []
        for y, c in enumerate(plan):
            if c not in ym:
                ym[c] = max(1e-9, float(opt.rotation_arrays([c] * 4, ss, p["awc"], p["irrigation_mm"], p["price_mult"])["yield"].max()))
            resid.append(float(a["yield"][:, y].mean() / ym[c]))
        st_rows = []
        for name, t in stress.items():
            tss = sc.ScenSet(t["key"], t["scen"])
            at = opt.rotation_arrays(plan, tss, p["awc"], p["irrigation_mm"], p["price_mult"])
            st_rows.append({"test": name, "label": t["label"], "source_year": t["source_year"], "description": t["description"],
                            "profit": float(at["profit"][0]), "yield_kg_ha": at["yield"][0].tolist(),
                            "water_stress_mm": float(at["stress"][0]), "irrigation_mm": float(at["irrig"][0])})
        out["rotations"][rid] = {"plan": plan, "profit": a["profit"], "yield_kg_ha": a["yield"], "yield_mean": a["yield"].mean(0),
            "profit_year_mean": a["profit_year"].mean(0), **m, "J": float(df[df.id == opt.plan_id(plan)].J.iloc[0]),
            "residue_index": resid, "residue_index_note": "proxy: modeled yield relative to best modeled yield of that crop, not measured residue",
            "historical_blocks": {"labels": hist.scen["labels"], "profit": ah["profit"]},
            "stress_tests": st_rows, "badges": {"profit": "modeled", "water": "modeled", "yield": "modeled"}}
    return out


def recommend(params=None) -> dict:
    p = norm_params(params)
    ss, df = _table(p)
    r = opt.recommend_from_table(df)
    strategies = {"A": opt.REF["A"], "B": opt.REF["B"], "C": opt.REF["C"], "current": p["current_rotation"]}
    rep = opt.three_strategy_report(df, ss, p["awc"], p["irrigation_mm"], p, strategies, p["price_mult"])
    pts = df[["id", "mean_profit", "worst10_profit", "water_stress_mm", "irrigation_mm", "total_water_mm", "J", "rank", "on_frontier"]]
    return {"params": p, "top": r["top"], "runner_up": r["runner_up"], "metrics": df, "pareto": pts,
            "three_strategy_report": rep, "badges": _badges(p), "n_scenarios": ss.n,
            "scale_rs_per_mm": df.attrs["scale"],
            "objective": "J = (1-lam)*mean + lam*worst10 - w*scale*water_stress",
            "fixed_prices_note": economics.load_prices()["fixed_prices_note"]}


def tipping_points(params=None) -> dict:
    p = norm_params(params)
    ss, df = _table(p)
    bs = boot_set(min(BOUNDARY_N_SCEN, ss.n)) if BOUNDARY_N_SCEN < ss.n else ss
    scale = df.attrs["scale"]
    cands = bd.candidate_plans(df)
    prices = economics.load_prices()
    awc, irr, pm = p["awc"], p["irrigation_mm"], p["price_mult"]
    out = {"params": p, "badges": _badges(p), "n_scenarios": bs.n, "frame": bd.FRAME}
    out["rainfall_crossover"] = bd.rainfall_crossover(bs, awc, irr, p, scale, cands)
    irr_levels = np.round(np.linspace(0, max(2 * irr, 1.0), 9), 1)
    g = bd.decision_grid(bs, awc, p, scale, cands, irr_levels)
    out["grid"] = {"rain_mult": g["rain_mult"], "irrigation_mm": g["irrigation_mm"], "winner": g["winner"],
                   "rice_shift_threshold_mm": g["rice_shift_threshold_mm"], "text": g["text"], "badge": "modeled"}
    out["late_monsoon"] = bd.late_monsoon_curve(bs, awc, irr, p, scale, cands[:6] if len(cands) > 6 else cands)
    si = soil_info()
    lo, hi = si.get("awc_low_pm25"), si.get("awc_high_pm25")
    if lo and hi and hi > lo > 0:
        # fetch_soil's SoilGrids 5-95% band is unphysically wide here (awc_low 0, awc_high 342 mm/m), so use its
        # +-25% band (assumption, flagged by fetch_soil) and say so.
        awc_vals = np.linspace(lo, hi, 9)
        awc_note = (f"AWC range {lo:.0f}-{hi:.0f} mm/m = +-25% of the SoilGrids value (fetch_soil awc_low_pm25/high_pm25, assumption); "
                    f"the raw SoilGrids 5-95% band ({si.get('awc_low')}-{si.get('awc_high')} mm/m) is too wide to be physical.")
    else:
        awc_vals = np.linspace(0.7 * awc, 1.3 * awc, 9)
        awc_note = "AWC uncertainty range +-30% of the base value, assumption, team to verify"
    e1 = bd.evpi(bs, p, scale, cands, "awc", awc_vals, awc, irr,
                 prices["soil_test_cost_rs"] / prices["farm_area_acres"], prices["badges"]["soil_test_cost_rs"], "soil water capacity")
    e1["range_note"] = awc_note
    e1["text"] = bd.evpi_text_awc(e1)
    irr_vals = np.linspace(0.5 * irr, 1.5 * irr, 9)     # +-50% range: ASSUMPTION
    e2 = bd.evpi(bs, p, scale, cands, "irr", irr_vals, awc, irr,
                 prices["water_measure_cost_rs"] / prices["farm_area_acres"], prices["badges"]["water_measure_cost_rs"], "available irrigation water")
    e2["range_note"] = "irrigation uncertainty range +-50% of the input, assumption, team to verify"
    e2["text"] = bd.evpi_text_irr(e2)
    out["evpi_awc"], out["evpi_irrigation"] = e1, e2
    return out


def hindcast(params=None) -> dict:
    p = norm_params(params)
    ss, df = _table(p)
    h = hc.hindcast(annual(), p["awc"], p["irrigation_mm"])
    h["baseline"] = hc.baseline_table(df, ss, p["awc"], p["irrigation_mm"], p)
    h["note"] = h.get("note") or ("Single-season model vs district yield, linearly detrended. District rice yields mix irrigated and rainfed fields.")
    return h


def assumptions_table() -> pd.DataFrame:
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
        rows.append({"name": f"price.{c}", "value": pr["price_rs_per_quintal"][c], "range": None, "unit": "Rs/quintal",
                     "source": "config/prices_india.yaml" if pr["badges"][f"price_{c}"] != "placeholder" else "unverified placeholder, team to verify",
                     "badge": pr["badges"][f"price_{c}"]})
        rows.append({"name": f"operating_cost.{c}", "value": pr["operating_cost_rs_per_acre"][c], "range": None, "unit": "Rs/acre",
                     "source": "config/prices_india.yaml" if pr["badges"][f"opcost_{c}"] != "placeholder" else "unverified placeholder, team to verify",
                     "badge": pr["badges"][f"opcost_{c}"]})
    for k in ("n_cost_rs_per_kg", "irrigation_cost_rs_per_m3", "soil_test_cost_rs", "water_measure_cost_rs", "farm_area_acres"):
        rows.append({"name": k, "value": pr[k], "range": None, "unit": k.split("_rs_")[-1] if "_rs_" in k else "", "source": "config/prices_india.yaml"
                     if pr["badges"][k] != "placeholder" else "unverified placeholder, team to verify", "badge": pr["badges"][k]})
    rows += [{"name": "et0_per_degC", "value": sc.ET0_PER_DEGC, "range": "0.02-0.05", "unit": "fraction per degC", "source": "team to verify", "badge": "assumption"},
             {"name": "awc_uncertainty_range", "value": 0.3, "range": None, "unit": "fraction", "source": "team to verify", "badge": "assumption"},
             {"name": "irrigation_uncertainty_range", "value": 0.5, "range": None, "unit": "fraction", "source": "team to verify", "badge": "assumption"},
             {"name": "scenario_seed", "value": sc.SEED, "range": None, "unit": "", "source": "project rule", "badge": "assumption"}]
    return pd.DataFrame(rows)
