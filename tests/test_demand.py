import geopandas as gpd
import h3
import pandas as pd
from shapely.geometry import Point

from planner.demand import count_by_hex, demand_index, demand_index_log
from planner.grid import cells_to_gdf

CELLS = sorted(h3.grid_disk(h3.latlng_to_cell(17.385, 78.4867, 8), 1))


def _points(cells_with_flags):
    rows, geoms = [], []
    for cell, office, food in cells_with_flags:
        lat, lng = h3.cell_to_latlng(cell)
        rows.append({"office": office, "food_retail": food})
        geoms.append(Point(lng, lat))
    return gpd.GeoDataFrame(pd.DataFrame(rows), geometry=geoms, crs="EPSG:4326")


def test_count_by_hex_counts_flags_per_cell_and_zero_fills():
    hexes = cells_to_gdf(CELLS)
    pts = _points([(CELLS[0], True, False), (CELLS[0], True, True), (CELLS[1], False, True)])
    out = count_by_hex(pts, hexes, ["office", "food_retail"]).set_index("h3")
    assert out.loc[CELLS[0], "office"] == 2 and out.loc[CELLS[0], "food_retail"] == 1
    assert out.loc[CELLS[1], "office"] == 0 and out.loc[CELLS[1], "food_retail"] == 1
    assert out.loc[CELLS[2], ["office", "food_retail"]].tolist() == [0, 0]


def test_count_by_hex_ignores_points_outside_the_grid():
    hexes = cells_to_gdf(CELLS[:1])
    pts = gpd.GeoDataFrame({"office": [True]}, geometry=[Point(0, 0)], crs="EPSG:4326")
    assert count_by_hex(pts, hexes, ["office"])["office"].tolist() == [0]


def _feature_grid():
    return pd.DataFrame({
        "density_per_km2": [100.0, 5000.0, 20000.0, 0.0],
        "office": [0, 2, 10, 0],
    })


def test_demand_index_is_higher_where_every_feature_is_higher_and_bounded():
    out = demand_index(_feature_grid(), {"density_per_km2": 0.6, "office": 0.4})
    idx = out["demand_index"].tolist()
    assert idx[2] > idx[1] > idx[0] >= idx[3]
    assert all(0 <= v <= 100 for v in idx)


def test_demand_index_is_invariant_to_weight_scale():
    a = demand_index(_feature_grid(), {"density_per_km2": 0.6, "office": 0.4})["demand_index"]
    b = demand_index(_feature_grid(), {"density_per_km2": 6, "office": 4})["demand_index"]
    assert (a - b).abs().max() < 1e-9


def test_tied_zero_counts_rank_at_the_bottom():
    out = demand_index(_feature_grid(), {"office": 1.0})
    zero_pct = out.loc[out["office"] == 0, "office_pct"]
    assert (zero_pct == zero_pct.min()).all() and zero_pct.iloc[0] <= 0.25


CENTER = h3.latlng_to_cell(17.385, 78.4867, 8)
RING1 = sorted(h3.grid_ring(CENTER, 1))


def _disk_grid(office_by_cell):
    grid = cells_to_gdf(h3.grid_disk(CENTER, 2))
    grid["office"] = grid["h3"].map(lambda c: office_by_cell.get(c, 0))
    grid["density_per_km2"] = 5000.0
    return grid


def test_log_index_returns_series_aligned_to_input_and_bounded():
    grid = _disk_grid({RING1[0]: 10})
    idx = demand_index_log(grid, {"density_per_km2": 0.5, "office": 0.5})
    assert isinstance(idx, pd.Series) and idx.index.equals(grid.index)
    assert idx.rank(pct=True).notna().all()
    assert idx.between(0, 100).all()


def test_log_index_rewards_intensity_not_just_rank():
    a = RING1[0]
    b = next(c for c in RING1 if h3.grid_distance(a, c) == 2)
    grid = _disk_grid({a: 216, b: 35}).set_index("h3", drop=False)
    idx = demand_index_log(grid, {"office": 1.0})
    assert idx[a] > idx[b] > 0
    assert idx[a] - idx[b] > 10


def test_log_index_is_invariant_to_weight_scale():
    grid = _disk_grid({RING1[0]: 20, RING1[3]: 5})
    a = demand_index_log(grid, {"density_per_km2": 0.45, "office": 0.55})
    b = demand_index_log(grid, {"density_per_km2": 45, "office": 55})
    assert (a - b).abs().max() < 1e-9
