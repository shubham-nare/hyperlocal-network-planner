"""DB layer tests. Runs against the real local Postgres test database
(DATABASE_URL_TEST in .env), not a mock -- this is the same database
scripts/load_db.py's real data gets loaded into, just a separate one so tests never
touch the dev data. Skipped automatically if no test database is configured.
"""
from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

load_dotenv()

from planner.db import Base, make_engine  # noqa: E402
from planner.db_models import DecisionBriefRecord, Hex, RecommendedSite, ScenarioRun, StoreRecord  # noqa: E402

TEST_DB_URL = os.environ.get("DATABASE_URL_TEST")
pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason="DATABASE_URL_TEST not set -- see .env.example")

TABLES = (Hex, StoreRecord, RecommendedSite, DecisionBriefRecord, ScenarioRun)


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(TEST_DB_URL)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        for table in TABLES:
            s.execute(text(f"TRUNCATE TABLE {table.__tablename__} RESTART IDENTITY CASCADE"))
        s.commit()
        yield s


def test_make_engine_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        make_engine(None)


def test_hex_round_trip_preserves_geometry_and_flags(session):
    geom = {"type": "Polygon", "coordinates": [[[78.5, 17.4], [78.6, 17.4], [78.6, 17.5], [78.5, 17.4]]]}
    session.add(Hex(h3="8860a25b69fffff", city="hyderabad", lat=17.4, lng=78.5, population=1234.0,
                   density_per_km2=500.0, demand_index=78.9, office=0.1, education=0.2, food_retail=0.3,
                   residential_highrise=0.4, in_core=True, geometry_geojson=geom))
    session.commit()
    row = session.execute(select(Hex).where(Hex.h3 == "8860a25b69fffff")).scalar_one()
    assert row.city == "hyderabad"
    assert row.in_core is True
    assert row.geometry_geojson == geom


def test_store_record_rejects_duplicate_identity(session):
    session.add(StoreRecord(city="pune", brand="blinkit", store_id="s1", lat=18.5, lng=73.8))
    session.commit()
    session.add(StoreRecord(city="pune", brand="blinkit", store_id="s1", lat=18.6, lng=73.9))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_recommended_site_round_trip(session):
    session.add(RecommendedSite(city="hyderabad", scenario_tag="base", rank=1, h3="8860a25b69fffff", lat=17.38636,
                                lng=78.51653, locality="Amberpet", pincode="500013", demand_index=78.9,
                                site_orders_per_day=2094.0, incremental_orders_per_day=2094.0,
                                new_coverage_orders=2094.0, capacity_relief_orders=0.0, breakeven_cover=3.89,
                                competitor_stores_reaching_hex=1))
    session.commit()
    row = session.execute(select(RecommendedSite).where(RecommendedSite.city == "hyderabad")).scalar_one()
    assert row.locality == "Amberpet"
    assert row.breakeven_cover == pytest.approx(3.89)


def test_decision_brief_record_round_trips_json_input_state_and_markdown(session):
    input_state = {"city": "hyderabad", "micro_market": "Amberpet", "served_share": 0.7}
    session.add(DecisionBriefRecord(city="hyderabad", micro_market="Amberpet", recommended_intervention="open_dark_store",
                                    score=92.7, confidence="medium", input_state=input_state,
                                    brief_markdown="# Decision brief: Amberpet, Hyderabad"))
    session.commit()
    row = session.execute(select(DecisionBriefRecord)).scalar_one()
    assert row.input_state == input_state
    assert row.brief_markdown.startswith("# Decision brief")
    assert row.created_at is not None


def test_scenario_run_round_trips_json_params_and_result(session):
    params = {"city": "hyderabad", "shock_pct": 0.25}
    result = {"breakeven_increase_pct": 0.149}
    session.add(ScenarioRun(scenario_type="rent_shock", city="hyderabad", input_params=params, result=result))
    session.commit()
    row = session.execute(select(ScenarioRun)).scalar_one()
    assert row.input_params == params
    assert row.result == result


def test_load_db_functions_load_real_hyderabad_data(session):
    """End-to-end check of scripts/load_db.py's loader functions against real project data,
    run into the test database rather than the dev one."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from load_db import load_hexes, load_recommended_sites, load_stores  # noqa: E402

    n_hex = load_hexes(session, "hyderabad")
    n_store = load_stores(session, "hyderabad")
    n_site = load_recommended_sites(session, "hyderabad")
    session.commit()

    assert n_hex == 1194
    assert n_store == 282
    assert n_site == 10
    assert session.execute(select(Hex)).scalars().first().city == "hyderabad"
