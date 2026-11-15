# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Continuous daily root-zone water balance over a 4-year plan (FAO-56 ch.8 + SCS runoff + FAO-33 yield).

Design
- One soil column of depth Zcol = max crop root depth. State Dr = depletion (mm below field capacity), 0..TAWcol.
  Rain (after SCS runoff) refills Dr; excess above field capacity drains (deep percolation).
  Stress uses the crop's own root zone: TAW_r = AWC*Zr (AWC in mm per m; = 1000*AWC[m/m]*Zr), RAW = p*TAW_r,
  Ks = clip((TAW_r - Dr)/((1-p)*TAW_r), 0, 1) (FAO-56 eq. 84), so Ks = 1 while Dr <= RAW.
  This treats Dr (mm) as the depletion of the root zone itself; roots cannot lift ETa above the water that exists.
- Rainfed crops (jowar, bajra, pigeonpea): ETa = Ks*Kc*ET0; Kc is the FAO-56 piecewise curve from assumptions.yaml.
- Fallow days (before sowing, after harvest): evaporation only, Kc_fallow, Ks over the evaporation depth Ze.
- Rice = irrigated paddy (SPEC_CHANGES_INDIA sec.2): a ponded layer h (0..bund height) over saturated soil.
  Daily demand = ETc + seepage; irrigation needed = max(0, demand + soil deficit - (pond + rain));
  one-time puddling water at sowing; season supply = base*(season_rain/median_season_rain)^k per scenario.
  If supply runs out, ETa < ETm and the FAO-33 reduction applies. Pond above the bund spills as runoff;
  the pond is drained at harvest (counted as runoff).
- Mass closure (whole 4-year run, per scenario): rain + irrigation = ETa + percolation + runoff + change in storage.

Performance: the production kernel compiles daily loops, reuses identical plan prefixes,
and parallelizes independent weather sequences. simulate_plan is the R = 1 case.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

from engine.crops import A, CROP_IDS, load_crops
from engine.yieldmodel import rotation_factor, season_yield

NDAY = 365


def ks_from_depletion(dr, taw, p):
    """FAO-56 eq. 84 water stress coefficient."""
    return np.clip((taw - dr) / ((1.0 - p) * taw), 0.0, 1.0)


def scs_runoff(precip, cn, ia_ratio=0.2):
    """SCS curve-number daily runoff (mm)."""
    s = 25400.0 / cn - 254.0
    ia = ia_ratio * s
    ex = np.maximum(precip - ia, 0.0)
    return ex * ex / (ex + s)


def _record(rec, name, day, v, val):
    """Write one day's values into the daily record, only for the scenarios that are in this phase on that day."""
    rec[name][:, v, day] = val[:, v]


def _dry_phase(Dr, kcet0T, peT, taw, inv, dcol, rec=None, off=0):
    """Rainfed / fallow daily loop. Dr [g,S]; kcet0T, peT [n,S]. Returns Dr, sum ETa, sum drainage."""
    se = np.zeros_like(Dr)
    sd = np.zeros_like(Dr)
    for i in range(kcet0T.shape[0]):
        ks = (taw - Dr) * inv
        np.clip(ks, 0.0, 1.0, out=ks)
        eta = ks * kcet0T[i]
        pei = peT[i]
        np.minimum(eta, dcol - Dr + pei, out=eta)
        if rec is not None:
            rec["dr"][:, :, off + i] = Dr
            rec["ks"][:, :, off + i] = ks
            rec["eta"][:, :, off + i] = eta
        Dr = Dr - pei + eta
        dp = np.maximum(-Dr, 0.0)
        np.maximum(Dr, 0.0, out=Dr)
        se += eta
        sd += dp
    return Dr, se, sd


def _rice_phase(Dr, et0T, rainT, supply, well, kc, perc, hmax, taw, inv, dcol, rec=None, off=0):
    """Irrigated paddy daily loop. Returns Dr, and dict of season sums."""
    z = np.zeros_like(Dr)
    h = z.copy()
    out = {k: z.copy() for k in ("eta", "etm", "irr", "irr_c", "irr_w", "need", "dp", "ro", "rain")}
    for i in range(et0T.shape[0]):
        etc = kc[i] * et0T[i]
        rain = rainT[i]
        demand = etc + perc
        need = np.maximum(demand + Dr - (h + rain), 0.0)
        irr_c = np.minimum(need, supply)            # canal first
        irr_w = np.minimum(need - irr_c, well)      # wells cover the shortfall only
        supply = supply - irr_c
        well = well - irr_w
        irr = irr_c + irr_w
        W = h + rain + irr
        fill = np.minimum(Dr, W)
        Dr = Dr - fill
        W = W - fill
        e1 = np.minimum(etc, W)
        W = W - e1
        ks = (taw - Dr) * inv
        np.clip(ks, 0.0, 1.0, out=ks)
        e2 = np.minimum((etc - e1) * ks, dcol - Dr)
        Dr = Dr + e2
        pact = np.minimum(perc, W)
        W = W - pact
        over = np.maximum(W - hmax, 0.0)
        h = W - over
        if rec is not None:
            rec["dr"][:, :, off + i] = Dr
            rec["ks"][:, :, off + i] = ks
            rec["eta"][:, :, off + i] = e1 + e2
            rec["need"][:, :, off + i] = need
        out["eta"] += e1 + e2
        out["etm"] += etc
        out["irr"] += irr
        out["irr_c"] += irr_c
        out["irr_w"] += irr_w
        out["need"] += need
        out["dp"] += pact
        out["ro"] += over
        out["rain"] += rain
    out["ro"] += h          # drain the pond at harvest
    return Dr, out


def _simulate_fixed_reference(scen: dict, plans: Sequence[Sequence[str]], awc_mm_per_m: float,
                   irrigation_available_mm: float, params: dict | None = None) -> dict:
    """Vectorised simulation of R plans over S scenarios. Arrays are [R,S,4] ([R,S] for storage/closure)."""
    params = params or {}
    crops = load_crops(params)
    plans = [list(p) for p in plans]
    R = len(plans)
    plan_arr = np.array(plans)
    et0 = np.asarray(scen["et0"], float)
    precip = np.asarray(scen["precip"], float)
    S, NY, _ = et0.shape
    assert NY == 4 and plans and all(len(p) == 4 for p in plans)

    awc = float(awc_mm_per_m)
    zcol = max(c.root_depth_m for c in crops.values())
    dcol = awc * zcol
    grp = A(params, "hydrology.hydrologic_group")
    cn_crop = A(params, f"hydrology.cn_crop_group_{grp}")
    cn_fall = A(params, f"hydrology.cn_fallow_group_{grp}")
    ia = A(params, "hydrology.ia_ratio")
    ro_crop = scs_runoff(precip, cn_crop, ia)
    ro_fall = scs_runoff(precip, cn_fall, ia)
    pe_crop = precip - ro_crop
    pe_fall = precip - ro_fall

    kc_f = A(params, "fallow.kc")
    taw_f = awc * A(params, "fallow.evap_depth_m")
    inv_f = 1.0 / ((1.0 - A(params, "fallow.depletion_fraction")) * taw_f)
    perc = float(A(params, "rice_irrigation.percolation_seepage_mm_day"))
    pud = float(A(params, "rice_irrigation.puddling_water_mm"))
    hmax = float(A(params, "rice_irrigation.bund_height_mm"))
    k = float(A(params, "rice_irrigation.recharge_exponent_k"))
    base = float(irrigation_available_mm)

    rice = crops["rice"]
    ra, rb = rice.sowing_doy - 1, min(rice.sowing_doy - 1 + rice.season_days, NDAY)
    rice_rain = precip[:, :, ra:rb].sum(axis=2)                      # [S,4] season rain
    med = params.get("median_season_rain_mm")
    med = float(np.median(rice_rain)) if med is None else float(med)
    source = params.get("water_source", "unset")
    if source not in ("unset", "borewell", "tank", "canal", "canal_and_well"):
        raise ValueError(f"water_source must be unset|borewell|tank|canal|canal_and_well, got {source!r}")
    zeros = np.zeros((S, 4))
    if source == "canal_and_well":
        # S = S_canal + S_well; canal first, wells cover the shortfall (irrigation_available_mm is ignored here:
        # use params canal_supply_mm / well_supply_mm to override the formulas).
        def _sf(v):
            v = np.asarray(v, float)
            return np.broadcast_to(v[:, None] if v.ndim == 1 else v, (S, 4))
        if params.get("canal_supply_mm") is not None:
            s_canal = _sf(params["canal_supply_mm"]).copy()
        else:
            if "upstream_season_rain" not in scen:
                raise KeyError("water_source='canal_and_well' needs scen['upstream_season_rain'] shaped [S,4] "
                               "(from engine.fetch_upstream); it is missing")
            up = np.asarray(scen["upstream_season_rain"], float)
            med_up = params.get("median_upstream_rain")
            med_up = float(np.median(up)) if med_up is None else float(med_up)
            s_canal = A(params, "rice_irrigation.base_canal") * (
                np.maximum(up, 0.0) / max(med_up, 1e-9)) ** A(params, "rice_irrigation.k_canal")
        if params.get("well_supply_mm") is not None:
            s_well = _sf(params["well_supply_mm"]).copy()
        else:
            med_loc = params.get("median_local_rain")
            med_loc = float(np.median(rice_rain)) if med_loc is None else float(med_loc)
            s_well = np.minimum(A(params, "rice_irrigation.max_well"),
                                A(params, "rice_irrigation.base_well") *
                                (np.maximum(rice_rain, 0.0) / max(med_loc, 1e-9)) ** A(params, "rice_irrigation.k_well"))
        avail_c, avail_w = np.maximum(s_canal, 0.0), np.maximum(s_well, 0.0)
    elif source == "canal":
        # proxy for canal water availability: driven by a canal release factor, NOT local rain
        cf = np.asarray(params.get("canal_release_factor", A(params, "rice_irrigation.canal_release_factor")), float)
        f = np.maximum(cf, 0.0) ** float(A(params, "rice_irrigation.canal_exponent_k"))
        if f.ndim == 1:
            f = f[:, None]
        avail_c, avail_w = base * np.broadcast_to(f, (S, 4)), zeros
    else:   # simplified local-rainfall recharge proxy (well-like)
        avail_c, avail_w = zeros, base * (np.maximum(rice_rain, 0.0) / max(med, 1e-9)) ** k

    keys3 = ("yield_kg_ha", "eta_mm", "etm_mm", "rain_mm", "irrig_mm", "irrig_needed_mm", "runoff_mm",
             "drainage_mm", "puddle_mm", "rain_total_mm", "eta_total_mm", "runoff_total_mm",
             "drainage_total_mm", "irrig_total_mm", "irrig_canal_mm", "irrig_well_mm",
             "supply_canal_mm", "supply_well_mm")
    res = {kk: np.zeros((R, S, 4)) for kk in keys3}
    rec_on = bool(params.get("record_daily"))
    daily = {n: np.zeros((R, S, 4, NDAY)) for n in ("dr", "ks", "eta", "need")} if rec_on else None

    Dr = np.full((R, S), A(params, "hydrology.init_depletion_frac") * dcol)
    Dr0 = Dr.copy()
    fr = np.stack([rotation_factor(p, params) for p in plans])       # [R,4]

    for y in range(4):
        for cid in np.unique(plan_arr[:, y]):
            idx = np.where(plan_arr[:, y] == cid)[0]
            c = crops[cid]
            a = c.sowing_doy - 1
            b = min(a + c.season_days, NDAY)
            n = b - a
            g = len(idx)
            d = Dr[idx].copy()
            rec = {n_: np.zeros((g, S, NDAY)) for n_ in ("dr", "ks", "eta", "need")} if rec_on else None
            eta_all = np.zeros((g, S)); dp_all = np.zeros((g, S)); ro_all = np.zeros((g, S))
            irr_all = np.zeros((g, S))

            def fallow(d, lo, hi):
                if hi <= lo:
                    return d
                e0 = (kc_f * et0[:, y, lo:hi]).T
                pe = pe_fall[:, y, lo:hi].T
                d, se, sd = _dry_phase(d, e0, pe, taw_f, inv_f, dcol, rec, lo)
                eta_all[:] += se; dp_all[:] += sd
                ro_all[:] += ro_fall[:, y, lo:hi].sum(axis=1)
                return d

            d = fallow(d, 0, a)
            kc = c.kc_curve()[:n]
            taw = awc * c.root_depth_m
            if cid == "rice":
                supply = np.broadcast_to(avail_c[:, y], (g, S)).copy()
                well = np.broadcast_to(avail_w[:, y], (g, S)).copy()
                need_p = np.maximum(pud, d)                          # land prep + saturate soil
                ip_c = np.minimum(need_p, supply)
                ip_w = np.minimum(need_p - ip_c, well)
                irr_p = ip_c + ip_w
                supply = supply - ip_c
                well = well - ip_w
                fill = np.minimum(d, irr_p)
                d = d - fill
                dp_all += irr_p - fill                               # puddling water beyond soil fill leaves as drainage
                irr_all += irr_p
                inv = 1.0 / ((1.0 - c.p) * taw)
                d, o = _rice_phase(d, et0[:, y, a:b].T, precip[:, y, a:b].T, supply, well, kc, perc, hmax,
                                   taw, inv, dcol, rec, a)
                eta_all += o["eta"]; dp_all += o["dp"]; ro_all += o["ro"]; irr_all += o["irr"]
                res["eta_mm"][idx, :, y] = o["eta"]
                res["etm_mm"][idx, :, y] = o["etm"]
                res["irrig_mm"][idx, :, y] = irr_p + o["irr"]
                res["irrig_canal_mm"][idx, :, y] = ip_c + o["irr_c"]
                res["irrig_well_mm"][idx, :, y] = ip_w + o["irr_w"]
                res["supply_canal_mm"][idx, :, y] = avail_c[:, y]
                res["supply_well_mm"][idx, :, y] = avail_w[:, y]
                res["irrig_needed_mm"][idx, :, y] = need_p + o["need"]
                res["puddle_mm"][idx, :, y] = need_p
                res["runoff_mm"][idx, :, y] = o["ro"]
                res["drainage_mm"][idx, :, y] = o["dp"] + (irr_p - fill)
            else:
                inv = 1.0 / ((1.0 - c.p) * taw)
                e0 = kc[:, None] * et0[:, y, a:b].T
                pe = pe_crop[:, y, a:b].T
                d, se, sd = _dry_phase(d, e0, pe, taw, inv, dcol, rec, a)
                eta_all += se; dp_all += sd
                rsum = ro_crop[:, y, a:b].sum(axis=1)
                ro_all += rsum
                res["eta_mm"][idx, :, y] = se
                res["etm_mm"][idx, :, y] = e0.sum(axis=0)
                res["runoff_mm"][idx, :, y] = rsum
                res["drainage_mm"][idx, :, y] = sd
            res["rain_mm"][idx, :, y] = precip[:, y, a:b].sum(axis=1)
            d = fallow(d, b, NDAY)
            Dr[idx] = d
            res["rain_total_mm"][idx, :, y] = precip[:, y, :].sum(axis=1)
            res["eta_total_mm"][idx, :, y] = eta_all
            res["runoff_total_mm"][idx, :, y] = ro_all
            res["drainage_total_mm"][idx, :, y] = dp_all
            res["irrig_total_mm"][idx, :, y] = irr_all
            ym = c.ym_kg_ha
            res["yield_kg_ha"][idx, :, y] = season_yield(ym, c.ky, res["eta_mm"][idx, :, y],
                                                         res["etm_mm"][idx, :, y], fr[idx, y][:, None])
            if rec_on:
                for n_ in daily:
                    daily[n_][idx, :, y, :] = rec[n_]

    storage_change = -(Dr - Dr0)
    closure = (res["rain_total_mm"] + res["irrig_total_mm"] - res["eta_total_mm"]
               - res["drainage_total_mm"] - res["runoff_total_mm"]).sum(axis=2) - storage_change
    res["storage_change_mm"] = storage_change
    res["closure_error_mm"] = closure
    res["dcol_mm"] = dcol
    res["plans"] = plans
    if rec_on:
        res["daily"] = daily
    return res


def simulate_batch(scen: dict, plans: Sequence[Sequence[str]], awc_mm_per_m: float,
                   irrigation_available_mm: float, params: dict | None = None) -> dict:
    """Continuous accounting with scenario-specific onset, crop stages and heat stress.

    Inputs without onset metadata retain the fixed-calendar behavior for standalone
    physics use. API scenarios always carry detected rainfall onset.
    """
    from engine._water_kernel import run
    params = params or {}
    crops = load_crops(params)
    ids = list(CROP_IDS)
    plans = [list(p) for p in plans]
    if not plans or any(len(p) != 4 or any(c not in ids for c in p) for p in plans):
        raise ValueError("Each rotation must contain four supported crop IDs")
    arrays = [np.ascontiguousarray(scen[k], dtype=float) for k in ("et0", "precip", "tmax")]
    et0, rain, tmax = arrays
    if et0.ndim != 3 or et0.shape[1:] != (4, 365) or any(a.shape != et0.shape for a in arrays):
        raise ValueError("Weather arrays must have the same [scenario, 4, 365] shape")
    if not all(np.isfinite(a).all() for a in arrays) or (et0 < 0).any() or (rain < 0).any():
        raise ValueError("Weather must be finite; rain and ET0 cannot be negative")
    awc, base = float(awc_mm_per_m), float(irrigation_available_mm)
    if not np.isfinite(awc) or awc <= 0 or not np.isfinite(base) or base < 0:
        raise ValueError("Soil capacity must be positive and irrigation nonnegative")
    ns = rain.shape[0]
    starts = np.empty((ns, 4, len(ids)), dtype=np.int64)
    from engine import monsoon
    for ci, cid in enumerate(ids):
        if "onset_doy" in scen and "onset_median" in scen:
            starts[:, :, ci] = monsoon.sowing_doy(crops[cid].sowing_doy, crops[cid].season_days,
                                                  scen["onset_doy"], scen["onset_median"]) - 1
        elif "onset_doy" in scen:
            # Legacy standalone scenarios use zero-based absolute planting onset.
            lag = A(params, "monsoon.rice_sowing_lag_days" if cid == "rice" else "monsoon.rainfed_sowing_lag_days")
            starts[:, :, ci] = np.minimum(365, np.asarray(scen["onset_doy"], dtype=int) + int(lag))
        else:
            starts[:, :, ci] = crops[cid].sowing_doy - 1
    rice_rain = rain[:, :, 151:304].sum(-1)  # Jun-Oct local recharge; fixed seasonal window
    median = float(params.get("median_local_rain", params.get("median_season_rain_mm", np.median(rice_rain))))
    source = params.get("water_source", "unset")
    def supply(value):
        a = np.asarray(value, float)
        if a.ndim == 1:
            a = a[:, None]
        a = np.broadcast_to(a, (ns, 4)).copy()
        if not np.isfinite(a).all() or (a < 0).any():
            raise ValueError("Irrigation supplies must be finite and nonnegative")
        return a
    canal = np.zeros((ns, 4)); well = canal.copy()
    if source == "canal_and_well":
        if params.get("canal_supply_mm") is not None:
            canal = supply(params["canal_supply_mm"])
        else:
            upstream = np.asarray(scen["upstream_season_rain"], float)
            med_up = float(params.get("median_upstream_rain", np.median(upstream)))
            canal = supply(A(params, "rice_irrigation.base_canal") * (np.maximum(upstream, 0) / max(med_up, 1e-9)) ** A(params, "rice_irrigation.k_canal"))
        well = supply(params["well_supply_mm"]) if params.get("well_supply_mm") is not None else supply(
            A(params, "rice_irrigation.base_well") * (rice_rain / max(median, 1e-9)) ** A(params, "rice_irrigation.k_well"))
        well = np.minimum(well, A(params, "rice_irrigation.max_well"))
    elif source == "canal":
        canal = supply(base * np.asarray(A(params, "rice_irrigation.canal_release_factor")) ** A(params, "rice_irrigation.canal_exponent_k"))
    elif source in ("unset", "borewell", "tank"):
        # Fixed-calendar calls keep their historical season window for backwards compatibility.
        if "onset_doy" not in scen:
            c = crops["rice"]
            rice_rain = rain[:, :, c.sowing_doy - 1:c.sowing_doy - 1 + c.season_days].sum(-1)
            median = float(params.get("median_season_rain_mm", np.median(rice_rain)))
        well = supply(base * (rice_rain / max(median, 1e-9)) ** A(params, "rice_irrigation.recharge_exponent_k"))
    else:
        raise ValueError(f"Unsupported water source: {source}")
    cp = [crops[c] for c in ids]
    kc = np.zeros((len(ids), 365))
    for i, c in enumerate(cp):
        kc[i, :c.season_days] = c.kc_curve()
    group = A(params, "hydrology.hydrologic_group")
    dcol = awc * max(c.root_depth_m for c in cp)
    heat_on = bool(A(params, "heat.enabled"))
    thresholds = np.array([A(params, f"heat.tmax_c.{c}") for c in ids])
    seen, owners = {}, np.zeros((len(plans), 4), dtype=np.int64)
    for r, plan in enumerate(plans):
        for y in range(4):
            prefix = tuple(plan[:y + 1])
            owners[r, y] = seen.setdefault(prefix, r)
    raw, storage, daily = run(
        np.array([[ids.index(c) for c in p] for p in plans], dtype=np.int64), owners, et0, rain, tmax, starts, kc,
        np.array([c.season_days for c in cp]), np.array([c.root_depth_m for c in cp]), np.array([c.p for c in cp]),
        np.array([c.ky for c in cp]), np.array([c.ym_kg_ha for c in cp]), np.stack([rotation_factor(p, params) for p in plans]),
        canal, well, awc, dcol, float(A(params, f"hydrology.cn_crop_group_{group}")),
        float(A(params, f"hydrology.cn_fallow_group_{group}")), float(A(params, "hydrology.ia_ratio")),
        float(A(params, "fallow.kc")), awc * float(A(params, "fallow.evap_depth_m")), float(A(params, "fallow.depletion_fraction")),
        float(A(params, "hydrology.init_depletion_frac")), float(A(params, "rice_irrigation.percolation_seepage_mm_day")),
        float(A(params, "rice_irrigation.puddling_water_mm")), float(A(params, "rice_irrigation.bund_height_mm")),
        heat_on, float(A(params, "heat.pen_per_day")), thresholds,
        np.array([sum(c.stages_days[:2]) for c in cp]), np.array([int(A(params, f"heat.flowering_days.{c}")) for c in ids]), bool(params.get("record_daily")))
    keys = ("yield_kg_ha", "eta_mm", "etm_mm", "rain_mm", "irrig_mm", "irrig_needed_mm", "runoff_mm", "drainage_mm", "puddle_mm",
            "rain_total_mm", "eta_total_mm", "runoff_total_mm", "drainage_total_mm", "irrig_total_mm", "irrig_canal_mm", "irrig_well_mm",
            "supply_canal_mm", "supply_well_mm", "heat_days")
    out = dict(zip(keys, raw))
    out.update(storage_change_mm=storage, dcol_mm=dcol, plans=plans,
               sowing_doy=np.stack([starts[:, y, ids.index(p[y])] + 1 for p in plans for y in range(4)]).reshape(len(plans), 4, ns).transpose(0, 2, 1))
    out["hot_days"] = out["heat_days"]
    out["heat_factor"] = np.maximum(0., 1. - out["heat_days"] * float(A(params, "heat.pen_per_day")))
    base_sow = np.array([min(crops[c].sowing_doy, 366 - crops[c].season_days) for c in ids])
    out["late_days"] = np.stack([np.maximum(starts[:, y, ids.index(p[y])] + 1 - base_sow[ids.index(p[y])], 0)
                                 for p in plans for y in range(4)]).reshape(len(plans), 4, ns).transpose(0, 2, 1)
    out["late_factor"] = (np.maximum(0., 1. - out["late_days"] * float(A(params, "late_sowing.pen_per_day")))
                           if A(params, "late_sowing.enabled") else np.ones_like(out["late_days"]))
    out["yield_kg_ha"] *= out["late_factor"]
    out["closure_error_mm"] = (out["rain_total_mm"] + out["irrig_total_mm"] - out["eta_total_mm"] - out["runoff_total_mm"] - out["drainage_total_mm"]).sum(-1) - storage
    if params.get("record_daily"):
        out["daily"] = dict(zip(("dr", "ks", "eta", "need"), daily))
    return out


def simulate_plan(scen: dict, plan: Sequence[str], awc_mm_per_m: float, irrigation_available_mm: float,
                  params: dict | None = None) -> dict:
    """PlanResult for one rotation: dict of [S,4] arrays and [S] storage_change_mm / closure_error_mm."""
    b = simulate_batch(scen, [plan], awc_mm_per_m, irrigation_available_mm, params)
    out = {}
    for k, v in b.items():
        if k == "daily":
            out[k] = {n: x[0] for n, x in v.items()}
        elif isinstance(v, np.ndarray):
            out[k] = v[0]
        elif k != "plans":
            out[k] = v
    return out


# =====================================================================================================
# v4 (universal, any farm). Feature 2, Person 2. Everything above is the v3 Nalgonda code, kept working.
#
# One continuous daily root-zone water balance across the whole 4-year plan (FAO-56 ch.8, single Kc),
# vectorized over rotations and scenarios:
#   build_timeline(rotation, clim)   when each crop of the plan is planted and harvested at this location
#   yearly_supply(water, scenarios)  irrigation water available in each plan year (dry years get less, R6)
#   run_balance(timelines, ...)      the daily balance; returns season and yearly water numbers
#
# The soil is one column as deep as the deepest-rooted crop of the plan. It is split into the root zone of
# whatever is growing today (for bare soil: the thin layer that dries by evaporation) and the layer below.
# Rain and irrigation fill the root zone first, the surplus fills the layer below, and what is left drains
# away. When the root depth changes (planting, harvest) the column's water is shared out evenly by depth.
# Water in = water out exactly: rain + irrigation = ET + runoff + drainage + change in stored soil water.
# =====================================================================================================
from dataclasses import dataclass as _dc, field as _fld

from engine import crops as _crops

PLAN_YEARS_V4 = 4
NDOY = 365
D4 = PLAN_YEARS_V4 * NDOY


@_dc
class Segment:
    kind: str                 # "crop" (cash crop) or "cover"
    crop: str
    name: str
    plan_year: int            # 0..3: the plan year this crop belongs to (the year it is harvested in)
    start: int                # day index on the 4-year timeline; negative = planted before plan year 1 began
    days: int
    plant_doy: int            # 0-based day of year
    harvest_doy: int
    shifted: bool = False     # planted later than its preferred day because the field was still busy
    ky: float = 0.0
    heat_tmax_c: float = 99.0
    flower_start: int = 0     # day offset in the season where the heat-sensitive window starts
    flower_days: int = 0
    kc: np.ndarray = _fld(default=None, repr=False)
    root_depth_m: float = 0.0
    p: float = 0.5

    @property
    def end(self) -> int:
        return self.start + self.days - 1

    def idx(self) -> np.ndarray:
        """Timeline day indexes of the season (wrapped onto the 4-year cycle)."""
        return (self.start + np.arange(self.days)) % D4

    def timing(self) -> dict:
        return {"kind": self.kind, "crop": self.crop, "name": self.name, "plan_year": self.plan_year + 1,
                "plant_day_of_year": self.plant_doy + 1, "harvest_day_of_year": self.harvest_doy + 1,
                "season_days": self.days, "starts_in_previous_year": self.start < self.plan_year * NDOY,
                "planted_late_after_previous_crop": self.shifted}


@_dc
class Timeline:
    feasible: bool
    reason: str = ""
    crops: list = _fld(default_factory=list)          # normalized: 4 lists of crop ids
    cover_crops: list = _fld(default_factory=list)    # normalized: 4 cover ids or None
    segments: list = _fld(default_factory=list)       # cash crops first (in time order), then cover crops
    kc: np.ndarray = _fld(default=None, repr=False)   # [1460] crop coefficient (fallow value on bare days)
    zr: np.ndarray = _fld(default=None, repr=False)   # [1460] root-zone depth (m)
    p: np.ndarray = _fld(default=None, repr=False)    # [1460] depletion fraction
    irrigable: np.ndarray = _fld(default=None, repr=False)   # [1460] cash crop growing
    covered: np.ndarray = _fld(default=None, repr=False)     # [1460] crop or cover growing (runoff curve number)

    @property
    def cash(self) -> list:
        return [s for s in self.segments if s.kind == "crop"]


def normalize_rotation(rotation) -> tuple[list, list]:
    """Any rotation shape -> (4 lists of crop ids, 4 cover crop ids or None).

    Accepts a list of crop names, a list whose items are lists (double crops in one year), or an object or
    dict with crops and cover_crops. A shorter plan repeats to fill 4 years (corn, soy -> corn, soy, corn, soy).
    "fallow", "" or None in a year means nothing is grown that year.
    """
    cov = None
    if isinstance(rotation, dict):
        cr, cov = rotation.get("crops"), rotation.get("cover_crops")
    elif hasattr(rotation, "crops"):
        cr, cov = rotation.crops, getattr(rotation, "cover_crops", None)
    else:
        cr = rotation
    if isinstance(cr, str):
        cr = [cr]
    cr = list(cr or [])
    if not cr:
        raise ValueError("the rotation has no crops")

    def entry(e):
        if e is None or (isinstance(e, str) and e.strip().lower() in ("", "fallow", "none")):
            return []
        return [_crops.crop_id(e)] if isinstance(e, str) else [_crops.crop_id(x) for x in e]

    def cover(e):
        if e is None or str(e).strip().lower() in ("", "none", "no", "false"):
            return None
        return str(e).strip().lower().replace(" ", "_")

    crops4 = [entry(cr[i % len(cr)]) for i in range(PLAN_YEARS_V4)]
    cov = list(cov) if cov else [None]
    return crops4, [cover(cov[i % len(cov)]) for i in range(PLAN_YEARS_V4)]


def _clim_of(clim_or_weather) -> dict:
    return clim_or_weather if isinstance(clim_or_weather, dict) else _crops.climatology(clim_or_weather)


def build_timeline(rotation, clim_or_weather, irrigated: bool = True) -> Timeline:
    """Lay the plan's crops on a repeating 4-year (1460-day) timeline using this location's climate calendar.

    The crop of plan year y is the one harvested in year y (winter wheat harvested in year 2 was planted in
    the fall of year 1; for year 1 it wraps to the fall of year 4, because the plan repeats). A crop that
    would be planted while the field is still busy is planted after the previous harvest plus the turnaround
    days if the season still fits; if it does not, the rotation is not feasible and the reason says why.
    """
    clim = _clim_of(clim_or_weather)
    lib, covers = _crops.crop_library(), _crops.cover_crops()
    crops4, cov4 = normalize_rotation(rotation)
    turn = int(_crops.rule("turnaround_days"))

    def bad(reason):
        return Timeline(False, reason, crops4, cov4)

    segs = []
    for y, entry in enumerate(crops4):
        prev_end = None
        for j, cid in enumerate(entry):
            if cid not in lib:
                return bad(f"unknown crop '{cid}'")
            c = lib[cid]
            if j == 0:
                cal = _crops.crop_calendar(c, clim, irrigated=irrigated)
                if not cal.feasible:
                    return bad(f"{c.name}: {cal.reason}")
                start = y * NDOY + cal.harvest_doy - (cal.season_days - 1)
            else:
                e = prev_end + turn + 1
                cal = _crops.crop_calendar(c, clim, earliest=e % NDOY, irrigated=irrigated)
                if not cal.feasible:
                    return bad(f"{c.name} as a second crop: {cal.reason}")
                start = e + (cal.plant_doy - e) % NDOY
            segs.append([c, cal, y, start])
            prev_end = start + cal.season_days - 1
    if not segs:
        return bad("nothing is grown in any year")
    segs.sort(key=lambda s: s[3])
    n = len(segs)
    for i in range(n if n > 1 else 0):
        prev, cur = segs[i - 1], segs[i]
        prev_end = prev[3] + prev[1].season_days - 1 - (D4 if i == 0 else 0)
        if cur[3] < prev_end + turn + 1:
            e = prev_end + turn + 1
            cal = _crops.crop_calendar(cur[0], clim, earliest=e % NDOY, irrigated=irrigated)
            if not cal.feasible:
                return bad(f"{cur[0].name} cannot follow {prev[0].name}: {cal.reason}")
            cur[1], cur[3] = cal, e + (cal.plant_doy - e) % NDOY
    for i in range(n if n > 1 else 0):
        prev, cur = segs[i - 1], segs[i]
        prev_end = prev[3] + prev[1].season_days - 1 - (D4 if i == 0 else 0)
        if cur[3] < prev_end + 1:
            return bad(f"{cur[0].name} cannot follow {prev[0].name}: the seasons overlap")

    out = []
    for c, cal, y, start in segs:
        st = cal.stages_days
        out.append(Segment("crop", c.id, c.name, y, int(start), int(cal.season_days), int(cal.plant_doy),
                           int(cal.harvest_doy), bool(cal.shifted or start != y * NDOY + cal.harvest_doy - (cal.season_days - 1)),
                           ky=c.ky, heat_tmax_c=c.heat_tmax_c, flower_start=int(st[0] + st[1]),
                           flower_days=int(min(c.flowering_days, st[2])),
                           kc=_crops.kc_curve(st, cal.kc_ini, c.kc_mid, c.kc_end), root_depth_m=c.root_depth_m, p=c.p))
    # cover crops: in the gap after the last cash crop of a plan year, ended before the next cash crop is planted
    frozen = float(clim["tmean"][clim["coldest_doy"]]) < 0.0
    kc0 = float(_crops.rule("cover_kc_start_frozen" if frozen else "cover_kc_start"))
    min_days, before = int(_crops.rule("cover_min_days")), int(_crops.rule("cover_terminate_days_before"))
    cover_segs = []
    for i, s in enumerate(out):
        nxt = out[(i + 1) % n]
        last_of_year = not any(o.plan_year == s.plan_year and o.start > s.start for o in out)
        cid = cov4[s.plan_year]
        if cid is None or not last_of_year:
            continue
        if cid not in covers:
            return bad(f"unknown cover crop '{cid}'")
        cc = covers[cid]
        first = s.end + turn + 1
        last = nxt.start + (D4 if i == n - 1 else 0) - before - 1
        length = min(last - first + 1, cc.max_days)
        if length < min_days:
            continue                                   # gap too short: no cover crop this year
        cover_segs.append(Segment("cover", cc.id, cc.name, s.plan_year, int(first), int(length), int(first % NDOY),
                                  int((first + length - 1) % NDOY), kc=np.linspace(kc0, cc.kc_full, length),
                                  root_depth_m=cc.root_depth_m, p=cc.p))
    kc = np.full(D4, float(_crops.sim_setting("fallow", "kc")))
    zr = np.full(D4, float(_crops.sim_setting("fallow", "evap_depth_m")))
    pp = np.full(D4, float(_crops.sim_setting("fallow", "depletion_fraction")))
    irrigable, covered = np.zeros(D4, bool), np.zeros(D4, bool)
    for s in out + cover_segs:
        ix = s.idx()
        kc[ix], zr[ix], pp[ix], covered[ix] = s.kc, s.root_depth_m, s.p, True
        if s.kind == "crop":
            irrigable[ix] = True
    return Timeline(True, "", crops4, cov4, out + cover_segs, kc, zr, pp, irrigable, covered)


def scs_runoff_v4(precip, cn: float, ia_ratio: float):
    """Daily runoff (mm) by the SCS curve number method (NRCS NEH 630 ch.10): Q = (P - Ia)^2 / (P - Ia + S)."""
    s = 25400.0 / cn - 254.0
    ia = ia_ratio * s
    pe = np.maximum(np.asarray(precip, float) - ia, 0.0)
    return pe * pe / (pe + s)


def curve_numbers(hydrologic_group: str | None) -> tuple[float, float]:
    """(curve number under a crop, curve number on bare soil) for the soil's hydrologic group (A to D)."""
    g = str(hydrologic_group or _crops.rule("default_hydrologic_group")).strip().upper()[:1]
    if g not in "ABCD" or not g:
        g = str(_crops.rule("default_hydrologic_group"))
    return (float(_crops.sim_setting("hydrology", f"cn_crop_group_{g}")),
            float(_crops.sim_setting("hydrology", f"cn_fallow_group_{g}")))


def yearly_supply(water, scenarios) -> np.ndarray:
    """[S,4] irrigation water available in each plan year (mm).

    Rain-fed: 0. Irrigated with no amount given: unlimited. Otherwise the farmer's normal-year amount, falling
    in a straight line to the dry-year amount as that plan year's rainfall falls from the record's median year
    to its dry year (rule dry_year_quantile, default a 1-in-10 dry year) (R6). Never above the normal amount.
    """
    get = (lambda k: water.get(k)) if isinstance(water, dict) else (lambda k: getattr(water, k, None))
    shape = (scenarios.n, PLAN_YEARS_V4)
    mode = str(get("mode") or "rain").lower()
    if water is None or mode.startswith("rain"):
        return np.zeros(shape)
    normal = get("normal_mm")
    if normal is None:
        return np.full(shape, np.inf)
    normal = max(float(normal), 0.0)
    dry = get("dry_mm")
    dry = normal if dry is None else min(max(float(dry), 0.0), normal)
    rain = scenarios.annual_rain()
    span = max(scenarios.rain_normal_mm - scenarios.rain_dry_mm, 1e-9)
    return dry + (normal - dry) * np.clip((rain - scenarios.rain_dry_mm) / span, 0.0, 1.0)


def run_balance(timelines, scenarios, supply, awc_mm_per_m: float, hydrologic_group: str | None = None,
                keep_daily: bool = False) -> dict:
    """Daily water balance of R timelines over S scenarios (all feasible timelines; arrays are [R,S,...]).

    Each day, in this order: rain minus runoff soaks in; on cash-crop days the farmer irrigates just enough to
    keep the crop out of water stress today, as long as this year's supply lasts; the crop (or bare soil)
    takes ET, reduced when the root zone is drier than the FAO-56 readily available water; surplus water fills
    the layer below the roots and then drains. The plan repeats, so one full pass is run first to get a
    realistic soil water start, and the second pass is reported.

    Returns per cash-crop season (K = most seasons in any timeline; unused slots are NaN):
      eta, etm, irr_season [R,S,K] (mm)
    and per plan year [R,S,4] (mm): irrigation, eta_year, runoff, drainage, rain; plus storage_change [R,S],
    closure_error [R,S] (rain + irrigation - ET - runoff - drainage - storage change; 0 up to rounding),
    and with keep_daily=True the daily root-zone depletion, its limit and irrigation ([R,S,1460]).
    """
    tls = list(timelines)
    R, S = len(tls), scenarios.n
    et0 = scenarios.et0.reshape(S, D4)
    precip = scenarios.precip.reshape(S, D4)
    awc = float(awc_mm_per_m)
    KC = np.stack([t.kc for t in tls])
    TAW = awc * np.stack([t.zr for t in tls])                     # [R,D] root-zone capacity today
    RAW = np.stack([t.p for t in tls]) * TAW
    IRR = np.stack([t.irrigable for t in tls])
    COV = np.stack([t.covered for t in tls])
    tawcol = TAW.max(axis=1)                                       # [R] whole column capacity
    cn_crop, cn_fallow = curve_numbers(hydrologic_group)
    ia = float(_crops.sim_setting("hydrology", "ia_ratio"))
    ro_crop, ro_fallow = scs_runoff_v4(precip, cn_crop, ia), scs_runoff_v4(precip, cn_fallow, ia)
    supply = np.broadcast_to(np.asarray(supply, float), (S, PLAN_YEARS_V4))

    K = max(len(t.cash) for t in tls)
    eta_s = np.full((R, S, K), np.nan)
    irr_s = np.full((R, S, K), np.nan)
    etm_s = np.full((R, S, K), np.nan)
    starts, ends = {}, {}
    for r, t in enumerate(tls):
        for k, s in enumerate(t.cash):
            starts.setdefault(s.start % D4, []).append(r)
            ends.setdefault(s.end % D4, []).append((r, k))
            etm_s[r, :, k] = et0[:, s.idx()] @ s.kc
    change = np.roll(TAW, 1, axis=1) != TAW                        # [R,D] root depth differs from yesterday
    change_rows = {d: np.nonzero(change[:, d])[0] for d in np.nonzero(change.any(axis=0))[0]}

    f0 = float(_crops.rule("init_depletion_frac"))
    dr = np.repeat((f0 * TAW[:, -1])[:, None], S, axis=1)          # root-zone depletion (mm)
    db = np.repeat((f0 * (tawcol - TAW[:, -1]))[:, None], S, axis=1)   # depletion of the layer below
    acc_eta, acc_irr = np.zeros((R, S)), np.zeros((R, S))
    yr = {k: np.zeros((R, S, PLAN_YEARS_V4)) for k in ("irrigation", "eta_year", "runoff", "drainage")}
    daily = {k: np.zeros((R, S, D4)) for k in ("depletion", "irrigation_daily")} if keep_daily else None
    rem = np.zeros((R, S))
    store0 = None
    for main in (False, True):
        if main:
            store0 = dr + db
        for d in range(D4):
            y = d // NDOY
            if d % NDOY == 0:
                rem = np.repeat(supply[None, :, y], R, axis=0)
            rows = change_rows.get(d)
            if rows is not None:                                   # root depth changed: share the water out by depth
                tot = dr[rows] + db[rows]
                dr[rows] = tot * (TAW[rows, d] / tawcol[rows])[:, None]
                db[rows] = tot - dr[rows]
            if d in starts:
                acc_eta[starts[d]] = 0.0
                acc_irr[starts[d]] = 0.0
            taw, raw = TAW[:, d, None], RAW[:, d, None]
            etc = KC[:, d, None] * et0[None, :, d]
            ro = np.where(COV[:, d, None], ro_crop[None, :, d], ro_fallow[None, :, d])
            x = dr - (precip[None, :, d] - ro)
            irr = np.minimum(rem, np.maximum(x + etc - raw, 0.0) * IRR[:, d, None])
            rem = rem - irr
            x = x - irr
            perc = np.maximum(-x, 0.0)
            x = np.maximum(x, 0.0)
            a = np.clip(raw - x, 0.0, etc)                         # taken at the full rate (no stress)
            eta = a + (taw - x - a) * -np.expm1(-(etc - a) / (taw - raw))   # the rest under stress (Ks < 1), exact
            dr = x + eta
            xb = db - perc
            drain = np.maximum(-xb, 0.0)
            db = np.maximum(xb, 0.0)
            acc_eta += eta
            acc_irr += irr
            if main:
                yr["irrigation"][:, :, y] += irr
                yr["eta_year"][:, :, y] += eta
                yr["runoff"][:, :, y] += ro
                yr["drainage"][:, :, y] += drain
                if keep_daily:
                    daily["depletion"][:, :, d] = dr
                    daily["irrigation_daily"][:, :, d] = irr
                for r, k in ends.get(d, ()):
                    eta_s[r, :, k] = acc_eta[r]
                    irr_s[r, :, k] = acc_irr[r]
    rain = np.broadcast_to(scenarios.annual_rain()[None], (R, S, PLAN_YEARS_V4))
    storage_change = store0 - (dr + db)                            # + = soil ended wetter than it started
    out = {"eta": eta_s, "etm": etm_s, "irr_season": irr_s, "rain": rain, "storage_change": storage_change, **yr}
    out["closure_error"] = (rain.sum(2) + yr["irrigation"].sum(2) - yr["eta_year"].sum(2) - yr["runoff"].sum(2)
                            - yr["drainage"].sum(2) - storage_change)
    if keep_daily:
        out.update(daily)
        out["root_zone_capacity"] = TAW
    return out
