# Product event contract and Experiment Studio

This document describes v2's canonical product-analytics contract. It is designed for an eventual production integration and for the repository's forthcoming **simulated** event harness. It is not a description of proprietary customer data.

## Journey

```text
serviceability_check -> browse -> add_to_cart -> checkout_started
    -> eta_promised -> order_completed | order_cancelled -> reorder
```

The location check is deliberately first. Expansion can increase serviceability; using all visitors as a conversion denominator would make a worthwhile expansion look worse simply by adding users that were previously ineligible. v2 therefore reports its north-star metric per eligible user.

## Required fields

| Field | Type | Purpose |
|---|---|---|
| `event_id` | string, unique | Idempotency and deduplication. |
| `event_at` | ISO-8601 timestamp | Event sequencing and period analysis; normalised to UTC. |
| `user_id` | string | User-level funnels and repeat measurement. |
| `session_id` | string | Session-level diagnostic cuts. |
| `event_name` | enum | One of the supported journey events. |
| `city` | string | City-level reporting. |
| `micro_market` | string | H3-cluster/locality decision context. |

`serviceability_check` additionally requires `is_serviceable`. Completed orders can carry `eta_promised_min` and `actual_delivery_min`, allowing ETA-breach measurement.

## Metric definitions

| Metric | Definition | Why it matters |
|---|---|---|
| Eligible users | Distinct users with a serviceable location check. | Separates access from conversion. |
| Reliable completed orders / eligible user | Distinct eligible users with `order_completed` divided by eligible users. | v2 north-star metric. |
| Browse-to-cart | Eligible users with cart event / eligible users with browse event. | Assortment and price/selection signal. |
| Cart-to-checkout | Eligible users with checkout event / eligible users with cart event. | Checkout friction signal. |
| Checkout completion | Eligible users with completed order / eligible users with checkout event. | Payment, ETA, and fulfilment signal. |
| ETA breach | Completed orders with actual delivery minutes over promised minutes / completed orders with both measurements. | Product-trust guardrail. |
| Cancellation | Eligible users with cancelled order / eligible users with checkout start. | Reliability and assortment guardrail. |
| Reorder | Eligible users with reorder / eligible users with completed order. | Retention signal; needs a fixed future observation window in production. |

## Simulated-event harness

`planner.simulation` provides a deterministic two-arm dataset for demos, tests, and dashboard development. Every row has `data_origin = simulated`; the persistence helper rejects any other value. The control/treatment arms differ only according to explicit configuration, allowing the dashboard to show an access/reliability trade-off without claiming a measured business result.

The initial simulator models serviceability, browse, cart, checkout, completion/cancellation, ETA promise/breach, and reorder. It persists to a DuckDB table named `simulated_product_events` only when a caller provides an explicit output path. It never writes to the shared v1 `data/processed` cache.

## Experiment Studio rules

- Unit of randomisation: eligible user, assigned before the experience differs.
- Primary metric: one pre-registered metric, normally reliable completed orders per eligible user.
- Guardrails: ETA breach, cancellation, and contribution per completed order are mandatory defaults.
- Minimum sample size: two-sided two-proportion planning estimate using baseline rate, absolute MDE, alpha, and power.
- Ship rule: the primary metric must clear its pre-registered MDE and guardrails must show no material regression.
- Simulation disclaimer: any example results generated in this repository test analytics mechanics only; they are not evidence of real causal impact.
