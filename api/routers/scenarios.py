"""Counterfactual scenario endpoints. Each one calls the same functions in
scenarios.py that scripts/build_scenarios.py already validated against real Hyderabad
data -- this router adds no new modeling, only an HTTP wrapper and a persisted audit
trail (ScenarioRun) of every scenario actually run.

capex-portfolio solves a real MIP and can be slow for large budgets. By default it runs
synchronously with a short (30s) solver time limit. Pass run_async=true to instead
dispatch it to Celery (api/tasks.py) and poll GET /scenarios/tasks/{task_id} -- but note
no Redis broker is running in this development environment (see api/celery_app.py's
docstring), so the async path is untested against a live worker here.
"""
from __future__ import annotations

import h3
import numpy as np
from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.celery_app import celery_app
from api.deps import get_city_inputs, get_economics_config, get_network_config, get_session
from api.schemas import CapexPortfolioRequest, CompetitorEntryRequest, RentShockRequest
from api.tasks import run_capex_portfolio_task
from planner.db_models import ScenarioRun, StoreRecord
from planner.economics import calibrated_national_economics
from planner.scenarios import capex_constrained_portfolio, competitor_entry_impact, rent_shock

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


def _persist(session: Session, scenario_type: str, city: str, input_params: dict, result: dict) -> int:
    record = ScenarioRun(scenario_type=scenario_type, city=city, input_params=input_params, result=result)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record.id


@router.get("/calibration/{city}")
def get_calibration(city: str) -> dict:
    """The real calibrated numbers rent-shock needs, so a caller doesn't have to re-derive
    them -- exactly what scripts/build_scenarios.py uses for this city."""
    econ = get_economics_config()
    if city not in econ["cities"]:
        raise HTTPException(404, f"no economics config for city {city!r}")
    national = calibrated_national_economics(econ)
    return {
        "city": city, **national,
        "rent_per_sqft_month": econ["cities"][city]["rent_per_sqft_month_inr"],
        "size_sqft": econ["store"]["size_sqft"],
    }


@router.post("/rent-shock")
def run_rent_shock(request: RentShockRequest, session: Session = Depends(get_session)) -> dict:
    result = rent_shock(**request.model_dump())
    payload = {
        "baseline_rent_per_sqft_month": result.baseline_rent_per_sqft_month,
        "shocked_rent_per_sqft_month": result.shocked_rent_per_sqft_month,
        "baseline_breakeven_orders_per_day": result.baseline_breakeven_orders_per_day,
        "shocked_breakeven_orders_per_day": result.shocked_breakeven_orders_per_day,
        "breakeven_increase_pct": result.breakeven_increase_pct,
    }
    payload["id"] = _persist(session, "rent_shock", request.city, request.model_dump(), payload)
    return payload


@router.post("/competitor-entry")
def run_competitor_entry(request: CompetitorEntryRequest, session: Session = Depends(get_session)) -> dict:
    try:
        cov, demand, sites, budget_m = get_city_inputs(request.city)
    except FileNotFoundError as exc:
        raise HTTPException(404, f"no processed data for city {request.city!r}") from exc
    brand = get_network_config()["brand"]
    own = session.execute(select(StoreRecord).where(StoreRecord.city == request.city, StoreRecord.brand == brand)).scalars().all()
    if not own:
        raise HTTPException(404, f"no {brand!r} stores loaded for city {request.city!r}")

    demand_arr = cov["h3"].map(demand).fillna(0).to_numpy()
    hex_lat_lng = cov["h3"].map(h3.cell_to_latlng)
    hex_lat, hex_lng = np.array([ll[0] for ll in hex_lat_lng]), np.array([ll[1] for ll in hex_lat_lng])
    network_lat = np.append(np.array([s.lat for s in own]), request.our_lat)
    network_lng = np.append(np.array([s.lng for s in own]), request.our_lng)
    network_labels = [f"store:{s.store_id}" for s in own] + ["requested_site"]

    result = competitor_entry_impact(
        demand_arr, hex_lat, hex_lng, network_lat, network_lng, network_labels, "requested_site",
        request.competitor_lat, request.competitor_lng,
        max_distance_km=request.max_distance_km, distance_decay=request.distance_decay,
    )
    payload = {
        "competitor_distance_km": result.competitor_distance_km, "our_demand_before": result.our_demand_before,
        "our_demand_after": result.our_demand_after, "demand_lost": result.demand_lost,
        "demand_lost_share": result.demand_lost_share,
    }
    payload["id"] = _persist(session, "competitor_entry", request.city, request.model_dump(), payload)
    return payload


@router.post("/capex-portfolio")
def run_capex_portfolio(request: CapexPortfolioRequest, run_async: bool = False,
                        session: Session = Depends(get_session)) -> dict:
    c = get_network_config()
    if request.city not in c["breakeven"]:
        raise HTTPException(404, f"no break-even calibration for city {request.city!r}")

    if run_async:
        task = run_capex_portfolio_task.delay(request.city, request.capex_budget_cr,
                                              request.capex_per_store_cr, request.capacity)
        return {"task_id": task.id, "status": task.status}

    try:
        cov, demand, sites, budget_m = get_city_inputs(request.city)
    except FileNotFoundError as exc:
        raise HTTPException(404, f"no processed data for city {request.city!r}") from exc
    result = capex_constrained_portfolio(
        demand, sites, request.capacity, c["breakeven"][request.city], request.capex_budget_cr,
        request.capex_per_store_cr, city=request.city, time_limit_s=30,
    )
    payload = {
        "affordable_sites": result.affordable_sites, "sites_opened": result.sites_opened,
        "incremental_orders_per_day": result.incremental_orders_per_day, "solver_status": result.solver_status,
    }
    payload["id"] = _persist(session, "capex_portfolio", request.city, request.model_dump(), payload)
    return payload


@router.get("/tasks/{task_id}")
def get_task_status(task_id: str) -> dict:
    result = AsyncResult(task_id, app=celery_app)
    body = {"task_id": task_id, "status": result.status}
    if result.successful():
        body["result"] = result.result
    elif result.failed():
        body["error"] = str(result.result)
    return body
