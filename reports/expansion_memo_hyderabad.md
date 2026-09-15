# Hyderabad: where Blinkit should open its next 10 dark stores (memo v1)

## Answer

- **Core picks** (proposed in at least 4 of 6 model runs across scenarios): **Amberpet** (500013), **Secunderabad** (500003), **Begumbazar** (500012).
- Under the base scenario, 10 new sites add **20,653 orders/day**, lifting served demand from 67.6% to 77.6%.
- In that base solution, 7,582 site orders/day come from areas no Blinkit store reaches today and 13,069 relieve stores already at capacity.
- Picks outside the core move with assumptions (store capacity above all). Treat them as areas to scout, not addresses.

## Robust areas (sites within 1 km grouped across all 6 runs)

| Area | Pincode | Lat, Lng | Runs proposing it | Median incremental orders/day | New-coverage share | Competitor stores (median) |
|---|---|---|---|---|---|---|
| Amberpet | 500013 | 17.3937, 78.5145 | 5/6 | 2,094 | 82% | 2.5 |
| Secunderabad | 500003 | 17.4305, 78.4915 | 4/6 | 2,094 | 48% | 2 |
| Begumbazar | 500012 | 17.3782, 78.4689 | 4/6 | 1,956 | 68% | 1 |
| Khairatabad | 500004 | 17.3930, 78.4692 | 3/6 | 2,094 | 0% | 2 |
| Saidabad (Hyderabad) | 500059 | 17.3493, 78.5159 | 3/6 | 2,094 | 70% | 4 |
| I.M.Colony | 500038 | 17.4298, 78.4442 | 3/6 | 2,094 | 0% | 3 |
| Secunderabad | 500003 | 17.4453, 78.4918 | 3/6 | 2,094 | 37% | 2 |
| Padmaraonagar | 500025 | 17.4233, 78.5087 | 2/6 | 2,094 | 3% | 1.5 |
| Meerpet | 500097 | 17.3310, 78.5391 | 2/6 | 2,094 | 0% | 2 |
| Saidabad (Hyderabad) | 500059 | 17.3453, 78.5006 | 2/6 | 1,966 | 100% | 1.5 |
| Dr As Rao Nagar | 500062 | 17.4837, 78.5703 | 2/6 | 1,890 | 82% | 2 |
| Anandbagh | 500017 | 17.4422, 78.5285 | 2/6 | 1,722 | 73% | 2.5 |
| Vivekanandanagar Colony | 500072 | 17.5070, 78.4090 | 2/6 | 1,450 | 63% | 1 |
| Vanastalipuram | 500070 | 17.3462, 78.5610 | 2/6 | 1,426 | 54% | 3.5 |

## Base-scenario solution (10 sites)

| Site | Locality | Pincode | Lat, Lng | Incremental orders/day | New coverage / capacity relief | Competitor stores reaching | Robust (scenarios) |
|---|---|---|---|---|---|---|---|
| 1 | Amberpet | 500013 | 17.38636, 78.51653 | 2,094 | 2,094 / 0 | 1 | 4/5 |
| 2 | Begumbazar | 500012 | 17.37816, 78.46891 | 2,094 | 1,660 / 434 | 1 | 3/5 |
| 3 | Huda Residential Complex | 500035 | 17.34929, 78.52009 | 2,094 | 1,297 / 797 | 4 | 2/5 |
| 4 | Secunderabad | 500003 | 17.43797, 78.49601 | 2,094 | 860 / 1,234 | 2 | 5/5 |
| 5 | Gandhinagar (Hyderabad) | 500080 | 17.41563, 78.49124 | 2,094 | 292 / 1,802 | 3 | 0/5 |
| 6 | Sitaphalmandi | 500061 | 17.42341, 78.51298 | 2,094 | 136 / 1,958 | 1 | 1/5 |
| 7 | Begumpet | 500016 | 17.43740, 78.46148 | 2,094 | 0 / 2,094 | 2 | 0/5 |
| 8 | Khairatabad | 500004 | 17.39300, 78.46921 | 2,094 | 0 / 2,094 | 2 | 2/5 |
| 9 | Huda Residential Complex | 500035 | 17.36470, 78.55494 | 2,094 | 0 / 2,094 | 5 | 0/5 |
| 10 | Uppal (K.V.Rangareddy) | 500039 | 17.41676, 78.56032 | 1,805 | 1,243 / 562 | 2 | 0/5 |

Robust = number of alternative scenarios that still place a site within 1 km.

## Scenarios

| Scenario | Incremental orders/day (top 10) | Base sites kept within 1 km |
|---|---|---|
| Adoption elasticity 0 (population only) | 20,429 | 4/10 |
| Adoption elasticity 1 (fully POI-driven) | 20,940 | 5/10 |
| Demand growth x1.5 | 20,940 | 1/10 |
| Store capacity 1,600 orders/day | 16,000 | 4/10 |
| Store capacity 3,000 orders/day | 17,344 | 3/10 |

## Does the model find where Blinkit actually builds? (hold-out validation)

20% of real Blinkit stores are hidden, 5 times; each method proposes the same number of sites. Recall = hidden stores with a proposed site within 1.5 km.

| method | recall | precision | median_km_true_to_pred |
|---|---|---|---|
| optimiser | 28% | 31% | 3.86 |
| top_demand_index | 22% | 29% | 3.88 |
| random_pop_weighted | 16% | 16% | 3.28 |
| top_unserved_hexes | 16% | 39% | 5.21 |

## Method (one paragraph)

Latent orders/day per H3 hex = population × a POI-based adoption multiplier, calibrated so hexes Blinkit covers today carry its disclosed throughput (Eternal Q4 FY26: 1,462 orders/day/store; snapshot store completeness 87%). A capacitated maximal-covering model (PuLP/CBC) keeps existing stores open, adds up to N sites that must clear the city's break-even orders/day (Week 3 unit economics), and lets hex demand split across any store within the calibrated 10-minute radius. Per-site gains are leave-one-out.

## Caveats

- Store locations are a third-party March 2026 snapshot (unlicensed, ~87% complete); some 'capacity relief' may be stores missing from it.
- One national capacity and throughput for every store; no city-specific order value or margins.
- Adoption multiplier weights are assumptions (swept in Scenarios); OpenStreetMap POI coverage varies by area.
- Competitor share is not modelled in demand; competitor presence is shown for context only.

![Map](network_hyderabad_base.png)
