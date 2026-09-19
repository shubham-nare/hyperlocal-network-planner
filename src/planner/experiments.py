"""Experiment-design primitives for Hyperlocal Growth & Reliability OS.

The module designs a prospective two-arm user-randomised test.  It does not claim
causal impact from the repository's public spatial inputs or simulated events.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist


DEFAULT_GUARDRAILS = ("eta_breach_rate", "cancellation_rate", "contribution_per_completed_order")


@dataclass(frozen=True)
class ExperimentPlan:
    hypothesis: str
    intervention: str
    eligibility_rule: str
    primary_metric: str
    baseline_rate: float
    minimum_detectable_effect: float
    treatment_share: float
    alpha: float
    power: float
    guardrails: tuple[str, ...]
    users_per_arm: int
    total_users: int
    decision_rule: str


def required_users_per_arm(
    baseline_rate: float,
    minimum_detectable_effect: float,
    alpha: float = 0.05,
    power: float = 0.8,
) -> int:
    """Required users per arm for a two-sided two-proportion comparison.

    ``minimum_detectable_effect`` is an absolute percentage-point difference, not
    a relative lift.  The normal approximation is suitable for an initial planning
    estimate; the resulting plan states that limitation explicitly.
    """
    _probability("baseline_rate", baseline_rate, inclusive=False)
    if not 0 < minimum_detectable_effect < 1:
        raise ValueError("minimum_detectable_effect must be in (0, 1)")
    treatment_rate = baseline_rate + minimum_detectable_effect
    if treatment_rate >= 1:
        raise ValueError("baseline_rate + minimum_detectable_effect must be below 1")
    if not 0 < alpha < 1 or not 0 < power < 1:
        raise ValueError("alpha and power must be in (0, 1)")
    normal = NormalDist()
    z_alpha = normal.inv_cdf(1 - alpha / 2)
    z_power = normal.inv_cdf(power)
    pooled = (baseline_rate + treatment_rate) / 2
    numerator = (
        z_alpha * math.sqrt(2 * pooled * (1 - pooled))
        + z_power * math.sqrt(baseline_rate * (1 - baseline_rate) + treatment_rate * (1 - treatment_rate))
    ) ** 2
    return math.ceil(numerator / minimum_detectable_effect**2)


def design_experiment(
    *,
    hypothesis: str,
    intervention: str,
    eligibility_rule: str,
    primary_metric: str,
    baseline_rate: float,
    minimum_detectable_effect: float,
    treatment_share: float = 0.5,
    alpha: float = 0.05,
    power: float = 0.8,
    guardrails: tuple[str, ...] = DEFAULT_GUARDRAILS,
) -> ExperimentPlan:
    """Create an auditable experiment card with cohorts, guardrails, and rule."""
    for name, value in (("hypothesis", hypothesis), ("intervention", intervention), ("eligibility_rule", eligibility_rule),
                        ("primary_metric", primary_metric)):
        if not value.strip():
            raise ValueError(f"{name} must not be blank")
    if not 0 < treatment_share < 1:
        raise ValueError("treatment_share must be in (0, 1)")
    if len(guardrails) < 3 or len(set(guardrails)) != len(guardrails):
        raise ValueError("provide at least three unique guardrails")
    if primary_metric in guardrails:
        raise ValueError("primary metric cannot also be a guardrail")
    users_per_arm = required_users_per_arm(baseline_rate, minimum_detectable_effect, alpha, power)
    treatment_users = math.ceil(users_per_arm / treatment_share)
    control_users = math.ceil(users_per_arm / (1 - treatment_share))
    total = max(treatment_users, control_users)
    effect_pp = minimum_detectable_effect * 100
    rule = (
        f"Ship only if {primary_metric} improves by at least {effect_pp:.1f} percentage points versus control "
        f"at alpha={alpha:.2f}, with no material regression in: {', '.join(guardrails)}."
    )
    return ExperimentPlan(
        hypothesis=hypothesis.strip(), intervention=intervention.strip(), eligibility_rule=eligibility_rule.strip(),
        primary_metric=primary_metric.strip(), baseline_rate=baseline_rate,
        minimum_detectable_effect=minimum_detectable_effect, treatment_share=treatment_share, alpha=alpha, power=power,
        guardrails=guardrails, users_per_arm=users_per_arm, total_users=total, decision_rule=rule,
    )


def _probability(name: str, value: float, inclusive: bool) -> None:
    valid = 0 <= value <= 1 if inclusive else 0 < value < 1
    if not valid:
        interval = "[0, 1]" if inclusive else "(0, 1)"
        raise ValueError(f"{name} must be in {interval}")
