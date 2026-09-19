"""Pydantic request/response models. Field names mirror the real dataclasses in
src/planner so the API is a thin, faithful wrapper, not a reinterpretation."""
from __future__ import annotations

from pydantic import BaseModel, Field


class MicroMarketRequest(BaseModel):
    city: str
    micro_market: str
    latent_orders_per_day: float = Field(ge=0)
    unserved_orders_per_day: float = Field(ge=0)
    served_share: float = Field(ge=0, le=1)
    nearby_capacity_utilisation: float = Field(ge=0, le=1)
    nearby_capacity_orders_per_day: float = Field(ge=0)
    new_store_incremental_orders_per_day: float = Field(ge=0)
    new_store_break_even_orders_per_day: float = Field(gt=0)
    eta_breach_rate: float | None = Field(default=None, ge=0, le=1)
    assortment_fit_score: float = Field(default=0.5, ge=0, le=1)


class InterventionOptionOut(BaseModel):
    intervention: str
    score: float
    expected_incremental_orders_per_day: float | None
    confidence: str
    evidence: tuple[str, ...]
    assumptions: tuple[str, ...]
    guardrails: tuple[str, ...]


class DecisionBriefOut(BaseModel):
    id: int
    city: str
    micro_market: str
    recommendation: InterventionOptionOut
    alternatives: list[InterventionOptionOut]
    markdown: str


class RentShockRequest(BaseModel):
    city: str
    rent_per_sqft_month: float = Field(gt=0)
    size_sqft: float = Field(gt=0)
    other_fixed_cost_per_day: float = Field(ge=0)
    gross_profit_per_order: float
    variable_cost_per_order: float
    shock_pct: float = Field(gt=-1)


class CompetitorEntryRequest(BaseModel):
    city: str
    our_lat: float
    our_lng: float
    competitor_lat: float
    competitor_lng: float
    max_distance_km: float = Field(gt=0)
    distance_decay: float = Field(default=2.0, gt=0)


class CapexPortfolioRequest(BaseModel):
    city: str
    capex_budget_cr: float = Field(ge=0)
    capex_per_store_cr: float = Field(gt=0)
    capacity: float = Field(gt=0)
