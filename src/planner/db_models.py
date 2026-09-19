"""ORM tables. Hex/store/recommended-site tables are loaded from already-validated
project outputs (scripts/load_db.py); decision-brief and scenario-run tables are
populated live by the API as real requests happen -- a genuine decision log, not a demo
stub, per the Growth & Reliability OS charter's acceptance criteria.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from planner.db import Base


class Hex(Base):
    __tablename__ = "hexes"
    __table_args__ = (UniqueConstraint("h3", name="uq_hex_h3"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    h3: Mapped[str] = mapped_column(String(20), index=True)
    city: Mapped[str] = mapped_column(String(40), index=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    population: Mapped[float] = mapped_column(Float)
    density_per_km2: Mapped[float] = mapped_column(Float)
    demand_index: Mapped[float] = mapped_column(Float)
    office: Mapped[float] = mapped_column(Float)
    education: Mapped[float] = mapped_column(Float)
    food_retail: Mapped[float] = mapped_column(Float)
    residential_highrise: Mapped[float] = mapped_column(Float)
    in_core: Mapped[bool] = mapped_column(Boolean)
    geometry_geojson: Mapped[dict] = mapped_column(JSON)


class StoreRecord(Base):
    __tablename__ = "stores"
    __table_args__ = (UniqueConstraint("city", "brand", "store_id", name="uq_store_identity"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    city: Mapped[str] = mapped_column(String(40), index=True)
    brand: Mapped[str] = mapped_column(String(40))
    store_id: Mapped[str] = mapped_column(String(80))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)


class RecommendedSite(Base):
    __tablename__ = "recommended_sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    city: Mapped[str] = mapped_column(String(40), index=True)
    scenario_tag: Mapped[str] = mapped_column(String(40), default="base")
    rank: Mapped[int] = mapped_column(Integer)
    h3: Mapped[str] = mapped_column(String(20))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    locality: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pincode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    demand_index: Mapped[float] = mapped_column(Float)
    site_orders_per_day: Mapped[float] = mapped_column(Float)
    incremental_orders_per_day: Mapped[float] = mapped_column(Float)
    new_coverage_orders: Mapped[float] = mapped_column(Float)
    capacity_relief_orders: Mapped[float] = mapped_column(Float)
    breakeven_cover: Mapped[float] = mapped_column(Float)
    competitor_stores_reaching_hex: Mapped[int] = mapped_column(Integer)


class DecisionBriefRecord(Base):
    """The real decision log: every decision brief the API has ever generated, kept for audit."""
    __tablename__ = "decision_briefs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.now(dt.UTC))
    city: Mapped[str] = mapped_column(String(40), index=True)
    micro_market: Mapped[str] = mapped_column(String(80))
    recommended_intervention: Mapped[str] = mapped_column(String(60))
    score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String(20))
    input_state: Mapped[dict] = mapped_column(JSON)
    brief_markdown: Mapped[str] = mapped_column(Text)


class ScenarioRun(Base):
    """Every counterfactual scenario the API has actually executed, with its real result."""
    __tablename__ = "scenario_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=lambda: dt.datetime.now(dt.UTC))
    scenario_type: Mapped[str] = mapped_column(String(40), index=True)
    city: Mapped[str] = mapped_column(String(40), index=True)
    input_params: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
