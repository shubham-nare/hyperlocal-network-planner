# Hyperlocal Growth & Reliability OS (v2 product charter)

## One-line product

An evidence-first decision system that helps a quick-commerce city team choose the best way to improve a micro-market's customer experience: open a store, extend coverage, add operating capacity, alter an ETA promise, or test an assortment intervention.

## Why v2 exists

The v1 Network Intelligence Engine answers a valuable but narrow supply question: where can a new dark store serve capacity-constrained or uncovered demand? Its public-data demand model, reach calibration, economics, optimiser, and three-city validation are retained unchanged.

The decision a product and city team actually faces is broader. A locality with poor customer access could need network coverage, rider capacity, a different promise, inventory availability, or a controlled experiment before capital is committed. v2 turns the v1 engine into one component of an operating product that frames those alternatives, measures their trade-offs, and produces a testable rollout plan.

## Target users

| User | Current pain | v2 outcome |
|---|---|---|
| City / operations lead | Receives maps and competing anecdotes, but lacks a comparable action plan. | A prioritised intervention with operational requirements and risk flags. |
| Product analyst | Needs a defensible funnel, metric definition, experiment setup, and post-launch reporting. | An experiment-ready decision card with primary and guardrail metrics. |
| APM / product manager | Must align product, operations, finance, and engineering around one ambiguous local problem. | A concise evidence brief, explicit assumptions, and a decision log. |
| Finance / network planning | Needs economics before committing to fixed capacity. | A scenario comparison with capacity, incremental service, break-even, and uncertainty. |

## Job to be done

When a neighbourhood has low serviceability, long delivery estimates, poor availability, or unmet demand, a city team needs to choose an intervention and a low-risk way to validate it, so it can improve completed orders and user reliability without creating uneconomic operations.

## Product decision loop

```text
Diagnose a locality
        -> compare plausible interventions
        -> expose economics, customer impact, and uncertainty
        -> design a controlled validation
        -> record the decision and monitor its outcomes
```

## The intervention catalogue

Every recommendation must select from an explicit set of actions rather than assuming a new store is the answer.

| Intervention | Use when | Customer-facing benefit | Key downside / guardrail |
|---|---|---|---|
| Open a dark store | Existing reach is insufficient or nearby stores are capacity constrained. | More serviceable users and better reliability. | Fixed cost, ramp-up risk, utilisation below break-even. |
| Extend service zone | Demand lies just outside the current network and the delivery budget permits it. | More eligible users. | ETA breach, cancellation, rider utilisation. |
| Add delivery / picking capacity | A served area is constrained by store or delivery capacity. | Fewer delays and higher completion. | Idle capacity, cost/order. |
| Change promise tier | Reliability supports a faster promise or an existing promise is unsafe. | Clearer, more credible customer expectation. | ETA-breach rate and trust loss. |
| Assortment / availability pilot | A locality appears attractive but inventory-fit is uncertain. | Better conversion and repeat potential. | Fill rate, waste, contribution/order. |

## MVP: what we will actually build

The MVP is deliberately narrow and demonstrable. It will work on the three existing cities and use one micro-market decision card as its central product object.

1. **Micro-market diagnostic** - show coverage, latent demand, capacity pressure, calibrated reach, competitor context, and data confidence for an H3 cluster.
2. **Intervention comparator** - compare the five actions above using transparent scenario logic. Store opening reuses v1's optimiser; other actions have clearly labelled scenario assumptions rather than invented ML predictions.
3. **Experiment Studio** - create a hypothesis, eligibility rule, primary metric, guardrails, rollout/holdout setup, minimum detectable effect, and decision rule.
4. **Product event model** - define and analyse the journey `serviceability_check -> browse -> add_to_cart -> checkout -> ETA_promise -> delivered/cancelled -> reorder`.
5. **Decision brief** - generate a shareable recommendation that names supporting evidence, input versions, assumptions, open risks, field checks, and experiment plan.

## Metrics tree

**North-star metric: reliable completed orders per eligible user.**

```text
Reliable completed orders per eligible user
|- Eligible users / serviceability rate
|- Conversion among eligible users
|  |- browse-to-cart rate
|  |- cart-to-checkout rate
|  `- checkout completion rate
|- Delivery reliability
|  |- ETA breach rate
|  `- cancellation rate
|- Repeat behaviour
|  `- 30-day reorder rate
`- Economic guardrails
   |- contribution per completed order
   |- store / delivery capacity utilisation
   `- intervention break-even coverage
```

The current repository does not have proprietary behavioural events. Any generated event stream is a **simulation harness**, never evidence of real customer behaviour or business impact. The dashboard must label it accordingly.

## Data and evidence policy

- Keep v1's public WorldPop, OpenStreetMap, road, pincode, public economics, and third-party store-snapshot sources.
- Preserve input versions and scenario parameters with every decision.
- Treat public data as evidence for relative opportunity, not proof of actual orders or retention.
- Do not scrape consumer apps or bypass a platform's terms of service.
- Distinguish four labels in the product: **observed public data**, **calibrated estimate**, **scenario assumption**, and **simulated experiment data**.

## Technical shape

```text
Public spatial inputs + v1 processed GeoPackages
                    |
              v1 planning engine
                    |
     micro-market diagnostic / intervention layer
          |                         |
    DuckDB product-event model   Experiment-design engine
          |                         |
          +----------- decision-card API -----------+
                                                      |
                                      Streamlit product workspace
                                                      |
                                  evidence-first decision brief
```

The first implementation stays Python, DuckDB, GeoPandas/H3, PuLP/CBC, and Streamlit. No LLM is added until every output has structured provenance; the AI layer will summarise and retrieve evidence, not replace the decision logic.

## Acceptance criteria

v2 is ready for a CV and interview demo only when it can:

- compare at least three interventions for a selected micro-market in each existing city;
- make each recommendation traceable to data, a calibration, or an explicitly editable assumption;
- create an experiment card with a primary metric, at least three guardrails, cohorts, and a decision rule;
- analyse a documented simulated journey-event dataset in DuckDB without implying it is real user data;
- produce a shareable decision brief with limitations and a field-validation checklist;
- retain or extend the existing test suite; and
- demonstrate one polished end-to-end case: diagnose -> decide -> design pilot -> monitor simulated outcomes.

## Build sequence

1. Define the product event contract, data dictionary, and experiment-design formulas.
2. Add pure, tested domain modules for intervention comparison and experiment design.
3. Create a reproducible simulated-event generator and DuckDB analytics queries.
4. Extend the Streamlit app into a decision workspace.
5. Add a provenance-aware decision-brief generator.
6. Validate the end-to-end scenario, polish the README/case study, then write CV bullets only from real output.

## Explicit non-goals for MVP

- Claiming revenue, retention, or A/B-test impact without real company data.
- Training a black-box store-location model solely to claim AI or ML usage.
- Building a generic chatbot with no provenance.
- Replacing v1's validated methods or regenerating shared processed data without a reason.
- Pretending a large synthetic dataset is real big data.
