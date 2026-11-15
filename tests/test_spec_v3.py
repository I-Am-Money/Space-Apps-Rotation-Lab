# AI use: this file was written by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""Build Spec v3 section 11.2: one test per row of the table, named after the row, plus tests for the
monsoon-onset rule (6.2), the heat penalty (5.4), the soil-cover index (5.6) and the team's plan rule.

Synthetic weather (tests/synth.py, seed 42) is used only to exercise the physics; it is not data.
Tests that make a claim about Nalgonda use the cached NASA POWER record through engine.api.
"""
import numpy as np
import pandas as pd
import pytest

from engine import api_v3 as api, economics, monsoon
from engine import optimize as opt
from engine import scenarios as sc
from engine.crops import load_crops
from engine.waterbalance import simulate_batch, simulate_plan
from engine.yieldmodel import season_yield
from tests.synth import make_scen

AWC = 150.0
RAINFED = ["jowar", "bajra", "pigeonpea", "ragi"]
RICE4 = ["rice"] * 4


def with_onset(scen, onset=None, median=None):
    """Add a per-year monsoon onset to a synthetic scenario (computed with the real rule unless given)."""
    s = dict(scen)
    S = s["precip"].shape[0]
    on = (monsoon.onset_doy_years(s["precip"].reshape(-1, 365)).reshape(S, 4) if onset is None
          else np.broadcast_to(np.asarray(onset), (S, 4)).copy())
    s["onset_doy"] = on
    s["onset_median"] = float(np.median(on)) if median is None else float(median)
    return s


@pytest.fixture
def real():
    """The real engine on the cached Nalgonda record, 100 bootstrap scenarios (seed 42)."""
    opt.set_simulator(None); api.set_annual(None); api._scensets.clear()
    opt.configure()
    p = api.norm_params({})
    api._apply_sim_params(p)
    yield p, api.boot_set(100)
    api._scensets.clear()


# ------------------------------------------------------------------ the 16 rows of section 11.2
def test_et0_matches_fao56():
    """Reproduces the FAO-56 daily worked example (Example 18, Uccle, 6 July: 3.9 mm/day) within 0.2 mm/day."""
    from engine.et0 import _sat_vp, et0_penman_monteith, extraterrestrial_radiation
    ra, _ = extraterrestrial_radiation(50.80, 187)
    rs = (0.25 + 0.5 * 9.25 / 16.1) * float(ra)
    ea = (_sat_vp(12.3) * 0.84 + _sat_vp(21.5) * 0.63) / 2
    assert abs(float(et0_penman_monteith(21.5, 12.3, rs, 2.078, ea, 50.80, 187, 100.0)) - 3.9) < 0.2


def test_rainfed_mass_balance():
    """Sum P = sum ETa + sum RO + sum DP + change in storage, within 1e-6 mm (sowing moving with onset)."""
    r = simulate_plan(with_onset(make_scen(S=10)), RAINFED, AWC, 0.0)
    assert r["irrig_total_mm"].sum() == 0
    p = r["rain_total_mm"].sum(1)
    out = (r["eta_total_mm"] + r["runoff_total_mm"] + r["drainage_total_mm"]).sum(1) + r["storage_change_mm"]
    assert np.abs(p - out).max() < 1e-6


def test_paddy_water_accounting():
    """Rain + irrigation = ETa + percolation + runoff + change in storage, for plenty, short and no supply."""
    for avail in (0.0, 300.0, 900.0, 2000.0):
        r = simulate_plan(with_onset(make_scen(S=8)), RICE4, AWC, avail)
        inflow = (r["rain_total_mm"] + r["irrig_total_mm"]).sum(1)
        out = (r["eta_total_mm"] + r["drainage_total_mm"] + r["runoff_total_mm"]).sum(1) + r["storage_change_mm"]
        assert np.abs(inflow - out).max() < 1e-6
        assert np.all(r["irrig_mm"] <= r["irrig_needed_mm"] + 1e-9)        # never more than the paddy needs


def test_depletion_bounds():
    """0 <= Dr <= TAW; Ks = 1 while Dr <= RAW and below 1 after."""
    r = simulate_plan(make_scen(S=6, rain_mult=0.25), ["jowar", "bajra", "pigeonpea", "jowar"], AWC, 0.0, {"record_daily": True})
    dr, ks = r["daily"]["dr"], r["daily"]["ks"]
    assert dr.min() >= 0 and dr.max() <= r["dcol_mm"] + 1e-9
    c = load_crops()["jowar"]
    taw = AWC * c.root_depth_m
    sow, n = c.sowing_doy - 1, c.season_days
    d, k = dr[:, 0, sow:sow + n], ks[:, 0, sow:sow + n]
    below = d <= c.p * taw
    assert below.any() and (~below).any()
    assert np.all(k[below] == 1.0) and np.all(k[~below & (d < taw)] < 1.0)


def test_irrigation_need():
    """Never negative; near zero during sustained heavy rain."""
    for m in (0.0, 0.5, 1.0, 3.0):
        r = simulate_plan(make_scen(S=6, rain_mult=m), RICE4, AWC, 900.0, {"record_daily": True})
        assert r["daily"]["need"].min() >= 0 and r["irrig_needed_mm"].min() >= 0 and r["irrig_mm"].min() >= 0
    wet = make_scen(S=3)
    wet["precip"][:] = 40.0
    r = simulate_plan(wet, RICE4, AWC, 900.0, {"rice_irrigation.puddling_water_mm": 0.0})
    assert r["irrig_needed_mm"].max() < 1.0


def test_supply_monotonicity():
    """Less irrigation supply never raises rice yield."""
    scen = with_onset(make_scen(S=10))
    prev = None
    for avail in (2000, 1500, 1000, 600, 300, 0):
        y = simulate_plan(scen, RICE4, AWC, avail, {"median_season_rain_mm": 600.0})["yield_kg_ha"]
        assert prev is None or np.all(y <= prev + 1e-9)
        prev = y


def test_rainfall_monotonicity():
    """A lower rainfall multiplier never raises ANY crop's mean yield."""
    crops = ["rice", "jowar", "bajra", "ragi", "pigeonpea"]
    means = []
    for m in (0.5, 0.7, 0.9, 1.0, 1.1, 1.3):
        b = simulate_batch(make_scen(S=12, rain_mult=m), [[c] * 4 for c in crops], AWC, 900.0, {"median_season_rain_mm": 600.0})
        means.append(b["yield_kg_ha"].mean(axis=(1, 2)))
    assert np.all(np.diff(np.array(means), axis=0) >= -1e-9)


def test_onset_monotonicity(real):
    """A later monsoon onset never raises mean yield (real Nalgonda record, every crop in the tool)."""
    p, bs = real
    plans = [[c] * 4 for c in opt.CROPS]
    prev = None
    for delay in (0, 5, 10, 15, 20, 25, 30):
        s = bs.derive(shift_days=delay)
        b = simulate_batch(s.scen, plans, p["awc"], p["irrigation_mm"], opt.params_for(p["irrigation_mm"]))
        m = b["yield_kg_ha"].mean(axis=(1, 2))
        assert prev is None or np.all(m <= prev + 1e-9), (delay, m, prev)
        prev = m


def test_water_saving():
    """Rotations with millet use less irrigation water than rice-only under identical weather (every scenario)."""
    scen = with_onset(make_scen(S=10))
    irr = lambda plan: simulate_plan(scen, plan, AWC, 900.0)["irrig_mm"].sum(axis=1)
    a = irr(RICE4)
    for plan in (["rice", "bajra", "rice", "bajra"], ["rice", "pigeonpea", "bajra", "rice"], ["rice", "jowar", "rice", "rice"]):
        assert np.all(irr(plan) < a)


def test_legume_effect():
    """The crop after pigeon pea out-yields the same crop after itself under identical weather."""
    scen = with_onset(make_scen(S=8, rain_mult=1.5))
    for crop in ("rice", "bajra", "jowar", "ragi"):
        after_pp = simulate_plan(scen, ["pigeonpea", crop, "rice", "rice"], AWC, 900.0)["yield_kg_ha"][:, 1]
        after_self = simulate_plan(scen, [crop, crop, "rice", "rice"], AWC, 900.0)["yield_kg_ha"][:, 1]
        assert np.all(after_pp >= after_self) and after_pp.mean() > after_self.mean()


def test_yield_limits():
    """ETa = ETm gives Ya = Ym; Ya is never negative."""
    assert season_yield(5000, 1.09, 600, 600, 1.0) == 5000
    assert season_yield(5000, 1.5, 0.0, 600, 1.0) == 0.0
    for m in (0.0, 1.0, 4.0):
        r = simulate_plan(make_scen(S=4, rain_mult=m), ["jowar", "bajra", "pigeonpea", "rice"], AWC, 0.0)
        assert np.all(r["yield_kg_ha"] >= 0)
        ym = np.array([load_crops()[c].ym_kg_ha for c in ["jowar", "bajra", "pigeonpea", "rice"]])
        assert np.all(r["yield_kg_ha"] <= ym[None, :] * 1.2 + 1e-9)      # only the rotation bonus can exceed Ym


def test_worst_10_percent_calc():
    """Matches a hand-computed value on a small array."""
    assert opt.worst_fraction_mean(np.arange(1, 21, dtype=float)) == 1.5        # two lowest of 20: (1 + 2) / 2
    assert opt.worst_fraction_mean(np.array([5.0, 3.0, 9.0])) == 3.0            # at least one value
    x = np.array([10.0, -4.0, 7.0, 3.0, 8.0, 2.0, 9.0, 6.0, 5.0, 1.0] * 3)      # 30 values: three lowest are all -4
    assert opt.worst_fraction_mean(x) == -4.0


def test_lambda_endpoints():
    """lam = 0 picks the highest mean; lam = 1 picks the highest worst-10%."""
    df = pd.DataFrame({"id": ["rice-rice-rice-rice", "x", "y"], "plan": [RICE4, ["x"], ["y"]], "offered": True,
                       "mean_profit": [100.0, 140.0, 120.0], "worst10_profit": [60.0, 20.0, 90.0],
                       "irrigation_mm": [2000.0, 900.0, 1000.0], "total_water_mm": 0.0, "water_stress_mm": 0.0})
    df.attrs["scale"] = 0.2
    assert opt.recommend_from_table(opt.rescore(df, 0.0, 0.0))["top"]["id"] == "x"
    assert opt.recommend_from_table(opt.rescore(df, 1.0, 0.0))["top"]["id"] == "y"


def test_unit_conversion():
    """kg/ha to quintals/acre and INR/ha to INR/acre match hand calculations; so does one year of profit."""
    # 1 acre = 0.404686 ha, 1 quintal = 100 kg: 2,471.05 kg/ha = 10.0000 quintals/acre
    assert abs(float(economics.kg_ha_to_quintal_acre(2471.05)) - 10.0) < 1e-4
    assert abs(float(economics.kg_ha_to_quintal_acre(1000.0)) - 4.04686) < 1e-9
    # 100,000 INR/ha = 40,468.6 INR/acre
    assert abs(float(economics.rs_ha_to_rs_acre(100000.0)) - 40468.6) < 1e-6
    pr = economics.load_prices()
    # operating cost of rice by hand: 72,353.64 Rs/ha x (1627 / 1245) x 0.404686 = 38,265 Rs/acre (rounded in the YAML)
    assert abs(72353.64 * (1627 / 1245) * 0.404686 - pr["operating_cost_rs_per_acre"]["rice"]) < 1.0
    # one rice year by hand: 3,000 kg/ha milled rice = 3000 / 0.66 = 4,545.45 kg/ha paddy = 1,839.48 kg/acre
    # = 18.3948 quintals/acre x 2,441 Rs = 44,901.8 Rs/acre; minus 38,265 Rs/acre cost = 6,636.8 Rs/acre
    sim = {"yield_kg_ha": np.full((1, 4), 3000.0)}
    e = economics.plan_economics(RICE4, sim, 1.0, pr, n_credit=np.zeros(4))
    assert abs(e["sold_kg_acre"][0, 0] - 1839.4818) < 1e-3
    assert abs(e["revenue"][0, 0] - 44901.75) < 0.1
    assert abs(e["profit_year"][0, 0] - (44901.75 - pr["operating_cost_rs_per_acre"]["rice"])) < 0.1
    assert abs(e["profit"][0] - 4 * e["profit_year"][0, 0]) < 1e-6       # plan profit = sum of 4 years, undiscounted


def test_data_sanity(real):
    """No -999 or NaN reaches the engine; complete years; units in range."""
    a = api.annual()
    Y = len(a["years"])
    assert Y >= 40 and list(a["years"]) == list(range(int(a["years"][0]), int(a["years"][0]) + Y))     # no missing year
    for k in ("et0", "precip", "tmax"):
        x = np.asarray(a[k])
        assert x.shape == (Y, 365) and np.all(np.isfinite(x)) and x.min() > -100
    assert a["precip"].min() >= 0 and a["precip"].max() < 500            # mm/day
    assert 1 < a["et0"].mean() < 9                                        # mm/day
    assert 20 < a["tmax"].mean() < 45                                     # degC
    on = np.asarray(a["onset"])
    q = monsoon.onset_params()
    assert on.shape == (Y,) and on.min() >= q["start_doy"] and on.max() <= q["last_doy"]


def test_determinism(real):
    """Two runs with seed 42 are identical."""
    p, bs = real
    a = api.annual()
    b1, b2 = sc.bootstrap_plans(a, 50, 42), sc.bootstrap_plans(a, 50, 42)
    assert np.array_equal(b1.scen["year_idx"], b2.scen["year_idx"]) and np.array_equal(b1.scen["precip"], b2.scen["precip"])
    assert not np.array_equal(b1.scen["year_idx"], sc.bootstrap_plans(a, 50, 43).scen["year_idx"])
    prm = opt.params_for(p["irrigation_mm"])
    r1 = simulate_plan(b1.scen, ["rice", "pigeonpea", "bajra", "rice"], p["awc"], p["irrigation_mm"], prm)
    r2 = simulate_plan(b2.scen, ["rice", "pigeonpea", "bajra", "rice"], p["awc"], p["irrigation_mm"], prm)
    assert np.array_equal(r1["yield_kg_ha"], r2["yield_kg_ha"]) and np.array_equal(r1["irrig_mm"], r2["irrig_mm"])


# ------------------------------------------------------------------ monsoon onset (section 6.2)
def _year(events):
    p = np.zeros(365)
    for doy, mm in events:
        p[doy - 1] = mm
    return p


def test_onset_rule_by_hand():
    q = monsoon.onset_params()
    assert (q["start_doy"], q["window_days"], q["threshold_mm"], q["dry_spell_days"], q["dry_spell_mm"]) == (152, 5, 25.0, 10, 5.0)
    follow = [(d, 8.0) for d in range(165, 300, 4)]                 # steady rain afterwards: no dry spell
    # 30 mm on day 160: the first 5-day window (starting on or after day 152) holding 25 mm starts on day 156
    assert monsoon.onset_doy(_year([(160, 30.0)] + follow)) == 156
    # false start: 30 mm on day 155, then nothing until day 180 (a dry spell of more than 10 days) -> not an onset.
    # The real onset is the wet window that contains day 180: it starts on day 176.
    real_rain = [(180, 30.0)] + [(d, 8.0) for d in range(184, 300, 4)]
    assert monsoon.onset_doy(_year([(155, 30.0)] + real_rain)) == 176
    # rain before 1 June never counts
    assert monsoon.onset_doy(_year([(140, 80.0), (160, 30.0)] + follow)) == 156
    # no rain at all: no clean onset, the last allowed day is used
    assert monsoon.onset_doy(np.zeros(365)) == q["last_doy"]


def test_sowing_follows_onset_and_is_capped():
    # base sowing day 180 in a median-onset (day 162) year; onset 10 days late -> sow 10 days late
    assert int(monsoon.sowing_doy(180, 120, 172, 162)) == 190
    assert int(monsoon.sowing_doy(180, 120, 152, 162)) == 170
    assert int(monsoon.sowing_doy(180, 120, 172, 162, delay_days=10)) == 200
    assert int(monsoon.sowing_doy(180, 120, 300, 162)) == 365 - 120 + 1          # the season must end inside the year
    assert list(monsoon.sowing_doy(180, 120, np.array([162, 170]), 162)) == [180, 188]


def test_simulator_sows_later_when_onset_is_later():
    base = make_scen(S=4)
    c = load_crops()["bajra"]
    early = simulate_plan(with_onset(base, onset=160, median=160), ["bajra"] * 4, AWC, 0.0)
    late = simulate_plan(with_onset(base, onset=175, median=160), ["bajra"] * 4, AWC, 0.0)
    assert np.all(early["sowing_doy"] == c.sowing_doy) and np.all(late["sowing_doy"] == c.sowing_doy + 15)
    assert np.abs(late["closure_error_mm"]).max() < 1e-6
    # late-sowing penalty (assumption, toggle): 0.3 percent of yield per day sown after the median-year date
    assert np.all(early["late_days"] == 0) and np.all(late["late_days"] == 15) and np.allclose(late["late_factor"], 1 - 0.003 * 15)
    off = simulate_plan(with_onset(base, onset=175, median=160), ["bajra"] * 4, AWC, 0.0, {"late_sowing.enabled": False})
    assert np.all(off["late_factor"] == 1.0) and np.allclose(late["yield_kg_ha"], off["yield_kg_ha"] * (1 - 0.003 * 15))
    sooner = simulate_plan(with_onset(base, onset=150, median=160), ["bajra"] * 4, AWC, 0.0)
    assert np.all(sooner["late_factor"] == 1.0)                       # sowing early earns no bonus


def test_onset_summary_for_our_farm_tab(real):
    s = monsoon.summary(api.annual())
    assert len(s["onset_doy"]) == len(s["years"]) and s["earliest_doy"] <= s["median_doy"] <= s["latest_doy"]
    assert s["badge"] == "modeled" and s["rain_badge"] == "observed" and "1 June" in s["rule"]


# ------------------------------------------------------------------ heat penalty (section 5.4)
def test_heat_penalty_counts_hot_days_at_flowering():
    scen = with_onset(make_scen(S=3, rain_mult=3.0), onset=160, median=160)
    c = load_crops()["rice"]
    cool = simulate_plan(scen, RICE4, AWC, 2000.0)
    assert np.all(cool["hot_days"] == 0) and np.all(cool["heat_factor"] == 1.0)        # 32 degC all year: no penalty
    hot = dict(scen); hot["tmax"] = scen["tmax"].copy()
    f0 = c.sowing_doy - 1 + c.stages_days[0] + c.stages_days[1]                        # first day of flowering (0-based)
    hot["tmax"][:, 0, f0:f0 + 5] = 41.0                                                # 5 hot days, year 1 only
    r = simulate_plan(hot, RICE4, AWC, 2000.0)
    assert np.all(r["hot_days"][:, 0] == 5) and np.all(r["hot_days"][:, 1:] == 0)
    assert np.allclose(r["yield_kg_ha"][:, 0], cool["yield_kg_ha"][:, 0] * (1 - 0.01 * 5))     # 1 percent per hot day
    assert np.allclose(r["yield_kg_ha"][:, 1:], cool["yield_kg_ha"][:, 1:])
    off = simulate_plan(hot, RICE4, AWC, 2000.0, {"heat.enabled": False})                      # the toggle
    assert np.allclose(off["yield_kg_ha"], cool["yield_kg_ha"])
    hot2 = dict(scen); hot2["tmax"] = scen["tmax"].copy()
    hot2["tmax"][:, 0, f0 - 30:f0 - 20] = 41.0                                         # heat outside flowering: no penalty
    assert np.allclose(simulate_plan(hot2, RICE4, AWC, 2000.0)["yield_kg_ha"], cool["yield_kg_ha"])


def test_warming_never_raises_mean_yield(real):
    p, bs = real
    plans = [[c] * 4 for c in opt.CROPS]
    prev = None
    for dT in (0.0, 1.0, 2.0, 3.0):
        b = simulate_batch(bs.derive(dT=dT).scen, plans, p["awc"], p["irrigation_mm"], opt.params_for(p["irrigation_mm"]))
        m = b["yield_kg_ha"].mean(axis=(1, 2))
        assert prev is None or np.all(m <= prev + 1e-9)
        prev = m


# ------------------------------------------------------------------ soil cover (5.6) and the plan rule
def test_soil_cover_index_and_direction():
    a = api.soil_cover_trend(RICE4)
    assert a["soc_direction"] == "flat" and np.allclose(a["index"], a["start"])
    c = api.soil_cover_trend(["rice", "pigeonpea", "bajra", "rice"])
    assert c["soc_direction"] == "up" and all(0 <= x <= 1 for x in c["index"])
    # by hand, carry 0.5: year 1 rice 0.40; year 2 pigeon pea 0.5 x 0.40 + 0.5 x 0.75 = 0.575
    assert abs(c["index"][1] - 0.575) < 1e-9
    assert "direction only" in c["soc_note"] and c["badge"] == "assumption"


def test_same_nonrice_crop_four_years_is_not_offered():
    opt.configure()
    assert opt.plan_allowed(RICE4) and not opt.plan_allowed(["pigeonpea"] * 4) and not opt.plan_allowed(["bajra"] * 4)
    assert opt.plan_allowed(["pigeonpea", "pigeonpea", "pigeonpea", "rice"])
    ids = {opt.plan_id(p) for p in opt.ALL_PLANS}
    assert "rice-rice-rice-rice" in ids and "pigeonpea-pigeonpea-pigeonpea-pigeonpea" not in ids
