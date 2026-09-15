"""Hold-out validation helpers: hide some real stores, then check whether proposed sites land near them."""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from planner.coverage import nearest_store_km


def holdout_split(ids: Sequence[str], share: float, rng: np.random.Generator) -> tuple[list[str], list[str]]:
    """(kept, held_out), each in the original order; at least one store is held out."""
    if not 0 < share < 1:
        raise ValueError("share must be in (0, 1)")
    n_held = max(1, round(len(ids) * share))
    held = set(rng.choice(np.asarray(ids), size=n_held, replace=False).tolist())
    return [i for i in ids if i not in held], [i for i in ids if i in held]


def match_metrics(true_lat: np.ndarray, true_lng: np.ndarray, pred_lat: np.ndarray, pred_lng: np.ndarray,
                  within_km: float) -> dict[str, float]:
    """Recall = held-out stores with a proposed site within `within_km`; precision = proposed sites near a held-out store."""
    true_to_pred = nearest_store_km(true_lat, true_lng, pred_lat, pred_lng)
    pred_to_true = nearest_store_km(pred_lat, pred_lng, true_lat, true_lng)
    return {
        "recall": float((true_to_pred <= within_km).mean()) if len(true_lat) else float("nan"),
        "precision": float((pred_to_true <= within_km).mean()) if len(pred_lat) else float("nan"),
        "median_km_true_to_pred": float(np.median(true_to_pred)) if len(true_lat) else float("nan"),
    }
