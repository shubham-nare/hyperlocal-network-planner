"""Read-only endpoints over the already-computed, already-validated project outputs
loaded into Postgres by scripts/load_db.py. This router computes nothing new."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from api.deps import get_session
from planner.db_models import Hex, RecommendedSite, StoreRecord

router = APIRouter(prefix="/cities", tags=["cities"])


@router.get("")
def list_cities(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.execute(
        select(Hex.city, func.count(distinct(Hex.h3)), func.sum(Hex.population)).group_by(Hex.city)
    ).all()
    store_counts = dict(session.execute(select(StoreRecord.city, func.count()).group_by(StoreRecord.city)).all())
    return [
        {"city": city, "hex_count": hex_count, "population": round(population or 0),
         "store_count": store_counts.get(city, 0)}
        for city, hex_count, population in rows
    ]


def _require_city(city: str, session: Session) -> None:
    exists = session.execute(select(Hex.id).where(Hex.city == city).limit(1)).first()
    if not exists:
        raise HTTPException(404, f"no data loaded for city {city!r}")


@router.get("/{city}/hexes")
def get_hexes(city: str, limit: int = Query(500, le=2000), offset: int = 0,
              session: Session = Depends(get_session)) -> list[dict]:
    _require_city(city, session)
    rows = session.execute(
        select(Hex).where(Hex.city == city).order_by(Hex.demand_index.desc()).offset(offset).limit(limit)
    ).scalars().all()
    return [
        {"h3": r.h3, "lat": r.lat, "lng": r.lng, "population": r.population, "demand_index": r.demand_index,
         "in_core": r.in_core, "geometry": r.geometry_geojson}
        for r in rows
    ]


@router.get("/{city}/stores")
def get_stores(city: str, session: Session = Depends(get_session)) -> list[dict]:
    _require_city(city, session)
    rows = session.execute(select(StoreRecord).where(StoreRecord.city == city)).scalars().all()
    return [{"brand": r.brand, "store_id": r.store_id, "lat": r.lat, "lng": r.lng, "label": r.label} for r in rows]


@router.get("/{city}/recommended-sites")
def get_recommended_sites(city: str, scenario_tag: str = "base",
                          session: Session = Depends(get_session)) -> list[dict]:
    _require_city(city, session)
    rows = session.execute(
        select(RecommendedSite).where(RecommendedSite.city == city, RecommendedSite.scenario_tag == scenario_tag)
        .order_by(RecommendedSite.rank)
    ).scalars().all()
    if not rows:
        raise HTTPException(404, f"no recommended sites loaded for city={city!r} scenario_tag={scenario_tag!r}")
    return [
        {"id": r.id, "rank": r.rank, "h3": r.h3, "lat": r.lat, "lng": r.lng, "locality": r.locality, "pincode": r.pincode,
         "demand_index": r.demand_index, "site_orders_per_day": r.site_orders_per_day,
         "incremental_orders_per_day": r.incremental_orders_per_day, "new_coverage_orders": r.new_coverage_orders,
         "capacity_relief_orders": r.capacity_relief_orders, "breakeven_cover": r.breakeven_cover,
         "competitor_stores_reaching_hex": r.competitor_stores_reaching_hex}
        for r in rows
    ]
