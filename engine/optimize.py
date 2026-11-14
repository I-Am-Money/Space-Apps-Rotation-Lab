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

CROPS = list(economics.CROPS)
REF = {"A": ["rice"] * 4, "B": ["rice", "jowar", "rice", "jowar"], "C": ["rice", "pigeonpea", "jowar", "rice"]}
ALL_PLANS = [list(p) for p in itertools.product(CROPS, repeat=4)]

_SIM = None
_SIM_CACHE: dict = {}
_ARR_CACHE: dict = {}


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
    """Simulate all not-yet-cached plans in ONE batched call (waterbalance.simulate_batch)."""
    if _SIM is not None:          # test stand-in: per-plan simulator
        return
    todo, seen = [], set()
    for p in plans:
        k = _sim_key(p, scenset, awc, irr)
        if k not in _SIM_CACHE and k not in seen:
            seen.add(k); todo.append(list(p))
    if not todo:
        return
    from engine.waterbalance import simulate_batch
    res = simulate_batch(scenset.scen, todo, float(awc), float(irr))
    for r, p in enumerate(todo):
        _SIM_CACHE[_sim_key(p, scenset, awc, irr)] = {k: (v[r] if isinstance(v, np.ndarray) and v.ndim >= 2 and v.shape[0] == len(todo) else v)
                                                      for k, v in res.items()}


def _sim_key(plan, scenset, awc, irr):
    # irrigation only matters when the plan contains rice: drop it from the key otherwise
    return (scenset.key, tuple(plan), round(float(awc), 4), round(float(irr), 4) if "rice" in plan else None)


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
             "yield": np.asarray(sim["yield_kg_ha"]), "eco": eco}
        _ARR_CACHE[key] = a
    return a


def metrics(a: dict) -> dict:
    return {"mean_profit": float(a["profit"].mean()), "worst10_profit": worst_fraction_mean(a["profit"]),
            "water_stress_mm": float(a["stress"].mean()), "irrigation_mm": float(a["irrig"].mean()),
            "total_water_mm": float(a["total"].mean())}


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
    return df


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
        ev = {"rank_of_256": int(row["rank"]), "J": float(row.J), "mean_profit_rs_acre": float(row.mean_profit),
              "worst10_profit_rs_acre": float(row.worst10_profit), "water_stress_mm": float(row.water_stress_mm),
              "irrigation_mm": float(row.irrigation_mm), "total_water_mm": float(row.total_water_mm),
              "share_of_scenarios_at_least_as_profitable_as_recommended": p_beat,
              "share_of_scenarios_with_loss": p_loss, "n_credit_kg_ha_over_plan": credit,
              "n_scenarios": int(scenset.n)}
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
