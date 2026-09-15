import geopandas as gpd
import h3
from shapely.geometry import box

from planner.grid import hex_grid


def _boundary():
    # ~0.1 x 0.1 degree box in central Hyderabad; offline, no geocoding.
    return gpd.GeoDataFrame(geometry=[box(78.40, 17.35, 78.50, 17.45)], crs="EPSG:4326")


def test_cells_are_unique_and_at_requested_resolution():
    g = hex_grid(_boundary(), 8)
    assert len(g) > 0
    assert g["h3"].is_unique
    assert all(h3.get_resolution(c) == 8 for c in g["h3"])


def test_median_hex_area_matches_h3_resolution_8():
    g = hex_grid(_boundary(), 8)
    assert 0.6 < g["area_km2"].median() < 0.9


def test_total_hex_area_approximates_boundary_area():
    b = _boundary()
    g = hex_grid(b, 8)
    boundary_km2 = b.to_crs(b.estimate_utm_crs()).area.sum() / 1e6
    assert abs(g["area_km2"].sum() - boundary_km2) / boundary_km2 < 0.15
