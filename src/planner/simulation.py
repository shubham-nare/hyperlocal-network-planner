"""Deterministic, explicitly simulated journey data for v2 demos and tests.

This is a product-analytics harness, not a demand forecast or a substitute for
company event data.  Its purpose is to exercise the event contract, DuckDB query
layer, experiment workflow, and dashboard with reproducible inputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from planner.product_events import validate_event_frame


@dataclass(frozen=True)
class SimulationConfig:
    city: str = "pune"
    micro_market: str = "kothrud"
    users_per_variant: int = 10_000
    seed: int = 7
    control_serviceability: float = 0.68
    treatment_serviceability: float = 0.75
    browse_rate: float = 0.72
    cart_rate: float = 0.38
    checkout_rate: float = 0.62
    completion_rate: float = 0.90
    reorder_rate: float = 0.24
    control_eta_breach_rate: float = 0.08
    treatment_eta_breach_rate: float = 0.10


def generate_simulated_events(config: SimulationConfig = SimulationConfig()) -> pd.DataFrame:
    """Generate a deterministic two-arm event stream following the v2 contract."""
    if config.users_per_variant < 1:
        raise ValueError("users_per_variant must be at least 1")
    for name, value in vars(config).items():
        if name.endswith("rate") or name.endswith("serviceability"):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
    rng = np.random.default_rng(config.seed)
    rows: list[dict] = []
    start = pd.Timestamp("2026-09-01T09:00:00Z")
    event_number = 0

    def emit(user_id: str, session_id: str, variant: str, event_name: str, minute: int, **extra: object) -> None:
        nonlocal event_number
        event_number += 1
        rows.append({
            "event_id": f"sim-{event_number}", "event_at": start + pd.Timedelta(minutes=minute),
            "user_id": user_id, "session_id": session_id, "event_name": event_name,
            "city": config.city, "micro_market": config.micro_market, "variant": variant,
            "data_origin": "simulated", **extra,
        })

    for variant, serviceability, breach_rate in (
        ("control", config.control_serviceability, config.control_eta_breach_rate),
        ("treatment", config.treatment_serviceability, config.treatment_eta_breach_rate),
    ):
        for i in range(config.users_per_variant):
            user_id, session_id = f"{variant}-u{i}", f"{variant}-s{i}"
            minute = i * 2 + (0 if variant == "control" else 1)
            eligible = rng.random() < serviceability
            emit(user_id, session_id, variant, "serviceability_check", minute, is_serviceable=eligible)
            if not eligible or rng.random() >= config.browse_rate:
                continue
            emit(user_id, session_id, variant, "browse", minute + 1)
            if rng.random() >= config.cart_rate:
                continue
            emit(user_id, session_id, variant, "add_to_cart", minute + 2)
            if rng.random() >= config.checkout_rate:
                continue
            emit(user_id, session_id, variant, "checkout_started", minute + 3)
            if rng.random() >= config.completion_rate:
                emit(user_id, session_id, variant, "order_cancelled", minute + 4)
                continue
            promised = 10
            breached = rng.random() < breach_rate
            actual = promised + int(rng.integers(1, 6)) if breached else promised - int(rng.integers(0, 3))
            emit(user_id, session_id, variant, "eta_promised", minute + 4, eta_promised_min=promised)
            emit(user_id, session_id, variant, "order_completed", minute + actual,
                 eta_promised_min=promised, actual_delivery_min=actual)
            if rng.random() < config.reorder_rate:
                emit(user_id, f"{session_id}-repeat", variant, "reorder", minute + 7 * 24 * 60)
    return validate_event_frame(pd.DataFrame(rows))


def write_simulated_events(events: pd.DataFrame, database_path: str | Path) -> int:
    """Persist validated simulated events to DuckDB and return the row count."""
    frame = validate_event_frame(events)
    if set(frame.get("data_origin", [])) != {"simulated"}:
        raise ValueError("only explicitly simulated event data may be written by this harness")
    with duckdb.connect(str(database_path)) as connection:
        connection.register("events_frame", frame)
        connection.execute("CREATE OR REPLACE TABLE simulated_product_events AS SELECT * FROM events_frame")
        return connection.execute("SELECT count(*) FROM simulated_product_events").fetchone()[0]


def duckdb_funnel_by_variant(events: pd.DataFrame) -> pd.DataFrame:
    """Calculate the eligible-user funnel in DuckDB for each experiment arm."""
    frame = validate_event_frame(events)
    if "variant" not in frame.columns:
        raise ValueError("events must include variant")
    with duckdb.connect(":memory:") as connection:
        connection.register("events", frame)
        return connection.execute("""
            WITH eligible AS (
                SELECT DISTINCT variant, user_id
                FROM events
                WHERE event_name = 'serviceability_check' AND is_serviceable = TRUE
            ), journey AS (
                SELECT e.variant, e.user_id, e.event_name, e.eta_promised_min, e.actual_delivery_min
                FROM events e INNER JOIN eligible u USING (variant, user_id)
            )
            SELECT variant,
                count(DISTINCT user_id) AS eligible_users,
                count(DISTINCT CASE WHEN event_name = 'browse' THEN user_id END) AS browsed_users,
                count(DISTINCT CASE WHEN event_name = 'add_to_cart' THEN user_id END) AS carted_users,
                count(DISTINCT CASE WHEN event_name = 'checkout_started' THEN user_id END) AS checkout_started_users,
                count(DISTINCT CASE WHEN event_name = 'order_completed' THEN user_id END) AS completed_users,
                count(DISTINCT CASE WHEN event_name = 'order_cancelled' THEN user_id END) AS cancelled_users,
                count(DISTINCT CASE WHEN event_name = 'reorder' THEN user_id END) AS reordered_users,
                avg(CASE WHEN event_name = 'order_completed' AND actual_delivery_min > eta_promised_min THEN 1.0
                         WHEN event_name = 'order_completed' THEN 0.0 END) AS eta_breach_rate
            FROM journey
            GROUP BY variant
            ORDER BY variant
        """).fetchdf()
