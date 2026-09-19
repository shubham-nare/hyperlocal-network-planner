"""Celery tasks. Each one runs the exact same function its synchronous API counterpart
calls -- this module adds an async execution path, not a second implementation."""
from __future__ import annotations

from sqlalchemy.orm import Session

from api.celery_app import celery_app
from api.deps import get_city_inputs, get_network_config
from planner.db import get_engine
from planner.db_models import ScenarioRun
from planner.scenarios import capex_constrained_portfolio


@celery_app.task(name="scenarios.capex_portfolio")
def run_capex_portfolio_task(city: str, capex_budget_cr: float, capex_per_store_cr: float, capacity: float) -> dict:
    """Async twin of POST /scenarios/capex-portfolio, for callers who'd rather poll a
    task id than hold a connection open through a potentially slow MIP solve. A worker
    process has no FastAPI request to hang a DB session off, so this opens its own."""
    c = get_network_config()
    if city not in c["breakeven"]:
        raise ValueError(f"no break-even calibration for city {city!r}")
    cov, demand, sites, budget_m = get_city_inputs(city)
    result = capex_constrained_portfolio(
        demand, sites, capacity, c["breakeven"][city], capex_budget_cr, capex_per_store_cr,
        city=city, time_limit_s=120,
    )
    payload = {
        "affordable_sites": result.affordable_sites, "sites_opened": result.sites_opened,
        "incremental_orders_per_day": result.incremental_orders_per_day, "solver_status": result.solver_status,
    }
    with Session(get_engine()) as session:
        record = ScenarioRun(
            scenario_type="capex_portfolio", city=city,
            input_params={"city": city, "capex_budget_cr": capex_budget_cr,
                         "capex_per_store_cr": capex_per_store_cr, "capacity": capacity},
            result=payload,
        )
        session.add(record)
        session.commit()
        payload["id"] = record.id
    return payload
