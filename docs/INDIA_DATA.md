# India data and cost basis

## District crop observations

The current file data/raw/icrisat_dld/nalgonda_apportioned_1966_2017.csv is the Nalgonda-only extraction from ICRISAT/TCI's apportioned Crops_Area Production Yield.csv, distributed in the World Bank reproducibility package RR_IND_2025_488.

Catalog: https://reproducibility.worldbank.org/catalog/409
Package download: https://reproducibility.worldbank.org/catalog/409/download/1152
Original DLD publisher: http://data.icrisat.org/dld/src/crops.html
License: CC BY 4.0, as stated in the archive catalog.

The direct publisher endpoint could not be retrieved. The archive member was recovered from its ZIP local record and verified against the complete member's CRC-32 data descriptor. SOURCE.json records the member SHA-256 and extracted-file SHA-256. Only Nalgonda rows were retained; the original columns and values are unchanged. The source labels the state Telangana and district code 59. The apportioned historical district differs from today's district boundary.

There are 52 positive-yield years each for rice, kharif sorghum, bajra and pigeonpea (1966-2017). Ragi has 17 (1969-2000). Both equally complete millets are selected; bajra remains the reference-plan millet. The loader prefers kharif sorghum and does not also ingest the annual sorghum yield column. Zero/negative sentinel yields are excluded rather than used as observations. The two bajra values of exactly 500 kg/ha in 2014 and 2015 are present in the archived source and are retained with this caveat.

Operational potential yield is the P90 of a linearly detrended crop series, recentered on its last observed year. It is a derived statistic, badge Modeled, not a farm observation. Hindcast potential yields and trends are estimated independently from training years only; the latest eight overlap years are held out. Weather overlap is 1984-2017. Ragi is available in the source but is not selected for optimization.

## Prices and budgets

Government source: https://www.pib.gov.in/PressReleasePage.aspx?PRID=2260617&reg=3&lang=1
Accessed 2026-11-14; marketing season 2026-27. Cached release: data/raw/msp_kharif_2026_27_pib_PRID2260617.html.

Official MSP / national A2+FL cost, Rs per quintal: paddy common 2441 / 1627; hybrid jowar 4023 / 2682; bajra 2900 / 1858; ragi 5205 / 3470; tur 8450 / 5496. These are not state-specific costs per acre. The cost concept includes paid-out expenses and imputed family labour, including ordinary irrigation and pump energy.

Rice and pigeon-pea costs use the official Telangana A2+FL cultivation survey: paddy Rs 72,353.64/ha and red gram Rs 33,341.27/ha in 2020-21, verified against https://www.pjtau.edu.in/Cost_Cultivation_Crops.html on 2026-11-15. They are scaled using the national 2026-27/2020-21 A2+FL unit-cost ratios (rice 1627/1245; tur 5496/3796) and 0.404686 ha/acre, giving rounded defaults Rs 38,265 and Rs 19,535 per acre. The historical survey is observed; scaling to current budgets is an assumption. The earlier PIB release is https://pib.gov.in/PressReleasePage.aspx?PRID=1628349.

Millet budgets remain assumptions: national A2+FL Rs/quintal times district potential kg/ha / 100 times 0.404686. No verified Telangana millet budget is bundled. Local cost overrides are preferable. Irrigation is already included in A2+FL; no extra water charge is deducted from profit.

Rice district yields are milled rice, per the ICRISAT apportioned-database documentation (https://vdsa.icrisat.org/Include/document/all-apportioned-web-document.pdf). Sales convert milled yield to paddy by dividing by 0.66. Model yields and validation remain in milled-rice units.

Nitrogen-credit savings use an assumed urea-equivalent price: Rs 266.50 per 45 kg bag divided by 46% nitrogen content. The official subsidized bag price is reported at https://www.pib.gov.in/PressReleasePage.aspx?PRID=2272695&lang=2&reg=3 (14 June 2026). This is a price proxy, not a purchase receipt, and does not validate the assumed legume credit.

No verified local soil-test or water-measurement quote was found. Those values remain null. EVPI is shown without a purchase verdict until an explicit quote is entered. Farm records and local cost overrides remain optional; no records are fabricated.

## Farm and soil

Farm input: 40 acres, black soil, rice-only baseline. SoilGrids is a separate district-point prediction. The black-soil capacity range and physical parameters retain their literature references and verification notes in config/farm.yaml and config/assumptions.yaml. Canal/well supply defaults are planning assumptions, not measurements of this farm.
