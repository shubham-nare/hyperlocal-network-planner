"""Latent quick-commerce orders/day per hex, calibrated so hexes the brand already covers reproduce its actual orders."""
from __future__ import annotations

import pandas as pd


def adoption_index(hexes: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """0-100 weighted mean of `<feature>_pct` columns, meant for non-density features only.

    Order weights already multiply by population, so feeding a density-weighted index in would count density twice.
    """
    if "density_per_km2" in weights:
        raise ValueError("adoption index must exclude density; population already carries it")
    total = sum(weights.values())
    return 100 * sum(w * hexes[f"{k}_pct"] for k, w in weights.items()) / total


def adoption_multiplier(demand_index: pd.Series, elasticity: float) -> pd.Series:
    """Per-hex orders-per-person multiplier with city mean 1: 0 ignores the index, 1 is proportional to it."""
    if not 0 <= elasticity <= 1:
        raise ValueError("elasticity must be in [0, 1]")
    return (1 - elasticity) + elasticity * demand_index / demand_index.mean()


def order_weights(population: pd.Series, demand_index: pd.Series, elasticity: float) -> pd.Series:
    return population * adoption_multiplier(demand_index, elasticity)


def calibrate_orders_per_weight(weights: pd.Series, served: pd.Series, observed_stores: int,
                                snapshot_completeness: float, orders_per_store_day: float) -> float:
    """Orders/day per unit weight such that served hexes carry all of the brand's orders in the city.

    Observed stores are scaled up by snapshot completeness (share of the brand's real stores present in the snapshot).
    """
    if not 0 < snapshot_completeness <= 1:
        raise ValueError("snapshot completeness must be in (0, 1]")
    served_weight = weights[served].sum()
    if served_weight <= 0:
        raise ValueError("no served weight to calibrate against")
    return observed_stores / snapshot_completeness * orders_per_store_day / served_weight
