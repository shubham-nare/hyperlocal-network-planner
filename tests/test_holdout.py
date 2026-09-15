import numpy as np
import pytest

from planner.holdout import holdout_split, match_metrics

IDS = [f"s{i}" for i in range(10)]


def test_split_is_disjoint_complete_and_seeded():
    kept, held = holdout_split(IDS, 0.2, np.random.default_rng(7))
    assert len(held) == 2 and set(kept) | set(held) == set(IDS) and not set(kept) & set(held)
    assert holdout_split(IDS, 0.2, np.random.default_rng(7)) == (kept, held)
    with pytest.raises(ValueError):
        holdout_split(IDS, 1.0, np.random.default_rng(7))


def test_split_holds_out_at_least_one():
    assert len(holdout_split(IDS[:2], 0.1, np.random.default_rng(1))[1]) == 1


def test_match_metrics_recall_and_precision():
    # Two held-out stores ~11 km apart; one proposed site ~0.5 km from the first.
    true_lat, true_lng = np.array([17.40, 17.50]), np.array([78.50, 78.50])
    pred_lat, pred_lng = np.array([17.4045]), np.array([78.50])
    m = match_metrics(true_lat, true_lng, pred_lat, pred_lng, within_km=1.5)
    assert m["recall"] == pytest.approx(0.5)
    assert m["precision"] == pytest.approx(1.0)
