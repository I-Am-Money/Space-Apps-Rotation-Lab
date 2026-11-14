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


def candidate_plans(df, k: int = 10, extra=()):
    plans, seen = [], set()
    def add(p):
        i = opt.plan_id(p)
        if i not in seen:
            seen.add(i); plans.append(list(p))
    for p in opt.REF.values():
        add(p)
    for p in extra:
        add(p)
    for c in opt.CROPS:
        add([c] * 4)
    for _, r in df.sort_values("J", ascending=False).head(k).iterrows():
        add(r["plan"])
    return plans


def _stack(plans, scenset, awc, irr, price_mult):
    opt.prefetch(plans, scenset, awc, irr)
    A = [opt.rotation_arrays(p, scenset, awc, irr, price_mult) for p in plans]
    return np.stack([a["profit"] for a in A]), np.stack([a["stress"] for a in A])


def _J(profit, stress, lam, w, scale):
    """profit, stress [..., S] -> J [...]. worst10 via partition."""
    S = profit.shape[-1]
    k = max(1, int(np.ceil(0.1 * S)))
    worst = np.sort(profit, axis=-1)[..., :k].mean(-1)
    return opt.objective(profit.mean(-1), worst, stress.mean(-1), lam, w, scale)


def _first_crossover(winners, Jm, ms):
    """winners [M] index; Jm [M,R]. Returns list of (m_cross, from, to) via linear interpolation."""
    out = []
    for i in range(1, len(winners)):
        a, b = winners[i - 1], winners[i]
        if a != b:
            d0 = Jm[i - 1, a] - Jm[i - 1, b]
            d1 = Jm[i, a] - Jm[i, b]
            t = d0 / (d0 - d1) if abs(d0 - d1) > 1e-12 else 0.5
            out.append((float(ms[i - 1] + np.clip(t, 0, 1) * (ms[i] - ms[i - 1])), int(a), int(b)))
    return out


def rainfall_crossover(scenset, awc, irr, params, scale, cands, n_boot=200, seed=42, m_grid=M_GRID):
    lam, w, pm = params["lam"], params["w"], params.get("price_mult", 1.0)
    P, St = [], []
    for m in m_grid:
        p, s = _stack(cands, scenset.derive(rain_mult=m), awc, irr, pm)
        P.append(p); St.append(s)
    P, St = np.stack(P), np.stack(St)                      # [M,R,S]
    Jm = _J(P, St, lam, w, scale)                          # [M,R]
    win = Jm.argmax(1)
    names = [opt.plan_id(p) for p in cands]
    cross = _first_crossover(win, Jm, m_grid)
    rng = np.random.default_rng(seed)
    S = P.shape[-1]
    firsts = []
    for _ in range(n_boot):
        idx = rng.integers(0, S, S)
        Jb = _J(P[..., idx], St[..., idx], lam, w, scale)
        c = _first_crossover(Jb.argmax(1), Jb, m_grid)
        firsts.append(c[0][0] if c else np.nan)
    firsts = np.array(firsts)
    ok = firsts[~np.isnan(firsts)]
    band = {"p10": float(np.percentile(ok, 10)) if len(ok) else None,
            "p90": float(np.percentile(ok, 90)) if len(ok) else None,
            "share_resamples_with_crossover": float(len(ok) / n_boot), "n_boot": n_boot}
    crossovers = [{"rain_mult": c, "from": names[a], "to": names[b]} for c, a, b in cross]
    if crossovers:
        c0 = crossovers[0]
        text = (f"As seasonal rainfall rises from {m_grid[0]:.2f}x, the best rotation switches from {c0['from']} to {c0['to']} "
                f"near {c0['rain_mult']:.2f}x normal")
        if band["p10"] is not None:
            text += f" (bootstrap 10th-90th percentile {band['p10']:.2f}x to {band['p90']:.2f}x, switch seen in {band['share_resamples_with_crossover']*100:.0f}% of {n_boot} resamples)"
        text += f". {FRAME}."
    else:
        text = f"The same rotation ({names[int(win[0])]}) wins across the whole rainfall range {m_grid[0]:.2f}x to {m_grid[-1]:.2f}x. {FRAME}."
    return {"rain_mult": m_grid.tolist(), "winner": [names[i] for i in win], "J": Jm.tolist(), "candidates": names,
            "mean_profit": P.mean(-1).tolist(), "crossovers": crossovers, "band": band, "text": text,
            "badge": "modeled", "n_candidates": len(cands)}


def _rice_share(plan_id_str):
    return plan_id_str.split("-").count("rice") / 4.0


def decision_grid(scenset, awc, params, scale, cands, irr_levels, rain_levels=GRID_M):
    lam, w, pm = params["lam"], params["w"], params.get("price_mult", 1.0)
    names = [opt.plan_id(p) for p in cands]
    win = [[None] * len(rain_levels) for _ in irr_levels]
    for j, m in enumerate(rain_levels):
        sc = scenset.derive(rain_mult=m)
        for i, irr in enumerate(irr_levels):
            p, s = _stack(cands, sc, awc, irr, pm)
            win[i][j] = names[int(_J(p, s, lam, w, scale).argmax())]
    # water level at which the winner turns rice-heavy (>= 50% rice years), per rainfall column
    thr = []
    for j in range(len(rain_levels)):
        t = None
        for i in range(len(irr_levels)):
            if _rice_share(win[i][j]) >= 0.5:
                t = float(irr_levels[i]); break
        thr.append(t)
    j1 = int(np.argmin(np.abs(np.asarray(rain_levels) - 1.0)))
    if thr[j1] is None:
        text = (f"At normal rainfall ({rain_levels[j1]:.2f}x) no tested irrigation level up to {irr_levels[-1]:.0f} mm makes a rice-majority rotation win; millet-heavy plans win.")
    elif thr[j1] <= irr_levels[0]:
        text = f"At normal rainfall rice-majority rotations already win at {irr_levels[0]:.0f} mm available irrigation."
    else:
        text = (f"At normal rainfall, rice-majority rotations win once available irrigation reaches about {thr[j1]:.0f} mm per season; "
                f"below that the model shifts land from rice to millets or pigeon pea.")
    text += f" Winners compared among {len(cands)} candidate rotations. {FRAME}."
    return {"rain_mult": list(map(float, rain_levels)), "irrigation_mm": list(map(float, irr_levels)),
            "winner": win, "rice_shift_threshold_mm": thr, "text": text, "badge": "modeled"}


def late_monsoon_curve(scenset, awc, irr, params, scale, plans, days=LATE_DAYS):
    lam, w, pm = params["lam"], params["w"], params.get("price_mult", 1.0)
    out = {"days": list(days), "rotations": {}}
    P, St = [], []
    for n in days:
        p, s = _stack(plans, scenset.derive(shift_days=n), awc, irr, pm)
        P.append(p); St.append(s)
    P, St = np.stack(P), np.stack(St)
    Jm = _J(P, St, lam, w, scale)
    for r, pl in enumerate(plans):
        k = max(1, int(np.ceil(0.1 * P.shape[-1])))
        out["rotations"][opt.plan_id(pl)] = {"mean_profit": P[:, r].mean(-1).tolist(),
            "worst10_profit": np.sort(P[:, r], -1)[..., :k].mean(-1).tolist(), "water_stress_mm": St[:, r].mean(-1).tolist(),
            "J": Jm[:, r].tolist()}
    names = [opt.plan_id(p) for p in plans]
    out["winner"] = [names[i] for i in Jm.argmax(1)]
    first, last = names[int(Jm[0].argmax())], names[int(Jm[-1].argmax())]
    d = out["rotations"][first]
    tail = (f"the best rotation stays {first}" if first == last else f"the best rotation goes from {first} to {last}")
    out["text"] = (f"Delaying Jun-Jul rain by {days[-1]} days (total conserved) changes {first}'s mean profit by "
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
            "test_cost": float(test_cost_per_acre), "test_cost_badge": cost_badge, "worth_measuring": bool(val > test_cost_per_acre),
            "label": label, "badge": "modeled", "n_candidates": len(cands),
            "units": "Rs/acre over the 4-year plan, same units as J"}


def evpi_text_awc(e):
    return (f"Expected value of perfect information on soil water capacity: {e['value']:,.0f} Rs/acre over 4 years "
            f"(uniform over {len(e['values'])} values from {min(e['values']):.0f} to {max(e['values']):.0f} mm/m). "
            f"Soil test cost {e['test_cost']:,.0f} Rs/acre ({e['test_cost_badge']}): "
            + ("above the test cost, so measuring could pay." if e["worth_measuring"] else "not above the test cost, so measuring is unlikely to change the decision enough to pay.")
            + " Upper bound on any real test's value.")


def evpi_text_irr(e):
    return ("Is it worth measuring your borewell or tank capacity before deciding? "
            f"Expected value of perfect information on available irrigation water: {e['value']:,.0f} Rs/acre over 4 years "
            f"(uniform over {len(e['values'])} values from {min(e['values']):.0f} to {max(e['values']):.0f} mm). "
            f"Measurement cost {e['test_cost']:,.0f} Rs/acre ({e['test_cost_badge']}): "
            + ("above it, so measuring could pay." if e["worth_measuring"] else "not above it, so measuring is unlikely to pay for itself."))
