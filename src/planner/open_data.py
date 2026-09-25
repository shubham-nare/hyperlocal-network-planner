"""Per-hex features from open data that is reachable without OSM/WorldPop servers.

The v1 pipeline builds its features from WorldPop (population) and OpenStreetMap (POIs, city
boundaries). This module rebuilds the *same kind* of features from two other public sources:

- **Population:** Meta / CIESIN High Resolution Settlement Layer (HRSL, ~30 m), read as a
  Cloud-Optimized GeoTIFF from the public ``dataforgood-fb-data`` S3 bucket.
- **POIs, buildings and city boundaries:** Overture Maps (public ``overturemaps-us-west-2`` S3
  bucket). Overture's divisions carry the original OSM relation id in ``sources``, so Hyderabad
  and Bengaluru use the *exact same* municipal polygons v1 pinned (R7868535, R7902476).

This is a documented deviation, not a silent swap: numbers built on these features are not
directly comparable with v1's WorldPop/OSM-based numbers, and every output that uses them says so.
The functions below are pure (no network) so they are unit-tested; the S3 reads live in
``scripts/build_open_features.py``.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

import h3
import numpy as np
import pandas as pd

# Overture places taxonomy -> the four v1 demand categories (config/demand.yaml), matched on any
# level of ``taxonomy.hierarchy``. Chosen to mirror the intent of the OSM tag sets, not copied 1:1:
# office = places people work at a desk; education = colleges/universities and student lodging;
# food_retail = eating out plus grocery/convenience/mall retail. Alcohol venues are left out.
POI_TAXONOMY: dict[str, frozenset[str]] = {
    "office": frozenset({
        "corporate_or_business_office", "b2b_service", "professional_service", "technical_service",
        "media_service", "legal_service", "design_service", "government_office", "coworking_space",
    }),
    "education": frozenset({"college_university", "university", "college", "hostel"}),
    "food_retail": frozenset({
        "restaurant", "casual_eatery", "cafe", "coffee_shop", "fast_food_restaurant", "bakery",
        "non_alcoholic_beverage_venue", "food_and_beverage_store", "grocery_store", "supermarket",
        "convenience_store", "shopping_mall", "department_store", "warehouse_club_store",
    }),
}
POI_CATEGORIES = tuple(POI_TAXONOMY)
MIN_PLACE_CONFIDENCE = 0.5  # Overture's own guidance: low-confidence places are often stale/duplicates.
HIGHRISE_BUILDING_CLASSES = frozenset({"apartments"})


def classify_places(hierarchies: Sequence[Sequence[str] | None], confidence: Sequence[float | None],
                    min_confidence: float = MIN_PLACE_CONFIDENCE) -> pd.DataFrame:
    """One boolean column per POI category; a place may count toward several categories."""
    rows = []
    for hier, conf in zip(hierarchies, confidence):
        levels = set(hier or ())
        ok = conf is not None and conf >= min_confidence
        rows.append({cat: ok and bool(levels & keys) for cat, keys in POI_TAXONOMY.items()})
    return pd.DataFrame(rows, columns=list(POI_CATEGORIES))


def count_points_by_cell(lat: np.ndarray, lng: np.ndarray, flags: pd.DataFrame, resolution: int) -> pd.DataFrame:
    """Sum boolean flag columns per H3 cell. Returns a frame indexed by cell id."""
    cells = [h3.latlng_to_cell(a, b, resolution) for a, b in zip(lat, lng)]
    frame = flags.astype(int).copy()
    frame["h3"] = cells
    return frame.groupby("h3").sum()


def raster_to_cells(values: np.ndarray, west: float, north: float, res_x: float, res_y: float,
                    resolution: int, cells: Iterable[str] | None = None) -> pd.Series:
    """Sum a north-up lat/lng raster window into H3 cells by pixel centre.

    Pixel-centre assignment gives every pixel to exactly one cell, the same no-double-count rule
    v1's ``population.hex_population`` uses (rasterstats ``all_touched=False``). NaN/negative -> 0.
    """
    vals = np.nan_to_num(values.astype(float), nan=0.0)
    vals[vals < 0] = 0.0
    rows, cols = np.nonzero(vals)
    lats = north - (rows + 0.5) * res_y
    lngs = west + (cols + 0.5) * res_x
    cell_ids = [h3.latlng_to_cell(a, b, resolution) for a, b in zip(lats, lngs)]
    sums = pd.Series(vals[rows, cols]).groupby(pd.Index(cell_ids)).sum()
    if cells is not None:
        sums = sums.reindex(sorted(set(cells)), fill_value=0.0)
    return sums


def disk_cells(lat: float, lng: float, radius_km: float, resolution: int) -> set[str]:
    """Cells whose centre lies within ``radius_km`` of a point (a stand-in core where no polygon exists)."""
    centre = h3.latlng_to_cell(lat, lng, resolution)
    k = int(np.ceil(radius_km / (h3.average_hexagon_edge_length(resolution, unit="km") * np.sqrt(3)))) + 2
    return {c for c in h3.grid_disk(centre, k) if h3.great_circle_distance((lat, lng), h3.cell_to_latlng(c), unit="km") <= radius_km}


def buffer_cells(cells: Iterable[str], rings: int) -> set[str]:
    out: set[str] = set()
    for c in cells:
        out.update(h3.grid_disk(c, rings))
    return out


def label_places(frame: pd.DataFrame, city: str, source: str = "open", processed_dir: str | Path = "data/processed") -> pd.DataFrame:
    """Add a ``place`` column: nearest named Overture neighbourhood within 2 km, else nearest
    locality. Readability only; empty names if build_open_features.py hasn't written the file."""
    from planner.revealed_demand import haversine_km  # local import: revealed_demand doesn't need this module

    try:
        places = pd.read_parquet(Path(processed_dir) / f"{city}_neighbourhoods.parquet")
    except FileNotFoundError:
        return frame.assign(place="")
    # a few Overture "neighborhood" records are really business listings ("X - Interior Designer in Y")
    places = places[~places["name"].str.contains(r" - | in (?:Hyderabad|Bengaluru|Bangalore|Pune)\b", regex=True)]
    fine = places[places["subtype"] != "locality"]
    names = []
    for lat, lng in zip(frame["lat"], frame["lng"]):
        d = haversine_km(lat, lng, fine["lat"].to_numpy(), fine["lng"].to_numpy())
        if len(d) and d.min() <= 2.0:
            names.append(fine["name"].iloc[int(d.argmin())])
        else:
            d = haversine_km(lat, lng, places["lat"].to_numpy(), places["lng"].to_numpy())
            names.append(places["name"].iloc[int(d.argmin())] if len(d) else "")
    return frame.assign(place=names)
