# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Decision boundaries (engine-decision). All results come from the model; captions are generated
from the computed numbers. Evaluated over a candidate set of rotations (reference plans, monocultures
and the top-J plans at the base point) to keep sweeps fast; this is stated in each result.
Terminology: "expected value of perfect information" (EVPI), never EVSI.
"""
from __future__ import annotations

import numpy as np

from engine import optimize as opt
from engine import economics

M_GRID = np.round(np.arange(0.5, 1.3001, 0.05), 3)
GRID_M = np.round(np.linspace(0.5, 1.3, 9), 3)
LATE_DAYS = list(range(0, 31, 5))
FRAME = "what-if adjustments to real years, not forecasts"


def candidate_plans(df, extra=(), per_rice_count: int = 2):
    """Rotations compared in the boundary sweeps: the reference plans A, B, C and, for every number of rice years
    (0 to 4), the `per_rice_count` plans with the highest mean profit plus the one with the highest worst-10% profit.
    Low-water cells therefore have real low-rice options, and the set does not move with the sliders (so slider
    changes reuse the cached simulations)."""
    plans, seen = [], set()
    def add(p):
        i = opt.plan_id(p)
        if i not in seen:
            seen.add(i); plans.append(list(p))
    for p in opt.REF.values():
        add(p)
    for p in extra:
        add(p)
    df = opt.offered(df)
    nrice = df["plan"].map(lambda pl: list(pl).count("rice"))
    for n in range(5):
        sub = df[nrice == n]
        for _, r in sub.sort_values("mean_profit", ascending=False).head(per_rice_count).iterrows():
            add(r["plan"])
        for _, r in sub.sort_values("worst10_profit", ascending=False).head(1).iterrows():
            add(r["plan"])
    return plans


def _stack(plans, scenset, awc, irr, price_mult):
    opt.prefetch(plans, scenset, awc, irr)
    A = [opt.rotation_arrays(p, scenset, awc, irr, price_mult) for p in plans]
    return np.stack([a["profit"] for a in A]), np.stack([a["irrig"] for a in A])


def _J(profit, irrig, lam, w, scale):
    """profit, irrig [..., S] -> J [...] (v3 section 7). worst10 = mean of the lowest 10% of plan profits."""
    S = profit.shape[-1]
    k = max(1, int(np.ceil(0.1 * S)))
    worst = np.partition(profit, k - 1, axis=-1)[..., :k].mean(-1)
    return opt.objective(profit.mean(-1), worst, irrig.mean(-1), lam, w, scale)


def _first_crossover(winners, Jm, ms, group=None):
    """winners [M] index; Jm [M,R]. Returns list of (m_cross, from, to) via linear interpolation.
    With `group` (one label per rotation), only switches between different groups count: a switch between two
    orderings of the same crops is not a tipping point."""
    out = []
    for i in range(1, len(winners)):
        a, b = winners[i - 1], winners[i]
        if a != b and (group is None or group[a] != group[b]):
            d0 = Jm[i - 1, a] - Jm[i - 1, b]
            d1 = Jm[i, a] - Jm[i, b]
            t = d0 / (d0 - d1) if abs(d0 - d1) > 1e-12 else 0.5
            out.append((float(ms[i - 1] + np.clip(t, 0, 1) * (ms[i] - ms[i - 1])), int(a), int(b)))
    return out


def rainfall_crossover(scenset, awc, irr, params, scale, cands, n_boot=200, seed=42, m_grid=M_GRID):
    lam, w, pm = params["lam"], params["w"], params.get("price_mult", 1.0)
    P, St = [], []
    scs = [scenset.derive(rain_mult=m) for m in m_grid]
    opt.prefetch_multi(cands, scs, awc, irr)               # one batched simulation for the whole sweep
    for sc_ in scs:
        p, s = _stack(cands, sc_, awc, irr, pm)
        P.append(p); St.append(s)
    P, St = np.stack(P), np.stack(St)                      # [M,R,S]
    Jm = _J(P, St, lam, w, scale)                          # [M,R]
    win = Jm.argmax(1)
    names = [opt.plan_id(p) for p in cands]
    iA = names.index(opt.plan_id(opt.REF[opt.BASELINE_ID]))
    mp = P.mean(-1)
    delta_win = [float(mp[i, win[i]] - mp[i, iA]) for i in range(len(m_grid))]
    names = [opt.plan_id(p) for p in cands]
    nrice = [n.split("-").count("rice") for n in names]        # a tipping point = the number of rice years changes
    cross = _first_crossover(win, Jm, m_grid, nrice)
    rng = np.random.default_rng(seed)
    S = P.shape[-1]
    firsts = []
    for _ in range(n_boot):
        idx = rng.integers(0, S, S)
        Jb = _J(P[..., idx], St[..., idx], lam, w, scale)
        c = _first_crossover(Jb.argmax(1), Jb, m_grid, nrice)
        firsts.append(c[0][0] if c else np.nan)
    firsts = np.array(firsts)
    ok = firsts[~np.isnan(firsts)]
    band = {"p10": float(np.percentile(ok, 10)) if len(ok) else None,
            "p90": float(np.percentile(ok, 90)) if len(ok) else None,
            "share_resamples_with_crossover": float(len(ok) / n_boot), "n_boot": n_boot}
    crossovers = [{"rain_mult": c, "from": names[a], "to": names[b], "rice_years_from": nrice[a], "rice_years_to": nrice[b]}
                  for c, a, b in cross]
    i1 = int(np.argmin(np.abs(m_grid - 1.0)))
    yrs = lambda n: f"{n} rice year{'s' if n != 1 else ''}"
    text = (f"At normal rainfall the best rotation has {yrs(nrice[int(win[i1])])} ({names[int(win[i1])]}); at {m_grid[0]:.2f}x it has "
            f"{yrs(nrice[int(win[0])])} ({names[int(win[0])]}) and at {m_grid[-1]:.2f}x {yrs(nrice[int(win[-1])])} ({names[int(win[-1])]}). ")
    if crossovers:
        text += ("The number of rice years changes near " + ", ".join(f"{c['rain_mult']:.2f}x" for c in crossovers[:3])
                 + (" and more" if len(crossovers) > 3 else "") + " of normal rainfall")
        if band["p10"] is not None:
            text += (f" (first change: bootstrap 10th to 90th percentile {band['p10']:.2f}x to {band['p90']:.2f}x, "
                     f"seen in {band['share_resamples_with_crossover']*100:.0f}% of {n_boot} resamples)")
        text += f". {FRAME}."
    else:
        text += f"The number of rice years does not change anywhere in that range. {FRAME}."
    return {"rain_mult": m_grid.tolist(), "winner": [names[i] for i in win], "winner_rice_years": [nrice[i] for i in win],
            "J": Jm.tolist(), "candidates": names,
            "mean_profit": mp.tolist(), "baseline_id": opt.BASELINE_ID,
            "baseline_mean_profit": mp[:, iA].tolist(), "delta_vs_baseline": delta_win, "crossovers": crossovers, "band": band, "text": text,
            "badge": "modeled", "n_candidates": len(cands)}


def _rice_share(plan_id_str):
    return plan_id_str.split("-").count("rice") / 4.0


def _boundary_line(J, rice_major, irr_levels):
    """J [I,M,R]. For each rainfall column, the irrigation supply (mm) at which the best rice-majority rotation
    starts to beat the best other rotation, by linear interpolation between tested levels.
    NaN = rice-majority never wins in the tested range; the lowest level = it already wins there."""
    d = J[:, :, rice_major].max(-1) - J[:, :, ~rice_major].max(-1)        # [I,M] > 0 where rice-majority wins
    irr = np.asarray(irr_levels, float)
    out = np.full(d.shape[1], np.nan)
    for j in range(d.shape[1]):
        col = d[:, j]
        if col[0] >= 0:
            out[j] = irr[0]
            continue
        for i in range(1, len(irr)):
            if col[i] >= 0:
                t = -col[i - 1] / (col[i] - col[i - 1]) if col[i] != col[i - 1] else 0.0
                out[j] = irr[i - 1] + t * (irr[i] - irr[i - 1])
                break
    return out


def decision_grid(scenset, awc, params, scale, cands, irr_levels, rain_levels=GRID_M, n_boot=200, seed=42):
    """Tipping-point map (v3 section 8.1): x = season rainfall multiplier, y = available irrigation supply,
    cell = winning rotation at the current lam and w. The boundary line is where rice-majority rotations
    (2 or more rice years) start to win; its 10th to 90th percentile band comes from n_boot resamples of the scenarios."""
    lam, w, pm = params["lam"], params["w"], params.get("price_mult", 1.0)
    names = [opt.plan_id(p) for p in cands]
    iA = names.index(opt.plan_id(opt.REF[opt.BASELINE_ID]))
    scs = [scenset.derive(rain_mult=m) for m in rain_levels]
    P, W = [], []
    for irr in irr_levels:
        opt.prefetch_multi(cands, scs, awc, irr)           # one batched call per irrigation level
        pr, wr = zip(*[_stack(cands, sc_, awc, irr, pm) for sc_ in scs])
        P.append(np.stack(pr)); W.append(np.stack(wr))
    P, W = np.stack(P), np.stack(W)                        # [I,M,R,S]
    J = _J(P, W, lam, w, scale)                            # [I,M,R]
    k = J.argmax(-1)
    win = [[names[k[i, j]] for j in range(len(rain_levels))] for i in range(len(irr_levels))]
    mp = P.mean(-1)
    dlt = [[float(mp[i, j, k[i, j]] - mp[i, j, iA]) for j in range(len(rain_levels))] for i in range(len(irr_levels))]
    rice_years = [[int(round(4 * _rice_share(win[i][j]))) for j in range(len(rain_levels))] for i in range(len(irr_levels))]
    rice_major = np.array([_rice_share(n) >= 0.5 for n in names])
    band = {"p10": None, "p90": None, "n_boot": 0, "share_with_boundary": None}
    if rice_major.any() and (~rice_major).any():
        line = _boundary_line(J, rice_major, irr_levels)
        rng = np.random.default_rng(seed)
        S = P.shape[-1]
        lines = np.full((n_boot, len(rain_levels)), np.nan)
        for b in range(n_boot):
            idx = rng.integers(0, S, S)
            lines[b] = _boundary_line(_J(P[..., idx], W[..., idx], lam, w, scale), rice_major, irr_levels)
        top = float(np.max(irr_levels))
        filled = np.where(np.isnan(lines), top * 1.0001, lines)     # "never in range" sorts above the top level
        p10, p90 = np.percentile(filled, 10, axis=0), np.percentile(filled, 90, axis=0)
        band = {"p10": [None if v > top else float(v) for v in p10], "p90": [None if v > top else float(v) for v in p90],
                "n_boot": n_boot, "share_with_boundary": [float(x) for x in (~np.isnan(lines)).mean(0)]}
    else:
        line = np.full(len(rain_levels), np.nan)
    thr = [None if np.isnan(v) else float(v) for v in line]
    j1 = int(np.argmin(np.abs(np.asarray(rain_levels) - 1.0)))
    lo, hi = float(np.min(irr_levels)), float(np.max(irr_levels))
    if thr[j1] is None:
        text = (f"At normal rainfall ({rain_levels[j1]:.2f}x) no tested water supply up to {hi:.0f} mm a season makes a rotation with "
                f"two or more rice years win; plans with less rice win.")
    elif thr[j1] <= lo:
        text = f"At normal rainfall, rotations with two or more rice years already win at {lo:.0f} mm of irrigation supply a season."
    else:
        text = (f"At normal rainfall, rotations with two or more rice years win once the irrigation supply reaches about {thr[j1]:.0f} mm a season")
        if band["p10"] is not None and band["p10"][j1] is not None and band["p90"][j1] is not None:
            text += f" (10th to 90th percentile {band['p10'][j1]:.0f} to {band['p90'][j1]:.0f} mm over {n_boot} resamples)"
        text += "; below that the model moves land out of rice."
    dry = [j for j in range(len(rain_levels)) if rain_levels[j] < 1.0 and thr[j] is not None and thr[j1] is not None and thr[j] > thr[j1] + 1]
    if dry:
        j0 = dry[0]
        text += f" In a monsoon at {rain_levels[j0]*100:.0f}% of normal the switch point rises to about {thr[j0]:.0f} mm."
    text += f" Winners compared among {len(cands)} candidate rotations. {FRAME}."
    return {"rain_mult": list(map(float, rain_levels)), "irrigation_mm": list(map(float, irr_levels)),
            "winner": win, "rice_years": rice_years, "baseline_id": opt.BASELINE_ID, "delta_mean_profit_vs_baseline": dlt,
            "rice_shift_threshold_mm": thr, "boundary_band": band, "text": text, "badge": "modeled"}


HEAT_DT = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]


def heat_curve(scenset, awc, irr, params, scale, plans, dts=HEAT_DT):
    """J and profit versus a uniform warming of +0 to +3 degC (v3 section 8.2, optional chart). Warming raises ET0
    by the documented scaling and adds hot days at flowering (heat penalty)."""
    out = late_monsoon_curve(scenset, awc, irr, params, scale, plans, days=dts, kind="heat")
    out["dT"] = out.pop("days")
    return out


def late_monsoon_curve(scenset, awc, irr, params, scale, plans, days=LATE_DAYS, kind="onset"):
    lam, w, pm = params["lam"], params["w"], params.get("price_mult", 1.0)
    out = {"days": list(days), "rotations": {}}
    P, St = [], []
    scs = [scenset.derive(shift_days=n) if kind == "onset" else scenset.derive(dT=n) for n in days]
    opt.prefetch_multi(plans, scs, awc, irr)
    for sc_ in scs:
        p, s = _stack(plans, sc_, awc, irr, pm)
        P.append(p); St.append(s)
    P, St = np.stack(P), np.stack(St)
    Jm = _J(P, St, lam, w, scale)
    names0 = [opt.plan_id(p) for p in plans]
    bid = opt.plan_id(opt.REF[opt.BASELINE_ID])
    iA = names0.index(bid) if bid in names0 else None
    out["baseline_id"] = opt.BASELINE_ID
    for r, pl in enumerate(plans):
        k = max(1, int(np.ceil(0.1 * P.shape[-1])))
        out["rotations"][opt.plan_id(pl)] = {"mean_profit": P[:, r].mean(-1).tolist(),
            "worst10_profit": np.sort(P[:, r], -1)[..., :k].mean(-1).tolist(), "irrigation_mm": St[:, r].mean(-1).tolist(),
            "J": Jm[:, r].tolist(),
            "delta_mean_profit_vs_baseline": None if iA is None else (P[:, r].mean(-1) - P[:, iA].mean(-1)).tolist()}
    names = [opt.plan_id(p) for p in plans]
    out["winner"] = [names[i] for i in Jm.argmax(1)]
    first, last = names[int(Jm[0].argmax())], names[int(Jm[-1].argmax())]
    d = out["rotations"][first]
    tail = (f"the best rotation stays {first}" if first == last else f"the best rotation goes from {first} to {last}")
    lead = (f"A monsoon onset {days[-1]} days later (the rain of those first days is lost and sowing moves with it)"
            if kind == "onset" else f"Warming of +{days[-1]:g} degC (more crop water demand and more hot days at flowering)")
    out["text"] = (f"{lead} changes {first}'s mean profit by "
                   f"{d['mean_profit'][-1] - d['mean_profit'][0]:+,.0f} Rs/acre and its worst-10% profit by "
                   f"{d['worst10_profit'][-1] - d['worst10_profit'][0]:+,.0f} Rs/acre; {tail}. {FRAME}.")
    out["badge"] = "modeled"
    return out


def evpi(scenset, params, scale, cands, vary: str, values, base_awc, base_irr, test_cost_per_acre, cost_badge, label):
    """EVPI = mean_k[max_r J(r,a_k)] - max_r mean_k[J(r,a_k)], uniform weights on `values`."""
    lam, w, pm = params["lam"], params["w"], params.get("price_mult", 1.0)
    J = []
    for v in values:
        awc, irr = (v, base_irr) if vary == "awc" else (base_awc, v)
        p, s = _stack(cands, scenset, awc, irr, pm)
        J.append(_J(p, s, lam, w, scale))
    J = np.stack(J)                                   # [K,R]
    perfect = float(J.max(1).mean())
    now = float(J.mean(0).max())
    val = max(0.0, perfect - now)
    names = [opt.plan_id(p) for p in cands]
    return {"value": val, "perfect_info_value": perfect, "no_info_value": now, "values": list(map(float, values)),
            "best_without_info": names[int(J.mean(0).argmax())],
            "best_by_value": [names[i] for i in J.argmax(1)],
            "test_cost": float(test_cost_per_acre), "test_cost_badge": cost_badge,
            "worth_measuring": None if cost_badge == "placeholder" else bool(val > test_cost_per_acre),
            "changes_plan": bool(len(set(int(i) for i in J.argmax(1))) > 1),
            "label": label, "badge": "modeled", "n_candidates": len(cands),
            "units": "Rs/acre over the 4-year plan, same units as J"}


def _evpi_tail(e, what):
    if e["worth_measuring"] is None:
        return (f"We have no sourced price for {what} yet (placeholder), so compare this number with a real quote: "
                f"measuring is worth at most {e['value']:,.0f} Rs/acre.")
    return (f"{what.capitalize()} costs about {e['test_cost']:,.0f} Rs/acre ({e['test_cost_badge']}): "
            + ("the value is above that, so measuring could pay." if e["worth_measuring"] else "the value is not above that, so measuring is unlikely to pay for itself."))


def evpi_text_awc(e):
    lead = ("Your best plan is the same across your likely soil range; a soil test probably won't change it. "
            if not e["changes_plan"] else "Your best plan changes across your likely soil range, so knowing your soil could change the plan. ")
    return (lead + f"Expected value of perfect information on soil water capacity: {e['value']:,.0f} Rs/acre over 4 years "
            f"(uniform over {len(e['values'])} values from {min(e['values']):.0f} to {max(e['values']):.0f} mm/m). "
            + _evpi_tail(e, "a soil test") + " This is an upper bound on any real test's value.")


SUPPLY_WORDS = {"canal_and_well": "canal and well supply", "canal": "canal supply", "borewell": "borewell supply",
                "tank": "tank supply"}


def evpi_text_irr(e, water_source=None):
    what = SUPPLY_WORDS.get(water_source, "borewell, tank or canal supply")
    lead = (f"Measuring your {what} could change the best plan: " if e["changes_plan"]
            else "Your best plan is the same across the likely range of water supply: ")
    return (lead + f"worth up to {e['value']:,.0f} Rs/acre over 4 years (expected value of perfect information, "
            f"uniform over {len(e['values'])} values from {min(e['values']):.0f} to {max(e['values']):.0f} mm a season). "
            + _evpi_tail(e, "a water-supply measurement") + " This is an upper bound on any real measurement's value.")


UL_LEVELS = np.array([0.5, 0.7, 0.85, 1.0, 1.1, 1.2, 1.3])
UL_N_SCEN = 150


def _short(pid):
    return pid.replace("pigeonpea", "pigeon pea")


def upstream_local_grid(scenset, awc, irr, params, scale, cands, levels=UL_LEVELS, n_scen=UL_N_SCEN):
    """Upstream rain multiplier (x, canal proxy) vs local rain multiplier (y, wells + crop rain); cell = winning
    rotation among the candidates. One batched simulation for all cells (first n_scen bootstrap plans)."""
    if "upstream_season_rain" not in scenset.scen:
        return {"available": False, "reason": "no upstream rain data (engine.fetch_upstream not available)", "badge": "modeled"}
    lam, w, pm = params["lam"], params["w"], params.get("price_mult", 1.0)
    ss = scenset.subset(n_scen) if scenset.n > n_scen else scenset
    names = [opt.plan_id(p) for p in cands]
    iA = names.index(opt.plan_id(opt.REF[opt.BASELINE_ID]))
    scs = [[ss.derive(rain_mult=loc, upstream_mult=up) for up in levels] for loc in levels]
    opt.prefetch_multi(cands, [c for row in scs for c in row], awc, irr)
    win, dlt = [], []
    for i in range(len(levels)):
        wr, dr = [], []
        for j in range(len(levels)):
            p, st = _stack(cands, scs[i][j], awc, irr, pm)
            k = int(_J(p, st, lam, w, scale).argmax())
            wr.append(names[k]); dr.append(float(p[k].mean() - p[iA].mean()))
        win.append(wr); dlt.append(dr)
    L = [float(x) for x in levels]
    i1 = int(np.argmin(np.abs(levels - 1.0)))
    base = win[i1][i1]
    cells = [c for r in win for c in r]
    n_rice = sum(1 for c in cells if _rice_share(c) >= 0.5)
    low_up, low_loc = win[i1][0], win[0][i1]
    def move(x, what):
        return f"stays {_short(base)}" if x == base else f"changes to {_short(x)}"
    text = (f"At normal upstream and local rain ({levels[i1]:.2f}x each) the winner is {_short(base)}. "
            f"With upstream rain at {levels[0]:.2f}x and local rain normal it {move(low_up, 'u')}; "
            f"with local rain at {levels[0]:.2f}x and upstream normal it {move(low_loc, 'l')}. "
            f"Rice-majority rotations win in {n_rice} of {len(cells)} cells; {len(set(cells))} different rotations win somewhere. "
            f"Upstream rain stands in for canal releases (a proxy, not a reservoir model). {FRAME}.")
    return {"available": True, "upstream_mult": L, "local_mult": L, "winner": win, "baseline_id": opt.BASELINE_ID,
            "delta_mean_profit_vs_baseline": dlt, "text": text, "n_scenarios": ss.n, "n_candidates": len(cands), "badge": "modeled"}
