"""Rotation optimisation: configured four-year sequences, J score, Pareto frontier, reports.

J = (1-lam)*mean_profit + lam*worst10_profit - w*scale*irrigation_mm.
Scale (rupees/acre/mm) is a fixed explicit water preference, independent of the
profit spread. It is never deducted from the displayed profit.
"""
from __future__ import annotations

import itertools
import math
from contextvars import ContextVar
from contextlib import contextmanager

import numpy as np
import pandas as pd

from engine import economics
from engine.cache import ArrayCache
from engine.configuration import version as configuration_version

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
        mt = (rp.stat().st_mtime_ns if rp.exists() else None, configuration_version())
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
    ALL_PLANS = [list(p) for p in itertools.product(CROPS, repeat=4) if plan_allowed(p)]


def plan_allowed(plan) -> bool:
    """Team rule (assumptions.yaml plan_rules): the same non-rice crop in all 4 years is not offered.
    Rice x4 always stays: it is the baseline, our farm today."""
    from engine.crops import A
    if not bool(A(None, "plan_rules.block_same_nonrice_crop_4_years")):
        return True
    return not (len(set(plan)) == 1 and plan[0] != "rice")


def water_price_proxy_rs_per_mm_acre() -> float:
    """v3 section 7 water_price_proxy, converted from INR per mm per ha to INR per mm per acre."""
    from engine.crops import A
    return float(A(None, "objective.water_price_proxy_rs_per_mm_ha")) * economics.HA_PER_ACRE


configure()
_SIM = None
_SIM_CACHE = ArrayCache(192 * 1024 * 1024)
_ARR_CACHE = ArrayCache(96 * 1024 * 1024)
_SIM_CONTEXT = ContextVar("rotationlab_sim_params", default=())
_SPLIT_CONTEXT = ContextVar("rotationlab_water_split", default=())
_ECON_CONTEXT = ContextVar("rotationlab_economics", default=())


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
    x = np.asarray(x, float)
    k = max(1, int(math.ceil(frac * len(x))))
    return float(np.partition(x, k - 1)[:k].mean())


def prefetch(plans, scenset, awc: float, irr: float) -> None:
    prefetch_multi(plans, [scenset], awc, irr)


def prefetch_multi(plans, scensets, awc: float, irr: float) -> None:
    """Simulate every missing (plan, scenario set) in ONE simulate_batch call by concatenating the
    scenario sets along the scenario axis. Needs a fixed median_season_rain_mm in SIM_PARAMS so that
    concatenation does not change the rice water-availability scaling."""
    if _SIM is not None:          # test stand-in: per-plan simulator
        return
    if len(scensets) > 1 and sum(ss.n for ss in scensets) > 2000:
        chunk, count = [], 0
        for ss in scensets:
            if chunk and count + ss.n > 2000:
                prefetch_multi(plans, chunk, awc, irr)
                chunk, count = [], 0
            chunk.append(ss); count += ss.n
        if chunk:
            prefetch_multi(plans, chunk, awc, irr)
        return
    todo, seen = [], set()
    for ss in scensets:
        for p in plans:
            if _sim_key(p, ss, awc, irr) not in _SIM_CACHE and tuple(p) not in seen:
                seen.add(tuple(p)); todo.append(list(p))
    if not todo:
        return
    from engine.waterbalance import simulate_batch
    keys = ["et0", "precip", "tmax"] + [k for k in ("upstream_season_rain", "onset_doy") if all(k in ss.scen for ss in scensets)]
    cat = {k: np.concatenate([ss.scen[k] for ss in scensets]) for k in keys}
    if all("onset_median" in ss.scen for ss in scensets):
        medians = {ss.scen["onset_median"] for ss in scensets}
        if len(medians) != 1:
            for ss in scensets:
                prefetch_multi(plans, [ss], awc, irr)
            return
        cat["onset_median"] = medians.pop()
    res = simulate_batch(cat, todo, float(awc), float(irr), params_for(irr))
    off = 0
    for ss in scensets:
        n = ss.n
        for r, p in enumerate(todo):
            _SIM_CACHE[_sim_key(p, ss, awc, irr)] = {
                k: (v[r, off:off + n].copy() if isinstance(v, np.ndarray) and v.ndim >= 2 and v.shape[0] == len(todo) else v)
                for k, v in res.items() if k not in ("plans", "daily")}
        off += n


def set_sim_params(split=None, **kw):
    kw["_configuration_version"] = configuration_version()
    _SIM_CONTEXT.set(tuple(sorted((k, v) for k, v in kw.items() if v is not None)))
    _SPLIT_CONTEXT.set(tuple(sorted((split or {}).items())))


def set_economic_params(overrides=None):
    _ECON_CONTEXT.set(tuple(sorted((overrides or {}).items())))


@contextmanager
def simulation_overrides(**values):
    params = dict(_SIM_CONTEXT.get())
    params.update(values)
    token = _SIM_CONTEXT.set(tuple(sorted(params.items())))
    try:
        yield
    finally:
        _SIM_CONTEXT.reset(token)


def current_prices():
    import copy
    prices = economics.load_prices()
    if not _ECON_CONTEXT.get():
        return prices
    prices = copy.deepcopy(prices)
    for key, value in _ECON_CONTEXT.get():
        if key.startswith("cost."):
            crop = key.split(".", 1)[1]
            prices["operating_cost_rs_per_acre"][crop] = value
            prices["badges"][f"opcost_{crop}"] = "local"
        else:
            prices[key] = value
            prices["badges"][key] = "local"
    return prices


@contextmanager
def irrigation_sweep(level, reference):
    """Scale entered source capacities with total supply in a what-if sweep."""
    params = dict(_SIM_CONTEXT.get())
    factor = float(level) / float(reference) if reference > 0 else 0.
    changes = {key: params[key] * factor for key in ("canal_supply_mm", "well_supply_mm") if key in params}
    if reference <= 0 and level > 0:
        split = dict(_SPLIT_CONTEXT.get())
        total = sum(split.values())
        if total > 0:
            changes = {key: float(level) * split[base] / total for key, base in
                       (("canal_supply_mm", "base_canal"), ("well_supply_mm", "base_well")) if key in params}
    with simulation_overrides(**changes):
        yield


def params_for(irr: float) -> dict | None:
    """simulate_batch params for a given irrigation level. In canal_and_well mode physics ignores the
    irrigation argument, so the slider (total base supply, mm) scales base_canal and base_well in their
    assumption ratio (rain linkage kept). Explicit canal_supply_mm / well_supply_mm stay as fixed overrides."""
    prm = dict(_SIM_CONTEXT.get())
    split = dict(_SPLIT_CONTEXT.get())
    if prm.get("water_source") == "canal_and_well" and split:
        tot = split["base_canal"] + split["base_well"]
        prm["base_canal"] = float(irr) * split["base_canal"] / tot
        prm["base_well"] = float(irr) * split["base_well"] / tot
    return prm or None


def _sim_key(plan, scenset, awc, irr):
    # irrigation only matters when the plan contains rice: drop it from the key otherwise
    return (scenset.key, scenset.scen.get("source_version", ()), tuple(plan), round(float(awc), 4), round(float(irr), 4) if "rice" in plan else None,
            tuple(sorted((params_for(irr) or {}).items())))


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
    key = (_sim_key(plan, scenset, awc, irr), float(price_mult), _ECON_CONTEXT.get(),
           economics.PRICES_PATH.stat().st_mtime_ns)
    # Explicit price dictionaries may differ from the configured prices.
    a = _ARR_CACHE.get(key) if prices is None else None
    if a is None:
        sim = sim_plan(plan, scenset, awc, irr)
        from engine.yieldmodel import nitrogen_credit_kg_ha
        eco = economics.plan_economics(plan, sim, price_mult, prices or current_prices(), n_credit=nitrogen_credit_kg_ha(plan, dict(_SIM_CONTEXT.get())))
        a = {"profit": eco["profit"], "profit_year": eco["profit_year"],
             "stress": (np.asarray(sim["etm_mm"]) - np.asarray(sim["eta_mm"])).sum(1),
             "irrig": np.asarray(sim["irrig_mm"]).sum(1),
             "total": (np.asarray(sim["rain_mm"]) + np.asarray(sim["irrig_mm"])).sum(1),
             "yield": np.asarray(sim["yield_kg_ha"]), "eco": eco,
             "hot_days": (np.asarray(sim["hot_days"]) if "hot_days" in sim else None),
             "sowing_doy": (np.asarray(sim["sowing_doy"]) if "sowing_doy" in sim else None),
             "irrig_canal": (np.asarray(sim["irrig_canal_mm"]).sum(1) if "irrig_canal_mm" in sim else None),
             "irrig_well": (np.asarray(sim["irrig_well_mm"]).sum(1) if "irrig_well_mm" in sim else None)}
        if prices is None:
            _ARR_CACHE[key] = a
    return a


def metrics(a: dict) -> dict:
    return {"mean_profit": float(a["profit"].mean()), "worst10_profit": worst_fraction_mean(a["profit"]),
            "water_stress_mm": float(a["stress"].mean()), "irrigation_mm": float(a["irrig"].mean()),
            "total_water_mm": float(a["total"].mean()),
            "irrigation_canal_mm": float("nan") if a.get("irrig_canal") is None else float(a["irrig_canal"].mean()),
            "irrigation_well_mm": float("nan") if a.get("irrig_well") is None else float(a["irrig_well"].mean())}


def objective(mean, worst10, irrigation, lam, w, scale):
    return (1 - lam) * mean + lam * worst10 - w * scale * irrigation


def compute_scale(mean_profit, irrigation) -> float:
    dp = float(np.max(mean_profit) - np.min(mean_profit))
    ds = float(np.max(irrigation) - np.min(irrigation))
    return dp / ds if ds > 1e-9 else 0.0


def breakeven_shortfall(plan, scenset, awc, irr, lam, w, price_mult=1.0, scale=None) -> dict | None:
    """How much less money the non-rice crops of `plan` can bring in (a lower price or a lower yield) before rice every
    year (rotation A) scores at least as high on J. A sensitivity check on the least certain inputs, not a forecast.
    Returns None for a plan with no non-rice year. `shortfall` is a fraction of the non-rice revenue (0 to 1), or None
    when the plan still scores higher with no non-rice revenue at all."""
    plan = list(plan)
    cols = [i for i, c in enumerate(plan) if c != "rice"]
    if not cols:
        return None
    scale = water_price_proxy_rs_per_mm_acre() if scale is None else scale
    a = rotation_arrays(plan, scenset, awc, irr, price_mult)
    b = rotation_arrays(REF[BASELINE_ID], scenset, awc, irr, price_mult)
    alt_rev = np.asarray(a["eco"]["revenue"])[:, cols].sum(1)
    jb = float(objective(b["profit"].mean(), worst_fraction_mean(b["profit"]), b["irrig"].mean(), lam, w, scale))

    def j(short):
        prof = a["profit"] - short * alt_rev
        return float(objective(prof.mean(), worst_fraction_mean(prof), a["irrig"].mean(), lam, w, scale))

    out = {"crops": sorted({plan[i] for i in cols}), "non_rice_revenue_mean": float(alt_rev.mean()),
           "lead_over_baseline": j(0.0) - jb, "baseline_id": plan_id(REF[BASELINE_ID])}
    if j(0.0) <= jb:
        return {**out, "shortfall": 0.0}
    if j(1.0) > jb:
        return {**out, "shortfall": None}
    lo, hi = 0.0, 1.0
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if j(mid) > jb else (lo, mid)
    return {**out, "shortfall": 0.5 * (lo + hi)}


def without_rotation_effects(plan, scenset, awc, irr, price_mult=1.0) -> dict | None:
    """Profit of `plan` against rice every year if every rotation effect were zero: no yield change from the previous
    crop and no nitrogen credit. The rotation effects are unsourced assumptions (Build Spec v3 section 5.5), so this
    shows how much of the result rests on them. The yield multiplier is applied last in the yield model, so dividing
    revenue by it removes it exactly. Returns None for rice every year."""
    plan, base = list(plan), list(REF[BASELINE_ID])
    if plan_id(plan) == plan_id(base):
        return None
    from engine.yieldmodel import rotation_factor

    def prof(pl):
        e = rotation_arrays(pl, scenset, awc, irr, price_mult)["eco"]
        f = np.asarray(rotation_factor(pl, dict(_SIM_CONTEXT.get()) or None), float)
        return (np.asarray(e["revenue"]) / f[None, :] - np.asarray(e["op_cost"])).sum(1)

    p, b = prof(plan), prof(base)
    with_fx = rotation_arrays(plan, scenset, awc, irr, price_mult)["profit"].mean() - rotation_arrays(base, scenset, awc, irr, price_mult)["profit"].mean()
    return {"d_mean_profit": float(p.mean() - b.mean()), "d_worst10_profit": float(worst_fraction_mean(p) - worst_fraction_mean(b)),
            "d_mean_profit_with_effects": float(with_fx), "baseline_id": plan_id(base)}


def evaluate_table(scenset, awc, irr, lam, w, price_mult=1.0, plans=None, extra=()) -> pd.DataFrame:
    """One row per rotation. `extra` = rotations the team rule does not offer (plan_allowed is False) but that the
    user asked to see, e.g. their current rotation: they get offered=False, are never recommended and have rank 0."""
    plans = [list(p) for p in (plans or ALL_PLANS)]
    seen = {plan_id(p) for p in plans}
    n_offered = len(plans)
    for p in extra:
        if plan_id(p) not in seen:
            seen.add(plan_id(p)); plans.append(list(p))
    prefetch(plans, scenset, awc, irr)
    rows = []
    for i, p in enumerate(plans):
        m = metrics(rotation_arrays(p, scenset, awc, irr, price_mult))
        rows.append({"id": plan_id(p), "plan": list(p), "offered": i < n_offered, **m})
    df = pd.DataFrame(rows)
    scale = water_price_proxy_rs_per_mm_acre()
    df.attrs["scale"] = scale
    return rescore(df, lam, w, scale)


def rescore(df: pd.DataFrame, lam, w, scale=None) -> pd.DataFrame:
    scale = df.attrs.get("scale", 0.0) if scale is None else scale
    df = df.copy()
    df.attrs["scale"] = scale
    df["J"] = objective(df.mean_profit, df.worst10_profit, df.irrigation_mm, lam, w, scale)
    off = df["offered"].astype(bool) if "offered" in df else pd.Series(True, index=df.index)
    df["rank"] = 0
    df.loc[off, "rank"] = df.J[off].rank(ascending=False, method="first").astype(int)
    df["on_frontier"] = False
    df.loc[off, "on_frontier"] = pareto_mask(df.mean_profit[off].values, df.worst10_profit[off].values)
    return add_deltas(df)


def offered(df: pd.DataFrame) -> pd.DataFrame:
    """Rows the tool may recommend (drops rotations shown only for comparison)."""
    return df[df["offered"].astype(bool)] if "offered" in df else df


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
    order = np.argsort(-x, kind="stable")
    mask = np.zeros(len(x), bool)
    best = -np.inf
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and x[order[end]] == x[order[start]]:
            end += 1
        group = order[start:end]
        top = y[group].max()
        if top > best + 1e-12:
            mask[group[np.abs(y[group] - top) <= 1e-12]] = True
        best = max(best, top)
        start = end
    return mask


def recommend_from_table(df: pd.DataFrame) -> dict:
    d = offered(df).sort_values("J", ascending=False)
    return {"top": d.iloc[0].to_dict(), "runner_up": d.iloc[1].to_dict()}


# ----------------------------------------------------------------- reports
def _count_pairs(plan, same):
    return sum(1 for a, b in zip(plan[:-1], plan[1:]) if a == b and same(a))


def three_strategy_report(df, scenset, awc, irr, params, strategies: dict, price_mult=1.0, prices=None) -> dict:
    """strategies: name -> plan. Text is generated from computed numbers and fixed rules only."""
    prices = prices or current_prices()
    n_off = len(offered(df))
    top = offered(df).sort_values("J", ascending=False).iloc[0]
    top_arr = rotation_arrays(top["plan"], scenset, awc, irr, price_mult, prices)
    a_row = df[df.id == plan_id(REF["A"])].iloc[0]
    out = {}
    for name, plan in strategies.items():
        row = df[df.id == plan_id(plan)].iloc[0]
        arr = rotation_arrays(plan, scenset, awc, irr, price_mult, prices)
        p_beat = float((arr["profit"] >= top_arr["profit"]).mean())
        p_loss = float((arr["profit"] < 0).mean())
        credit = float(np.sum(economics.n_credit_kg_ha(plan)))
        ev = {"rank_of_256": int(row["rank"]), "rank": int(row["rank"]), "n_rotations": n_off, "offered": bool(row.get("offered", True)), "J": float(row.J), "mean_profit_rs_acre": float(row.mean_profit),
              "worst10_profit_rs_acre": float(row.worst10_profit), "water_stress_mm": float(row.water_stress_mm),
              "irrigation_mm": float(row.irrigation_mm), "total_water_mm": float(row.total_water_mm),
              "share_of_scenarios_at_least_as_profitable_as_recommended": p_beat,
              "share_of_scenarios_with_loss": p_loss, "n_credit_kg_ha_over_plan": credit,
              "n_scenarios": int(scenset.n), "delta_vs_baseline": delta_vs_baseline(row), "baseline_id": BASELINE_ID}
        if row.id == top.id:
            why = (f"Ranked 1 of {n_off} on the objective J (lam={params['lam']:.2f}, w={params['w']:.2f}): "
                   f"mean {row.mean_profit:,.0f} Rs/acre, worst-10% {row.worst10_profit:,.0f} Rs/acre, "
                   f"irrigation {row.irrigation_mm:.0f} mm over the plan.")
        else:
            lead = (f"Ranked {int(row['rank'])} of {n_off}. " if bool(row.get("offered", True)) else
                    "Shown for comparison only: the tool does not offer the same non-rice crop in all 4 years (team rule). ")
            why = (lead + "Versus the recommended rotation: mean profit "
                   f"{row.mean_profit - top.mean_profit:+,.0f} Rs/acre, worst-10% {row.worst10_profit - top.worst10_profit:+,.0f} Rs/acre, "
                   f"irrigation {row.irrigation_mm - top.irrigation_mm:+.0f} mm. "
                   f"It matches or beats the recommended plan in {p_beat*100:.0f}% of scenarios.")
        benefits = []
        d_irr = a_row.irrigation_mm - row.irrigation_mm
        if d_irr > 1:
            benefits.append(f"Uses {d_irr:.0f} mm less irrigation water over 4 years than rice every year.")
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
        gaps.append("Irrigation available (mm) is a user input or a proxy, not a measured canal allocation or well yield.")
        if any(c in ("pigeonpea", "jowar", "ragi") for c in plan):
            gaps.append("District yields aggregate farms, irrigation regimes and crop seasons; they do not establish field-level performance.")
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
            risks.append(f"Needs about {row.irrigation_mm:.0f} mm irrigation over 4 years against {irr:.0f} mm per season available before monsoon scaling; check the canal allocation and well yield locally.")
        if "pigeonpea" in plan:
            risks.append("Pigeon pea is assumed to sell at the minimum support price; local market prices can be lower. Check with the local market yard.")
        out[name] = {"plan": list(plan), "id": plan_id(plan), "why": why, "evidence": ev, "benefits": benefits,
                     "info_gaps": gaps, "risks_for_local_review": risks}
    return out


def combine_profit(p_rice, p_alt, n_acres: int) -> np.ndarray:
    """Per-scenario farm total [n_acres+1, S] for k = 0..n_acres acres on rotation A (rice) and the rest on the alternative."""
    k = np.arange(n_acres + 1, dtype=float)[:, None]
    return k * np.asarray(p_rice)[None, :] + (n_acres - k) * np.asarray(p_alt)[None, :]

def cache_mb():
    return (_SIM_CACHE.bytes + _ARR_CACHE.bytes) / 1024 ** 2

def trim_cache(max_mb=None):
    if max_mb is not None and cache_mb() > max_mb:
        clear_cache()
        return True
    return False
