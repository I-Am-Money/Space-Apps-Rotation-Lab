"""Mock of engine/api.py for UI development. Mirrors the contract signatures.

Everything returned here is PLACEHOLDER data produced by a toy model so the UI can be built
and screenshotted before the real engine exists. Never present these numbers as results.
"""
from __future__ import annotations

import itertools
from functools import lru_cache

import numpy as np
import pandas as pd

IS_MOCK = True
CROPS = ["rice", "jowar", "bajra", "pigeonpea"]
CROP_LABEL = {"rice": "Rice", "jowar": "Jowar", "bajra": "Bajra", "pigeonpea": "Pigeon pea"}
REF = {
    "A": ["rice"] * 4,
    "B": ["rice", "jowar", "rice", "jowar"],
    "C": ["rice", "pigeonpea", "jowar", "rice"],
}
S = 40
_rng = np.random.default_rng(42)
_RAIN = np.clip(_rng.lognormal(0.0, 0.26, size=(S, 4)), 0.45, 1.7)
LABELS = [f"{1981 + s}-{1984 + s}" for s in range(S)]
# crop: (water need mm, revenue, cost, rain use factor)
_P = {
    "rice": (1100.0, 48000.0, 27000.0),
    "jowar": (450.0, 24000.0, 9000.0),
    "bajra": (400.0, 21000.0, 8000.0),
    "pigeonpea": (500.0, 30000.0, 12000.0),
}


def _plan(rid_or_plan, params=None):
    if isinstance(rid_or_plan, (list, tuple)):
        return list(rid_or_plan)
    if rid_or_plan == "current":
        return list((params or {}).get("current_rotation") or REF["A"])
    if rid_or_plan in REF:
        return list(REF[rid_or_plan])
    return rid_or_plan.split("-")


def _label(plan):
    return ", ".join(CROP_LABEL[c] for c in plan)


@lru_cache(maxsize=4096)
def _sim(plan: tuple, rm: float, irr: float, price: float, awc: float):
    profit = np.zeros((S, 4))
    stress = np.zeros((S, 4))
    irr_used = np.zeros((S, 4))
    rain = np.zeros((S, 4))
    ykg = np.zeros((S, 4))
    prev = None
    for y, crop in enumerate(plan):
        need, rev, cost = _P[crop]
        r = _RAIN[:, y] * rm
        awc_f = 0.9 + 0.2 * min(awc, 200) / 150.0
        if crop == "rice":
            rain_y = 600.0 * r
            irr_y = irr * np.sqrt(np.clip(r, 0.05, None))
            supply = rain_y + irr_y
            used = np.minimum(irr_y, np.clip(need - rain_y, 0, None))
        else:
            rain_y = 600.0 * r * 0.7 * awc_f
            supply = rain_y
            used = np.zeros(S)
        factor = np.clip(supply / need, 0, 1) ** (1.2 if crop == "rice" else 0.8)
        mult = 1.0
        if crop == "rice" and prev == "rice":
            mult = 0.96
        if prev == "pigeonpea":
            mult = 1.06
        if crop in ("jowar", "bajra") and prev in ("jowar", "bajra"):
            mult = 0.97
        profit[:, y] = rev * price * factor * mult - cost
        stress[:, y] = np.clip(need - supply, 0, None)
        irr_used[:, y] = used
        rain[:, y] = rain_y
        ykg[:, y] = {"rice": 5200, "jowar": 2400, "bajra": 2100, "pigeonpea": 1100}[crop] * factor * mult
        prev = crop
    return profit, stress, irr_used, rain, ykg


def _p(params):
    p = params or {}
    awc = p.get("awc_mm_per_m") or 140.0
    return (float(500 if p.get("irrigation_mm") is None else p["irrigation_mm"]), float(p.get("price_mult", 1.0)), float(awc))


def _metrics(plan, params, rm=1.0):
    irr, price, awc = _p(params)
    profit, stress, used, rain, ykg = _sim(tuple(plan), round(rm, 3), irr, price, awc)
    tot = profit.sum(1)
    k = max(1, int(round(0.1 * S)))
    worst = float(np.sort(tot)[:k].mean())
    mean = float(tot.mean())
    st = float(stress.sum(1).mean())
    lam = (params or {}).get("lam", 0.3)
    w = (params or {}).get("w", 0.3)
    J = (1 - lam) * mean + lam * worst - w * st * 20.0
    return dict(plan=list(plan), mean_profit=mean, worst10_profit=worst, water_stress_mm=st,
                irrigation_mm=float(used.sum(1).mean()), total_water_mm=float((rain + used).sum(1).mean()), J=float(J))


def _pid(plan):
    return "-".join(plan)


def get_field_summary():
    rain_m = [8, 5, 9, 18, 40, 105, 165, 160, 150, 85, 20, 6]
    g = np.random.default_rng(1)
    rows = []
    for c, base in zip(CROPS, (2300, 900, 1000, 620)):
        for k, y in enumerate(range(2000, 2020)):
            rows.append(dict(year=y, crop=c, yield_kg_ha=float(base + k * base * 0.012 + g.normal(0, base * 0.08))))
    return dict(
        region=dict(district="TEAM_TO_FILL", lat=17.5, lon=78.5, dev_placeholder=True),
        dev_placeholder=True,
        climate=dict(first_year=1981, last_year=2025, annual_rain_mm=float(sum(rain_m)), monsoon_rain_mm=float(sum(rain_m[5:9])),
                     monsoon_rain_p10_mm=0.0, annual_et0_mm=0.0, badge="placeholder", note="MOCK placeholder values", monthly_rain_mm=rain_m),
        soil=dict(awc_mm_per_m=140.0, badge="placeholder"),
        yield_history=rows,
        farm_records=None,
    )


def list_rotations():
    out = [dict(id=k, plan=v, label=f"{k}: " + ", ".join(v)) for k, v in REF.items()]
    out.append(dict(id="current", plan=None, label="Your current rotation"))
    for combo in itertools.product(CROPS, repeat=4):
        out.append(dict(id=_pid(combo), plan=list(combo), label=", ".join(combo)))
    return out


def compare(rotation_ids, params=None):
    irr, price, awc = _p(params)
    rots = {}
    for rid in rotation_ids:
        plan = _plan(rid, params)
        profit, stress, used, rain, ykg = _sim(tuple(plan), 1.0, irr, price, awc)
        m = _metrics(plan, params)
        res = [float(np.clip(ykg[:, y].mean() / 5200 if plan[y] == "rice" else ykg[:, y].mean() / 2400, 0, 1)) for y in range(4)]
        rots[rid] = dict(plan=plan, profit=profit.sum(1), yield_kg_ha=ykg, yield_mean=ykg.mean(0), profit_year_mean=profit.mean(0),
                         **{k: m[k] for k in ("mean_profit", "worst10_profit", "water_stress_mm", "irrigation_mm", "total_water_mm", "J")},
                         irrigation_canal_mm=float(used.sum(1).mean()) * 0.6, irrigation_well_mm=float(used.sum(1).mean()) * 0.4,
                         residue_index=res, residue_index_note="proxy (mock)",
                         historical_blocks=dict(labels=LABELS, profit=profit.sum(1)), stress_tests=[], badges=dict(profit="placeholder", water="placeholder", yield_="placeholder"))
        weak = int(np.argmin(_RAIN[:, 1]))
        for name, label in (("low canal release year", "low canal release year (source year MOCK)"),
                            ("driest monsoon in year 2", "driest monsoon in year 2 (source year MOCK)"),
                            ("hottest summer in year 3", "hottest summer in year 3 (source year MOCK)")):
            rots[rid]["stress_tests"].append(dict(test=name, label=label, source_year=0, description="mock", profit=float(profit[weak].sum()) * (0.9 if "hot" in name else 1.0),
                                                  yield_kg_ha=list(ykg[weak]), water_stress_mm=float(stress[weak].sum()), irrigation_mm=float(used[weak].sum())))
    if "A" in rots:
        for rid, r in rots.items():
            r["delta_vs_baseline"] = {k: float(r[k] - rots["A"][k]) for k in ("mean_profit", "worst10_profit", "total_water_mm", "irrigation_mm", "water_stress_mm")}
    return dict(baseline_id="A", params=params, badges=dict(profit="placeholder", water="placeholder"), n_scenarios=S, scenario_note="MOCK", fixed_prices_note="MOCK", rotations=rots)


def recommend(params=None):
    rows = []
    for r in list_rotations()[4:]:
        m = _metrics(r["plan"], params)
        rows.append(dict(id=r["id"], plan=r["plan"], **{k: m[k] for k in ("mean_profit", "worst10_profit", "water_stress_mm", "irrigation_mm", "total_water_mm", "J")}))
    df = pd.DataFrame(rows)
    df["rank"] = df.J.rank(ascending=False, method="first").astype(int)
    on = np.zeros(len(df), bool); best = -1e18
    for i in np.argsort(-df.mean_profit.values):
        if df.worst10_profit.values[i] > best:
            on[i] = True; best = df.worst10_profit.values[i]
    df["on_frontier"] = on
    d = df.sort_values("J", ascending=False)
    strategies = {"A": REF["A"], "B": REF["B"], "C": REF["C"], "current": list((params or {}).get("current_rotation") or REF["A"])}
    rep = {}
    for k, plan in strategies.items():
        row = df[df.id == _pid(plan)].iloc[0]
        rep[k] = dict(plan=plan, id=_pid(plan), why=f"MOCK placeholder. Ranked {int(row['rank'])} of 256.",
                      evidence=dict(rank_of_256=int(row["rank"]), mean_profit_rs_acre=float(row.mean_profit), worst10_profit_rs_acre=float(row.worst10_profit),
                                    water_stress_mm=float(row.water_stress_mm), irrigation_mm=float(row.irrigation_mm)),
                      benefits=["MOCK placeholder benefit."], info_gaps=["MOCK: soil water capacity not measured.", "MOCK: irrigation supply is an input."],
                      risks_for_local_review=["MOCK: check seed and market access locally."])
    return dict(params=params, top=d.iloc[0].to_dict(), runner_up=d.iloc[1].to_dict(), metrics=df,
                pareto=df[["id", "mean_profit", "worst10_profit", "water_stress_mm", "irrigation_mm", "total_water_mm", "J", "rank", "on_frontier"]],
                three_strategy_report=rep, badges=dict(profit="placeholder"), n_scenarios=S, scale_rs_per_mm=0.0, objective="MOCK", fixed_prices_note="MOCK")


def tipping_points(params=None):
    irr0, price, awc = _p(params)
    cands = [REF["A"], REF["B"], REF["C"], ["jowar"] * 4, ["rice", "jowar", "jowar", "jowar"], ["pigeonpea", "jowar", "pigeonpea", "jowar"]]
    names = [_pid(c) for c in cands]
    rms = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
    irrs = list(np.linspace(0, max(2 * irr0, 1.0), 9))
    win = [[names[int(np.argmax([_metrics(c, dict(params or {}, irrigation_mm=iv), rm=rm)["mean_profit"] for c in cands]))] for rm in rms] for iv in irrs]
    thr = []
    for j in range(len(rms)):
        t = None
        for i, iv in enumerate(irrs):
            if win[i][j].split("-").count("rice") >= 2:
                t = float(iv); break
        thr.append(t)
    j1 = rms.index(1.0)
    gtext = (f"MOCK: at normal rainfall, rice-majority rotations win once available irrigation reaches about {thr[j1]:.0f} mm per season." if thr[j1] is not None
             else "MOCK: millet-heavy plans win across the tested range.")
    m_grid = np.linspace(0.5, 1.4, 19)
    P = [[_metrics(c, params, rm=float(rm))["mean_profit"] for c in cands] for rm in m_grid]
    P = np.array(P)
    wi = P.argmax(1)
    cross = [dict(rain_mult=float(m_grid[k]), **{"from": names[wi[k - 1]], "to": names[wi[k]]}) for k in range(1, len(m_grid)) if wi[k] != wi[k - 1]]
    xo = dict(rain_mult=list(map(float, m_grid)), winner=[names[i] for i in wi], J=P.tolist(), candidates=names, mean_profit=P.tolist(), crossovers=cross,
              band=dict(p10=(cross[0]["rain_mult"] - 0.08) if cross else None, p90=(cross[0]["rain_mult"] + 0.08) if cross else None, share_resamples_with_crossover=1.0, n_boot=0),
              text="MOCK crossover text.", badge="placeholder", n_candidates=len(cands))
    days = [0, 7, 14, 21]
    lm = dict(days=days, rotations={n: dict(mean_profit=[_metrics(c, params, rm=1 - 0.006 * d)["mean_profit"] for d in days]) for n, c in zip(names[:3], cands[:3])},
              winner=names[:1] * 4, text="MOCK late-monsoon text.", badge="placeholder")
    for row in lm["rotations"].values():
        row["J"] = row["mean_profit"]
    ev = lambda lbl: dict(value=0.0, test_cost=0.0, test_cost_badge="placeholder", worth_measuring=False, label=lbl, badge="placeholder",
                          text="MOCK: value of information is not computed in mock mode.")
    ups = [0.6, 0.8, 1.0, 1.2]
    gul = [[names[int(np.argmax([_metrics(c, params, rm=0.5 * u + 0.5 * l)["mean_profit"] for c in cands]))] for u in ups] for l in ups]
    return dict(params=params, badges={}, n_scenarios=S, frame="MOCK", rainfall_crossover=xo,
                grid_upstream_local=dict(upstream_mult=ups, local_mult=ups, winner=gul, text="MOCK upstream versus local rain text.", badge="placeholder"),
                grid=dict(rain_mult=rms, irrigation_mm=[float(v) for v in irrs], winner=win, rice_shift_threshold_mm=thr, text=gtext, badge="placeholder"),
                late_monsoon=lm, evpi_awc=ev("soil water capacity"), evpi_irrigation=dict(ev("available irrigation water"),
                text="Is it worth measuring your borewell or tank capacity before deciding? MOCK: not computed."))


def hindcast(params=None):
    g = np.random.default_rng(7)
    out = dict(per_crop={}, farm_records=None, badge_observed="placeholder", badge_modeled="placeholder", available=True, note="MOCK series, not ICRISAT data.")
    yrs = list(range(2000, 2020))
    for c, base in zip(CROPS, (2800, 1000, 1100, 650)):
        obs = base + g.normal(0, base * 0.12, 20)
        mod = base + 0.6 * (obs - base) + g.normal(0, base * 0.07, 20)
        ao, am = obs - obs.mean(), mod - mod.mean()
        out["per_crop"][c] = dict(years=yrs, observed=list(obs), modeled=list(mod), observed_anomaly=list(ao), modeled_anomaly=list(am),
                                  pearson_r=float(np.corrcoef(ao, am)[0, 1]), mae_kg_ha=float(np.abs(obs - mod).mean()), mae_anomaly_kg_ha=0.0,
                                  heldout_years=yrs[-6:], heldout_r=float(np.corrcoef(ao[-6:], am[-6:])[0, 1]), n_years=20, bias_kg_ha=0.0,
                                  weak=False, weak_reason=None, text=f"{c}: MOCK")
    out["baseline"] = [dict(strategy=n, id="mock", mean_profit=0.0, worst10_profit=0.0, water_stress_mm=0.0, irrigation_mm=0.0)
                       for n in ("recommended", "always rice (A)", "mean-profit only (lam=0)")]
    return out


def assumptions_table(params=None):
    rows = [("rice water need (mock)", 1100, "900-1400", "mm", "placeholder, team to verify", "placeholder"),
            ("irrigation recharge exponent k (mock)", 0.5, "0.2-1.0", "", "placeholder, team to verify", "placeholder")]
    return pd.DataFrame(rows, columns=["name", "value", "range", "unit", "source", "badge"])


def land_split(alt_id, params=None, acres=None):
    """MOCK: linear mix of the all-rice baseline and the alternative, for 0..acres acres in rice (not engine output)."""
    if acres is None:
        import yaml
        from pathlib import Path
        acres = float(yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "farm.yaml").read_text())["farm"]["acres"])
    a = _metrics(REF["A"], params); b = _metrics(_plan(alt_id, params), params)
    xs = list(range(0, int(acres) + 1))
    mix = lambda k: [(x * a[k] + (acres - x) * b[k]) for x in xs]
    irr = [(x * a["irrigation_mm"] + (acres - x) * b["irrigation_mm"]) * 4.0469 for x in xs]
    return dict(alt_id=alt_id, baseline_id="A", acres_total=acres, acres_rice=xs, total_profit_mean=mix("mean_profit"),
                total_profit_worst10=mix("worst10_profit"), total_irrigation_m3=irr, badge="placeholder")
