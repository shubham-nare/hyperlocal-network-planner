import math

import h3
import numpy as np
import rasterio
from rasterio.transform import from_origin

from planner.grid import cells_to_gdf
from planner.population import hex_population

CENTER_LAT, CENTER_LNG = 17.385, 78.4867
PIXEL_DEG = 0.001
NODATA = -99999.0


def _raster(tmp_path, value):
    n = 100
    path = tmp_path / "pop.tif"
    with rasterio.open(
        path, "w", driver="GTiff", height=n, width=n, count=1, dtype="float32", crs="EPSG:4326",
        transform=from_origin(CENTER_LNG - 0.05, CENTER_LAT + 0.05, PIXEL_DEG, PIXEL_DEG), nodata=NODATA,
    ) as dst:
        dst.write(np.full((n, n), value, dtype="float32"), 1)
    return str(path)


def _hexes():
    return cells_to_gdf(h3.grid_disk(h3.latlng_to_cell(CENTER_LAT, CENTER_LNG, 8), 1))


def test_hex_population_matches_uniform_density(tmp_path):
    pixel_km2 = (PIXEL_DEG * 111.32) * (PIXEL_DEG * 111.32 * math.cos(math.radians(CENTER_LAT)))
    out = hex_population(_hexes(), _raster(tmp_path, value=2.0))
    expected = out["area_km2"] / pixel_km2 * 2.0
    assert ((out["population"] - expected).abs() / expected).max() < 0.15


def test_all_nodata_hexes_get_zero_population_not_none(tmp_path):
    out = hex_population(_hexes(), _raster(tmp_path, value=NODATA))
    assert (out["population"] == 0.0).all()


def test_density_is_population_per_km2(tmp_path):
    out = hex_population(_hexes(), _raster(tmp_path, value=1.0))
    assert np.allclose(out["density_per_km2"], out["population"] / out["area_km2"])
