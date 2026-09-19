import pytest

from planner.experiments import design_experiment, required_users_per_arm


def test_sample_size_is_positive_and_smaller_effect_requires_more_users():
    assert required_users_per_arm(0.20, 0.02) > required_users_per_arm(0.20, 0.05)


def test_design_has_guardrails_cohorts_and_decision_rule():
    plan = design_experiment(
        hypothesis="A small zone expansion improves reliable completion.",
        intervention="extend_service_zone",
        eligibility_rule="Users in Kothrud's proposed outer ring.",
        primary_metric="reliable_completed_orders_per_eligible_user",
        baseline_rate=0.20,
        minimum_detectable_effect=0.03,
    )
    assert plan.users_per_arm > 0
    assert plan.total_users >= 2 * plan.users_per_arm
    assert len(plan.guardrails) == 3
    assert "Ship only if" in plan.decision_rule


@pytest.mark.parametrize("kwargs", [
    {"baseline_rate": 0.0, "minimum_detectable_effect": 0.03},
    {"baseline_rate": 0.99, "minimum_detectable_effect": 0.03},
])
def test_invalid_probability_inputs_fail_loudly(kwargs):
    with pytest.raises(ValueError):
        required_users_per_arm(**kwargs)


def test_design_rejects_weak_or_duplicated_guardrails():
    with pytest.raises(ValueError, match="three unique"):
        design_experiment(
            hypothesis="h", intervention="i", eligibility_rule="e", primary_metric="primary", baseline_rate=0.2,
            minimum_detectable_effect=0.03, guardrails=("eta_breach_rate", "eta_breach_rate"),
        )
