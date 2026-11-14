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

Performance: simulate_batch vectorises over rotations x scenarios and loops only over days;
simulate_plan is the R = 1 case.
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


def _rice_phase(Dr, et0T, rainT, supply, kc, perc, hmax, taw, inv, dcol, rec=None, off=0):
    """Irrigated paddy daily loop. Returns Dr, and dict of season sums."""
    z = np.zeros_like(Dr)
    h = z.copy()
    out = {k: z.copy() for k in ("eta", "etm", "irr", "need", "dp", "ro", "rain")}
    for i in range(et0T.shape[0]):
        etc = kc[i] * et0T[i]
        rain = rainT[i]
        demand = etc + perc
        need = np.maximum(demand + Dr - (h + rain), 0.0)
        irr = np.minimum(need, supply)
        supply = supply - irr
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
        out["need"] += need
        out["dp"] += pact
        out["ro"] += over
        out["rain"] += rain
    out["ro"] += h          # drain the pond at harvest
    return Dr, out


def simulate_batch(scen: dict, plans: Sequence[Sequence[str]], awc_mm_per_m: float,
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
    avail = base * (np.maximum(rice_rain, 0.0) / max(med, 1e-9)) ** k   # [S,4]

    keys3 = ("yield_kg_ha", "eta_mm", "etm_mm", "rain_mm", "irrig_mm", "irrig_needed_mm", "runoff_mm",
             "drainage_mm", "puddle_mm", "rain_total_mm", "eta_total_mm", "runoff_total_mm",
             "drainage_total_mm", "irrig_total_mm")
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
                supply = np.broadcast_to(avail[:, y], (g, S)).copy()
                need_p = np.maximum(pud, d)                          # land prep + saturate soil
                irr_p = np.minimum(need_p, supply)
                supply = supply - irr_p
                fill = np.minimum(d, irr_p)
                d = d - fill
                dp_all += irr_p - fill                               # puddling water beyond soil fill leaves as drainage
                irr_all += irr_p
                inv = 1.0 / ((1.0 - c.p) * taw)
                d, o = _rice_phase(d, et0[:, y, a:b].T, precip[:, y, a:b].T, supply, kc, perc, hmax,
                                   taw, inv, dcol, rec, a)
                eta_all += o["eta"]; dp_all += o["dp"]; ro_all += o["ro"]; irr_all += o["irr"]
                res["eta_mm"][idx, :, y] = o["eta"]
                res["etm_mm"][idx, :, y] = o["etm"]
                res["irrig_mm"][idx, :, y] = irr_p + o["irr"]
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
