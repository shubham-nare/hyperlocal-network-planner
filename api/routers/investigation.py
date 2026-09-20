"""Multi-agent site investigation endpoint. Wraps planner.investigation -- see that
module's docstring for what each "agent" actually is: three real, deterministic
functions over an already-recommended site, synthesized via the same verified-
narration guardrail decision briefs use (planner.llm_narration.generate_and_verify).
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.deps import get_economics_config, get_network_config, get_session
from planner.db_models import RecommendedSite
from planner.investigation import investigate_and_synthesize

router = APIRouter(prefix="/sites", tags=["investigation"])


@router.post("/{site_id}/investigate")
def investigate_site(site_id: int, session: Session = Depends(get_session)) -> dict:
    site = session.get(RecommendedSite, site_id)
    if site is None:
        raise HTTPException(404, f"no recommended site with id {site_id}")
    brand = get_network_config()["brand"]
    econ = get_economics_config()
    spatial, competitive, financial, memo = investigate_and_synthesize(session, site, brand, econ)
    return {
        "site_id": site_id, "city": site.city, "locality": site.locality,
        "spatial": asdict(spatial), "competitive": asdict(competitive), "financial": asdict(financial),
        "memo": {
            "text": memo.text, "verified": memo.verified, "unverified_numbers": memo.unverified_numbers,
            "critic_flags": memo.critic_flags, "used_fallback": memo.used_fallback,
        },
    }
