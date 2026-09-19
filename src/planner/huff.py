"""Huff gravity model: probabilistic demand allocation and cannibalization.

Replaces the binary "does this store reach this hex" question with "how much of this
hex's demand does each nearby store actually get," weighted by distance decay. This is a
genuinely different mechanism from the existing optimizer's shared-capacity constraint: two
stores can both reach a hex under a hard radius cutoff and still receive very different
shares of its demand here, because the closer one wins more of it.

Attractiveness is assumed uniform across stores of the same brand -- there is no real
per-store size/quality signal in this repository (the economics model already assumes a
uniform store size; see config/economics.yaml). The distance-decay exponent is a labeled
assumption, swept rather than presented as one calibrated truth (see
scripts/validate_huff_zepto.py). The real contribution here is the distance-decay
weighting itself, not a claim to have measured customer attractiveness.
"""
from __future__ import annotations

import numpy as np

EARTH_RADIUS_KM = 6371.0
MIN_DISTANCE_KM = 0.05  # avoids a singularity when a store sits exactly at a hex centroid


def pairwise_distance_km(hex_lat: np.ndarray, hex_lng: np.ndarray, store_lat: np.ndarray, store_lng: np.ndarray) -> np.ndarray:
    """(n_hex, n_store) haversine distance matrix in km."""
    lat1 = np.radians(np.asarray(hex_lat, dtype=float))[:, None]
    lat2 = np.radians(np.asarray(store_lat, dtype=float))[None, :]
    dlng = np.radians(np.asarray(store_lng, dtype=float))[None, :] - np.radians(np.asarray(hex_lng, dtype=float))[:, None]
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def choice_probability_matrix(
    hex_lat: np.ndarray, hex_lng: np.ndarray, store_lat: np.ndarray, store_lng: np.ndarray,
    distance_decay: float = 2.0, attractiveness: np.ndarray | None = None, max_distance_km: float | None = None,
) -> np.ndarray:
    """(n_hex, n_store) Huff probabilities. A row sums to 1, or is all-zero if no store is in range."""
    if distance_decay <= 0:
        raise ValueError("distance_decay must be positive")
    if len(store_lat) == 0:
        return np.zeros((len(hex_lat), 0))
    dist = np.maximum(pairwise_distance_km(hex_lat, hex_lng, store_lat, store_lng), MIN_DISTANCE_KM)
    attract = np.ones(dist.shape[1]) if attractiveness is None else np.asarray(attractiveness, dtype=float)
    if (attract <= 0).any():
        raise ValueError("attractiveness must be positive")
    weights = attract[None, :] / dist**distance_decay
    if max_distance_km is not None:
        weights = np.where(dist <= max_distance_km, weights, 0.0)
    row_sums = weights.sum(axis=1, keepdims=True)
    return np.divide(weights, row_sums, out=np.zeros_like(weights), where=row_sums > 0)


def allocate_demand(demand_per_hex: np.ndarray, probabilities: np.ndarray) -> np.ndarray:
    """(n_store,) demand received by each store: probabilities.T @ demand_per_hex."""
    return probabilities.T @ np.asarray(demand_per_hex, dtype=float)


def evaluate_candidate_site(
    demand_per_hex: np.ndarray, hex_lat: np.ndarray, hex_lng: np.ndarray,
    existing_lat: np.ndarray, existing_lng: np.ndarray, candidate_lat: float, candidate_lng: float,
    **huff_kwargs,
) -> dict[str, float]:
    """Gross demand a candidate site would draw, how much of it is cannibalized from
    existing stores, and the resulting net-incremental demand -- computed by comparing
    Huff allocation with and without the candidate in the choice set.
    """
    without = allocate_demand(demand_per_hex, choice_probability_matrix(hex_lat, hex_lng, existing_lat, existing_lng, **huff_kwargs))
    all_lat, all_lng = np.append(existing_lat, candidate_lat), np.append(existing_lng, candidate_lng)
    with_candidate = allocate_demand(demand_per_hex, choice_probability_matrix(hex_lat, hex_lng, all_lat, all_lng, **huff_kwargs))
    candidate_gross = float(with_candidate[-1])
    cannibalized = float(np.clip(without - with_candidate[:-1], 0, None).sum())
    net_incremental = candidate_gross - cannibalized
    return {
        "candidate_gross_demand": candidate_gross, "cannibalized_from_existing": cannibalized,
        "net_incremental_demand": net_incremental,
        "cannibalization_rate": cannibalized / candidate_gross if candidate_gross > 0 else 0.0,
    }
