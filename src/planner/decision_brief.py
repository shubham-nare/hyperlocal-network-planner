"""Evidence-first decision brief: the v2 "AI copilot," scoped honestly.

Per the charter (docs/HYPERLOCAL_GROWTH_OS.md): "the AI layer will summarise and retrieve
evidence, not replace the decision logic." This module is that layer's deterministic core —
it composes a shareable brief entirely from numbers `interventions.py` and `experiments.py`
already computed, with every claim traceable to one of four labels: observed public data,
calibrated estimate, scenario assumption, or simulated experiment data. It never invents a
number. An optional LLM narration pass (not built here) could turn this into flowing prose
later, but could only rephrase what's already in this object — it could not add a fact.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from planner.experiments import ExperimentPlan
from planner.interventions import InterventionOption, MicroMarketState

STANDARD_LIMITATIONS = (
    "Store-location data is a third-party snapshot (see CONTEXT.md for date and completeness); "
    "it may undercount live stores.",
    "Reach and capacity figures are calibrated to public data and one company's disclosed "
    "economics; they are estimates, not this business's actual figures.",
    "Any experiment sample-size or event-funnel numbers referencing the simulation harness are "
    "for testing analytics mechanics only and are not evidence of real customer behavior.",
)


@dataclass(frozen=True)
class DecisionBrief:
    city: str
    micro_market: str
    recommendation: InterventionOption
    alternatives: tuple[InterventionOption, ...]
    experiment_plan: ExperimentPlan | None
    limitations: tuple[str, ...]
    field_validation: tuple[str, ...]

    def render_markdown(self) -> str:
        rec = self.recommendation
        lines = [
            f"# Decision brief: {self.micro_market}, {self.city.title()}",
            "",
            f"**Recommendation: {_label(rec.intervention)}** (score {rec.score}, confidence: {rec.confidence})",
        ]
        if rec.expected_incremental_orders_per_day is not None:
            lines.append(f"Expected incremental orders/day: **{rec.expected_incremental_orders_per_day:,.0f}** "
                        f"(scenario estimate — see assumptions).")
        lines += ["", "## Why", ""]
        lines += [f"- {item}" for item in rec.evidence]
        lines += ["", "## Assumptions behind this number", ""]
        lines += [f"- {item}" for item in rec.assumptions] if rec.assumptions else ["- None beyond the evidence above."]
        lines += ["", "## Guardrails to watch if this ships", ""]
        lines += [f"- {item}" for item in rec.guardrails]
        lines += ["", "## What would invalidate this recommendation", ""]
        lines += [f"- {reason}" for reason in _invalidation_reasons(rec)]
        if self.alternatives:
            lines += ["", "## Alternatives considered", ""]
            for alt in self.alternatives:
                lines.append(f"- **{_label(alt.intervention)}** (score {alt.score}, confidence: {alt.confidence}) — "
                            f"ranked below {_label(rec.intervention)} on this evidence.")
        if self.experiment_plan is not None:
            plan = self.experiment_plan
            lines += ["", "## Proposed validation before full rollout", "",
                      f"- **Hypothesis:** {plan.hypothesis}",
                      f"- **Eligibility:** {plan.eligibility_rule}",
                      f"- **Primary metric:** {plan.primary_metric} (baseline {plan.baseline_rate:.1%}, "
                      f"MDE {plan.minimum_detectable_effect * 100:.1f} pp)",
                      f"- **Guardrails:** {', '.join(plan.guardrails)}",
                      f"- **Sample size:** {plan.users_per_arm:,} eligible users per arm "
                      f"({plan.total_users:,} total, alpha={plan.alpha}, power={plan.power})",
                      f"- **Decision rule:** {plan.decision_rule}"]
        lines += ["", "## Field validation before committing capital", ""]
        lines += [f"- {item}" for item in self.field_validation]
        lines += ["", "## Limitations", ""]
        lines += [f"- {item}" for item in self.limitations]
        return "\n".join(lines)


def _label(intervention: str) -> str:
    return intervention.replace("_", " ")


def _invalidation_reasons(option: InterventionOption) -> tuple[str, ...]:
    """Turn each assumption into a concrete 'what if this is wrong' check, plus one for confidence."""
    reasons = tuple(f"If the assumption \"{a}\" is off by more than ~25%, this ranking may not hold." for a in option.assumptions)
    if option.confidence == "low":
        reasons += ("This is already a low-confidence estimate — treat the ranking as directional, not decisive.",)
    return reasons or ("No stated assumptions to invalidate beyond normal calibration error in the underlying evidence.",)


def build_decision_brief(
    state: MicroMarketState,
    ranked_options: list[InterventionOption],
    *,
    experiment_plan: ExperimentPlan | None = None,
    extra_field_checks: tuple[str, ...] = (),
) -> DecisionBrief:
    """Compose a brief from already-computed intervention rankings. Adds no new numbers."""
    if not ranked_options:
        raise ValueError("ranked_options must not be empty")
    recommendation, *alternatives = ranked_options
    field_validation = (
        f"Confirm current rider/picking capacity utilisation in {state.micro_market} with local ops "
        "before assuming the modeled capacity figure still holds.",
        "Spot-check 10-15 real addresses in this micro-market against the calibrated reach polygon.",
    ) + extra_field_checks
    return DecisionBrief(
        city=state.city, micro_market=state.micro_market, recommendation=recommendation,
        alternatives=tuple(alternatives), experiment_plan=experiment_plan,
        limitations=STANDARD_LIMITATIONS, field_validation=field_validation,
    )
