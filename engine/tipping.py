# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Feature 2: tipping points (Build Spec v4 R18). Where does the best plan change?

    tipping_points(site, inputs, sliders=None, recommend=None, progress=None, budget_s=None) -> dict

The result has the five parts of api.TippingPoints (rainfall_curve, heat_curve, water_curve, map_2d, bands) plus
plain-English headlines and a method note:

  rainfall_curve   x = rainfall multiplier 0.5 to 1.3, at the farm's own water supply
  heat_curve       x = heat shift 0 to 3 degC
  water_curve      x = water supply (mm a year)
  map_2d           rainfall multiplier x water supply, each cell the winning rotation; the farm's current
                   setting is marked
  bands            10th to 90th percentile range of each tipping point (where the winner changes)

Each curve carries, for the farm's current plan and for every rotation that wins somewhere along it, the average
result and its 10th to 90th percentile band across the 500 bootstrap weather plans.

HOW THE WINNER IS FOUND. At every what-if point this module calls recommend() through engine/api.py inside a
simulate.what_if(...) block, so Feature 3's own picks decide the winner (its headline pick; its highest-profit
pick if it has no headline). The what-if only changes the weather and the water supply that simulate() sees;
the farm's potential yields and planting dates stay as they are. To stay fast, the search away from the farm's
current setting uses a short list of crops (the current plan's, the three picks', then the most profitable
others) and the first 100 of the 500 weather plans; both are settings in simulation.yaml and both are reported
on the result. If recommend() is missing, still a stub, needs a price or cost, or fails, the module says so and
falls back to ranking rotations itself by average profit (or by share of potential yield when a price or cost
is missing).

WHAT THE CURVES SHOW. Average profit per hectare per year = yield x price - cost, using the same prices and
costs Feature 3 uses (the farmer's entries, else the county numbers on the site). When a price, a cost or a
yield number is missing for any plan on a chart, the charts show the share of potential yield instead.

Everything here is a what-if applied to real weather years, not a forecast.
"""
from __future__ import annotations

import copy
import dataclasses
import inspect
import itertools
import time

import numpy as np

from engine import climate_shift as CS
from engine import crops as C
from engine import simulate as SIM
from engine import waterbalance as WB
from engine import yieldmodel as YM

NOTE = "what-if adjustments to real years, not forecasts"
CURRENT = "Your current plan"
CUR = "cur"                      # key of the farm's own water answer


def _get(obj, key, default=None):
    if obj is None:
        return default
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _with(obj, **changes):
    """A shallow copy of a dict, dataclass or plain object with some fields replaced."""
    if isinstance(obj, dict):
        return {**obj, **changes}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.replace(obj, **changes)
    new = copy.copy(obj)
    for k, v in changes.items():
        setattr(new, k, v)
    return new


# ------------------------------------------------------------------------------------------ rotations

def rot_key(rotation) -> tuple:
    """A rotation in any shape -> ((crops of year 1), ..., (crops of year 4)), (cover crop yes/no x 4)."""
    crops, covers = WB.normalize_rotation(rotation)
    return tuple(tuple(y) for y in crops), tuple(c is not None for c in covers)


def rot_dict(key: tuple) -> dict:
    return {"crops": [list(y) for y in key[0]], "cover_crops": list(key[1])}


def _short(crop: str) -> str:
    try:
        return C.get_crop(crop).name.split(" (")[0]
    except KeyError:
        return str(crop).replace("_", " ").capitalize()


def rot_label(key: tuple) -> str:
    """'Maize > Soybean > Winter wheat > Soybean (with cover crops)'."""
    text = " > ".join(" + ".join(_short(c) for c in y) if y else "Fallow" for y in key[0])
    return text + (" (with cover crops)" if any(key[1]) else "")


def same_rotation(key: tuple, prefer=()) -> tuple:
    """One name for a rotation whatever year it starts in. The plan repeats every four years, so
    'maize, soybean, maize, soybean' and 'soybean, maize, soybean, maize' are the same rotation started a year
    apart. Returns the first of `prefer` that is such a shift of `key` (so the farm's current plan keeps its
    own order), otherwise the shift whose label sorts first."""
    shifts = [(key[0][i:] + key[0][:i], key[1][i:] + key[1][:i]) for i in range(len(key[0]))]
    for p in prefer:
        if p in shifts:
            return p
    return min(shifts, key=rot_label)


def _raw_crops(rotation) -> list:
    """Crop names exactly as the other feature wrote them, in order, no repeats."""
    cr = rotation.get("crops") if isinstance(rotation, dict) else getattr(rotation, "crops", rotation)
    out = []
    for year in ([cr] if isinstance(cr, str) else list(cr or [])):
        for c in ([year] if isinstance(year, str) else list(year or [])):
            if c and c not in out and str(c).lower() != "fallow":
                out.append(c)
    return out


# ------------------------------------------------------------------------------------------ money

def economics(site, inputs, crop_ids) -> dict:
    """{crop: (price per tonne, cost per hectare)} from the farmer's entries, else the county numbers carried
    on the site (the same order Feature 3 uses). None for a crop when either number is missing: never a default."""
    ov, us = _get(inputs, "crop_overrides") or {}, _get(site, "us_defaults")

    def find(table, cid):
        for k, v in (table or {}).items():
            if C.crop_id(k) == cid:
                return v
        return None

    out = {}
    for cid in crop_ids:
        node = find(ov, cid)
        price, cost = _get(node, "price"), _get(node, "cost")
        price = find(_get(us, "prices"), cid) if price is None else price
        cost = find(_get(us, "costs"), cid) if cost is None else cost
        out[cid] = None if price is None or cost is None else (float(price), float(cost))
    return out


def _cover_cost(inputs) -> float:
    node = (_get(inputs, "crop_overrides") or {}).get("cover_crop")
    return float(_get(node, "cost") or 0.0)


def plan_metric(res, econ: dict | None, cover_cost: float = 0.0) -> np.ndarray:
    """[S] one number per weather plan. With econ: average profit per hectare per year (first crop of each plan
    year, as in Feature 3; a cover crop costs cover_cost in its year). Without: share of potential yield (%)."""
    if econ is None:
        return res.rel_yields.mean(axis=1) * 100.0
    y = res.yields_kg_ha
    profit = np.zeros_like(y)
    for yr in range(y.shape[1]):
        crops = res.crops[yr] if yr < len(res.crops) else []
        if crops:
            price, cost = econ[crops[0]]
            profit[:, yr] = np.maximum(y[:, yr], 0.0) / 1000.0 * price - cost
        if yr < len(res.cover_crops) and res.cover_crops[yr]:
            profit[:, yr] -= cover_cost
    return profit.mean(axis=1)


def _money_ready(site, inputs, keys) -> tuple:
    """(econ or None, why not). Profit can be shown only when every crop of every plan has a price, a cost and
    a yield number."""
    crops = sorted({c for k in keys for y in k[0] for c in y})
    econ = economics(site, inputs, crops)
    no_money = [c for c in crops if econ[c] is None]
    no_yield = [c for c in crops if c in C.crop_library() and YM.potential_yield(c, site, inputs, 1.0)[0] is None]
    if no_money or no_yield:
        why = []
        if no_money:
            why.append("no price or cost for " + ", ".join(_short(c) for c in no_money))
        if no_yield:
            why.append("no yield number for " + ", ".join(_short(c) for c in no_yield))
        return None, "; ".join(why)
    return econ, ""


# ------------------------------------------------------------------------------------------ recommend()

def _api_recommend():
    """engine.api.recommend when it is the v4 one (site, inputs, sliders); None otherwise."""
    try:
        from engine import api
        fn = getattr(api, "recommend", None)
        if fn is None:
            return None
        kinds = [p.kind for p in inspect.signature(fn).parameters.values()]
        positional = sum(k in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD) for k in kinds)
        return fn if positional >= 3 or inspect.Parameter.VAR_POSITIONAL in kinds else None
    except Exception:
        return None


def _accepts(fn, name: str) -> bool:
    try:
        ps = inspect.signature(fn).parameters
        return name in ps or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in ps.values())
    except (TypeError, ValueError):
        return False


def _why_unusable(rec) -> str:
    if rec is None:
        return "recommend() returned nothing"
    if _get(rec, "input_needed"):
        need = _get(rec, "input_needed")
        return "recommend() needs " + ", ".join(f"{_get(n, 'field')} for {_get(n, 'crop')}" for n in need)
    if _get(rec, "example"):
        return "recommend() still returns example data"
    if _get(rec, "highest_profit") is None and _get(rec, "headline") is None:
        return "recommend() returned no picks"
    return ""


def _winner_of(rec) -> tuple:
    pick = _get(rec, "headline")
    return rot_key(pick if pick is not None else _get(rec, "highest_profit"))


def _short_list(rec, inputs, max_crops: int) -> list:
    """Crops (as Feature 3 names them) for the what-if search: the current plan's, the three picks', then the
    crops of the most profitable other rotations, up to max_crops (never dropping a current or pick crop)."""
    pool = _raw_crops(_get(inputs, "current_plan") or [])
    for name in ("headline", "highest_profit", "best_soil"):
        pick = _get(rec, name)
        if pick is not None:
            pool += [c for c in _raw_crops(pick) if c not in pool]
    ranked = sorted(_get(rec, "all_results") or [], key=lambda r: -float(_get(r, "mean_profit", 0.0) or 0.0))
    for r in ranked[:200]:
        for c in _raw_crops(r):
            if len(pool) >= max_crops:
                return pool
            if c not in pool:
                pool.append(c)
    return pool


def _restrict_site(site, pool):
    """The same site with the county crop list cut down to the short list (what Feature 3's candidate filter
    reads). (site, True) when that was possible."""
    us = _get(site, "us_defaults")
    if us is None or _get(us, "crops") is None:
        return site, False
    try:
        return _with(site, us_defaults=_with(us, crops=list(pool))), True
    except Exception:
        return site, False


# ------------------------------------------------------------------------------------------ water levels

def water_levels(inputs) -> dict:
    """The water supplies to try. Irrigated farm with an amount: shares of the farmer's normal-year supply (the
    dry-year answer scaled the same way). Rain-fed farm, or no amount given: fixed amounts in mm a year."""
    water = _get(inputs, "water")
    mode = str(_get(water, "mode") or "rain").lower()
    rainfed = mode.startswith("rain")
    normal, dry = _get(water, "normal_mm"), _get(water, "dry_mm")
    if not rainfed and normal is not None and float(normal) > 0:
        n = float(normal)
        d = n if dry is None else min(max(float(dry), 0.0), n)
        rows = [{"mm": round(f * n, 1), "water": {"mode": "irrigated", "normal_mm": f * n, "dry_mm": f * d},
                 "current": abs(f - 1.0) < 1e-9} for f in C.rule("tipping_water_fractions")]
        if not any(r["current"] for r in rows):
            rows.append({"mm": n, "water": None, "current": True})
            rows.sort(key=lambda r: r["mm"])
        return {"rows": rows, "current_mm": n, "note": "Shares of your normal-year water supply; your dry-year "
                "answer is scaled the same way.", "current_text": f"{n:.0f} mm a year (your answer)"}
    unlimited = not rainfed and normal is None
    at_zero = rainfed or (normal is not None and float(normal) <= 0)
    rows = [{"mm": float(v), "water": {"mode": "irrigated", "normal_mm": float(v), "dry_mm": float(v)},
             "current": at_zero and float(v) == 0.0} for v in C.rule("tipping_water_levels_mm")]
    return {"rows": rows, "current_mm": 0.0 if at_zero else None,
            "note": ("What if this farm had this much irrigation water a year (the same in dry years)? "
                     "The cost of getting the water is not counted."),
            "current_text": "rain only" if at_zero else "no limit given (above the top of the map)" if unlimited else ""}


# ------------------------------------------------------------------------------------------ the analysis

def _crossings(xs, winners, vals, keys, weights, n_resample: int, seed: int) -> list:
    """Where the winner changes along a curve. For each change: the two x values it lies between, an estimate
    (where the two plans' averages are equal, else the midpoint) and the 10th to 90th percentile range of that
    estimate when the weather plans are drawn again (bootstrap, fixed seed)."""
    out = []
    rng = np.random.default_rng(seed)
    S = vals.shape[2]
    for j in range(len(xs) - 1):
        a, b = winners[j], winners[j + 1]
        if a == b:
            continue
        x0, x1 = float(xs[j]), float(xs[j + 1])
        d = vals[keys.index(b), j:j + 2, :] - vals[keys.index(a), j:j + 2, :]          # [2,S] new minus old winner
        d0, d1 = (float(np.average(d[i], weights=weights)) for i in (0, 1))
        item = {"between": [x0, x1], "from": rot_label(a), "to": rot_label(b), "at": (x0 + x1) / 2.0,
                "p10": x0, "p90": x1, "by": "settings"}
        if d0 * d1 < 0:                                                                 # the averages really cross here
            item["at"] = x0 + (x1 - x0) * d0 / (d0 - d1)
            p = weights / weights.sum()
            draws = rng.choice(S, size=(n_resample, S), p=p)
            m0, m1 = d[0][draws].mean(axis=1), d[1][draws].mean(axis=1)
            with np.errstate(divide="ignore", invalid="ignore"):
                x = np.where(m0 * m1 < 0, x0 + (x1 - x0) * m0 / (m0 - m1), np.where(np.abs(m0) < np.abs(m1), x0, x1))
            item.update(p10=float(np.quantile(x, 0.10)), p90=float(np.quantile(x, 0.90)), by="average")
        out.append(item)
    return out


def tipping_points(site, inputs, sliders=None, recommend=None, progress=None, budget_s: float | None = None) -> dict:
    """Where the best plan changes with rainfall, heat and water supply. See the module docstring.

    recommend   the recommend(site, inputs, sliders) function to ask for the winner; default engine.api.recommend.
                Pass False to skip it and use the module's own ranking.
    progress    optional progress(done, total, text) callback for the screen.
    budget_s    time to aim for (default rule tipping_time_budget_s).
    """
    t_start = time.perf_counter()
    budget = float(C.rule("tipping_time_budget_s") if budget_s is None else budget_s)
    mode = CS.normalize_mode(_get(sliders, "climate_shift"))
    full = CS.scenarios_for(site, mode)
    current = rot_key(_get(inputs, "current_plan"))
    rains = [float(v) for v in C.rule("tipping_rain_mults")]
    heats = [float(v) for v in C.rule("tipping_heat_shifts_c")]
    if 1.0 not in rains:
        rains = sorted(rains + [1.0])
    if 0.0 not in heats:
        heats = sorted(heats + [0.0])
    wl = water_levels(inputs)
    rows = wl["rows"]
    wkeys = [CUR if r["current"] else i for i, r in enumerate(rows)]
    water_of = {k: (None if k == CUR else rows[k]["water"]) for k in wkeys}
    water_of[CUR] = None                                             # the farm's own answer, untouched
    notes, method = [], {"climate_shift": mode, "scenarios_bands": full.n}

    # ---- who decides the winner: recommend() through the api, or this module's own ranking
    fn = _api_recommend() if recommend is None else (recommend or None)
    rec0, why = None, "engine.api.recommend is not available yet" if fn is None else ""
    if fn is not None:
        try:
            with SIM.what_if(climate_shift=mode):
                rec0 = fn(site, inputs, sliders)
            why = _why_unusable(rec0)
        except Exception as e:                                           # the other feature failed: say so, carry on
            why = f"recommend() failed ({type(e).__name__}: {e})"
        if why:
            rec0 = None
    s_w = min(int(C.rule("tipping_winner_scenarios")), full.n)
    s_min = min(int(C.rule("tipping_min_scenarios")), full.n)
    max_crops = int(C.rule("tipping_max_crops"))

    if rec0 is not None:
        pool = _short_list(rec0, inputs, max_crops)
        by_kw = _accepts(fn, "crops")
        small_site, by_site = (site, False) if by_kw else _restrict_site(site, pool)
        restricted = by_kw or by_site
        method.update(winner_source="recommend() through engine/api.py", crops_searched=[_short(c) for c in pool] if restricted else "all candidate crops")

        def ask(scen):
            rec = fn(site, inputs, sliders, crops=list(pool)) if by_kw else fn(small_site, inputs, sliders)
            bad = _why_unusable(rec)
            if bad:
                raise RuntimeError(bad)
            return _winner_of(rec)
        base_winner = _winner_of(rec0)
        econ_rank = None
    else:
        notes.append(f"The winner is ranked by this page itself, not by the recommendation engine, because {why}.")
        cur_crops = list(dict.fromkeys(c for y in current[0] for c in y))
        us = _get(site, "us_defaults")
        fit = C.candidate_crops(SIM.site_climate(site), irrigated=SIM._is_irrigated(inputs), county_crops=_get(us, "crops"))
        money = economics(site, inputs, fit)
        ref = SIM.reference_relative_yields(site, inputs, fit) if fit else {}
        fit = sorted((c for c in fit if c not in cur_crops),
                     key=lambda c: (money[c] is None, -(ref.get(c) if np.isfinite(ref.get(c, np.nan)) else -1.0)))
        pool = cur_crops + fit[:max(max_crops - len(cur_crops), 0)]
        rot_keys = list(dict.fromkeys([current] + [same_rotation(rot_key(list(seq)), (current,))
                                                   for seq in itertools.product(pool, repeat=4)]))
        econ_rank, why_yield = _money_ready(site, inputs, rot_keys)
        cc = _cover_cost(inputs)
        method.update(winner_source="own ranking by " + ("average profit" if econ_rank else "share of potential yield"),
                      crops_searched=[_short(c) for c in pool])
        if not econ_rank:
            notes.append(f"Plans are ranked by share of potential yield, not profit ({why_yield}).")
        rot_dicts = [rot_dict(k) for k in rot_keys]

        def ask(scen):
            res = SIM.simulate_many(site, inputs, rot_dicts, None)
            score = np.array([np.average(plan_metric(r, econ_rank, cc), weights=r.weights) if r.feasible else -np.inf
                              for r in res])
            return rot_keys[int(np.argmax(score))]
        with SIM.what_if(scenarios=full):
            base_winner = ask(full)

    # ---- every what-if point: (rain multiplier, heat shift, water key)
    base_pt = (1.0, 0.0, CUR)
    curve_pts = [(r, 0.0, CUR) for r in rains] + [(1.0, 0.0, k) for k in wkeys] + [(1.0, h, CUR) for h in heats]
    map_rains, map_w = list(rains), list(wkeys)
    base_winner = same_rotation(base_winner, (current,))
    winners = {base_pt: base_winner}
    prefer = (current, base_winner)

    def plan(points):
        return [p for p in dict.fromkeys(points) if p not in winners]

    def run(points, s):
        scen = full.subset(np.arange(s)) if s < full.n else full
        for p in points:
            r, h, k = p
            try:
                with SIM.what_if(rain_mult=r, heat_shift_c=h, water=water_of[k], scenarios=scen):
                    winners[p] = same_rotation(ask(scen), prefer)
            except Exception as e:
                winners[p] = None
                if not any("could not be worked out" in n for n in notes):
                    notes.append(f"Some what-if points could not be worked out ({type(e).__name__}: {e}).")
            if progress:
                progress(len(winners), total[0], "Checking what-if climates")

    todo = plan(curve_pts + [(r, 0.0, k) for k in map_w for r in map_rains])
    total = [len(todo) + 1]
    coarse = False
    if todo:
        t0 = time.perf_counter()
        run(todo[:1], s_w)
        dt = time.perf_counter() - t0
        left = budget - (time.perf_counter() - t_start)
        need = dt * (len(todo) - 1)
        if need > max(left, 1.0):
            s_new = int(max(s_min, min(s_w, np.floor(s_w * max(left, 1.0) / need / 10.0) * 10)))
            need *= s_new / s_w
            s_w = s_new
            if need > 1.5 * max(left, 1.0):                           # still too slow: a coarser map, full curves
                coarse = True
                map_rains = [r for i, r in enumerate(rains) if i % 2 == 0 or r == 1.0]
                map_w = [k for i, k in enumerate(wkeys) if i % 2 == 0 or k == CUR or i == len(wkeys) - 1]
                todo = todo[:1] + plan(curve_pts + [(r, 0.0, k) for k in map_w for r in map_rains])
                total[0] = len(todo) + 1
        run(todo[1:], s_w)
    method.update(scenarios_winner=s_w, coarse_map=coarse)
    if s_w < full.n:
        notes.append(f"Winners away from your current setting are found with the first {s_w} of the {full.n} weather plans "
                     f"(for speed); the curves and bands use all {full.n}.")
    if coarse:
        notes.append("The map is drawn on a coarser grid to keep the wait short.")
    notes.append("The same crops in the same order, started in a different year, count as one plan.")
    if method["crops_searched"] != "all candidate crops":
        notes.append("What-if winners are searched among rotations of: " + ", ".join(method["crops_searched"]) + ".")

    # ---- curves: average and 10th to 90th percentile band for the current plan and every winner on the curve
    cc = _cover_cost(inputs)
    all_keys = [current] + [k for k in dict.fromkeys(w for w in winners.values() if w is not None) if k != current]
    econ, why_yield = _money_ready(site, inputs, all_keys)
    if rec0 is None and econ_rank is None:
        econ = None
    if econ is None and rec0 is not None:
        notes.append(f"The charts show share of potential yield, not profit ({why_yield}).")
    metric = {"name": "profit" if econ else "yield_share", "badge": "estimated",
              "label": "Average profit per hectare per year" if econ else "Share of potential yield (%)"}
    n_res, seed = int(C.rule("tipping_crossover_resamples")), int(C.rule("seed"))

    def name_of(key):
        if key is None:
            return "Not worked out"
        return f"{CURRENT}: {rot_label(key)}" if key == current else rot_label(key)

    def curve(xs, pts, what_ifs, x_label, current_x):
        win = [winners.get(p) for p in pts]
        keys = [current] + [k for k in dict.fromkeys(w for w in win if w is not None) if k != current]
        rots = [rot_dict(k) for k in keys]
        vals = np.empty((len(keys), len(xs), full.n))
        for j, kw in enumerate(what_ifs):
            with SIM.what_if(scenarios=full, **kw):
                res = SIM.simulate_many(site, inputs, rots, None)
            for i, r in enumerate(res):
                vals[i, j] = plan_metric(r, econ, cc)
        mean = np.average(vals, axis=2, weights=full.weights)
        p10, p90 = np.quantile(vals, 0.10, axis=2), np.quantile(vals, 0.90, axis=2)
        filled = [w if w is not None else current for w in win]
        cross = _crossings(xs, filled, vals, keys, full.weights, n_res, seed)
        for c in cross:
            for side in ("from", "to"):
                if c[side] == rot_label(current):
                    c[side] = name_of(current)
        return {"x": [float(v) for v in xs], "x_label": x_label, "current_x": current_x,
                "series": {name_of(k): [float(v) for v in mean[i]] for i, k in enumerate(keys)},
                "band": {"p10": {name_of(k): [float(v) for v in p10[i]] for i, k in enumerate(keys)},
                         "p90": {name_of(k): [float(v) for v in p90[i]] for i, k in enumerate(keys)}},
                "winner": [name_of(w) for w in win], "crossovers": [c["at"] for c in cross],
                "crossover_details": cross, "metric": metric}

    rc = curve(rains, [(r, 0.0, CUR) for r in rains], [{"rain_mult": r} for r in rains],
               "Rainfall (1.0 = the real record)", 1.0)
    if progress:
        progress(total[0], total[0], "Drawing the curves")
    hc = curve(heats, [(1.0, h, CUR) for h in heats], [{"heat_shift_c": h} for h in heats],
               "Heat shift (degC added to every day's maximum)", 0.0)
    wc = curve([rows[i]["mm"] if k != CUR else next(r["mm"] for r in rows if r["current"]) for i, k in enumerate(wkeys)],
               [(1.0, 0.0, k) for k in wkeys], [({"water": water_of[k]} if water_of[k] is not None else {}) for k in wkeys],
               "Water supply (mm a year)", wl["current_mm"])
    wc["note"] = wl["note"]

    # ---- the 2D map
    mm = {k: (rows[i]["mm"] if k != CUR else next(r["mm"] for r in rows if r["current"])) for i, k in enumerate(wkeys)}
    grid = [[name_of(winners.get((r, 0.0, k))) for r in map_rains] for k in map_w]
    labels = list(dict.fromkeys(v for row in grid for v in row))
    cur_row = map_w.index(CUR) if CUR in map_w else None
    map_2d = {"rain_mult": map_rains, "water_mm": [mm[k] for k in map_w], "winner": grid, "labels": labels,
              "current": {"rain_mult": 1.0, "water_mm": wl["current_mm"], "row": cur_row, "col": map_rains.index(1.0),
                          "text": wl["current_text"], "winner": name_of(base_winner)},
              "note": wl["note"], "badge": "estimated"}

    # ---- plain-English headlines
    def say(c, what, fmt):
        out = []
        for d in c["crossover_details"]:
            rng = (f"10th to 90th percentile across weather plans: {fmt(d['p10'])} to {fmt(d['p90'])}" if d["by"] == "average"
                   else f"somewhere between {fmt(d['between'][0])} and {fmt(d['between'][1])}; decided by your risk and soil "
                        f"settings, not by the average result alone")
            out.append(f"{what}: below about {fmt(d['at'])} the best plan is {d['from']}; above it, {d['to']} ({rng}).")
        return out
    head = [f"With the real weather record and your water, the best plan is {name_of(base_winner)}."]
    head += say(rc, "Rainfall", lambda v: f"{v:.2f} x the record")
    head += say(hc, "Heat shift", lambda v: f"+{v:.1f} degC")
    head += say(wc, "Water supply", lambda v: f"{v:.0f} mm a year")
    if len(head) == 1:
        head.append("The best plan stays the same across every rainfall, heat and water level tried here.")
    method["seconds"] = round(time.perf_counter() - t_start, 1)
    return {"rainfall_curve": rc, "heat_curve": hc, "water_curve": wc, "map_2d": map_2d,
            "bands": {"rainfall": rc["crossover_details"], "heat": hc["crossover_details"], "water": wc["crossover_details"]},
            "note": NOTE, "example": False, "headlines": head, "notes": notes, "method": method,
            "climate": CS.describe(SIM._site_parts(site)["weather"], mode, SIM._site_parts(site)["lat"], SIM._site_parts(site)["elevation_m"]),
            "current_plan": name_of(current), "winner_now": name_of(base_winner), "metric": metric,
            "badges": {"weather": "observed", "winner": "estimated", "curves": "estimated", "bands": "estimated",
                       "what_if_levels": "assumption"}}
