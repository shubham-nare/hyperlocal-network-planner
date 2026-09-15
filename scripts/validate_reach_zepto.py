"""Validate the road-network reach model against Zepto's own delivery zones (third-party snapshot).

Zepto zones are business-defined service areas, not literal isochrones: agreement measures how well the reach
model reproduces real service footprints, and the straight-line radius baseline shows whether roads add value.
"""
from __future__ import annotations

import argparse
import time

import geopandas as gpd
import h3
import osmnx as ox
import pandas as pd
import yaml

from planner.reach import NodeLocator, fill_holes, radius_cells, ride_budget_m, road_cells


def overlap(model: set[str], zone: set[str]) -> tuple[float, float, float]:
    inter, union = len(model & zone), len(model | zone)
    precision = inter / len(model) if model else 0.0
    recall = inter / len(zone) if zone else 0.0
    return precision, recall, inter / union if union else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="hyderabad")
    parser.add_argument("--resolution", type=int, default=9, help="finer than the res-8 grid so zone overlap is not blocky")
    parser.add_argument("--speeds", default=",".join(str(s) for s in range(10, 21)), help="rider speeds (km/h) to sweep")
    args = parser.parse_args()

    defaults = yaml.safe_load(open("config/cities.yaml", encoding="utf-8"))["defaults"]
    promise, picking = defaults["delivery_promise_min"], defaults["picking_time_min"]
    speeds = [float(s) for s in args.speeds.split(",")]

    t = time.time()
    graph = ox.load_graphml(f"data/interim/{args.city}_drive.graphml")
    locator = NodeLocator(graph)
    stores = gpd.read_file(f"data/processed/{args.city}_stores.gpkg")
    zepto = stores[stores["brand"] == "Zepto"]
    zones = gpd.read_file(f"data/processed/{args.city}_zepto_zones.gpkg").set_index("store_id").geometry
    print(f"loaded graph + {len(zepto)} Zepto stores / {len(zones)} zones in {time.time() - t:.0f}s")

    zone_cells = {sid: set(h3.geo_to_cells(zones.loc[sid], args.resolution)) for sid in zepto["store_id"] if sid in zones.index}
    rows = []
    for speed in speeds:
        budget = ride_budget_m(promise, picking, speed)
        for s in zepto.itertuples():
            cells = zone_cells.get(s.store_id)
            if not cells:
                continue
            road = road_cells(graph, locator, s.lat, s.lng, budget, args.resolution)
            filled = fill_holes(road)
            circle = radius_cells(s.lat, s.lng, budget, args.resolution)
            rp, rr, riou = overlap(road, cells)
            fp, fr, fiou = overlap(filled, cells)
            bp, br, biou = overlap(circle, cells)
            rows.append({"speed_kmph": speed, "budget_m": round(budget), "store_id": s.store_id, "label": s.label,
                         "zone_cells": len(cells), "road_cells": len(road), "road_filled_cells": len(filled),
                         "radius_cells": len(circle),
                         "road_precision": rp, "road_recall": rr, "road_iou": riou,
                         "road_filled_precision": fp, "road_filled_recall": fr, "road_filled_iou": fiou,
                         "radius_precision": bp, "radius_recall": br, "radius_iou": biou})

    df = pd.DataFrame(rows)
    out = f"reports/reach_validation_{args.city}.csv"
    df.to_csv(out, index=False)

    methods = ["road", "road_filled", "radius"]
    medians = df.groupby("speed_kmph")[[f"{m}_iou" for m in methods]].median().round(3)
    print(f"\n{args.city}: {df['store_id'].nunique()} stores x {len(speeds)} speeds at H3 res {args.resolution} "
          f"(promise {promise} min, picking {picking} min) -> {out}")
    print("median IoU by speed (km/h):")
    print(medians.to_string())

    # Fair comparison: each method at its own best-fitting speed, then store-by-store.
    best = {m: medians[f"{m}_iou"].idxmax() for m in methods}
    print("\nbest speed per method: " + " | ".join(
        f"{m} {best[m]:g} km/h -> {medians.loc[best[m], f'{m}_iou']}" for m in methods))
    per_store = {m: df[df["speed_kmph"] == best[m]].set_index("store_id")[f"{m}_iou"] for m in methods}
    for m in ("road", "road_filled"):
        diff = (per_store[m] - per_store["radius"]).dropna()
        print(f"{m} (at {best[m]:g}) vs radius (at {best['radius']:g}): wins {(diff > 0).mean():.0%} of stores | "
              f"median diff {diff.median():+.3f} | mean diff {diff.mean():+.3f}")


if __name__ == "__main__":
    main()
