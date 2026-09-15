"""Sanity check: where well-known demand hubs rank in each city's demand index (approximate landmark coordinates)."""
from __future__ import annotations

import geopandas as gpd
import h3

LANDMARKS = {
    "hyderabad": {"HITEC City": (17.4474, 78.3762), "Madhapur": (17.4483, 78.3915),
                  "Banjara Hills": (17.4156, 78.4347), "Charminar": (17.3616, 78.4747)},
    "bengaluru": {"Koramangala": (12.9352, 77.6245), "Indiranagar": (12.9784, 77.6408),
                  "Whitefield": (12.9698, 77.7499), "Electronic City": (12.8456, 77.6603)},
    "pune": {"Hinjewadi": (18.5913, 73.7389), "Koregaon Park": (18.5362, 73.8940),
             "Viman Nagar": (18.5679, 73.9143), "Pimpri": (18.6298, 73.7997)},
}
RES = 8


def main() -> None:
    for city, points in LANDMARKS.items():
        hexes = gpd.read_file(f"data/processed/{city}_demand_r{RES}.gpkg").set_index("h3")
        rank_pct = hexes["demand_index"].rank(pct=True)
        v1b_pct = hexes["demand_index_v1b"].rank(pct=True) if "demand_index_v1b" in hexes else None
        print(f"\n== {city} ({len(hexes):,} hexes) | landmark = best hex within k=1 ==")
        for name, (lat, lng) in points.items():
            # Exact-coordinate hexes can sit on a neighbourhood's edge (e.g. airport land), so judge the neighbourhood.
            ring = [c for c in h3.grid_disk(h3.latlng_to_cell(lat, lng, RES), 1) if c in hexes.index]
            if not ring:
                print(f"  {name:<16} not in study area")
                continue
            cell = max(ring, key=lambda c: rank_pct[c])
            row = hexes.loc[cell]
            v1b = f" | v1b top {100 * (1 - max(v1b_pct[c] for c in ring)):4.1f}%" if v1b_pct is not None else ""
            print(f"  {name:<16} index {row['demand_index']:5.1f} | top {100 * (1 - rank_pct[cell]):4.1f}% of hexes{v1b} | "
                  f"density {row['density_per_km2']:,.0f}/km2 | office {int(row['office'])} | food_retail {int(row['food_retail'])} "
                  f"| education {int(row['education'])} | apartments {int(row['residential_highrise'])}")


if __name__ == "__main__":
    main()
