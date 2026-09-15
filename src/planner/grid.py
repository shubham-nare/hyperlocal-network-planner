from __future__ import annotations

from collections.abc import Iterable

import geopandas as gpd
import h3
import osmnx as ox
from shapely.geometry import Polygon

WGS84 = "EPSG:4326"


def load_boundary(query: str, by_osmid: bool = False) -> gpd.GeoDataFrame:
    gdf = ox.geocode_to_gdf(query, by_osmid=by_osmid)
    return gdf[["display_name", "geometry"]].to_crs(WGS84)


def cells_to_gdf(cells: Iterable[str]) -> gpd.GeoDataFrame:
    cells = sorted(cells)
    hexes = gpd.GeoDataFrame(
        {"h3": cells},
        geometry=[Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)]) for c in cells],
        crs=WGS84,
    )
    # UTM zone differs by city (Hyderabad 44N, Bengaluru/Pune 43N), so estimate it per grid.
    hexes["area_km2"] = hexes.to_crs(hexes.estimate_utm_crs()).area / 1e6
    return hexes


def hex_grid(boundary: gpd.GeoDataFrame, resolution: int) -> gpd.GeoDataFrame:
    geom = boundary.to_crs(WGS84).geometry.union_all()
    return cells_to_gdf(h3.geo_to_cells(geom, resolution))
