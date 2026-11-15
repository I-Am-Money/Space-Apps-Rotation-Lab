# AI use: this file was written and revised by Claude Code (Anthropic) under the team's direction. See AI_USE.md.
"""FAO-56 Chapter 4, Example 18: ET0 for 6 July at Uccle (Brussels), 50.80 N, 100 m.
Inputs: Tmax 21.5, Tmin 12.3 C; RHmax 84, RHmin 63 %; u2 = 2.078 m/s;
sunshine n = 9.25 h of N = 16.1 h. Published answer: ET0 = 3.9 mm/day
(Ra = 41.09, Rs = 22.07 MJ/m2/day, Rn = 13.28, ea = 1.409 kPa).
Source (read 2026-11-14): Allen et al. 1998, FAO-56, ch. 4 Example 18,
https://www.fao.org/4/x0490e/x0490e08.htm (inputs and the answer "3.9 mm/day" confirmed there;
u2 = 0.748 x 2.78 m/s from 10 km/h at 10 m height).
"""
import numpy as np
import pandas as pd

from engine.et0 import (et0_daily, et0_hargreaves, et0_penman_monteith,
                        extraterrestrial_radiation, _sat_vp)


def test_fao56_example_uccle():
    doy = 187  # 6 July
    ra, n = extraterrestrial_radiation(50.80, doy)
    assert abs(float(ra) - 41.09) < 0.3
    assert abs(float(n) - 16.1) < 0.1
    rs = (0.25 + 0.5 * 9.25 / 16.1) * float(ra)
    assert abs(rs - 22.07) < 0.3
    ea = (_sat_vp(12.3) * 0.84 + _sat_vp(21.5) * 0.63) / 2
    assert abs(float(ea) - 1.409) < 0.01
    et = et0_penman_monteith(21.5, 12.3, rs, 2.078, ea, 50.80, doy, 100.0)
    assert abs(float(et) - 3.9) < 0.2


def test_et0_daily_missing_falls_back_to_hargreaves(caplog):
    idx = pd.date_range("2001-06-01", periods=5)
    df = pd.DataFrame({"tmax": [33.0] * 5, "tmin": [24.0] * 5, "tmean": [28.0] * 5, "rh": [70.0] * 5,
                       "wind2": [2.0] * 5, "precip": [0.0] * 5, "srad": [20.0] * 5}, index=idx)
    df.loc[idx[2], "srad"] = -999
    with caplog.at_level("WARNING"):
        et = et0_daily(df, 17.5, 500)
    assert "Hargreaves" in caplog.text
    assert np.all(np.isfinite(et)) and np.all(et > 2) and np.all(et < 10)
    assert abs(et[2] - et0_hargreaves(33, 24, 17.5, idx[2].day_of_year)) < 1e-9
