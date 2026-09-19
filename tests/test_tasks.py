"""Celery task tests. No Redis broker is available in this environment (see
api/celery_app.py's docstring), so these run tasks in Celery's "eager" mode -- fully
synchronous, in-process, no broker involved. This verifies the task body is correct; it
is not a substitute for an integration test against a live worker, which needs Docker.

The task opens its own DB session via planner.db.get_engine(), which binds to
DATABASE_URL (the dev database) by design -- a real worker process has no FastAPI
request to inherit a session from. To keep these tests off the dev database, an autouse
fixture points DATABASE_URL at DATABASE_URL_TEST for the duration of this module and
resets planner.db's cached engine/sessionmaker singletons so get_engine() picks it up.
"""
from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

load_dotenv()

import planner.db as db  # noqa: E402
from api.celery_app import celery_app  # noqa: E402
from api.deps import get_session  # noqa: E402
from api.main import app  # noqa: E402
from api.tasks import run_capex_portfolio_task  # noqa: E402
from planner.db_models import ScenarioRun  # noqa: E402

TEST_DB_URL = os.environ.get("DATABASE_URL_TEST")
pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason="DATABASE_URL_TEST not set -- see .env.example")


@pytest.fixture(scope="module", autouse=True)
def eager_celery():
    """Run tasks fully in-process with no broker, and store results in an in-memory
    backend rather than Redis. Note: a *second, independent* AsyncResult(task_id) lookup
    against this in-memory backend (as GET /scenarios/tasks/{id} does) is not reliable in
    this eager-test setup -- a Celery/pytest import-ordering quirk leaves some
    already-finalized Task objects pointing at the old (real) backend even after this
    conf update. Real deployments poll against a real Redis backend, where this isn't an
    issue; here, tests verify task success via its actual DB side effect instead (see
    test_async_dispatch_endpoint_runs_eagerly_and_persists_a_run below), not via a second
    backend lookup.
    """
    celery_app.conf.update(
        task_always_eager=True, task_eager_propagates=True, task_store_eager_result=True,
        broker_url="memory://", result_backend="cache+memory://",
    )
    yield
    celery_app.conf.update(
        task_always_eager=False, task_eager_propagates=False, task_store_eager_result=False,
        result_backend="redis://localhost:6379/0",
    )


@pytest.fixture(scope="module", autouse=True)
def route_task_db_to_test_database():
    old_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_DB_URL
    db._engine = None
    db._SessionLocal = None
    yield
    if old_url is not None:
        os.environ["DATABASE_URL"] = old_url
    db._engine = None
    db._SessionLocal = None


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(TEST_DB_URL)
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine):
    with Session(engine) as s:
        s.execute(text("TRUNCATE TABLE scenario_runs RESTART IDENTITY CASCADE"))
        s.commit()
        yield s


def test_capex_portfolio_task_matches_the_known_hyderabad_result_and_persists_a_run(engine, db_session):
    result = run_capex_portfolio_task.delay("hyderabad", 15, 2.5, 3000)
    payload = result.get()
    assert payload["affordable_sites"] == 6
    assert payload["solver_status"] in ("Optimal", "Feasible (time limit)")
    assert payload["incremental_orders_per_day"] > 0

    with Session(engine) as s:
        row = s.get(ScenarioRun, payload["id"])
        assert row is not None
        assert row.scenario_type == "capex_portfolio"
        assert row.result["incremental_orders_per_day"] == pytest.approx(payload["incremental_orders_per_day"])


def test_capex_portfolio_task_rejects_unknown_city():
    with pytest.raises(ValueError, match="atlantis"):
        run_capex_portfolio_task.delay("atlantis", 15, 2.5, 3000).get()


def test_async_dispatch_endpoint_runs_eagerly_and_persists_a_run(engine, db_session):
    def override_get_session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    try:
        from fastapi.testclient import TestClient
        client = TestClient(app)
        r = client.post("/scenarios/capex-portfolio", params={"run_async": "true"},
                        json={"city": "hyderabad", "capex_budget_cr": 15, "capex_per_store_cr": 2.5, "capacity": 3000})
        assert r.status_code == 200
        dispatched = r.json()
        assert "task_id" in dispatched
        assert dispatched["status"] == "SUCCESS"  # eager mode runs it inline, synchronously, within this call

        # Verified via the task's real side effect in the DB, not a second Celery
        # backend lookup -- see eager_celery's docstring for why.
        with Session(engine) as s:
            rows = s.execute(select(ScenarioRun).where(ScenarioRun.scenario_type == "capex_portfolio")).scalars().all()
            assert any(row.city == "hyderabad" and row.result["affordable_sites"] == 6 for row in rows)
    finally:
        app.dependency_overrides.clear()
