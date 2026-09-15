from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon

WGS84 = "EPSG:4326"


def _lat_first(pair: list, source: str) -> tuple[float, float]:
    # The snapshot was verified lat-first; fail loudly instead of silently swapping if that ever changes.
    lat, lng = float(pair[0]), float(pair[1])
    if not (6 <= lat <= 38 and 68 <= lng <= 98):
        raise ValueError(f"{source}: expected [lat, lng] inside India, got {pair!r}")
    return lat, lng


def _read(raw_dir: Path, name: str) -> list[dict]:
    return json.loads((raw_dir / name).read_text(encoding="utf-8"))


def load_stores(raw_dir: str | Path) -> gpd.GeoDataFrame:
    raw_dir = Path(raw_dir)
    rows = []
    for rec in _read(raw_dir, "blinkit.json"):
        lat, lng = _lat_first(rec["coordinates"], "blinkit.json")
        accuracy = rec.get("accuracy")
        rows.append({"brand": "Blinkit", "store_id": str(rec["id"]), "lat": lat, "lng": lng, "label": None,
                     "accuracy_m": float(accuracy) if accuracy not in (None, "") else None})
    for rec in _read(raw_dir, "swiggy.json"):
        lat, lng = _lat_first(rec["coordinates"], "swiggy.json")
        rows.append({"brand": "Swiggy Instamart", "store_id": str(rec["id"]), "lat": lat, "lng": lng,
                     "label": rec.get("locality"), "accuracy_m": None})
    for rec in _read(raw_dir, "zepto.json"):
        lat, lng = _lat_first([rec["lat"], rec["lng"]], "zepto.json")
        rows.append({"brand": "Zepto", "store_id": str(rec["id"]), "lat": lat, "lng": lng,
                     "label": rec.get("name"), "accuracy_m": None})
    df = pd.DataFrame(rows)
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["lng"], df["lat"]), crs=WGS84)


def load_zepto_zones(raw_dir: str | Path) -> gpd.GeoDataFrame:
    records = _read(Path(raw_dir), "zepto.json")
    geoms = [
        Polygon([(lng, lat) for lat, lng in (_lat_first(p, "zepto.json zone") for p in rec["zone"])])
        for rec in records
    ]
    return gpd.GeoDataFrame(
        {"store_id": [str(r["id"]) for r in records], "label": [r.get("name") for r in records],
         "city": [r.get("city") for r in records]},
        geometry=geoms, crs=WGS84,
    )
