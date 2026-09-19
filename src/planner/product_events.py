"""Canonical product-analytics event contract for the v2 simulation harness.

The contract is intentionally provider-neutral.  It models a user's journey after a
location check; it does *not* imply that the repository holds a quick-commerce
company's real behavioural data.  The simulator introduced later emits rows using
this shape, and production integrations would map their events into the same
schema.
"""
from __future__ import annotations

from collections.abc import Iterable

import pandas as pd


JOURNEY_EVENTS = (
    "serviceability_check",
    "browse",
    "add_to_cart",
    "checkout_started",
    "eta_promised",
    "order_completed",
    "order_cancelled",
    "reorder",
)

REQUIRED_COLUMNS = ("event_id", "event_at", "user_id", "session_id", "event_name", "city", "micro_market")


def validate_event_frame(events: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalise an event frame without modifying the caller's frame.

    ``event_at`` is normalised to UTC.  The narrow validation is deliberate:
    product clients can carry extra attributes, while every event must retain a
    stable identity, user/session linkage, geography, and event name.
    """
    missing = set(REQUIRED_COLUMNS) - set(events.columns)
    if missing:
        raise ValueError(f"events missing required columns: {sorted(missing)}")
    out = events.copy()
    if out.empty:
        return out
    for column in ("event_id", "user_id", "session_id", "event_name", "city", "micro_market"):
        if out[column].isna().any() or (out[column].astype(str).str.strip() == "").any():
            raise ValueError(f"events contain blank {column}")
    if out["event_id"].duplicated().any():
        raise ValueError("event_id must be unique")
    unknown = set(out["event_name"]) - set(JOURNEY_EVENTS)
    if unknown:
        raise ValueError(f"unknown event names: {sorted(unknown)}")
    out["event_at"] = pd.to_datetime(out["event_at"], utc=True, errors="coerce")
    if out["event_at"].isna().any():
        raise ValueError("event_at must be a valid timestamp")
    checks = out[out["event_name"] == "serviceability_check"]
    if not checks.empty and "is_serviceable" not in out.columns:
        raise ValueError("serviceability_check events require is_serviceable")
    if not checks.empty and checks["is_serviceable"].isna().any():
        raise ValueError("serviceability_check events require a non-null is_serviceable value")
    return out.sort_values("event_at", kind="stable").reset_index(drop=True)


def funnel_metrics(events: pd.DataFrame) -> dict[str, float | int]:
    """Return an eligible-user funnel and delivery-reliability guardrails.

    A user becomes eligible only after an explicitly serviceable location check.
    Subsequent events from ineligible users are excluded from conversion metrics,
    preventing an apparent conversion decline merely because the service area grew.
    """
    frame = validate_event_frame(events)
    if frame.empty:
        return _empty_metrics()
    checks = frame[(frame["event_name"] == "serviceability_check") & frame["is_serviceable"].astype(bool)]
    eligible = set(checks["user_id"])

    def users_at(event_name: str) -> int:
        return int(frame.loc[(frame["event_name"] == event_name) & frame["user_id"].isin(eligible), "user_id"].nunique())

    eligible_users = len(eligible)
    browsed = users_at("browse")
    carted = users_at("add_to_cart")
    checkout_started = users_at("checkout_started")
    completed = users_at("order_completed")
    reordered = users_at("reorder")
    delivered = frame[(frame["event_name"] == "order_completed") & frame["user_id"].isin(eligible)]
    breaches = 0
    if not delivered.empty and {"eta_promised_min", "actual_delivery_min"} <= set(delivered.columns):
        observed = delivered.dropna(subset=["eta_promised_min", "actual_delivery_min"])
        breaches = int((observed["actual_delivery_min"] > observed["eta_promised_min"]).sum())
        deliveries_with_eta = len(observed)
    else:
        deliveries_with_eta = 0
    cancelled = users_at("order_cancelled")
    return {
        "eligible_users": eligible_users,
        "browsed_users": browsed,
        "carted_users": carted,
        "checkout_started_users": checkout_started,
        "completed_users": completed,
        "reordered_users": reordered,
        "serviceability_to_browse_rate": _rate(browsed, eligible_users),
        "browse_to_cart_rate": _rate(carted, browsed),
        "cart_to_checkout_rate": _rate(checkout_started, carted),
        "checkout_completion_rate": _rate(completed, checkout_started),
        "reliable_completed_orders_per_eligible_user": _rate(completed, eligible_users),
        "reorder_rate": _rate(reordered, completed),
        "eta_breach_rate": _rate(breaches, deliveries_with_eta),
        "cancellation_rate": _rate(cancelled, checkout_started),
    }


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _empty_metrics() -> dict[str, float | int]:
    keys: Iterable[str] = (
        "eligible_users", "browsed_users", "carted_users", "checkout_started_users", "completed_users", "reordered_users",
    )
    counts = {key: 0 for key in keys}
    rates = {
        "serviceability_to_browse_rate": 0.0,
        "browse_to_cart_rate": 0.0,
        "cart_to_checkout_rate": 0.0,
        "checkout_completion_rate": 0.0,
        "reliable_completed_orders_per_eligible_user": 0.0,
        "reorder_rate": 0.0,
        "eta_breach_rate": 0.0,
        "cancellation_rate": 0.0,
    }
    return counts | rates
