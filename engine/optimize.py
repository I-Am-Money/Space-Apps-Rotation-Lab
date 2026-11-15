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


# =====================================================================================================
# Build Spec v4 / v5, Feature 3 (recommendations). Everything above this line is the v3 India model and is left
# untouched. Parameters: config/assumptions/recommend.yaml. Talks to Person 2's simulation only through
# `simulate(site, inputs, rotation, scenarios)` (engine.api.simulate once it exists).
#
# ASSUMED simulate() result (confirm with Person 2 when engine/simulate.py lands; adapt `_read_sim` only):
#   dict with arrays shaped [S, Y]:  "yields_kg_ha", "irrigation_mm", "total_water_mm"   (S scenarios, Y = 4 plan years)
# One crop per plan year in the enumeration; two seasons per year (R9) is below the cut line.
#
# Units: profit currency/ha, averaged per plan year; calories kcal/ha per plan year; water mm per plan year.
# =====================================================================================================
import functools
import yaml as _yaml3
from pathlib import Path as _Path3

from engine import soil_score as _ss3

_F3_YAML = _Path3(__file__).resolve().parent.parent / "config" / "assumptions" / "recommend.yaml"
COVER_CROP_ID = "cereal_rye"
DELTA_KEYS = ("mean_profit", "worst10_profit", "calories", "irrigation_mm", "total_water_mm", "soil_score")
YEARS_IN_PLAN = 4


@functools.lru_cache(maxsize=2)
def _f3_read(version) -> dict:
    return _yaml3.safe_load(_F3_YAML.read_text())["optimize"]


def _f3_params() -> dict:
    """Parsed `optimize` section of recommend.yaml; re-read only when the file changes."""
    return _f3_read(_F3_YAML.stat().st_mtime_ns)


def _slider(s, name, default):
    v = s.get(name) if isinstance(s, dict) else getattr(s, name, None)
    return default if v is None else v


def enumerate_rotations(crops, years: int = YEARS_IN_PLAN, allow_cover: bool = False, current_plan=None,
                        cap: int | None = None) -> list:
    """Every 4-year sequence of the candidate crops (R9), each with and without a cover crop when allowed.
    The farmer's current plan is always included. Sorted so results are reproducible. A rotation is a dict
    {"crops": [[crop], ...], "cover_crops": [bool, ...]}."""
    cap = cap or int(_f3_params()["max_rotations_scored"]["value"])
    cover_options = [[False] * years] + ([[False] + [True] * (years - 1)] if allow_cover else [])
    out = [{"crops": [[c] for c in seq], "cover_crops": list(cv)}
           for seq in itertools.product(sorted(set(crops)), repeat=years) for cv in cover_options]
    if current_plan is not None:
        cur = {"crops": [[c] if isinstance(c, str) else list(c) for c in current_plan], "cover_crops": [False] * years}
        if cur not in out:
            out.append(cur)
    if len(out) > cap:
        rng = np.random.default_rng(42)
        keep = set(rng.choice(len(out), size=cap, replace=False).tolist())
        out = [r for i, r in enumerate(out) if i in keep or (current_plan is not None and r["crops"] == cur["crops"]
                                                              and r["cover_crops"] == cur["cover_crops"])]
    return out


def _read_sim(sim) -> dict:
    get = (lambda k: sim[k]) if isinstance(sim, dict) else (lambda k: getattr(sim, k))
    return {k: np.asarray(get(k), dtype=float) for k in ("yields_kg_ha", "irrigation_mm", "total_water_mm")}


def _kcal(crop: str) -> float:
    try:
        from engine import crops as catalog
        fn = getattr(catalog, "calories_per_kg", None)
        if fn is not None and fn(crop) is not None:
            return float(fn(crop))
    except Exception:
        pass
    node = _f3_params()["calories_kcal_per_kg"].get(crop)
    return float(node["value"]) if node else 0.0


def _score_one(rotation: dict, sim: dict, econ: dict, history, frac: float, cover_cost_per_ha: float) -> dict:
    y = sim["yields_kg_ha"]                                           # [S, Y]
    crops = [yr[0] for yr in rotation["crops"]]
    profit = np.stack([economics.profit_per_ha(y[:, i], econ[c]["price_per_t"], econ[c]["cost_per_ha"])
                       for i, c in enumerate(crops)], axis=1)          # [S, Y]
    covers = rotation["cover_crops"]
    profit = profit - np.array([cover_cost_per_ha if cv else 0.0 for cv in covers])[None, :]
    plan_profit = profit.mean(axis=1)                                  # per scenario, per plan year
    kcal = np.array([_kcal(c) for c in crops])[None, :]
    mean_y = [[float(v)] for v in y.mean(axis=0)]
    ss = _ss3.soil_score(rotation["crops"], [COVER_CROP_ID if cv else None for cv in covers], mean_y, history)
    return {"crops": rotation["crops"], "cover_crops": list(covers),
            "mean_profit": float(plan_profit.mean()), "worst10_profit": worst_fraction_mean(plan_profit, frac),
            "calories": float((y * kcal).mean()), "irrigation_mm": float(sim["irrigation_mm"].mean()),
            "total_water_mm": float(sim["total_water_mm"].mean()), "soil_score": float(ss.score),
            "yields_by_year": [{c: float(v)} for c, v in zip(crops, y.mean(axis=0))], "deltas_vs_current": {},
            "badges": {"mean_profit": "estimated", "worst10_profit": "estimated", "calories": "estimated",
                       "irrigation_mm": "estimated", "total_water_mm": "estimated", "soil_score": "assumption",
                       "yields_by_year": "estimated"},
            "soil_notes": list(ss.notes), "example": False}


def _norm01(v: np.ndarray) -> np.ndarray:
    lo, hi = float(np.min(v)), float(np.max(v))
    return np.zeros_like(v, dtype=float) if hi - lo < 1e-12 else (v - lo) / (hi - lo)


def _argmax_stable(score: np.ndarray, tie_breaks: tuple) -> int:
    """Index of the largest score; ties broken by the arrays in `tie_breaks` (larger wins), then the highest index (deterministic)."""
    order = np.lexsort(tuple(np.asarray(t) for t in reversed(tie_breaks)) + (np.asarray(score),))
    return int(order[-1])


def choose_picks(results: list, current: dict, sliders, most_food: bool = False) -> dict:
    """Three picks (R13) from scored rotations, using the sliders (R14). `results` includes the current plan.
      highest_profit  largest (1-bad_year) * mean + bad_year * worst-10% profit (or most calories if most_food)
      best_soil       largest Soil Health Score, ties by profit and risk
      headline        'Best for soil and climate': largest balanced score among rotations whose mean profit is at
                      least the current plan's minus the tolerance; None if nothing qualifies (guardrail_met False)
      balanced = (1 - soil) * profit_risk_n + soil * soil_score_n - water * irrigation_n   (each 0..1 across rotations)
    """
    lam = float(_slider(sliders, "bad_year", 0.3)); s = float(_slider(sliders, "soil", 0.5))
    w = float(_slider(sliders, "water", 0.0)); tol = float(_slider(sliders, "profit_tolerance_pct", 0.0))
    mean = np.array([r["mean_profit"] for r in results]); w10 = np.array([r["worst10_profit"] for r in results])
    soil = np.array([r["soil_score"] for r in results]); cal = np.array([r["calories"] for r in results])
    irr = np.array([r["irrigation_mm"] for r in results]); tot = np.array([r["total_water_mm"] for r in results])
    pr = (1 - lam) * mean + lam * w10
    water_axis = irr if np.ptp(irr) > 1e-9 else tot
    balanced = (1 - s) * _norm01(pr) + s * _norm01(soil) - w * _norm01(water_axis)
    hp = _argmax_stable(cal if most_food else pr, (pr, mean))
    bs = _argmax_stable(soil, (pr, mean))
    floor = current["mean_profit"] - abs(current["mean_profit"]) * tol / 100.0
    ok = mean >= floor - 1e-9
    head = None
    if ok.any():
        masked = np.where(ok, balanced, -np.inf)
        head = _argmax_stable(masked, (pr, mean))
    return {"headline": head, "highest_profit": hp, "best_soil": bs, "guardrail_met": bool(ok.any()),
            "profit_floor": float(floor), "profit_risk": pr.tolist(), "balanced": balanced.tolist()}


def _stand_in_simulate(site, inputs, rotation, scenarios):
    """STAND-IN, NOT DATA. Deterministic placeholder so the optimizer runs before Person 2's simulate() exists.
    Results carry example=True through recommend_picks."""
    rng = np.random.default_rng(42)
    n = len(scenarios) if hasattr(scenarios, "__len__") else int(scenarios)
    rain = 0.6 + 0.8 * rng.random(n)
    crops = [yr[0] for yr in rotation["crops"]]
    base = {"maize": 9000.0, "soybean": 3000.0, "wheat_winter": 3500.0, "wheat_spring": 3000.0, "sorghum": 4000.0,
            "rice": 6000.0, "cotton": 1500.0, "peanut": 3000.0}
    y = np.zeros((n, len(crops)))
    for i, c in enumerate(crops):
        prev = crops[i - 1] if i else None
        legume_bonus = 1.10 if prev in ("soybean", "peanut", "pigeonpea") and c not in ("soybean", "peanut", "pigeonpea") else 1.0
        repeat = 0.92 if prev == c else 1.0
        y[:, i] = base.get(c, 3000.0) * (0.4 + 0.6 * np.clip(rain, 0, 1.2)) * legume_bonus * repeat
    irr = np.zeros_like(y)
    return {"yields_kg_ha": y, "irrigation_mm": irr, "total_water_mm": np.tile(300 + 200 * rain[:, None], (1, len(crops)))}


def _default_simulate():
    try:
        from engine import api as _api
        fn = getattr(_api, "simulate", None)
        if fn is not None:
            return fn, False
    except Exception:
        pass
    return _stand_in_simulate, True


def score_rotations(rotations, site, inputs, sim_fn, scenarios, econ, history=None, frac: float = 0.10,
                    cover_cost_per_ha: float = 0.0) -> list:
    """Simulate and score each rotation (mean and worst-10% profit, calories, water, Soil Health Score)."""
    return [_score_one(rot, _read_sim(sim_fn(site, inputs, rot, scenarios)), econ, history, frac, cover_cost_per_ha)
            for rot in rotations]


def prepare_economics(site, inputs, pool, current_crops) -> tuple:
    """Price and cost for every crop in `pool`. Returns (econ, input_needed, excluded): a missing price or cost for a
    current-plan crop is `input_needed`; for any other crop it is `excluded` (left out, reported). Never defaulted."""
    overrides = getattr(inputs, "crop_overrides", None) or {}
    us = getattr(site, "us_defaults", None)
    econ, needed, excluded = {}, [], []
    for c in pool:
        try:
            econ[c] = economics.crop_economics(c, us, overrides)
        except economics.InputNeeded as e:
            (needed if c in current_crops else excluded).append({"crop": c, "field": e.field})
    return econ, needed, excluded


def score_candidates(site, inputs, crops=None, simulate=None, scenarios=None) -> dict:
    """The slow part (R23): enumerate and simulate every rotation. Independent of the sliders, so the UI caches it and
    calls `assemble_recommendation` on every slider move. Returns a bundle, or {"input_needed": [...]} when a price or
    cost for a current-plan crop is missing (never defaulted)."""
    from engine import candidates as cand
    frac = float(_f3_params()["worst_tail"]["value"])
    sim_fn, is_stand_in = (simulate, False) if simulate is not None else _default_simulate()
    scenarios = list(range(41)) if scenarios is None else scenarios
    plan = [[c] if isinstance(c, str) else list(c) for c in inputs.current_plan]
    current_crops = {yr[0] for yr in plan}
    pool = list(crops) if crops is not None else cand.candidates(site, inputs)
    pool = sorted(set(pool) | current_crops)
    overrides = getattr(inputs, "crop_overrides", None) or {}
    econ, needed, excluded = prepare_economics(site, inputs, pool, current_crops)
    if needed:
        return {"input_needed": needed, "excluded_crops": excluded, "example": is_stand_in}
    pool = [c for c in pool if c in econ]
    cover_cost = (overrides.get("cover_crop") or {}).get("cost")
    allow_cover = cover_cost is not None
    rotations = enumerate_rotations(pool, allow_cover=allow_cover, current_plan=plan)
    history = getattr(inputs, "history", None)
    scored = score_rotations(rotations, site, inputs, sim_fn, scenarios, econ, history, frac, float(cover_cost or 0.0))
    cur_crops = plan
    idx_cur = next(i for i, r in enumerate(rotations) if r["crops"] == cur_crops and not any(r["cover_crops"]))
    current = scored[idx_cur]
    for r in scored:
        r["deltas_vs_current"] = {k: float(r[k] - current[k]) for k in DELTA_KEYS}
        r["example"] = is_stand_in
        if is_stand_in:
            r["badges"] = {k: "example" for k in r["badges"]}
    bundle = {"scored": scored, "current": current, "excluded_crops": excluded, "cover_crops_offered": allow_cover,
              "example": is_stand_in}
    if not allow_cover:
        bundle["cover_crop_note"] = "Cover-crop options need your seed and planting cost per hectare (not offered until entered)."
    return bundle


def assemble_recommendation(bundle: dict, sliders, most_food: bool = False, explain_text: bool = True) -> dict:
    """The fast part: apply the sliders to a scored bundle (vectorised, well under a second)."""
    if "input_needed" in bundle:
        return bundle
    scored, current = bundle["scored"], bundle["current"]
    picks = choose_picks(scored, current, sliders, most_food)
    out = {"headline": None if picks["headline"] is None else scored[picks["headline"]],
           "highest_profit": scored[picks["highest_profit"]], "best_soil": scored[picks["best_soil"]],
           "all_results": scored, "current_plan_result": current, "guardrail_met": picks["guardrail_met"],
           "explanations": {}, "excluded_crops": bundle["excluded_crops"], "profit_floor": picks["profit_floor"],
           "cover_crops_offered": bundle["cover_crops_offered"], "example": bundle["example"]}
    if "cover_crop_note" in bundle:
        out["cover_crop_note"] = bundle["cover_crop_note"]
    if explain_text:
        from engine import explain as _ex
        for name in ("headline", "highest_profit", "best_soil"):
            pick = out[name]
            out["explanations"][name] = (_ex.explain_pick(pick, current, pick=name, use_api=False) if pick is not None else
                                         "No rotation keeps your average profit within your tolerance, so there is no headline pick. "
                                         "Raise the tolerance or look at the other two picks.")
    return out


def recommend_picks(site, inputs, sliders, crops=None, simulate=None, scenarios=None, most_food: bool = False,
                    explain_text: bool = True) -> dict:
    """The full Feature 3 recommendation: enumerate, simulate, score, pick. Returns a dict shaped like
    api.Recommendations (headline, highest_profit, best_soil, all_results, current_plan_result, guardrail_met,
    explanations) plus `excluded_crops`, or {"input_needed": [...]}. Never fills a missing price or cost with a default."""
    return assemble_recommendation(score_candidates(site, inputs, crops, simulate, scenarios), sliders, most_food, explain_text)
