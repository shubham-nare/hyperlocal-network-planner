"""Tests for the multi-agent site investigation module. Competitive-agent tests use the
real hyperlocal_test Postgres database (skipped if not configured); synthesis tests
inject a fake LLM client for determinism, plus one real-model integration test."""
from __future__ import annotations

import os

import httpx
import pytest
import yaml
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

load_dotenv()

from planner.db import Base  # noqa: E402
from planner.db_models import RecommendedSite, StoreRecord  # noqa: E402
from planner.investigation import (  # noqa: E402
    investigate_and_synthesize, investigate_competitive, investigate_financial, investigate_spatial,
)
from planner.llm_narration import OLLAMA_HOST  # noqa: E402

TEST_DB_URL = os.environ.get("DATABASE_URL_TEST")
pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason="DATABASE_URL_TEST not set -- see .env.example")

OLLAMA_UP = False
try:
    OLLAMA_UP = httpx.get(f"{OLLAMA_HOST}/api/version", timeout=2).status_code == 200
except Exception:
    pass


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(TEST_DB_URL)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        for table in (RecommendedSite, StoreRecord):
            s.execute(text(f"TRUNCATE TABLE {table.__tablename__} RESTART IDENTITY CASCADE"))
        s.commit()
        yield s


def _site(**overrides) -> RecommendedSite:
    defaults = dict(
        city="hyderabad", scenario_tag="base", rank=1, h3="8860a25b69fffff", lat=17.38636, lng=78.51653,
        locality="Amberpet", pincode="500013", demand_index=78.9, site_orders_per_day=2094.0,
        incremental_orders_per_day=2094.0, new_coverage_orders=2094.0, capacity_relief_orders=0.0,
        breakeven_cover=3.89, competitor_stores_reaching_hex=1,
    )
    defaults.update(overrides)
    return RecommendedSite(**defaults)


def test_investigate_spatial_reads_the_sites_own_fields():
    site = _site()
    findings = investigate_spatial(site)
    assert findings.locality == "Amberpet"
    assert findings.site_orders_per_day == 2094.0
    assert findings.breakeven_cover == 3.89


def test_investigate_competitive_finds_the_real_nearest_store(session):
    site = _site()
    session.add(StoreRecord(city="hyderabad", brand="Blinkit", store_id="own1", lat=17.4, lng=78.5))
    session.add(StoreRecord(city="hyderabad", brand="Zepto", store_id="comp1", lat=17.387, lng=78.517))  # ~50m away
    session.add(StoreRecord(city="hyderabad", brand="Zepto", store_id="comp2", lat=17.5, lng=78.6))  # far
    session.commit()

    findings = investigate_competitive(session, site, own_brand="Blinkit")
    assert findings.nearest_competitor_km is not None
    assert findings.nearest_competitor_km < 0.2  # comp1 is genuinely close
    assert findings.competitors_within_1km == 1
    assert findings.competitor_stores_reaching_hex == 1  # from the site row itself


def test_investigate_competitive_handles_no_competitors_in_city(session):
    site = _site()
    findings = investigate_competitive(session, site, own_brand="Blinkit")
    assert findings.nearest_competitor_km is None
    assert findings.competitors_within_1km == 0


def test_investigate_financial_matches_the_known_hyderabad_baseline():
    econ = yaml.safe_load(open("config/economics.yaml", encoding="utf-8"))
    findings = investigate_financial("hyderabad", econ, shock_pct=0.25)
    assert findings.baseline_breakeven_orders_per_day == pytest.approx(495, abs=1)
    assert findings.shocked_breakeven_orders_per_day > findings.baseline_breakeven_orders_per_day
    assert findings.breakeven_increase_pct == pytest.approx(14.9, abs=0.2)


def test_investigate_and_synthesize_falls_back_when_narration_invents_a_number(session):
    site = _site()
    session.add(StoreRecord(city="hyderabad", brand="Zepto", store_id="comp1", lat=17.5, lng=78.6))
    session.commit()
    econ = yaml.safe_load(open("config/economics.yaml", encoding="utf-8"))

    def fabricating_client(prompt: str, model: str) -> str:
        return "This site is guaranteed to hit exactly 9999999 orders per day."

    spatial, competitive, financial, memo = investigate_and_synthesize(
        session, site, "Blinkit", econ, client=fabricating_client, run_critic=False,
    )
    assert memo.verified is False
    assert memo.used_fallback is True
    assert 9999999.0 in memo.unverified_numbers
    assert "Amberpet" in memo.text  # the deterministic fallback memo


@pytest.mark.skipif(not OLLAMA_UP, reason=f"no Ollama server reachable at {OLLAMA_HOST}")
def test_investigate_and_synthesize_against_a_real_local_model(session):
    site = _site()
    session.add(StoreRecord(city="hyderabad", brand="Zepto", store_id="comp1", lat=17.39, lng=78.52))
    session.commit()
    econ = yaml.safe_load(open("config/economics.yaml", encoding="utf-8"))

    spatial, competitive, financial, memo = investigate_and_synthesize(session, site, "Blinkit", econ)
    assert memo.text
    if not memo.verified:
        assert memo.used_fallback is True
        assert "Amberpet" in memo.text
