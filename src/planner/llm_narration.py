"""Evidence-grounded LLM narration -- the "AI copilot" layer the charter
(docs/HYPERLOCAL_GROWTH_OS.md) describes and decision_brief.py's docstring deliberately
deferred: "An optional LLM narration pass ... could only rephrase what's already in this
object -- it could not add a fact." This module is that pass, built so the promise is
enforced computationally, not just stated.

Two small agents, each with one job, run in sequence:
  1. Narrator  -- turns the brief's already-computed facts into flowing prose.
  2. Critic    -- a second, independent LLM pass that reads the same facts and the
                  narrator's prose and flags any claim, causal implication, or framing
                  the facts don't support (things a number-diff can't catch).
A third, non-LLM check is the actual hard gate: every number the narrator's prose
contains is extracted and compared against the exact set of numbers present in the
brief. If a number doesn't trace back to the brief, or the critic raises a flag, or the
model calls fail outright, the caller gets the brief's own deterministic markdown
instead of unverified prose -- never a half-verified narration.

Runs against a local Ollama instance (OLLAMA_HOST, default http://localhost:11434) --
no API key, no per-call cost, nothing leaves this machine.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, Protocol

import httpx

from planner.decision_brief import DecisionBrief

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")

_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")


class LLMClient(Protocol):
    def __call__(self, prompt: str, model: str) -> str: ...


def ollama_client(prompt: str, model: str) -> str:
    response = httpx.post(
        f"{OLLAMA_HOST}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["response"]


def _numbers_in(text: str) -> set[float]:
    numbers = set()
    for match in _NUMBER_RE.findall(text):
        cleaned = match.replace(",", "")
        if cleaned in ("", "-", "."):
            continue
        try:
            numbers.add(round(float(cleaned), 1))
        except ValueError:
            continue
    return numbers


def _brief_source_numbers(brief: DecisionBrief) -> set[float]:
    """Every number that legitimately appears in the brief -- the allowed set a
    narration's own numbers are checked against."""
    values: set[float] = set()
    for option in (brief.recommendation, *brief.alternatives):
        values.add(round(option.score, 1))
        if option.expected_incremental_orders_per_day is not None:
            values.add(round(option.expected_incremental_orders_per_day, 1))
    if brief.experiment_plan is not None:
        plan = brief.experiment_plan
        values.update({
            round(plan.baseline_rate * 100, 1),
            round(plan.minimum_detectable_effect * 100, 1),
            round(plan.alpha * 100, 1),
            round(plan.power * 100, 1),
            round(float(plan.users_per_arm), 1),
            round(float(plan.total_users), 1),
        })
    return values


def _facts_block(brief: DecisionBrief) -> str:
    rec = brief.recommendation
    lines = [f"- Recommended action: {rec.intervention.replace('_', ' ')} (score {rec.score}, confidence {rec.confidence})"]
    if rec.expected_incremental_orders_per_day is not None:
        lines.append(f"- Expected incremental orders/day: {rec.expected_incremental_orders_per_day:.0f}")
    lines.append(f"- Evidence behind this: {', '.join(rec.evidence)}")
    lines.append(f"- Assumptions behind this: {', '.join(rec.assumptions) if rec.assumptions else 'none stated'}")
    for alt in brief.alternatives:
        lines.append(f"- Alternative considered: {alt.intervention.replace('_', ' ')} (score {alt.score})")
    if brief.experiment_plan is not None:
        plan = brief.experiment_plan
        lines.append(
            f"- Proposed validation experiment needs {plan.users_per_arm} users per arm "
            f"({plan.total_users} total) to detect a {plan.minimum_detectable_effect * 100:.1f} "
            f"percentage-point change in {plan.primary_metric} from a baseline of {plan.baseline_rate * 100:.1f}%."
        )
    return "\n".join(lines)


_NARRATOR_PROMPT = """You are writing a short, plain-English narrative summary of a business \
decision brief for a non-technical stakeholder. You must use ONLY the facts given below. \
Do not invent, estimate, round differently, or add any number that is not explicitly listed. \
If you are unsure of a number, describe it in words instead of guessing a figure. Do not \
claim certainty this recommendation will succeed -- these are estimates, not guarantees.

Facts:
{facts}

Write 3-5 sentences of flowing prose. Do not use bullet points.
"""

_CRITIC_PROMPT = """You are a strict but fair fact-checker. Below are some FACTS and a \
NARRATIVE meant to restate those facts in plain English for a business audience.

FACTS:
{facts}

NARRATIVE:
{narrative}

Fail the narrative ONLY for a real violation:
- a number that does not appear in the facts (a different figure, a wrong total, a made-up percentage)
- a claim that the outcome is certain, guaranteed, or risk-free, when the facts only give an estimate
- a causal claim ("this will cause X") that the facts do not state
- a ranking, judgment, or comparison the facts do not make (e.g. calling an alternative "not worth it" when the facts only give it a lower score)

Do NOT fail the narrative for:
- using different words for the same fact (e.g. "solid confidence" for "medium confidence")
- reasonable business phrasing like "the recommended option" or "the best-scoring choice"
- summarizing multiple bullet points into one sentence, as long as no fact is changed

Answer with exactly one word first: "PASS" or "FAIL". If FAIL, follow with a one-sentence \
quote of the exact phrase that violates one of the rules above and which rule it breaks.
"""


@dataclass(frozen=True)
class NarrationResult:
    text: str
    verified: bool
    unverified_numbers: tuple[float, ...]
    critic_flags: tuple[str, ...]
    used_fallback: bool


def _check_numbers(narration: str, brief: DecisionBrief) -> tuple[float, ...]:
    allowed = _brief_source_numbers(brief)
    found = _numbers_in(narration)
    return tuple(sorted(n for n in found if not any(abs(n - a) < 0.6 for a in allowed)))


def _run_critic(facts: str, narration: str, model: str, client: LLMClient) -> tuple[str, ...]:
    try:
        response = client(_CRITIC_PROMPT.format(facts=facts, narrative=narration), model)
    except Exception:
        return ()  # a critic failure isn't grounds to reject a narration the number-check already passed
    verdict = response.strip()
    if verdict.upper().startswith("PASS"):
        return ()
    return (verdict,)


def narrate(
    brief: DecisionBrief, *, model: str = DEFAULT_MODEL,
    client: LLMClient = ollama_client, run_critic: bool = True,
) -> NarrationResult:
    """Turn a DecisionBrief into flowing prose, verified against its own facts.

    Falls back to the brief's own deterministic markdown -- never a half-verified
    narration -- if the narrator's prose contains an untraceable number, the critic
    flags an unsupported claim, or the model call fails outright.
    """
    facts = _facts_block(brief)
    try:
        narration = client(_NARRATOR_PROMPT.format(facts=facts), model)
    except Exception:
        return NarrationResult(brief.render_markdown(), verified=False, unverified_numbers=(), critic_flags=(), used_fallback=True)

    unverified = _check_numbers(narration, brief)
    critic_flags = _run_critic(facts, narration, model, client) if run_critic and not unverified else ()

    if unverified or critic_flags:
        return NarrationResult(brief.render_markdown(), verified=False, unverified_numbers=unverified,
                               critic_flags=critic_flags, used_fallback=True)
    return NarrationResult(narration.strip(), verified=True, unverified_numbers=(), critic_flags=(), used_fallback=False)
