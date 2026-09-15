from __future__ import annotations

import geopandas as gpd
import rasterio
from rasterstats import zonal_stats


def hex_population(hexes: gpd.GeoDataFrame, raster_path: str) -> gpd.GeoDataFrame:
    with rasterio.open(raster_path) as src:
        raster_crs = src.crs
    # Pixel-centre inclusion (all_touched=False) assigns each pixel to exactly one hex, so totals don't double count.
    stats = zonal_stats(hexes.to_crs(raster_crs).geometry, raster_path, stats=["sum"], all_touched=False)
    out = hexes.copy()
    out["population"] = [max(s["sum"] or 0.0, 0.0) for s in stats]
    out["density_per_km2"] = out["population"] / out["area_km2"]
    return out
