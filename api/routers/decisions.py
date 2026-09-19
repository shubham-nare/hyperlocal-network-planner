"""Decision-brief endpoint: the real "AI copilot" from decision_brief.py, wrapped as an
API that persists every brief it generates -- the real decision log the charter asks for,
not a demo stub. This computes nothing an LLM invents; see decision_brief.py's docstring."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.deps import get_session
from api.schemas import DecisionBriefOut, InterventionOptionOut, MicroMarketRequest
from planner.db_models import DecisionBriefRecord
from planner.decision_brief import build_decision_brief
from planner.interventions import MicroMarketState, compare_interventions

router = APIRouter(prefix="/decisions", tags=["decisions"])


def _to_option_out(option) -> InterventionOptionOut:
    return InterventionOptionOut(
        intervention=option.intervention, score=option.score,
        expected_incremental_orders_per_day=option.expected_incremental_orders_per_day,
        confidence=option.confidence, evidence=option.evidence, assumptions=option.assumptions,
        guardrails=option.guardrails,
    )


@router.post("/brief", response_model=DecisionBriefOut)
def create_decision_brief(request: MicroMarketRequest, session: Session = Depends(get_session)) -> DecisionBriefOut:
    state = MicroMarketState(**request.model_dump())
    try:
        ranked = compare_interventions(state)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    brief = build_decision_brief(state, ranked)
    record = DecisionBriefRecord(
        city=state.city, micro_market=state.micro_market, recommended_intervention=brief.recommendation.intervention,
        score=brief.recommendation.score, confidence=brief.recommendation.confidence,
        input_state=request.model_dump(), brief_markdown=brief.render_markdown(),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return DecisionBriefOut(
        id=record.id, city=brief.city, micro_market=brief.micro_market,
        recommendation=_to_option_out(brief.recommendation),
        alternatives=[_to_option_out(o) for o in brief.alternatives],
        markdown=brief.render_markdown(),
    )


@router.get("/{brief_id}", response_model=DecisionBriefOut)
def get_decision_brief(brief_id: int, session: Session = Depends(get_session)) -> DecisionBriefOut:
    record = session.get(DecisionBriefRecord, brief_id)
    if record is None:
        raise HTTPException(404, f"no decision brief with id {brief_id}")
    state = MicroMarketState(**record.input_state)
    ranked = compare_interventions(state)
    return DecisionBriefOut(
        id=record.id, city=record.city, micro_market=record.micro_market,
        recommendation=_to_option_out(ranked[0]), alternatives=[_to_option_out(o) for o in ranked[1:]],
        markdown=record.brief_markdown,
    )
