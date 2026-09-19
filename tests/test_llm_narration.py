"""Tests for the evidence-grounded LLM narration layer.

Most of these inject a fake LLM client so the guardrail logic itself is tested
deterministically -- not the nondeterministic behavior of a real model. One test runs
against a real local Ollama instance and is skipped if it isn't reachable; it checks
this system's own invariants hold with a real model, not that the model behaves
perfectly (a real model occasionally adding a stray number is exactly the case the
guardrail exists to catch).
"""
from __future__ import annotations

import httpx
import pytest

from planner.decision_brief import build_decision_brief
from planner.experiments import design_experiment
from planner.interventions import MicroMarketState, compare_interventions
from planner.llm_narration import DEFAULT_MODEL, OLLAMA_HOST, _brief_source_numbers, _numbers_in, narrate

OLLAMA_UP = False
try:
    OLLAMA_UP = httpx.get(f"{OLLAMA_HOST}/api/version", timeout=2).status_code == 200
except Exception:
    pass


def _state(**changes):
    base = dict(
        city="pune", micro_market="kothrud", latent_orders_per_day=4_000, unserved_orders_per_day=1_500,
        served_share=0.60, nearby_capacity_utilisation=0.94, nearby_capacity_orders_per_day=6_000,
        new_store_incremental_orders_per_day=1_100, new_store_break_even_orders_per_day=500,
        eta_breach_rate=0.06, assortment_fit_score=0.70,
    )
    base.update(changes)
    return MicroMarketState(**base)


def _brief(with_plan=False):
    state = _state()
    options = compare_interventions(state)
    plan = None
    if with_plan:
        plan = design_experiment(
            hypothesis="Extending the service zone increases eligible users without breaching ETA guardrails.",
            intervention=options[0].intervention, eligibility_rule="new-zone address at signup",
            primary_metric="reliable_completed_orders_per_eligible_user", baseline_rate=0.42,
            minimum_detectable_effect=0.03,
        )
    return build_decision_brief(state, options, experiment_plan=plan)


def test_numbers_in_extracts_and_rounds_numeric_tokens():
    assert _numbers_in("Score 92.7, up 1,100 orders, and -3.5% change.") == {92.7, 1100.0, -3.5}


def test_numbers_in_ignores_non_numeric_punctuation():
    assert _numbers_in("no numbers here, just words - and a dash.") == set()


def test_brief_source_numbers_includes_recommendation_and_alternative_scores():
    brief = _brief()
    numbers = _brief_source_numbers(brief)
    assert round(brief.recommendation.score, 1) in numbers
    for alt in brief.alternatives:
        assert round(alt.score, 1) in numbers


def test_brief_source_numbers_includes_experiment_plan_figures():
    brief = _brief(with_plan=True)
    numbers = _brief_source_numbers(brief)
    plan = brief.experiment_plan
    assert round(float(plan.users_per_arm), 1) in numbers
    assert round(plan.baseline_rate * 100, 1) in numbers


def test_narrate_accepts_a_clean_narration_matching_the_facts():
    brief = _brief()
    rec = brief.recommendation
    clean_text = f"The recommended action scores {rec.score}, with medium-to-high confidence."

    def fake_client(prompt: str, model: str) -> str:
        return clean_text

    result = narrate(brief, client=fake_client, run_critic=False)
    assert result.verified is True
    assert result.used_fallback is False
    assert result.text == clean_text
    assert result.unverified_numbers == ()


def test_narrate_falls_back_when_narration_invents_a_number():
    brief = _brief()

    def fake_client(prompt: str, model: str) -> str:
        return "This will generate exactly 999999 incremental orders per day, guaranteed."

    result = narrate(brief, client=fake_client, run_critic=False)
    assert result.verified is False
    assert result.used_fallback is True
    assert 999999.0 in result.unverified_numbers
    assert result.text == brief.render_markdown()


def test_narrate_falls_back_when_critic_flags_an_overclaim():
    brief = _brief()
    rec = brief.recommendation
    calls = []

    def fake_client(prompt: str, model: str) -> str:
        calls.append(prompt)
        if "FACTS:" in prompt and "NARRATIVE:" in prompt:
            return "FAIL: the narrative claims this is guaranteed to succeed, which is not supported."
        return f"This will definitely succeed with a score of {rec.score}."

    result = narrate(brief, client=fake_client, run_critic=True)
    assert result.verified is False
    assert result.used_fallback is True
    assert len(result.critic_flags) == 1
    assert "guaranteed" in result.critic_flags[0].lower()
    assert len(calls) == 2  # narrator, then critic


def test_narrate_falls_back_when_the_client_raises():
    brief = _brief()

    def broken_client(prompt: str, model: str) -> str:
        raise ConnectionError("no local model server")

    result = narrate(brief, client=broken_client)
    assert result.verified is False
    assert result.used_fallback is True
    assert result.text == brief.render_markdown()


@pytest.mark.skipif(not OLLAMA_UP, reason=f"no Ollama server reachable at {OLLAMA_HOST}")
def test_narrate_against_a_real_local_model_never_ships_unverified_text():
    brief = _brief(with_plan=True)
    result = narrate(brief, model=DEFAULT_MODEL)
    assert result.text  # some text came back either way
    if result.verified:
        assert result.unverified_numbers == ()
        assert result.critic_flags == ()
    else:
        # the guardrail's whole point: an unverified narration never ships on its own
        assert result.text == brief.render_markdown()
