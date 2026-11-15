"""Rotation optimisation (engine-decision): 256 sequences, J score, Pareto frontier, reports.

J = (1-lam)*mean_profit + lam*worst10_profit - w*scale*water_stress
 scale (rupees per mm) = (max-min mean_profit over the 256) / (max-min water_stress), so w=1 trades the
 whole profit spread against the whole water-stress spread. Computed from the model, not hardcoded.
"""
from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd

from engine import economics

BASELINE_ID = "A"
CROPS: list = []
MILLETS: list = []
REF: dict = {}
ALL_PLANS: list = []
SELECTION_SOURCE = ""
_SEL_MTIME = None


def configure(millets=None, region_path=None):
    """Set the crop universe from config/region.yaml `crop_selection.millets` (or an explicit list).
    CROPS = rice, pigeonpea + selected millets. A = rice x4 (baseline), B = rice,M,rice,M, C = rice,pigeonpea,M,rice."""
    global CROPS, MILLETS, REF, ALL_PLANS, SELECTION_SOURCE, _SEL_MTIME
    import yaml
    from pathlib import Path
    rp = Path(region_path) if region_path else Path(__file__).resolve().parent.parent / "config" / "region.yaml"
    if millets is None:
        mt = rp.stat().st_mtime if rp.exists() else None
        if CROPS and mt == _SEL_MTIME:
            return
        _SEL_MTIME = mt
        sel = ((yaml.safe_load(open(rp)) or {}).get("crop_selection") or {}) if rp.exists() else {}
        millets = list(sel.get("millets") or [])
        if not millets:
            raise ValueError("config/region.yaml has no crop_selection.millets; india-data must fill it (no default crop is assumed)")
        SELECTION_SOURCE = "config/region.yaml crop_selection"
    else:
        SELECTION_SOURCE = "explicit"
    m = millets[0]
    MILLETS = list(millets)
    CROPS = ["rice", "pigeonpea"] + MILLETS
    REF = {"A": ["rice"] * 4, "B": ["rice", m, "rice", m], "C": ["rice", "pigeonpea", m, "rice"]}
    ALL_PLANS = [list(p) for p in itertools.product(CROPS, repeat=4)]


configure()
_SIM = None
_SIM_CACHE: dict = {}
_ARR_CACHE: dict = {}
SIM_PARAMS: dict = {}       # passed to simulate_batch (water_source, median_season_rain_mm, ...)


def set_simulator(fn):
    """Override simulate_plan (tests use a synthetic stand-in)."""
    global _SIM
    _SIM = fn
    clear_cache()


def clear_cache():
    _SIM_CACHE.clear()
    _ARR_CACHE.clear()


def _simulator():
    if _SIM is not None:
        return _SIM
    from engine.waterbalance import simulate_plan
    return simulate_plan


def plan_id(plan) -> str:
    return "-".join(plan)


def worst_fraction_mean(x: np.ndarray, frac: float = 0.10) -> float:
    """Mean of the lowest ceil(frac*S) values (at least 1)."""
    x = np.sort(np.asarray(x, float))
    k = max(1, int(math.ceil(frac * len(x))))
    return float(x[:k].mean())


def prefetch(plans, scenset, awc: float, irr: float) -> None:
    prefetch_multi(plans, [scenset], awc, irr)


def prefetch_multi(plans, scensets, awc: float, irr: float) -> None:
    """Simulate every missing (plan, scenario set) in ONE simulate_batch call by concatenating the
    scenario sets along the scenario axis. Needs a fixed median_season_rain_mm in SIM_PARAMS so that
    concatenation does not change the rice water-availability scaling."""
    if _SIM is not None:          # test stand-in: per-plan simulator
        return
    todo, seen = [], set()
    for ss in scensets:
        for p in plans:
            if _sim_key(p, ss, awc, irr) not in _SIM_CACHE and tuple(p) not in seen:
                seen.add(tuple(p)); todo.append(list(p))
    if not todo:
        return
    from engine.waterbalance import simulate_batch
    keys = ["et0", "precip", "tmax"] + (["upstream_season_rain"] if all("upstream_season_rain" in ss.scen for ss in scensets) else [])
    cat = {k: np.concatenate([ss.scen[k] for ss in scensets]) for k in keys}
    res = simulate_batch(cat, todo, float(awc), float(irr), params_for(irr))
    off = 0
    for ss in scensets:
        n = ss.n
        for r, p in enumerate(todo):
            _SIM_CACHE[_sim_key(p, ss, awc, irr)] = {
                k: (v[r, off:off + n] if isinstance(v, np.ndarray) and v.ndim >= 2 and v.shape[0] == len(todo) else v)
                for k, v in res.items() if k not in ("plans", "daily")}
        off += n


SPLIT: dict = {}            # {"base_canal": .., "base_well": ..}: how the irrigation slider is split in canal_and_well mode


def set_sim_params(split=None, **kw):
    SIM_PARAMS.clear()
    SIM_PARAMS.update({k: v for k, v in kw.items() if v is not None})
    SPLIT.clear()
    SPLIT.update(split or {})


def params_for(irr: float) -> dict | None:
    """simulate_batch params for a given irrigation level. In canal_and_well mode physics ignores the
    irrigation argument, so the slider (total base supply, mm) scales base_canal and base_well in their
    assumption ratio (rain linkage kept). Explicit canal_supply_mm / well_supply_mm stay as fixed overrides."""
    prm = dict(SIM_PARAMS)
    if prm.get("water_source") == "canal_and_well" and SPLIT:
        tot = SPLIT["base_canal"] + SPLIT["base_well"]
        prm["base_canal"] = float(irr) * SPLIT["base_canal"] / tot
        prm["base_well"] = float(irr) * SPLIT["base_well"] / tot
    return prm or None


def _sim_key(plan, scenset, awc, irr):
    # irrigation only matters when the plan contains rice: drop it from the key otherwise
    return (scenset.key, tuple(plan), round(float(awc), 4), round(float(irr), 4) if "rice" in plan else None,
            tuple(sorted(SIM_PARAMS.items())))


def sim_plan(plan, scenset, awc: float, irr: float) -> dict:
    key = _sim_key(plan, scenset, awc, irr)
    r = _SIM_CACHE.get(key)
    if r is None:
        if _SIM is None:
            prefetch([plan], scenset, awc, irr)
            return _SIM_CACHE[key]
        r = _SIM(scenset.scen, list(plan), float(awc), float(irr))
        _SIM_CACHE[key] = r
    return r


def rotation_arrays(plan, scenset, awc, irr, price_mult=1.0, prices=None) -> dict:
    key = (scenset.key, tuple(plan), round(float(awc), 4), round(float(irr), 4), round(float(price_mult), 4))
    a = _ARR_CACHE.get(key)
    if a is None:
        sim = sim_plan(plan, scenset, awc, irr)
        eco = economics.plan_economics(plan, sim, price_mult, prices)
        a = {"profit": eco["profit"], "profit_year": eco["profit_year"],
             "stress": (np.asarray(sim["etm_mm"]) - np.asarray(sim["eta_mm"])).sum(1),
             "irrig": np.asarray(sim["irrig_mm"]).sum(1),
             "total": (np.asarray(sim["rain_mm"]) + np.asarray(sim["irrig_mm"])).sum(1),
             "yield": np.asarray(sim["yield_kg_ha"]), "eco": eco,
             "irrig_canal": (np.asarray(sim["irrig_canal_mm"]).sum(1) if "irrig_canal_mm" in sim else None),
             "irrig_well": (np.asarray(sim["irrig_well_mm"]).sum(1) if "irrig_well_mm" in sim else None)}
        _ARR_CACHE[key] = a
    return a


def metrics(a: dict) -> dict:
    return {"mean_profit": float(a["profit"].mean()), "worst10_profit": worst_fraction_mean(a["profit"]),
            "water_stress_mm": float(a["stress"].mean()), "irrigation_mm": float(a["irrig"].mean()),
            "total_water_mm": float(a["total"].mean()),
            "irrigation_canal_mm": float("nan") if a.get("irrig_canal") is None else float(a["irrig_canal"].mean()),
            "irrigation_well_mm": float("nan") if a.get("irrig_well") is None else float(a["irrig_well"].mean())}


def combine_profit(p_rice, p_alt, n_acres: int) -> np.ndarray:
    """Per-scenario farm total [n_acres+1, S] for k = 0..n_acres acres on rotation A (rice) and the rest on the alternative."""
    k = np.arange(n_acres + 1, dtype=float)[:, None]
    return k * np.asarray(p_rice)[None, :] + (n_acres - k) * np.asarray(p_alt)[None, :]


def objective(mean, worst10, stress, lam, w, scale):
    return (1 - lam) * mean + lam * worst10 - w * scale * stress


def compute_scale(mean_profit, stress) -> float:
    dp = float(np.max(mean_profit) - np.min(mean_profit))
    ds = float(np.max(stress) - np.min(stress))
    return dp / ds if ds > 1e-9 else 0.0


def evaluate_table(scenset, awc, irr, lam, w, price_mult=1.0, plans=None) -> pd.DataFrame:
    plans = plans or ALL_PLANS
    prefetch(plans, scenset, awc, irr)
    rows = []
    for p in plans:
        m = metrics(rotation_arrays(p, scenset, awc, irr, price_mult))
        rows.append({"id": plan_id(p), "plan": list(p), **m})
    df = pd.DataFrame(rows)
    scale = compute_scale(df.mean_profit.values, df.water_stress_mm.values)
    df.attrs["scale"] = scale
    return rescore(df, lam, w, scale)


def rescore(df: pd.DataFrame, lam, w, scale=None) -> pd.DataFrame:
    scale = df.attrs.get("scale", 0.0) if scale is None else scale
    df = df.copy()
    df.attrs["scale"] = scale
    df["J"] = objective(df.mean_profit, df.worst10_profit, df.water_stress_mm, lam, w, scale)
    df["rank"] = df.J.rank(ascending=False, method="first").astype(int)
    df["on_frontier"] = pareto_mask(df.mean_profit.values, df.worst10_profit.values)
    return add_deltas(df)


DELTA_FIELDS = {"mean_profit": "d_mean_profit", "worst10_profit": "d_worst10_profit", "total_water_mm": "d_total_water_mm",
                "irrigation_mm": "d_irrigation_mm", "water_stress_mm": "d_water_stress_mm"}


def add_deltas(df: pd.DataFrame) -> pd.DataFrame:
    """Columns d_* = value minus rotation A (rice x4, our farm today, the baseline)."""
    base = df[df.id == plan_id(REF[BASELINE_ID])]
    if base.empty:
        return df
    b = base.iloc[0]
    for src, dst in DELTA_FIELDS.items():
        df[dst] = df[src] - b[src]
    return df


def delta_vs_baseline(row) -> dict:
    return {dst: float(row[dst]) for dst in DELTA_FIELDS.values() if dst in row}


def pareto_mask(x, y) -> np.ndarray:
    """True for points not dominated in (x, y), both maximised."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    order = np.lexsort((-y, -x))
    mask = np.zeros(len(x), bool)
    best = -np.inf
    for i in order:
        if y[i] > best + 1e-12:
            mask[i] = True
            best = y[i]
    return mask


def recommend_from_table(df: pd.DataFrame) -> dict:
    d = df.sort_values("J", ascending=False)
    return {"top": d.iloc[0].to_dict(), "runner_up": d.iloc[1].to_dict()}


# ----------------------------------------------------------------- reports
def _count_pairs(plan, same):
    return sum(1 for a, b in zip(plan[:-1], plan[1:]) if a == b and same(a))


def three_strategy_report(df, scenset, awc, irr, params, strategies: dict, price_mult=1.0, prices=None) -> dict:
    """strategies: name -> plan. Text is generated from computed numbers and fixed rules only."""
    prices = prices or economics.load_prices()
    top = df.sort_values("J", ascending=False).iloc[0]
    top_arr = rotation_arrays(top["plan"], scenset, awc, irr, price_mult, prices)
    a_arr = rotation_arrays(REF["A"], scenset, awc, irr, price_mult, prices)
    a_row = df[df.id == plan_id(REF["A"])].iloc[0]
    out = {}
    for name, plan in strategies.items():
        row = df[df.id == plan_id(plan)].iloc[0]
        arr = rotation_arrays(plan, scenset, awc, irr, price_mult, prices)
        p_beat = float((arr["profit"] >= top_arr["profit"]).mean())
        p_loss = float((arr["profit"] < 0).mean())
        credit = float(np.sum(economics.n_credit_kg_ha(plan)))
        ev = {"rank_of_256": int(row["rank"]), "n_rotations": int(len(df)), "J": float(row.J), "mean_profit_rs_acre": float(row.mean_profit),
              "worst10_profit_rs_acre": float(row.worst10_profit), "water_stress_mm": float(row.water_stress_mm),
              "irrigation_mm": float(row.irrigation_mm), "total_water_mm": float(row.total_water_mm),
              "share_of_scenarios_at_least_as_profitable_as_recommended": p_beat,
              "share_of_scenarios_with_loss": p_loss, "n_credit_kg_ha_over_plan": credit,
              "n_scenarios": int(scenset.n), "delta_vs_baseline": delta_vs_baseline(row), "baseline_id": BASELINE_ID}
        if row.id == top.id:
            why = (f"Ranked 1 of {len(df)} on the objective J (lam={params['lam']:.2f}, w={params['w']:.2f}): "
                   f"mean {row.mean_profit:,.0f} Rs/acre, worst-10% {row.worst10_profit:,.0f} Rs/acre, "
                   f"water stress {row.water_stress_mm:.0f} mm.")
        else:
            why = (f"Ranked {int(row['rank'])} of {len(df)}. Versus the recommended rotation: mean profit "
                   f"{row.mean_profit - top.mean_profit:+,.0f} Rs/acre, worst-10% {row.worst10_profit - top.worst10_profit:+,.0f} Rs/acre, "
                   f"water stress {row.water_stress_mm - top.water_stress_mm:+.0f} mm, irrigation {row.irrigation_mm - top.irrigation_mm:+.0f} mm. "
                   f"It matches or beats the recommended plan in {p_beat*100:.0f}% of scenarios.")
        benefits = []
        d_irr = a_row.irrigation_mm - row.irrigation_mm
        if d_irr > 1:
            benefits.append(f"Uses {d_irr:.0f} mm less irrigation water over 4 years than rice every year.")
        if row.water_stress_mm < a_row.water_stress_mm - 1:
            benefits.append(f"Mean crop water stress {a_row.water_stress_mm - row.water_stress_mm:.0f} mm lower than rice every year.")
        if row.worst10_profit > a_row.worst10_profit:
            benefits.append(f"Worst-10% profit is {row.worst10_profit - a_row.worst10_profit:,.0f} Rs/acre higher than rice every year.")
        if row.mean_profit > a_row.mean_profit:
            benefits.append(f"Mean profit is {row.mean_profit - a_row.mean_profit:,.0f} Rs/acre higher than rice every year.")
        if credit > 0:
            benefits.append(f"Includes a legume: model N credit totals {credit:.0f} kg N/ha over the plan (rotation-effect assumption).")
        if not benefits:
            benefits.append("No computed advantage over rice every year at these settings.")
        gaps = ["Prices are fixed across all scenarios; the model has no price forecast."]
        pb = prices["badges"]
        if any(v == "placeholder" for v in pb.values()):
            gaps.append("Some cost or price inputs are unverified placeholders: "
                        + ", ".join(sorted(k for k, v in pb.items() if v == "placeholder")) + ".")
        if params.get("awc_mm_per_m") is None:
            gaps.append("Soil water capacity is the default value, not measured on this field.")
        gaps.append("Irrigation available (mm) is a user input, not a measured borewell or tank yield.")
        gaps.append("Rotation yield effects come from assumptions (ranges in assumptions table), not from this farm's trials.")
        risks = []
        rr = _count_pairs(plan, lambda c: c == "rice")
        if rr:
            risks.append(f"{rr} consecutive rice-after-rice year(s): the model applies a yield penalty there (assumption).")
        mm = _count_pairs(plan, lambda c: c in ("jowar", "bajra"))
        if mm:
            risks.append(f"{mm} consecutive millet-after-millet year(s): the model applies a small penalty (assumption).")
        if p_loss > 0:
            risks.append(f"Total 4-year profit is negative in {p_loss*100:.1f}% of scenarios.")
        gap = row.mean_profit - row.worst10_profit
        risks.append(f"Worst-10% profit sits {gap:,.0f} Rs/acre below the mean.")
        if row.irrigation_mm > 0 and irr > 0:
            risks.append(f"Needs about {row.irrigation_mm:.0f} mm irrigation over 4 years against {irr:.0f} mm per season available before monsoon scaling; check borewell or tank yield locally.")
        out[name] = {"plan": list(plan), "id": plan_id(plan), "why": why, "evidence": ev, "benefits": benefits,
                     "info_gaps": gaps, "risks_for_local_review": risks}
    return out
