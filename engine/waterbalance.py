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


def _record(rec, name, day, v, val):
    """Write one day's values into the daily record, only for the scenarios that are in this phase on that day."""
    rec[name][:, v, day] = val[:, v]


def _dry_phase(Dr, kcet0T, peT, taw, inv, dcol, rec=None, day0=0, valid=None):
    """Rainfed / fallow daily loop over calendar days day0, day0+1, ... Dr [g,S]; kcet0T, peT [n,S] are zero for the
    scenarios that are not in this phase on that day (valid [n,S] False), and a zero day changes nothing.
    Returns Dr, sum ETa, sum drainage."""
    se = np.zeros_like(Dr)
    sd = np.zeros_like(Dr)
    for i in range(kcet0T.shape[0]):
        ks = (taw - Dr) * inv
        np.clip(ks, 0.0, 1.0, out=ks)
        eta = ks * kcet0T[i]
        pei = peT[i]
        np.minimum(eta, dcol - Dr + pei, out=eta)
        if rec is not None:
            _record(rec, "dr", day0 + i, valid[i], Dr)
            _record(rec, "ks", day0 + i, valid[i], ks)
            _record(rec, "eta", day0 + i, valid[i], eta)
        Dr = Dr - pei + eta
        dp = np.maximum(-Dr, 0.0)
        np.maximum(Dr, 0.0, out=Dr)
        se += eta
        sd += dp
    return Dr, se, sd


def _rice_phase(Dr, et0T, rainT, supply, well, kc, perc, hmax, taw, inv, dcol, rec=None, day0=0, valid=None):
    """Irrigated paddy daily loop over calendar days day0, day0+1, ... kc, perc, et0T, rainT are [n,S] and are zero
    for scenarios outside their rice season on that day; such a day changes nothing (no demand, no rain, and the
    pond and the soil deficit are never both above zero). Returns Dr, and dict of season sums."""
    z = np.zeros_like(Dr)
    h = z.copy()
    out = {k: z.copy() for k in ("eta", "etm", "irr", "irr_c", "irr_w", "need", "dp", "ro", "rain")}
    for i in range(et0T.shape[0]):
        etc = kc[i] * et0T[i]
        rain = rainT[i]
        perc_i = perc[i]
        demand = etc + perc_i
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
        pact = np.minimum(perc_i, W)
        W = W - pact
        over = np.maximum(W - hmax, 0.0)
        h = W - over
        if rec is not None:
            _record(rec, "dr", day0 + i, valid[i], Dr)
            _record(rec, "ks", day0 + i, valid[i], ks)
            _record(rec, "eta", day0 + i, valid[i], e1 + e2)
            _record(rec, "need", day0 + i, valid[i], need)
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

    # --- sowing follows monsoon onset (v3 section 6.2). scen["onset_doy"] [S,4] (1-based) comes from engine.scenarios;
    # without it (synthetic test scenarios) every crop is sown on its median-year date.
    from engine import monsoon
    onset = scen.get("onset_doy")
    med_onset = scen.get("onset_median")
    if onset is not None and med_onset is None:
        med_onset = float(np.median(onset))
    cols = np.arange(S)
    tmax = scen.get("tmax")
    heat_on = bool(A(params, "heat.enabled")) and tmax is not None
    pen_day = float(A(params, "heat.pen_per_day"))
    res["sowing_doy"] = np.zeros((R, S, 4))
    res["hot_days"] = np.zeros((R, S, 4))
    res["heat_factor"] = np.ones((R, S, 4))
    # late-sowing penalty (assumption, toggle): each day a crop is sown after its median-year date cuts Ya
    late_on = bool(A(params, "late_sowing.enabled"))
    late_pen = float(A(params, "late_sowing.pen_per_day"))
    res["late_days"] = np.zeros((R, S, 4))
    res["late_factor"] = np.ones((R, S, 4))

    dayidx = np.arange(NDAY)

    for y in range(4):
        et0_y, p_y = et0[:, y, :], precip[:, y, :]
        pef_y, pec_y, rof_y, roc_y = pe_fall[:, y, :], pe_crop[:, y, :], ro_fall[:, y, :], ro_crop[:, y, :]
        for cid in np.unique(plan_arr[:, y]):
            idx = np.where(plan_arr[:, y] == cid)[0]
            c = crops[cid]
            n = c.season_days
            if onset is None:
                sow = np.full(S, min(c.sowing_doy, NDAY - n + 1), int)
            else:
                sow = monsoon.sowing_doy(c.sowing_doy, n, np.asarray(onset)[:, y], med_onset)
            a_s = sow - 1                                           # [S] 0-based first day of the season
            b_s = a_s + n                                           # [S] first fallow day after harvest (<= 365)
            amin, amax, bmin, bmax = int(a_s.min()), int(a_s.max()), int(b_s.min()), int(b_s.max())
            g = len(idx)
            d = Dr[idx].copy()
            rec = {n_: np.zeros((g, S, NDAY)) for n_ in ("dr", "ks", "eta", "need")} if rec_on else None
            eta_all = np.zeros((g, S)); dp_all = np.zeros((g, S)); ro_all = np.zeros((g, S))
            irr_all = np.zeros((g, S))

            def fallow(d, lo, hi, valid):
                """Fallow over calendar days lo..hi-1; valid [hi-lo, S] marks the scenarios that are fallow that day."""
                if hi <= lo:
                    return d
                e0 = kc_f * et0_y[:, lo:hi].T * valid
                pe = pef_y[:, lo:hi].T * valid
                d, se, sd = _dry_phase(d, e0, pe, taw_f, inv_f, dcol, rec, lo, valid)
                eta_all[:] += se; dp_all[:] += sd
                ro_all[:] += (rof_y[:, lo:hi].T * valid).sum(axis=0)
                return d

            # each scenario: fallow on days [0, a_s), crop on [a_s, b_s), fallow on [b_s, 365). The three loops run over
            # calendar days; a scenario that is not in the phase on a day gets zeros there, which change nothing.
            d = fallow(d, 0, amax, dayidx[:amax, None] < a_s[None, :])
            kc_pad = np.append(c.kc_curve(), 0.0)
            taw = awc * c.root_depth_m
            sd_idx = dayidx[amin:bmax, None] - a_s[None, :]          # [L,S] day of the season, valid in 0..n-1
            valid = (sd_idx >= 0) & (sd_idx < n)
            kcT = kc_pad[np.where(valid, sd_idx, n)]                 # [L,S] Kc of each scenario on that calendar day
            et0T = et0_y[:, amin:bmax].T
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
                d, o = _rice_phase(d, et0T, p_y[:, amin:bmax].T * valid, supply, well, kcT, perc * valid, hmax,
                                   taw, inv, dcol, rec, amin, valid)
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
                e0 = kcT * et0T
                pe = pec_y[:, amin:bmax].T * valid
                d, se, sd = _dry_phase(d, e0, pe, taw, inv, dcol, rec, amin, valid)
                eta_all += se; dp_all += sd
                rsum = (roc_y[:, amin:bmax].T * valid).sum(axis=0)
                ro_all += rsum
                res["eta_mm"][idx, :, y] = se
                res["etm_mm"][idx, :, y] = e0.sum(axis=0)
                res["runoff_mm"][idx, :, y] = rsum
                res["drainage_mm"][idx, :, y] = sd
            res["rain_mm"][idx, :, y] = (p_y[:, amin:bmax].T * valid).sum(axis=0)
            d = fallow(d, bmin, NDAY, dayidx[bmin:, None] >= b_s[None, :])
            Dr[idx] = d
            res["rain_total_mm"][idx, :, y] = precip[:, y, :].sum(axis=1)
            res["eta_total_mm"][idx, :, y] = eta_all
            res["runoff_total_mm"][idx, :, y] = ro_all
            res["drainage_total_mm"][idx, :, y] = dp_all
            res["irrig_total_mm"][idx, :, y] = irr_all
            res["sowing_doy"][idx, :, y] = sow
            # heat penalty (v3 section 5.4): hot days in the flowering window cut the yield
            hf = np.ones(S)
            if heat_on:
                f0 = int(c.stages_days[0] + c.stages_days[1])                 # flowering starts with the mid-season stage
                nf = int(A(params, f"heat.flowering_days.{cid}"))
                hotday = np.asarray(tmax, float)[:, y, :] > float(A(params, f"heat.tmax_c.{cid}"))      # [S,365]
                ch = np.concatenate([np.zeros((S, 1)), np.cumsum(hotday, axis=1)], axis=1)              # hot days before each day
                f_lo = np.minimum(a_s + f0, NDAY)
                f_hi = np.minimum(f_lo + nf, NDAY)
                hot = ch[cols, f_hi] - ch[cols, f_lo]
                hf = np.maximum(0.0, 1.0 - pen_day * hot)
                res["hot_days"][idx, :, y] = hot
                res["heat_factor"][idx, :, y] = hf
            late = np.maximum(sow - min(c.sowing_doy, NDAY - n + 1), 0)       # days sown after the median-year date
            lf = np.maximum(0.0, 1.0 - late_pen * late) if late_on else np.ones(S)
            res["late_days"][idx, :, y] = late
            res["late_factor"][idx, :, y] = lf
            ym = c.ym_kg_ha
            res["yield_kg_ha"][idx, :, y] = season_yield(ym, c.ky, res["eta_mm"][idx, :, y],
                                                         res["etm_mm"][idx, :, y], fr[idx, y][:, None]) * (hf * lf)[None, :]
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
