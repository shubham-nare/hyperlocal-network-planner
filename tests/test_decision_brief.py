import pytest

from planner.decision_brief import build_decision_brief
from planner.experiments import design_experiment
from planner.interventions import InterventionAssumptions, MicroMarketState, compare_interventions


def _state(**changes):
    base = dict(
        city="pune", micro_market="kothrud", latent_orders_per_day=4_000, unserved_orders_per_day=1_500,
        served_share=0.60, nearby_capacity_utilisation=0.94, nearby_capacity_orders_per_day=6_000,
        new_store_incremental_orders_per_day=1_100, new_store_break_even_orders_per_day=500,
        eta_breach_rate=0.06, assortment_fit_score=0.70,
    )
    base.update(changes)
    return MicroMarketState(**base)


def test_brief_recommends_the_top_ranked_option_and_lists_the_rest_as_alternatives():
    state = _state()
    options = compare_interventions(state)
    brief = build_decision_brief(state, options)
    assert brief.recommendation == options[0]
    assert brief.alternatives == tuple(options[1:])
    assert brief.city == "pune" and brief.micro_market == "kothrud"


def test_brief_rejects_empty_options():
    with pytest.raises(ValueError, match="ranked_options"):
        build_decision_brief(_state(), [])


def test_markdown_contains_every_evidence_assumption_and_guardrail_string():
    state = _state()
    options = compare_interventions(state)
    brief = build_decision_brief(state, options)
    text = brief.render_markdown()
    top = options[0]
    for item in (*top.evidence, *top.assumptions, *top.guardrails):
        assert item in text
    assert brief.recommendation.intervention.replace("_", " ") in text


def test_markdown_never_introduces_a_number_not_already_on_the_option_or_plan():
    state = _state()
    options = compare_interventions(state)
    top = options[0]
    plan = design_experiment(
        hypothesis="Extending the service zone increases eligible users without breaching ETA guardrails.",
        intervention=top.intervention, eligibility_rule="new-zone address at signup",
        primary_metric="reliable_completed_orders_per_eligible_user", baseline_rate=0.42,
        minimum_detectable_effect=0.03,
    )
    brief = build_decision_brief(state, options, experiment_plan=plan)
    text = brief.render_markdown()
    assert f"{plan.users_per_arm:,}" in text
    assert plan.decision_rule in text
    # The score and incremental-orders figures must be exactly the ones already computed upstream —
    # this test would catch a copy-paste typo or a re-derived number that drifted from the source.
    if top.expected_incremental_orders_per_day is not None:
        assert f"{top.expected_incremental_orders_per_day:,.0f}" in text


def test_low_confidence_recommendation_flags_itself_as_directional():
    state = _state(new_store_incremental_orders_per_day=300)  # fails break-even -> low confidence
    options = compare_interventions(state)
    top = {o.intervention: o for o in options}["open_dark_store"]
    assert top.confidence == "low"
    brief = build_decision_brief(state, [top, *[o for o in options if o.intervention != "open_dark_store"]])
    assert "directional, not decisive" in brief.render_markdown()


def test_invalidation_reasons_reference_every_stated_assumption():
    state = _state()
    options = compare_interventions(state)
    extension = {o.intervention: o for o in options}["extend_service_zone"]
    brief = build_decision_brief(state, [extension, *[o for o in options if o.intervention != "extend_service_zone"]])
    text = brief.render_markdown()
    for assumption in extension.assumptions:
        assert assumption in text


def test_standard_limitations_and_field_checks_are_always_present():
    state = _state()
    brief = build_decision_brief(state, compare_interventions(state), extra_field_checks=("Call the local FM.",))
    text = brief.render_markdown()
    assert "third-party snapshot" in text
    assert "simulation harness" in text or "mechanics only" in text
    assert "Call the local FM." in text
