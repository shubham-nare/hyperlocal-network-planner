"""Celery app for scenario endpoints whose solver runtime is too long to hold an HTTP
request open. Broker/backend default to a local Redis, matching docker-compose.yml's
`redis` service; override via env vars to point at a different broker.

No broker is running in this development environment (Redis has no clean admin-free
install path here, same blocker as Docker -- see CONTEXT.md), so this has not been
exercised against a live worker. Its task logic is tested with Celery's synchronous
"eager" mode instead (tests/test_tasks.py), which executes tasks in-process with no
broker at all -- a real test of the task body, not a substitute for an integration test
against a live Redis + worker, which is still pending Docker.
"""
from __future__ import annotations

import os

from celery import Celery
from dotenv import load_dotenv

load_dotenv()

celery_app = Celery(
    "planner",
    broker=os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
    include=["api.tasks"],
)
celery_app.conf.task_track_started = True
