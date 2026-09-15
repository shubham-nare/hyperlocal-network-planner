"""Population density of each city's core vs the surrounding candidate rings, to choose the urban threshold."""
from __future__ import annotations

import argparse

import geopandas as gpd
import numpy as np
import yaml

from planner.grid import cells_to_gdf
from planner.population import hex_population
from planner.study_area import candidate_cells

RASTER = "data/raw/ind_pop_2026_CN_100m_R2025A_v1.tif"
THRESHOLDS = [1_000, 2_500, 5_000, 10_000]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-rings", type=int, default=10)
    args = parser.parse_args()

    cfg = yaml.safe_load(open("config/cities.yaml", encoding="utf-8"))
    res = cfg["defaults"]["h3_resolution"]
    for city in cfg["cities"]:
        core = set(gpd.read_file(f"data/interim/{city}_h3_r{res}.gpkg")["h3"])
        hexes = hex_population(cells_to_gdf(candidate_cells(core, args.max_rings)), RASTER)
        hexes["in_core"] = hexes["h3"].isin(core)
        hexes.to_file(f"data/interim/{city}_candidates_pop_r{res}.gpkg", driver="GPKG")

        core_df, ring_df = hexes[hexes["in_core"]], hexes[~hexes["in_core"]]
        pct = lambda s: " / ".join(f"{v:,.0f}" for v in np.percentile(s, [10, 25, 50, 75, 90]))
        print(f"\n== {city}: {len(core_df):,} core hexes, {len(ring_df):,} ring hexes (max_rings={args.max_rings}) ==")
        print(f"core pop {core_df['population'].sum():,.0f} | ring pop {ring_df['population'].sum():,.0f}")
        print(f"density p10/p25/p50/p75/p90 per km2 | core: {pct(core_df['density_per_km2'])}")
        print(f"                                    | ring: {pct(ring_df['density_per_km2'])}")
        for t in THRESHOLDS:
            dense = ring_df[ring_df["density_per_km2"] >= t]
            share = dense["population"].sum() / max(ring_df["population"].sum(), 1)
            print(f"  ring hexes >= {t:>6,}/km2: {len(dense):>5,} hexes, {share:5.1%} of ring population")


if __name__ == "__main__":
    main()
