# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""What to measure next: expected value of perfect information, EVPI (Build Spec v4, R19). Owner: Feature 3.

For one uncertain input, take k equally weighted plausible values a_1..a_k and score the rotations at each:

    EVPI = mean_k[ max_r J(r, a_k) ] - max_r mean_k[ J(r, a_k) ]            (currency per hectare, then per acre)

J is the farmer's profit-and-risk score, (1 - bad_year) * mean profit + bad_year * worst-10% profit. EVPI is an
upper bound on what a real test is worth and is never negative. Not EVSI. It is judged on the best rotations at the
base inputs plus the current plan, to keep a new pin fast.

Inputs covered: water supply (irrigated farms), soil water capacity, organic matter. Organic matter needs a verified
relation between organic matter and water-holding capacity (awc_mm_per_m_per_om_pct in recommend.yaml, empty for now);
until it is filled the row says so and its EVPI is NOT computed from a guess.
"""
from __future__ import annotations

import copy

import numpy as np

from engine import economics, optimize as opt
from engine.optimize import _f3_read, _F3_YAML  # noqa: F401  (config path shared with optimize)

import functools
import yaml


@functools.lru_cache(maxsize=2)
def _read(version) -> dict:
    return yaml.safe_load(_F3_YAML.read_text())["evpi"]


def params() -> dict:
    return _read(_F3_YAML.stat().st_mtime_ns)


def evpi_value(J) -> float:
    """EVPI from a matrix J[k, r] (k plausible values by r rotations). Never negative."""
    J = np.asarray(J, dtype=float)
    return max(0.0, float(J.max(axis=1).mean() - J.mean(axis=0).max()))


def _g(obj, key, default=None):
    """Read a field from an object or a dict (Feature 2 accepts both)."""
    if obj is None:
        return default
    v = obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)
    return default if v is None else v


def _slider(s, name, default):
    v = s.get(name) if isinstance(s, dict) else getattr(s, name, None)
    return default if v is None else v


def _with_awc(site, awc: float):
    s2 = copy.copy(site)
    if isinstance(site, dict):
        s2["soil"] = {**site["soil"], "awc_mm_per_m": float(awc)}
    else:
        s2.soil = copy.copy(site.soil)
        if isinstance(site.soil, dict):
            s2.soil = {**site.soil, "awc_mm_per_m": float(awc)}
        else:
            s2.soil.awc_mm_per_m = float(awc)
    return s2


def _with_water(inputs, mult: float):
    i2 = copy.copy(inputs)
    w0 = _g(inputs, "water")
    if isinstance(w0, dict):
        w = {**w0, **{f: float(w0[f]) * mult for f in ("normal_mm", "dry_mm") if w0.get(f) is not None}}
    else:
        w = copy.copy(w0)
        for f in ("normal_mm", "dry_mm"):
            v = getattr(w, f, None)
            if v is not None:
                setattr(w, f, float(v) * mult)
    if isinstance(i2, dict):
        i2["water"] = w
    else:
        i2.water = w
    return i2


def _row(name, question, j, evpi_ha, ha_per_acre, plans, note, computed=True, test_cost=None, applicable=True):
    could = bool(computed and applicable and len({int(x) for x in np.argmax(j, axis=1)}) > 1) if j is not None else False
    row = {"input": name, "question": question, "evpi_per_ha": evpi_ha, "evpi_per_acre": evpi_ha * ha_per_acre,
           "could_change_answer": could, "computed": computed, "applicable": applicable, "badge": "estimated" if computed else "assumption",
           "note": note, "worth_it": None, "test_cost_per_ha": test_cost}
    if computed and test_cost is not None:
        row["worth_it"] = bool(evpi_ha > test_cost)
    row["plain"] = plain_words(row)
    return row


def plain_words(row: dict) -> str:
    if not row.get("applicable", True):
        return row["note"]
    if not row.get("computed", True):
        return row["note"]
    if row["could_change_answer"]:
        base = "Could change your answer: the best rotation is not the same across the plausible range."
    else:
        base = "Probably won't change your answer: the same rotation wins across the plausible range."
    if row.get("worth_it") is True:
        base += " Knowing it exactly is worth more than the test you entered."
    elif row.get("worth_it") is False:
        base += " Knowing it exactly is worth less than the test you entered."
    return base


def question_value(site, inputs, sliders, crops=None, simulate=None, scenarios=None, test_costs: dict | None = None) -> list:
    """Ranked list (largest EVPI first) of what to measure next. Each row: input, question, evpi_per_acre,
    could_change_answer, plain, note, computed, applicable, badge, worth_it. See api.QuestionValue."""
    from engine import candidates as cand
    p, f3 = params(), opt._f3_params()
    frac = float(f3["worst_tail"]["value"])
    lam = float(_slider(sliders, "bad_year", 0.3))
    sim_fn, stand_in = (simulate, simulate is opt._stand_in_simulate) if simulate is not None else opt._default_simulate()
    many_fn = opt._default_many() if (simulate is None and not stand_in) else None
    plan = [[c] if isinstance(c, str) else list(c) for c in _g(inputs, "current_plan")]
    current_crops = {yr[0] for yr in plan}
    pool = sorted(set(crops if crops is not None else cand.candidates(site, inputs)) | current_crops)
    econ, needed, _ = opt.prepare_economics(site, inputs, pool, current_crops)
    if needed:
        return [{"input": "prices", "question": "Enter your price and cost first.", "evpi_per_acre": 0.0, "evpi_per_ha": 0.0,
                 "could_change_answer": False, "computed": False, "applicable": False, "badge": "assumption",
                 "note": "input needed: " + ", ".join(f"{n['field']} for {n['crop']}" for n in needed), "worth_it": None,
                 "plain": "Input needed before value of information can be judged."}]
    pool = [c for c in pool if c in econ]
    overrides = _g(inputs, "crop_overrides", {}) or {}
    cover_cost = float((overrides.get("cover_crop") or {}).get("cost") or 0.0)
    rots = opt.enumerate_rotations(pool, allow_cover=bool(cover_cost), current_plan=plan)
    history = _g(inputs, "history")
    base = opt.score_rotations(rots, site, inputs, sim_fn, scenarios, econ, history, frac, cover_cost, many_fn=many_fn)
    cur_i = next((i for i, r in enumerate(base) if r["crops"] == plan and not any(r["cover_crops"])), None)
    if cur_i is None:
        return [{"input": "plan", "question": "Your current plan could not be simulated.", "evpi_per_acre": 0.0, "evpi_per_ha": 0.0,
                 "could_change_answer": False, "computed": False, "applicable": False, "badge": "assumption",
                 "note": "Check the yield for each crop in your current plan.", "worth_it": None,
                 "plain": "Value of information cannot be judged until your current plan can be simulated."}]
    pr0 = np.array([(1 - lam) * r["mean_profit"] + lam * r["worst10_profit"] for r in base])
    top = list(dict.fromkeys(np.argsort(-pr0, kind="stable")[: int(p["top_rotations"]["value"])].tolist() + [cur_i]))
    sub = [{"crops": base[i]["crops"], "cover_crops": base[i]["cover_crops"]} for i in top]
    k = int(p["samples"]["value"])
    ha_per_acre = economics._u("ha_per_acre")
    tc = {**{n: (v or {}).get("value") for n, v in p["test_cost_per_ha"].items()}, **(test_costs or {})}

    def J_matrix(make_site_inputs):
        rows = []
        for s_k, i_k in make_site_inputs:
            res = opt.score_rotations(sub, s_k, i_k, sim_fn, scenarios, econ, history, frac, cover_cost, many_fn=many_fn)
            by = {(repr(r["crops"]), tuple(r["cover_crops"])): (1 - lam) * r["mean_profit"] + lam * r["worst10_profit"] for r in res}
            rows.append([by.get((repr(r["crops"]), tuple(r["cover_crops"])), -np.inf) for r in sub])
        return np.array(rows)

    out = []
    # soil water capacity
    soil = _g(site, "soil")
    awc = _g(soil, "awc_mm_per_m")
    rel = float(p["awc_relative_range"]["value"])
    if awc:
        mults = np.linspace(1 - rel, 1 + rel, k)
        j = J_matrix([(_with_awc(site, awc * m), inputs) for m in mults])
        out.append(_row("soil_water", "What is your soil's water-holding capacity?", j, evpi_value(j), ha_per_acre, sub,
                        f"Judged over {awc * (1 - rel):.0f} to {awc * (1 + rel):.0f} mm of water per metre of soil.",
                        test_cost=tc.get("soil_water")))
    else:
        out.append(_row("soil_water", "What is your soil's water-holding capacity?", None, 0.0, ha_per_acre, sub,
                        "No soil water capacity is available for this site yet.", computed=False))
    # water supply
    w = _g(inputs, "water")
    if w is not None and _g(w, "mode", "rain") == "irrigated" and _g(w, "normal_mm"):
        wr = float(p["water_relative_range"]["value"])
        mults = np.linspace(1 - wr, 1 + wr, k)
        j = J_matrix([(site, _with_water(inputs, m)) for m in mults])
        out.append(_row("water_supply", "How much irrigation water can you count on?", j, evpi_value(j), ha_per_acre, sub,
                        f"Judged over {_g(w, 'normal_mm') * (1 - wr):.0f} to {_g(w, 'normal_mm') * (1 + wr):.0f} mm in a normal year.",
                        test_cost=tc.get("water_supply")))
    else:
        out.append(_row("water_supply", "How much irrigation water can you count on?", None, 0.0, ha_per_acre, sub,
                        "You farm on rain only, so your water supply is the rain at your site.", computed=False, applicable=False))
    # organic matter
    coef = (p["awc_mm_per_m_per_om_pct"] or {}).get("value")
    om = _g(soil, "organic_matter_pct")
    if coef is None or om is None or not awc:
        out.append(_row("organic_matter", "What is your soil's organic matter?", None, 0.0, ha_per_acre, sub,
                        "Not judged yet: this needs a verified link between organic matter and water-holding capacity (team to verify).",
                        computed=False))
    else:
        d = float(p["organic_matter_range_pct"]["value"])
        pts = np.linspace(-d, d, k)
        j = J_matrix([(_with_awc(site, awc + coef * x), inputs) for x in pts])
        out.append(_row("organic_matter", "What is your soil's organic matter?", j, evpi_value(j), ha_per_acre, sub,
                        f"Judged over {om - d:.1f} to {om + d:.1f} percent.", test_cost=tc.get("organic_matter")))
    out.sort(key=lambda r: (not r["computed"], -r["evpi_per_acre"]))
    return out
