# Three-city dark-store expansion comparison

| City | Latent demand/day | % served today | N=10 incremental orders/day | % served after N=10 | Hold-out recall@1.5km (optimiser / demand-index) | Core picks |
|---|---|---|---|---|---|---|
| Hyderabad | 206,463 | 67.6% | +20,653 | 77.6% | 28.4% / 22.1% | 3 |
| Bengaluru | 322,808 | 74.0% | +20,230 | 80.3% | 43.3% / 22.7% | 4 |
| Pune | 158,052 | 74.4% | +20,268 | 87.3% | 40.0% / 21.2% | 3 |

Bengaluru has the largest latent demand and the largest absolute pool not served by the current network, while Pune gains the most coverage from its first ten sites. Bengaluru also has the strongest validation edge over the demand-index heuristic; Pune is close behind, whereas Hyderabad's small edge is within noise. Core-pick counts are scenario-stable areas proposed in at least four of the six base-plus-scenario runs.
