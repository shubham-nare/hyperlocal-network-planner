from __future__ import annotations

import geopandas as gpd
import osmnx as ox
import pandas as pd
from shapely.geometry.base import BaseGeometry


def query_tags(categories: dict[str, dict]) -> dict[str, bool | list[str]]:
    tags: dict[str, bool | set[str]] = {}
    for spec in categories.values():
        for key, values in spec.items():
            if values is True or tags.get(key) is True:
                tags[key] = True
            else:
                tags[key] = set(tags.get(key, set())) | set(values)
    return {k: v if v is True else sorted(v) for k, v in tags.items()}


def classify(features: pd.DataFrame, categories: dict[str, dict]) -> pd.DataFrame:
    flags = {}
    for name, spec in categories.items():
        mask = pd.Series(False, index=features.index)
        for key, values in spec.items():
            if key in features.columns:
                mask |= features[key].notna() if values is True else features[key].isin(values)
        flags[name] = mask
    return pd.DataFrame(flags, index=features.index)


def fetch_pois(polygon: BaseGeometry, categories: dict[str, dict]) -> gpd.GeoDataFrame:
    ox.settings.requests_timeout = 600
    feats = ox.features_from_polygon(polygon, tags=query_tags(categories))
    feats = feats[~feats.index.duplicated()]
    flags = classify(feats, categories)
    keep = flags.any(axis=1)
    points = gpd.GeoDataFrame(
        flags[keep], geometry=feats.loc[keep].geometry.representative_point(), crs=feats.crs
    ).reset_index()
    return points
