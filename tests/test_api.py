"""API tests. Uses the real hyperlocal_test Postgres database (via a dependency
override) seeded with a handful of synthetic rows for the read-only city endpoints, and
the real project config/data for decision-brief and scenario endpoints -- the same
functions tests/test_scenarios.py and tests/test_interventions.py already validate, so
this only checks the HTTP wiring, not the modeling logic a second time.
"""
from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

load_dotenv()

from api.main import app  # noqa: E402
from api.deps import get_session  # noqa: E402
from planner.db import Base  # noqa: E402
from planner.db_models import Hex, RecommendedSite, ScenarioRun, StoreRecord  # noqa: E402

TEST_DB_URL = os.environ.get("DATABASE_URL_TEST")
pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason="DATABASE_URL_TEST not set -- see .env.example")

TABLES = (Hex, StoreRecord, RecommendedSite)


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(TEST_DB_URL)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def client(engine):
    def override_get_session():
        with Session(engine) as s:
            yield s

    with Session(engine) as s:
        for table in (Hex, StoreRecord, RecommendedSite, ScenarioRun):
            s.execute(text(f"TRUNCATE TABLE {table.__tablename__} RESTART IDENTITY CASCADE"))
        s.commit()
        s.add(Hex(h3="8860a25b69fffff", city="hyderabad", lat=17.4, lng=78.5, population=1000.0,
                  density_per_km2=500.0, demand_index=78.9, office=0.1, education=0.2, food_retail=0.3,
                  residential_highrise=0.4, in_core=True, geometry_geojson={"type": "Point", "coordinates": [78.5, 17.4]}))
        s.add(StoreRecord(city="hyderabad", brand="Blinkit", store_id="s1", lat=17.38, lng=78.51))
        s.add(RecommendedSite(city="hyderabad", scenario_tag="base", rank=1, h3="8860a25b69fffff", lat=17.38636,
                              lng=78.51653, locality="Amberpet", pincode="500013", demand_index=78.9,
                              site_orders_per_day=2094.0, incremental_orders_per_day=2094.0, new_coverage_orders=2094.0,
                              capacity_relief_orders=0.0, breakeven_cover=3.89, competitor_stores_reaching_hex=1))
        s.commit()

    app.dependency_overrides[get_session] = override_get_session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health():
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_list_cities_reflects_seeded_rows(client):
    r = client.get("/cities")
    assert r.status_code == 200
    row = next(c for c in r.json() if c["city"] == "hyderabad")
    assert row["hex_count"] == 1 and row["store_count"] == 1


def test_hexes_and_stores_and_sites_round_trip(client):
    assert client.get("/cities/hyderabad/hexes").json()[0]["h3"] == "8860a25b69fffff"
    assert client.get("/cities/hyderabad/stores").json()[0]["store_id"] == "s1"
    sites = client.get("/cities/hyderabad/recommended-sites").json()
    assert sites[0]["locality"] == "Amberpet"


def test_unknown_city_is_404(client):
    assert client.get("/cities/atlantis/stores").status_code == 404


def test_unknown_scenario_tag_is_404(client):
    assert client.get("/cities/hyderabad/recommended-sites", params={"scenario_tag": "rent_shock_25pct"}).status_code == 404


DECISION_BODY = {
    "city": "hyderabad", "micro_market": "Amberpet", "latent_orders_per_day": 3000,
    "unserved_orders_per_day": 900, "served_share": 0.7, "nearby_capacity_utilisation": 0.85,
    "nearby_capacity_orders_per_day": 2500, "new_store_incremental_orders_per_day": 2094,
    "new_store_break_even_orders_per_day": 495,
}


def test_decision_brief_is_created_and_persisted_then_refetchable(client):
    r = client.post("/decisions/brief", json=DECISION_BODY)
    assert r.status_code == 200
    body = r.json()
    assert body["recommendation"]["intervention"] == "open_dark_store"
    assert "Amberpet" in body["markdown"]

    refetch = client.get(f"/decisions/{body['id']}")
    assert refetch.status_code == 200
    assert refetch.json()["recommendation"]["intervention"] == body["recommendation"]["intervention"]


def test_decision_brief_rejects_invalid_state(client):
    bad = {**DECISION_BODY, "served_share": 1.5}
    assert client.post("/decisions/brief", json=bad).status_code == 422


def test_decision_brief_missing_id_is_404(client):
    assert client.get("/decisions/999999").status_code == 404


OLLAMA_UP = False
try:
    import httpx as _httpx
    from planner.llm_narration import OLLAMA_HOST as _OLLAMA_HOST
    OLLAMA_UP = _httpx.get(f"{_OLLAMA_HOST}/api/version", timeout=2).status_code == 200
except Exception:
    pass


@pytest.mark.skipif(not OLLAMA_UP, reason="no local Ollama server reachable")
def test_narrate_endpoint_never_returns_unverified_text_as_verified(client):
    """The narration guardrail's own logic is fully tested (with fake, deterministic
    clients) in tests/test_llm_narration.py -- this only checks the HTTP wiring against
    the real local model: that the endpoint responds, and that whatever it reports as
    verified/unverified matches the invariant the module promises."""
    created = client.post("/decisions/brief", json=DECISION_BODY).json()
    r = client.post(f"/decisions/{created['id']}/narrate")
    assert r.status_code == 200
    body = r.json()
    assert body["brief_id"] == created["id"]
    assert body["text"]
    if not body["verified"]:
        assert body["used_fallback"] is True
        assert body["text"] == created["markdown"]


def test_calibration_matches_the_known_hyderabad_breakeven(client):
    r = client.get("/scenarios/calibration/hyderabad")
    assert r.status_code == 200
    cal = r.json()
    assert cal["rent_per_sqft_month"] == 90
    assert cal["gross_profit_per_order"] > cal["variable_cost_per_order"] > 0


def test_rent_shock_matches_the_known_baseline_breakeven(client):
    cal = client.get("/scenarios/calibration/hyderabad").json()
    body = {"city": "hyderabad", "rent_per_sqft_month": cal["rent_per_sqft_month"], "size_sqft": cal["size_sqft"],
            "other_fixed_cost_per_day": cal["other_fixed_cost_per_day"], "gross_profit_per_order": cal["gross_profit_per_order"],
            "variable_cost_per_order": cal["variable_cost_per_order"], "shock_pct": 0.25}
    r = client.post("/scenarios/rent-shock", json=body)
    assert r.status_code == 200
    result = r.json()
    assert result["baseline_breakeven_orders_per_day"] == pytest.approx(495, abs=1)
    assert result["breakeven_increase_pct"] == pytest.approx(0.149, abs=0.001)


def test_competitor_entry_matches_the_known_amberpet_result(client, engine):
    """Uses real Hyderabad project data (data/processed/hyderabad_*.gpkg) via get_city_inputs,
    the same data build_scenarios.py's '300m away' case reports 2527 -> 1416 orders/day for.
    The single synthetic store the `client` fixture seeds isn't enough for this -- the real
    number depends on the full real store network -- so this test loads the real store
    snapshot into the test database first, via the same loader scripts/load_db.py uses.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from load_db import load_stores  # noqa: E402

    with Session(engine) as s:
        s.execute(text("TRUNCATE TABLE stores RESTART IDENTITY CASCADE"))
        load_stores(s, "hyderabad")
        s.commit()

    body = {"city": "hyderabad", "our_lat": 17.38636, "our_lng": 78.51653,
            "competitor_lat": 17.38636 + 300 / 111_000, "competitor_lng": 78.51653,
            "max_distance_km": 1.625, "distance_decay": 2.0}
    r = client.post("/scenarios/competitor-entry", json=body)
    assert r.status_code == 200
    result = r.json()
    assert result["our_demand_before"] == pytest.approx(2527, abs=1)
    assert result["our_demand_after"] == pytest.approx(1416, abs=1)


def test_capex_portfolio_runs_the_real_optimizer(client):
    body = {"city": "hyderabad", "capex_budget_cr": 15, "capex_per_store_cr": 2.5, "capacity": 3000}
    r = client.post("/scenarios/capex-portfolio", json=body)
    assert r.status_code == 200
    result = r.json()
    assert result["affordable_sites"] == 6
    assert result["solver_status"] in ("Optimal", "Feasible (time limit)")
    assert result["incremental_orders_per_day"] > 0
