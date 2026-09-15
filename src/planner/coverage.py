from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping

import numpy as np
import pandas as pd

EARTH_RADIUS_KM = 6371.0


def nearest_store_km(hex_lat: np.ndarray, hex_lng: np.ndarray, store_lat: np.ndarray, store_lng: np.ndarray) -> np.ndarray:
    """Great-circle distance (km) from each hex centroid to its nearest store; inf when there are no stores."""
    if len(store_lat) == 0:
        return np.full(len(hex_lat), np.inf)
    lat1 = np.radians(np.asarray(hex_lat, dtype=float))[:, None]
    lat2 = np.radians(np.asarray(store_lat, dtype=float))[None, :]
    dlng = np.radians(np.asarray(store_lng, dtype=float))[None, :] - np.radians(np.asarray(hex_lng, dtype=float))[:, None]
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlng / 2) ** 2
    return (2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))).min(axis=1)


def brand_slug(brand: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", brand.lower()).strip("_")


def coverage_table(
    store_cells: Mapping[tuple[str, str], set[str]],
    area_cells: set[str],
    brands: list[str],
) -> pd.DataFrame:
    """Per study-area hex: covering-store counts per brand, total stores, brands covering, and any-brand flag.

    `store_cells` maps (brand, store_id) to the cells that store reaches; cells outside `area_cells` are ignored.
    """
    counts: dict[str, defaultdict[str, int]] = {b: defaultdict(int) for b in brands}
    for (brand, _store_id), cells in store_cells.items():
        if brand not in counts:
            continue
        for cell in cells & area_cells:
            counts[brand][cell] += 1

    table = pd.DataFrame({"h3": sorted(area_cells)})
    brand_cols = []
    for brand in brands:
        col = f"stores_{brand_slug(brand)}"
        table[col] = table["h3"].map(counts[brand]).fillna(0).astype(int)
        brand_cols.append(col)
    table["stores_total"] = table[brand_cols].sum(axis=1)
    table["brands_covering"] = (table[brand_cols] > 0).sum(axis=1)
    table["covered_any"] = table["stores_total"] > 0
    return table
