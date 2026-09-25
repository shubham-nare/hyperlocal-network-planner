"""Rebuild per-hex features for the three cities from Overture Maps + Meta HRSL (public S3).

Why this exists: see src/planner/open_data.py. Output is one parquet per city at
data/processed/{city}_open_features_r8.parquet (gitignored, regenerable), holding the study-area
hexes plus a buffer ring of context hexes (``in_study_area`` False) so catchment sums near the
edge of the study area don't silently drop demand that sits just outside it.

Study area uses the v1 rule and thresholds from config/cities.yaml: core + contiguous hexes at
>= min_density_per_km2, ribbons trimmed. Core = the pinned OSM municipal polygon via Overture
(Hyderabad, Bengaluru). Pune's pinned polygon (R10351626, a sub-district) is not in Overture, so
its core is approximated by an equal-area (312 km2) disk around the city centre -- labelled in
the output and in CONTEXT.md.

    PYTHONPATH=src python scripts/build_open_features.py
"""
from __future__ import annotations

import os
import time

import h3
import numpy as np
import pandas as pd
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.fs as pafs
import rasterio
import yaml
from rasterio.windows import from_bounds
from shapely import wkb

from planner.open_data import (
    HIGHRISE_BUILDING_CLASSES, POI_CATEGORIES, buffer_cells, classify_places, count_points_by_cell, disk_cells,
    raster_to_cells,
)
from planner.study_area import candidate_cells, grow_dense_area, trim_ribbons

OVERTURE_RELEASE = "2026-09-23.0"
OVERTURE = f"overturemaps-us-west-2/release/{OVERTURE_RELEASE}"
HRSL_VRT = "/vsicurl/https://dataforgood-fb-data.s3.amazonaws.com/hrsl-cogs/hrsl_general/hrsl_general-latest.vrt"
CONTEXT_RINGS = 3  # ~2.4 km beyond the study-area edge; the widest calibrated reach radius is 1.625 km.
PUNE_FALLBACK = {"lat": 18.5204, "lng": 73.8567, "area_km2": 312.0}  # city centre; v1 core area


def _s3() -> pafs.S3FileSystem:
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    return pafs.S3FileSystem(anonymous=True, region="us-west-2", **({"proxy_options": proxy} if proxy else {}))


def _bbox_filter(west: float, south: float, east: float, north: float):
    return ((pc.field("bbox", "xmin") >= west) & (pc.field("bbox", "xmax") <= east)
            & (pc.field("bbox", "ymin") >= south) & (pc.field("bbox", "ymax") <= north))


def _core_cells(fs, osm_id: str, res: int, city: str) -> tuple[set[str], str]:
    relation = osm_id.lstrip("R")
    divisions = ds.dataset(f"{OVERTURE}/theme=divisions/type=division_area/", filesystem=fs, format="parquet")
    table = divisions.to_table(columns=["geometry", "sources", "names"],
                               filter=_bbox_filter(68, 6, 98, 38) & (pc.field("country") == "IN"))
    for row in table.to_pylist():
        if any((s.get("record_id") or "").startswith(f"r{relation}@") for s in row["sources"] or []):
            return set(h3.geo_to_cells(wkb.loads(row["geometry"]), res)), f"overture division = OSM r{relation}"
    if city == "pune":
        radius = float(np.sqrt(PUNE_FALLBACK["area_km2"] / np.pi))
        return (disk_cells(PUNE_FALLBACK["lat"], PUNE_FALLBACK["lng"], radius, res),
                f"APPROXIMATION: {PUNE_FALLBACK['area_km2']:.0f} km2 disk (r={radius:.2f} km); OSM r{relation} not in Overture")
    raise LookupError(f"{city}: OSM relation {osm_id} not found in Overture divisions")


def _population(cells: set[str], res: int) -> pd.Series:
    lats, lngs = zip(*(h3.cell_to_latlng(c) for c in cells))
    pad = 0.02
    bounds = (min(lngs) - pad, min(lats) - pad, max(lngs) + pad, max(lats) + pad)
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CURL_CA_BUNDLE=os.environ.get("CURL_CA_BUNDLE", "/etc/ssl/certs/ca-certificates.crt")):
        with rasterio.open(HRSL_VRT) as src:
            window = from_bounds(*bounds, src.transform).round_offsets().round_lengths()
            values = src.read(1, window=window)
            t = src.window_transform(window)
    return raster_to_cells(values, t.c, t.f, t.a, -t.e, res, cells)


def _places(fs, bounds, res: int) -> pd.DataFrame:
    places = ds.dataset(f"{OVERTURE}/theme=places/type=place/", filesystem=fs, format="parquet")
    table = places.to_table(columns=["bbox", "taxonomy", "confidence"], filter=_bbox_filter(*bounds))
    bbox = table.column("bbox").to_pylist()
    tax = table.column("taxonomy").to_pylist()
    flags = classify_places([(t or {}).get("hierarchy") for t in tax], table.column("confidence").to_pylist())
    lat = np.array([(b["ymin"] + b["ymax"]) / 2 for b in bbox])
    lng = np.array([(b["xmin"] + b["xmax"]) / 2 for b in bbox])
    flags["places_all"] = [c is not None and c >= 0.5 for c in table.column("confidence").to_pylist()]
    return count_points_by_cell(lat, lng, flags, res)


def _buildings(fs, bounds, res: int) -> pd.DataFrame:
    buildings = ds.dataset(f"{OVERTURE}/theme=buildings/type=building/", filesystem=fs, format="parquet")
    table = buildings.to_table(columns=["bbox", "class"], filter=_bbox_filter(*bounds))
    xmin, xmax = pc.struct_field(table.column("bbox"), "xmin"), pc.struct_field(table.column("bbox"), "xmax")
    ymin, ymax = pc.struct_field(table.column("bbox"), "ymin"), pc.struct_field(table.column("bbox"), "ymax")
    lat = ((ymin.to_numpy() + ymax.to_numpy()) / 2)
    lng = ((xmin.to_numpy() + xmax.to_numpy()) / 2)
    cls = table.column("class").to_pylist()
    flags = pd.DataFrame({"buildings": np.ones(len(cls), dtype=bool),
                          "residential_highrise": [c in HIGHRISE_BUILDING_CLASSES for c in cls]})
    return count_points_by_cell(lat, lng, flags, res)


def _neighbourhoods(fs, bounds) -> pd.DataFrame:
    """Named neighbourhood points (Overture divisions), only for labelling outputs readably."""
    divisions = ds.dataset(f"{OVERTURE}/theme=divisions/type=division/", filesystem=fs, format="parquet")
    table = divisions.to_table(columns=["names", "subtype", "bbox"], filter=_bbox_filter(*bounds)
                               & pc.field("subtype").isin(["microhood", "neighborhood", "macrohood", "locality"]))
    rows = [{"name": (r["names"] or {}).get("primary"), "subtype": r["subtype"],
             "lat": (r["bbox"]["ymin"] + r["bbox"]["ymax"]) / 2, "lng": (r["bbox"]["xmin"] + r["bbox"]["xmax"]) / 2}
            for r in table.to_pylist()]
    return pd.DataFrame(rows).dropna(subset=["name"])


def main() -> None:
    cfg = yaml.safe_load(open("config/cities.yaml", encoding="utf-8"))
    res = cfg["defaults"]["h3_resolution"]
    sa = cfg["defaults"]["study_area"]
    fs = _s3()
    for city, spec in cfg["cities"].items():
        t0 = time.time()
        core, core_note = _core_cells(fs, spec["osm_id"], res, city)
        cands = candidate_cells(core, sa["max_rings"])
        pop = _population(cands, res)
        area_km2 = pd.Series({c: h3.cell_area(c, unit="km^2") for c in cands})
        density = (pop / area_km2).to_dict()
        final = trim_ribbons(grow_dense_area(core, density, sa["min_density_per_km2"], sa["max_rings"]),
                             core, sa["ribbon_min_neighbours"])
        context = buffer_cells(final, CONTEXT_RINGS)
        missing = context - set(pop.index)
        if missing:
            pop = pd.concat([pop, _population(missing, res)])

        lats, lngs = zip(*(h3.cell_to_latlng(c) for c in context))
        bounds = (min(lngs) - 0.01, min(lats) - 0.01, max(lngs) + 0.01, max(lats) + 0.01)
        places = _places(fs, bounds, res)
        t1 = time.time()
        buildings = _buildings(fs, bounds, res)
        t2 = time.time()
        _neighbourhoods(fs, bounds).assign(city=city).to_parquet(f"data/processed/{city}_neighbourhoods.parquet", index=False)

        cells = sorted(context)
        out = pd.DataFrame({"h3": cells})
        out["lat"], out["lng"] = zip(*(h3.cell_to_latlng(c) for c in cells))
        out["area_km2"] = [h3.cell_area(c, unit="km^2") for c in cells]
        out["population"] = out["h3"].map(pop).fillna(0.0)
        out["density_per_km2"] = out["population"] / out["area_km2"]
        for col in (*POI_CATEGORIES, "places_all"):
            out[col] = out["h3"].map(places[col]).fillna(0).astype(int)
        for col in ("buildings", "residential_highrise"):
            out[col] = out["h3"].map(buildings[col]).fillna(0).astype(int)
        out["in_study_area"] = out["h3"].isin(final)
        out["in_core"] = out["h3"].isin(core)
        out["city"] = city
        out.attrs["core_source"] = core_note
        path = f"data/processed/{city}_open_features_r{res}.parquet"
        out.to_parquet(path, index=False)
        sa_rows = out[out["in_study_area"]]
        print(f"{city}: core {len(core):,} [{core_note}] | study area {len(final):,} hexes, "
              f"pop {sa_rows['population'].sum():,.0f} | context {len(context):,} | "
              f"POIs office/edu/food {sa_rows['office'].sum():,}/{sa_rows['education'].sum():,}/"
              f"{sa_rows['food_retail'].sum():,} | buildings {sa_rows['buildings'].sum():,} "
              f"(apartments {sa_rows['residential_highrise'].sum():,}) | "
              f"{t1 - t0:.0f}s + buildings {t2 - t1:.0f}s -> {path}", flush=True)


if __name__ == "__main__":
    main()
