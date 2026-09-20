"""Multi-agent site investigation: three real, deterministic "investigator" functions
over an already-recommended site, synthesized into one memo via the same verified-
narration guardrail decision briefs use (llm_narration.generate_and_verify).

Each investigator packages a function this project already built and validated --
none of them, or the synthesis step, runs a new analysis:
  - Spatial      -- the site's own already-computed demand/coverage numbers (DB).
  - Competitive  -- real competitor stores near the site, queried directly (no
                     hypothetical new entrant is invented; distances are real).
  - Financial    -- the same rent-shock/break-even calibration scenarios.py already
                     validates, run for this site's city.
The synthesis agent is llm_narration's Narrator+Critic pair, whose "allowed numbers"
set is the union of all three investigators' real figures -- the same enforced
guarantee a single decision brief gets, extended across three data sources.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from planner.db_models import RecommendedSite, StoreRecord
from planner.economics import calibrated_national_economics
from planner.huff import pairwise_distance_km
from planner.llm_narration import DEFAULT_MODEL, LLMClient, NarrationResult, generate_and_verify, ollama_client
from planner.scenarios import rent_shock


@dataclass(frozen=True)
class SpatialFindings:
    locality: str | None
    pincode: str | None
    demand_index: float
    site_orders_per_day: float
    incremental_orders_per_day: float
    new_coverage_orders: float
    capacity_relief_orders: float
    breakeven_cover: float


@dataclass(frozen=True)
class CompetitiveFindings:
    competitor_stores_reaching_hex: int
    nearest_competitor_km: float | None
    competitors_within_1km: int


@dataclass(frozen=True)
class FinancialFindings:
    baseline_breakeven_orders_per_day: float
    shocked_breakeven_orders_per_day: float
    shock_pct: float
    breakeven_increase_pct: float


def investigate_spatial(site: RecommendedSite) -> SpatialFindings:
    """The spatial agent: this site's own already-validated demand/coverage figures."""
    return SpatialFindings(
        locality=site.locality, pincode=site.pincode, demand_index=site.demand_index,
        site_orders_per_day=site.site_orders_per_day, incremental_orders_per_day=site.incremental_orders_per_day,
        new_coverage_orders=site.new_coverage_orders, capacity_relief_orders=site.capacity_relief_orders,
        breakeven_cover=site.breakeven_cover,
    )


def investigate_competitive(session: Session, site: RecommendedSite, own_brand: str) -> CompetitiveFindings:
    """The competitive agent: real competitor stores near this site. Reports actual
    distances to actual stores -- it does not simulate a hypothetical new entrant."""
    competitors = session.execute(
        select(StoreRecord).where(StoreRecord.city == site.city, StoreRecord.brand != own_brand)
    ).scalars().all()
    if not competitors:
        return CompetitiveFindings(site.competitor_stores_reaching_hex, None, 0)
    comp_lat = np.array([c.lat for c in competitors])
    comp_lng = np.array([c.lng for c in competitors])
    distances = pairwise_distance_km(np.array([site.lat]), np.array([site.lng]), comp_lat, comp_lng)[0]
    return CompetitiveFindings(
        competitor_stores_reaching_hex=site.competitor_stores_reaching_hex,
        nearest_competitor_km=round(float(distances.min()), 2),
        competitors_within_1km=int((distances <= 1.0).sum()),
    )


def investigate_financial(city: str, econ: dict, shock_pct: float = 0.25) -> FinancialFindings:
    """The financial agent: the same calibrated break-even and rent-shock scenario.py
    already validates against real Hyderabad numbers, run for this site's city."""
    national = calibrated_national_economics(econ)
    result = rent_shock(
        city=city, rent_per_sqft_month=econ["cities"][city]["rent_per_sqft_month_inr"],
        size_sqft=econ["store"]["size_sqft"], other_fixed_cost_per_day=national["other_fixed_cost_per_day"],
        gross_profit_per_order=national["gross_profit_per_order"], variable_cost_per_order=national["variable_cost_per_order"],
        shock_pct=shock_pct,
    )
    return FinancialFindings(
        baseline_breakeven_orders_per_day=round(result.baseline_breakeven_orders_per_day, 1),
        shocked_breakeven_orders_per_day=round(result.shocked_breakeven_orders_per_day, 1),
        shock_pct=shock_pct, breakeven_increase_pct=round(result.breakeven_increase_pct * 100, 1),
    )


def load_economics_config(path: str = "config/economics.yaml") -> dict:
    return yaml.safe_load(open(path, encoding="utf-8"))


def _facts_block(site: RecommendedSite, spatial: SpatialFindings, competitive: CompetitiveFindings,
                 financial: FinancialFindings) -> str:
    lines = [
        f"- Site: {spatial.locality or site.h3} ({spatial.pincode or 'no pincode on file'}), {site.city.title()}",
        f"- Demand index: {spatial.demand_index}",
        f"- Projected site orders/day: {spatial.site_orders_per_day:.0f}",
        f"- Incremental orders/day over the existing network: {spatial.incremental_orders_per_day:.0f}",
        f"- New demand coverage (no existing store reaches it): {spatial.new_coverage_orders:.0f} orders/day",
        f"- Capacity relief for already-full existing stores: {spatial.capacity_relief_orders:.0f} orders/day",
        f"- Break-even coverage: {spatial.breakeven_cover}x break-even",
        f"- Competing brands' stores already reaching this hex: {competitive.competitor_stores_reaching_hex}",
    ]
    if competitive.nearest_competitor_km is not None:
        lines.append(f"- Nearest real competitor store: {competitive.nearest_competitor_km} km away")
        lines.append(f"- Competitor stores within 1 km: {competitive.competitors_within_1km}")
    else:
        lines.append("- No competitor stores found in this city's snapshot")
    lines += [
        f"- Break-even orders/day today: {financial.baseline_breakeven_orders_per_day}",
        f"- Break-even orders/day if city-wide rent rose {financial.shock_pct:.0%}: "
        f"{financial.shocked_breakeven_orders_per_day} ({financial.breakeven_increase_pct:+.1f}% change)",
    ]
    return "\n".join(lines)


def _allowed_numbers(spatial: SpatialFindings, competitive: CompetitiveFindings, financial: FinancialFindings) -> set[float]:
    values = {
        round(spatial.demand_index, 1), round(spatial.site_orders_per_day, 1),
        round(spatial.incremental_orders_per_day, 1), round(spatial.new_coverage_orders, 1),
        round(spatial.capacity_relief_orders, 1), round(spatial.breakeven_cover, 1),
        float(competitive.competitor_stores_reaching_hex),
        float(competitive.competitors_within_1km),
        financial.baseline_breakeven_orders_per_day, financial.shocked_breakeven_orders_per_day,
        round(financial.shock_pct * 100, 1), financial.breakeven_increase_pct,
    }
    if competitive.nearest_competitor_km is not None:
        values.add(competitive.nearest_competitor_km)
    return values


def _fallback_markdown(site: RecommendedSite, spatial: SpatialFindings, competitive: CompetitiveFindings,
                       financial: FinancialFindings) -> str:
    lines = [
        f"# Site investigation memo: {spatial.locality or site.h3}, {site.city.title()}",
        "", "## Spatial", "",
        f"- Projected orders/day: {spatial.site_orders_per_day:.0f} ({spatial.incremental_orders_per_day:.0f} incremental)",
        f"- New coverage: {spatial.new_coverage_orders:.0f} orders/day | Capacity relief: {spatial.capacity_relief_orders:.0f} orders/day",
        f"- Break-even cover: {spatial.breakeven_cover}x",
        "", "## Competitive", "",
        f"- Competing-brand stores already reaching this hex: {competitive.competitor_stores_reaching_hex}",
    ]
    if competitive.nearest_competitor_km is not None:
        lines.append(f"- Nearest competitor store: {competitive.nearest_competitor_km} km ({competitive.competitors_within_1km} within 1 km)")
    lines += [
        "", "## Financial", "",
        f"- Break-even today: {financial.baseline_breakeven_orders_per_day} orders/day",
        f"- Break-even at +{financial.shock_pct:.0%} rent: {financial.shocked_breakeven_orders_per_day} orders/day "
        f"({financial.breakeven_increase_pct:+.1f}%)",
    ]
    return "\n".join(lines)


_SYNTHESIS_PROMPT = """You are an investment-committee analyst writing a short site-investigation \
memo from three specialist reports (spatial, competitive, financial) below. Use ONLY the facts \
given. Do not invent, estimate, or add any number not explicitly listed. Do not claim the site is \
certain to succeed -- these are estimates and scenario projections, not guarantees.

Facts:
{facts}

Write one short memo (4-6 sentences, no bullet points) covering: the demand opportunity, the \
competitive picture, and the financial risk if rent rises.
"""


def investigate_and_synthesize(
    session: Session, site: RecommendedSite, own_brand: str, econ: dict, *,
    shock_pct: float = 0.25, model: str = DEFAULT_MODEL, client: LLMClient = ollama_client, run_critic: bool = True,
) -> tuple[SpatialFindings, CompetitiveFindings, FinancialFindings, NarrationResult]:
    """Run all three investigator agents on ``site``, then synthesize one memo. Returns
    the three raw findings alongside the synthesis result so a caller can show its work."""
    spatial = investigate_spatial(site)
    competitive = investigate_competitive(session, site, own_brand)
    financial = investigate_financial(site.city, econ, shock_pct)
    facts = _facts_block(site, spatial, competitive, financial)
    allowed = _allowed_numbers(spatial, competitive, financial)
    fallback = _fallback_markdown(site, spatial, competitive, financial)
    memo = generate_and_verify(facts, allowed, fallback, model=model, client=client, run_critic=run_critic,
                               narrator_prompt=_SYNTHESIS_PROMPT)
    return spatial, competitive, financial, memo
