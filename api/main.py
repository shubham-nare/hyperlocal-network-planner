"""FastAPI app: serves already-validated project outputs from Postgres, and exposes the
decision-brief and counterfactual-scenario logic (decision_brief.py, scenarios.py) as a
persisted, auditable API. No endpoint here invents a number; each traces to a real
computation elsewhere in src/planner, per this project's standing anti-fabrication rule.
"""
from __future__ import annotations

from fastapi import FastAPI

from api.routers import cities, decisions, scenarios

app = FastAPI(title="Hyperlocal Network Planner API", version="0.1.0")
app.include_router(cities.router)
app.include_router(decisions.router)
app.include_router(scenarios.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
