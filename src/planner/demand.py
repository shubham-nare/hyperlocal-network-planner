from __future__ import annotations

import geopandas as gpd
import h3
import numpy as np
import pandas as pd


def count_by_hex(points: gpd.GeoDataFrame, hexes: gpd.GeoDataFrame, categories: list[str]) -> gpd.GeoDataFrame:
    pts = points[categories + ["geometry"]].to_crs(hexes.crs)
    joined = gpd.sjoin(pts, hexes[["h3", "geometry"]], predicate="within", how="inner")
    counts = joined.groupby("h3")[categories].sum()
    out = hexes.merge(counts, left_on="h3", right_index=True, how="left")
    out[categories] = out[categories].fillna(0).astype(int)
    return out


def demand_index(hexes: gpd.GeoDataFrame, weights: dict[str, float]) -> gpd.GeoDataFrame:
    """Weighted mean of within-city percentile ranks, scaled 0-100.

    method="min" ranks tied zeros at the bottom, so a hex with no activity for a feature scores ~0 on it.
    """
    out = hexes.copy()
    total = sum(weights.values())
    score = 0.0
    for feature, weight in weights.items():
        out[f"{feature}_pct"] = out[feature].rank(pct=True, method="min")
        score = score + weight * out[f"{feature}_pct"]
    out["demand_index"] = 100 * score / total
    return out


def smooth_k1(hexes: pd.DataFrame, column: str) -> pd.Series:
    """Mean of `column` over each hex and its in-area neighbours. Returns a Series aligned to hexes.index."""
    values = dict(zip(hexes["h3"], hexes[column]))
    return pd.Series(
        [np.mean([values[n] for n in h3.grid_disk(cell, 1) if n in values]) for cell in hexes["h3"]],
        index=hexes.index,
    )


def _minmax(s: pd.Series) -> pd.Series:
    span = s.max() - s.min()
    return (s - s.min()) / span if span > 0 else s * 0.0


def demand_index_log(
    hexes: pd.DataFrame,
    weights: dict[str, float],
    density_column: str = "density_per_km2",
    clip_quantile: float = 0.99,
) -> pd.Series:
    """Scenario index (0-100): k=1-smoothed features; counts log1p-scaled, density clipped at a quantile;
    each min-max scaled within the city, so intensity matters beyond rank order."""
    score = pd.Series(0.0, index=hexes.index)
    for feature, weight in weights.items():
        smoothed = smooth_k1(hexes, feature)
        if feature == density_column:
            scaled = _minmax(smoothed.clip(upper=smoothed.quantile(clip_quantile)))
        else:
            scaled = _minmax(np.log1p(smoothed))
        score = score + weight * scaled
    return 100 * score / sum(weights.values())
