# AI use: written with AI coding assistants (Claude Code and OpenAI Codex) under the team's direction. See AI_USE.md.
"""Daily accounting kernel. Numba compiles the same equations without Python day loops."""
import numpy as np
import os

try:
    from numba import njit, prange, get_num_threads, set_num_threads
    if not os.environ.get("NUMBA_NUM_THREADS"):
        set_num_threads(min(4, get_num_threads()))
    ACCELERATED = True
except ImportError:
    ACCELERATED = False
    prange = range
    def njit(**kwargs):
        return lambda fn: fn


# Field ordering is shared with waterbalance.simulate_batch.
@njit(cache=True, parallel=True)
def run(plans, prefix_owner, et0, rain, tmax, starts, kc, lengths, roots, depletion, ky, ym,
        rotation, canal, well, awc, dcol, cn_crop, cn_fallow, ia_ratio,
        fallow_kc, fallow_taw, fallow_p, initial, percolation, puddling,
        bund, heat_on, heat_penalty, thresholds, flower_start, flower_length,
        record):
    nr, ns = plans.shape[0], rain.shape[0]
    out = np.zeros((19, nr, ns, 4))
    storage = np.zeros((nr, ns))
    end_dr = np.zeros((nr, ns, 4))
    daily = np.zeros((4, nr, ns, 4, 365 if record else 0))
    for s in prange(ns):
        for r in range(nr):
            dr = initial * dcol
            dr0 = dr
            for y in range(4):
                owner = prefix_owner[r, y]
                if owner != r:
                    for k in range(19):
                        out[k, r, s, y] = out[k, owner, s, y]
                    if record:
                        for k in range(4):
                            for day in range(365):
                                daily[k, r, s, y, day] = daily[k, owner, s, y, day]
                    dr = end_dr[owner, s, y]
                    end_dr[r, s, y] = dr
                    continue
                crop = plans[r, y]
                start = starts[s, y, crop]
                length = lengths[crop]
                end = min(start + length, 365)
                taw = awc * roots[crop]
                supply_c, supply_w = canal[s, y], well[s, y]
                pond, hot = 0., 0
                for day in range(365):
                    active = day >= start and day < end
                    p = rain[s, y, day]
                    e0 = et0[s, y, day]
                    irr, ic, iw, need, dp, ro, eta, etm = 0., 0., 0., 0., 0., 0., 0., 0.
                    if active and crop == 0:
                        if day == start:
                            prep = max(puddling, dr)
                            pc = min(prep, supply_c)
                            pw = min(prep - pc, supply_w)
                            supply_c -= pc
                            supply_w -= pw
                            fill = min(dr, pc + pw)
                            dr -= fill
                            dp += pc + pw - fill
                            irr += pc + pw
                            ic += pc
                            iw += pw
                            need += prep
                            out[8, r, s, y] = prep
                        etm = kc[crop, day - start] * e0
                        demand = max(etm + percolation + dr - (pond + p), 0.)
                        ac = min(demand, supply_c)
                        aw = min(demand - ac, supply_w)
                        supply_c -= ac
                        supply_w -= aw
                        irr += ac + aw
                        ic += ac
                        iw += aw
                        need += demand
                        water = pond + p + ac + aw
                        fill = min(dr, water)
                        dr -= fill
                        water -= fill
                        surface_et = min(etm, water)
                        water -= surface_et
                        ks = min(1., max(0., (taw - dr) / ((1. - depletion[crop]) * taw)))
                        root_et = min((etm - surface_et) * ks, dcol - dr)
                        dr += root_et
                        eta = surface_et + root_et
                        perc = min(percolation, water)
                        dp += perc
                        water -= perc
                        ro = max(water - bund, 0.)
                        pond = water - ro
                        if day == end - 1:
                            ro += pond
                            pond = 0.
                    else:
                        cn = cn_crop if active else cn_fallow
                        retention = 25400. / cn - 254.0
                        excess = max(p - ia_ratio * retention, 0.)
                        ro = excess * excess / (excess + retention)
                        effective = p - ro
                        rtaw = taw if active else fallow_taw
                        frac = depletion[crop] if active else fallow_p
                        ks = min(1., max(0., (rtaw - dr) / ((1. - frac) * rtaw)))
                        etm = (kc[crop, day - start] if active else fallow_kc) * e0
                        eta = min(ks * etm, dcol - dr + effective)
                        old_dr = dr
                        dr = dr - effective + eta
                        dp = max(-dr, 0.)
                        dr = max(dr, 0.)
                        if record:
                            daily[0, r, s, y, day] = old_dr
                    out[9, r, s, y] += p
                    out[10, r, s, y] += eta
                    out[11, r, s, y] += ro
                    out[12, r, s, y] += dp
                    out[13, r, s, y] += irr
                    if active:
                        out[1, r, s, y] += eta
                        out[2, r, s, y] += etm
                        out[3, r, s, y] += p
                        out[4, r, s, y] += irr
                        out[5, r, s, y] += need
                        out[6, r, s, y] += ro
                        out[7, r, s, y] += dp
                        out[14, r, s, y] += ic
                        out[15, r, s, y] += iw
                        age = day - start
                        if heat_on and age >= flower_start[crop] and age < flower_start[crop] + flower_length[crop]:
                            if tmax[s, y, day] > thresholds[crop]:
                                hot += 1
                    if record:
                        if active and crop == 0:
                            daily[0, r, s, y, day] = dr
                        daily[1, r, s, y, day] = ks
                        daily[2, r, s, y, day] = eta
                        daily[3, r, s, y, day] = need if active and crop == 0 else 0.
                if crop == 0:
                    out[16, r, s, y] = canal[s, y]
                    out[17, r, s, y] = well[s, y]
                ratio = min(1., max(0., out[1, r, s, y] / max(out[2, r, s, y], 1e-9)))
                # No harvest is claimed if onset is absent or maturity falls outside the modeled year.
                complete = start < 365 and start + length <= 365
                heat_factor = max(0., 1. - hot * heat_penalty)
                out[18, r, s, y] = hot
                if complete:
                    out[0, r, s, y] = ym[crop] * max(0., 1. - ky[crop] * (1. - ratio)) * rotation[r, y] * heat_factor
                end_dr[r, s, y] = dr
            storage[r, s] = dr0 - dr
    return out, storage, daily
