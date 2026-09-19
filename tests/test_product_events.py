import pandas as pd
import pytest

from planner.product_events import funnel_metrics, validate_event_frame


def _events() -> pd.DataFrame:
    return pd.DataFrame([
        {"event_id": "1", "event_at": "2026-09-15T09:00:00Z", "user_id": "u1", "session_id": "s1", "event_name": "serviceability_check", "city": "pune", "micro_market": "kothrud", "is_serviceable": True},
        {"event_id": "2", "event_at": "2026-09-15T09:01:00Z", "user_id": "u1", "session_id": "s1", "event_name": "browse", "city": "pune", "micro_market": "kothrud"},
        {"event_id": "3", "event_at": "2026-09-15T09:02:00Z", "user_id": "u1", "session_id": "s1", "event_name": "add_to_cart", "city": "pune", "micro_market": "kothrud"},
        {"event_id": "4", "event_at": "2026-09-15T09:03:00Z", "user_id": "u1", "session_id": "s1", "event_name": "checkout_started", "city": "pune", "micro_market": "kothrud"},
        {"event_id": "5", "event_at": "2026-09-15T09:04:00Z", "user_id": "u1", "session_id": "s1", "event_name": "order_completed", "city": "pune", "micro_market": "kothrud", "eta_promised_min": 10, "actual_delivery_min": 12},
        {"event_id": "6", "event_at": "2026-09-15T09:05:00Z", "user_id": "u1", "session_id": "s2", "event_name": "reorder", "city": "pune", "micro_market": "kothrud"},
        {"event_id": "7", "event_at": "2026-09-15T09:00:00Z", "user_id": "u2", "session_id": "s3", "event_name": "serviceability_check", "city": "pune", "micro_market": "kothrud", "is_serviceable": False},
        {"event_id": "8", "event_at": "2026-09-15T09:01:00Z", "user_id": "u2", "session_id": "s3", "event_name": "browse", "city": "pune", "micro_market": "kothrud"},
    ])


def test_event_frame_is_normalised_and_rejects_bad_contracts():
    frame = validate_event_frame(_events())
    assert str(frame.event_at.dtype) == "datetime64[us, UTC]"
    with pytest.raises(ValueError, match="unknown"):
        validate_event_frame(_events().assign(event_name="not_an_event"))
    with pytest.raises(ValueError, match="unique"):
        validate_event_frame(pd.concat([_events(), _events().iloc[[0]]], ignore_index=True))
    with pytest.raises(ValueError, match="is_serviceable"):
        validate_event_frame(_events().drop(columns="is_serviceable"))


def test_funnel_uses_eligible_users_and_returns_reliability_guardrails():
    metrics = funnel_metrics(_events())
    assert metrics["eligible_users"] == 1
    assert metrics["browsed_users"] == 1
    assert metrics["completed_users"] == 1
    assert metrics["reliable_completed_orders_per_eligible_user"] == 1.0
    assert metrics["eta_breach_rate"] == 1.0
    assert metrics["reorder_rate"] == 1.0
