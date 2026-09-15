"""Cloud-kitchen opportunity scoring from public demand proxies.

This module intentionally stops at market discovery: WorldPop and OpenStreetMap do
not reveal meal-order volume, restaurant sales, kitchen costs, or platform take
rates.  The score helps select neighbourhoods for field validation, not sites to
open automatically.
"""
from __future__ import annotations

from collections.abc import Mapping

import h3
import pandas as pd


def opportunity_index(hexes: pd.DataFrame, weights: Mapping[str, float]) -> pd.Series:
    """Return a 0--100 within-city weighted percentile score for required features."""
    if not weights or sum(weights.values()) <= 0:
        raise ValueError("weights must sum to a positive value")
    missing = set(weights) - set(hexes.columns)
    if missing:
        raise ValueError(f"hexes missing required features: {sorted(missing)}")
    score = pd.Series(0.0, index=hexes.index)
    total = sum(weights.values())
    for feature, weight in weights.items():
        score += weight * hexes[feature].rank(pct=True, method="min")
    return 100 * score / total


def diversified_shortlist(hexes: pd.DataFrame, score: pd.Series, n: int, separation_rings: int = 2) -> pd.DataFrame:
    """Choose up to *n* high-scoring cells, suppressing nearby alternatives.

    H3 rings provide a transparent, city-agnostic minimum-separation rule.  The
    returned rows preserve score order and include ``cloud_kitchen_score``.
    """
    if n < 1:
        raise ValueError("n must be at least 1")
    if separation_rings < 0:
        raise ValueError("separation_rings must be non-negative")
    if "h3" not in hexes:
        raise ValueError("hexes must include an h3 column")

    ranked = hexes.copy()
    ranked["cloud_kitchen_score"] = score
    blocked: set[str] = set()
    chosen: list[int] = []
    for index, row in ranked.sort_values("cloud_kitchen_score", ascending=False).iterrows():
        cell = row["h3"]
        if cell in blocked:
            continue
        chosen.append(index)
        blocked.update(h3.grid_disk(cell, separation_rings))
        if len(chosen) == n:
            break
    return ranked.loc[chosen].sort_values("cloud_kitchen_score", ascending=False).reset_index(drop=True)
