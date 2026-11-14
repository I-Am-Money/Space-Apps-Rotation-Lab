# Limitations

RotationLab compares crop rotations using a simple water-balance model driven by real weather. It gives estimates, not guarantees.

1. **Estimates, not guarantees.** Outputs are model estimates under stated assumptions. They are not forecasts and not agronomic or financial advice. Review locally before acting.
2. **What-ifs are not forecasts.** Rainfall multipliers, +dT and late-monsoon shifts are what-if adjustments to real years, not forecasts. Warming raises ET0 by a documented scaling (4% per degC, assumption, team to verify), not a full recomputation.
3. **Weather is regional.** NASA POWER is a gridded product (about 0.5 degree, roughly 50 km). It is a regional estimate, not a measurement at your field. The district point is a DEV placeholder until the team sets the district in `config/region.yaml`.
4. **Weather record is trimmed to 1984-2025.** POWER solar radiation is missing for 1981-83 and we refuse to fill invented values, so the record starts in 1984. The number of historical 4-year blocks is derived from the record length. Fewer years mean a thinner tail for dry and hot extremes.
5. **Scenarios are resampled real years.** The 500 bootstrap plans draw 4 random real years (seed 42) and treat them as independent. Real multi-year droughts that persist longer than the record shows may be under- or over-represented. Overlapping historical blocks are strongly correlated.
6. **Rice is modeled as irrigated paddy with a limited, monsoon-linked water budget.** This is not a dryland model.
7. **Simplified recharge proxy.** Available irrigation is `base_available * (season_rain / median)^k`. This is a simplified recharge proxy for tanks and groundwater, team to verify.
8. **No rabi (yasangi) rice or other winter crops.** One kharif crop per year only.
9. **No multi-year groundwater depletion.** Water availability does not carry forward between years.
10. **District rice yields mix irrigated and rainfed fields.** Hindcast against ICRISAT district yields is therefore a weak test for rice. Weak correlations are reported as they are, with the reason.
11. **Prices are fixed.** Prices (MSP-based) are held constant across all scenarios; there is no price model or market risk. Any price, cost or measurement-cost value without a source in `config/prices_india.yaml` is an unverified placeholder and is badged so. Profits are undiscounted rupees per acre summed over 4 years.
12. **No soil nitrogen or carbon dynamics.** The nitrogen credit of a legume is a fixed per-year literature-based assumption converted to a fertiliser saving, not a simulated soil pool. Residue index is a proxy (modeled yield relative to the best modeled yield of that crop).
13. **Rotation effects are literature-based assumptions.** Rice-after-rice and millet-after-millet penalties and pigeon pea boosts come from `assumptions.yaml` ranges marked with their sources or "team to verify", not from this farm's trials.
14. **Candidate sets in boundary sweeps.** Rainfall crossovers, the decision grid and the EVPI calculations compare a candidate set of rotations (reference plans, monocultures, top-ranked plans), stated in each result. Crossovers are linearly interpolated between grid points.
15. **EVPI is an upper bound.** The expected value of perfect information assumes the measurement is exact and the uncertainty range is uniform over the stated range (assumptions, team to verify). A real soil test or borewell measurement is noisier and is worth less.
16. **Farm records.** If `data/raw/farm_records.csv` exists it is plotted as local input. Nothing is fabricated when it is absent.
17. **Hold-out is light.** The last 10 overlap years are not used to fit trends; there is no parameter tuning on any year, but 10 points give a noisy correlation.
