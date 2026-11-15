# Limitations

RotationLab compares four-year crop plans with a simple daily water-balance model driven by real weather. It gives modeled estimates for planning. It does not give guarantees.

## The short list (Build Spec v3, section 14)

- Kharif only; rabi (yasangi) rice and winter crops not modeled; no intercropping.
- Weather is district-scale (NASA POWER grid), not field-specific.
- Irrigation supply uses a simplified proxy, not a groundwater or reservoir model.
- District yields mix many farms and both irrigated and rainfed rice.
- Prices and costs are fixed; market risk not modeled.
- Nitrogen and soil carbon are not simulated dynamically.
- Rotation effects are literature-based assumptions and need local calibration.
- Results are modeled estimates for planning, not guarantees.

## The longer list

### Inputs that still have no verified source
1. **Eleven model inputs in use are placeholders.** They are the yield-response factor Ky for rice, bajra and pigeon pea, the bajra early-season crop coefficient, the pigeon pea growth-stage lengths, three bare-soil (fallow) parameters, the pigeon-pea-after-pigeon-pea effect, and the cost of a soil test and of a water-supply measurement. The app counts them on the first screen and lists them, with a yellow Placeholder badge, under How Good Is This. Until they are replaced, treat every recommendation as a demonstration.
2. **Pigeon pea has no yield record for the district.** Its yield ceiling (741 kg per ha) comes from a state cost-of-cultivation survey, not a district series, and its crop coefficients are stand-ins from the closest legume in FAO-56, as the build spec allows. Nothing about pigeon pea is checked against observed yields. Pigeon pea appears in most recommended plans, so this is the weakest link in the tool.
3. **Bajra cost is the least certain cost.** There is no Telangana cost survey for bajra, so the cost is the all-India cost per quintal times the district yield ceiling. The same method lands 12 and 16 percent below the Telangana survey for rice and pigeon pea.
4. **Costs are scaled across years.** Telangana survey costs are for 2020-21 and are brought to 2026-27 with the change in the all-India cost per quintal. The scaling is ours.
5. **Water source and supply are assumptions.** The farm is modeled with canal water plus wells (600 mm and 400 mm a season by default). The owner has not confirmed either number. Both can be changed on the Our Farm tab.

### Weather and scenarios
6. **Weather is regional.** NASA POWER is a gridded product (about half a degree, roughly 50 km), read at the centre of Nalgonda district. It is not a measurement on the field.
7. **The record is 1984 to 2025 (42 years).** POWER solar radiation is missing for 1981 to 1983 and missing values are never filled in.
8. **Scenarios are resampled real years.** The 500 four-year plans draw real years at random (seed 42) and treat them as independent, so a drought that lasts several years in a row is under-represented. The Tipping Points tab uses the first 200 of the 500 to stay fast, so plans that are nearly tied can swap places between tabs.
9. **What-ifs are not forecasts.** The rainfall multiplier, added warming and late onset are edits to real years. Warming raises crop water demand by a fixed 4 percent per degree C (assumption) and adds hot days at flowering; it is not a full recomputation and not a climate projection.
10. **Monsoon onset is a rule, not an official date.** Onset is the first day from 1 June when at least 25 mm falls within 5 days and no 10-day dry spell follows in the next 30 days. The rule follows Build Spec v3, section 6.2; the window, threshold and dry-spell length are the team's choices (assumptions). Sowing follows it within fixed windows. The late-onset what-if removes the rain of the first days and sows later.
11. **Late sowing costs yield by assumption.** Each day of sowing after the usual date takes 0.3 percent off yield (team to verify). Without it, a late start could raise modeled yield slightly by dodging heat, which is not credible. It can be turned off in `config/assumptions.yaml`.
12. **Heat at flowering is a simple count.** Each day above a crop's limit during flowering takes 1 percent off yield (spec default). The temperature limits are assumptions.

### Water and soil
13. **Rice is irrigated paddy with a limited supply.** Canal supply is scaled from monsoon rain at five NASA POWER points upstream of Nagarjuna Sagar. That is a stand-in for canal releases, not a reservoir model, and real releases depend on decisions the model does not see. Wells use a simple recharge rule with a ceiling. Nothing carries over from one year to the next, so groundwater depletion is not modeled.
14. **"Low canal release year"** is the real year with the least upstream rain in the record. It is a stand-in for a poor release year, not a record of one.
15. **Black soil is modeled as a deep clay bucket.** Water holding capacity is the midpoint of a published range for Indian Vertisols (145 to 380 mm per m). Cracking and bypass flow are not modeled. Runoff uses curve numbers for hydrologic group D (assumption).
16. **Soil cover and soil carbon are indicators only.** The soil-cover index is a per-crop rule of thumb scaled by modeled yield, and the soil-carbon arrow only shows direction. Nitrogen after pigeon pea is a fixed credit priced at the urea price, not a simulated soil pool.

### Money
17. **Prices are fixed.** Crops are valued at the 2026-27 minimum support price in every scenario. Many farmers sell below it, pigeon pea and bajra especially. There is no price model.
18. **Rice is sold as paddy.** District yields are reported as milled rice (paddy times 0.66), so modeled rice is converted back to paddy before it is priced.
19. **Profit is undiscounted rupees per acre summed over four years.** No loans, no rent, no change in costs when the plan changes machinery or labour.
20. **Saving water is a preference, not income.** The water slider subtracts a value for irrigation water in the ranking only (up to Rs 50 per mm per hectare, an assumption). It is never taken off the profit shown.

### The decision maths
21. **Plans the tool will not offer.** The same non-rice crop in all four years is blocked (a team rule for disease and soil reasons). Rice every year stays because it is the farm today. That leaves 79 plans.
22. **Close calls.** Plans that differ only in which year a crop is grown often score within a few rupees of each other. The app marks any gap under Rs 500 per acre as a tie. That threshold is a rule of thumb, not a statistical test.
23. **The tipping line is interpolated.** It is found on a grid of rainfall and supply values and compares a short list of candidate plans (stated on screen). The band around it is the 10th to 90th percentile when the weather record is resampled.
24. **The value of a measurement is an upper bound.** It assumes the soil test or water measurement is exact and that the unknown value is equally likely anywhere in its range. A real measurement is worth less. With no sourced cost for the measurement, the app says so and does not say whether it is worth buying.

### How well the model is checked
25. **The check is weak, and it is shown as it is.** Against district rice yields the correlation is 0.56 over 26 years and 0.51 on the last 8 years, which are held out. For bajra it is 0.33 and 0.64. District rice mixes irrigated and rainfed fields over a district larger than today's Nalgonda, and the model overshoots district rice by about 360 kg per ha on average. No parameter was tuned to these yields.
26. **The yield panel is third-party.** The ICRISAT site could not be reached, so yields come from a published panel built on ICRISAT district data (Mendeley Data, doi 10.17632/ywp3y5j9vv.1), 1990 to 2015, rice and pearl millet only.
27. **Farm records.** If `data/raw/farm_records.csv` exists it is plotted as local input. When it is absent, nothing is made up.
28. **The map.** NASA GIBS layers load live from NASA when the app has internet. They are pictures for context and are not used in the calculation.
