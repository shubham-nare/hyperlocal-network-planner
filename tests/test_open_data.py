import h3
import numpy as np
import pandas as pd

from planner.open_data import buffer_cells, classify_places, count_points_by_cell, disk_cells, raster_to_cells


def test_classify_places_matches_any_hierarchy_level_and_drops_low_confidence():
    flags = classify_places(
        [["food_and_drink", "restaurant"], ["education", "place_of_learning", "college_university"],
         ["services_and_business", "corporate_or_business_office"], ["food_and_drink", "restaurant"], None],
        [0.9, 0.8, 0.7, 0.2, 0.9],
    )
    assert flags.to_dict("list") == {
        "office": [False, False, True, False, False],
        "education": [False, True, False, False, False],
        "food_retail": [True, False, False, False, False],
    }


def test_count_points_by_cell_sums_flags():
    lat, lng = np.array([17.40, 17.40, 12.97]), np.array([78.45, 78.45, 77.59])
    flags = pd.DataFrame({"a": [True, False, True], "b": [True, True, False]})
    out = count_points_by_cell(lat, lng, flags, 8)
    cell = h3.latlng_to_cell(17.40, 78.45, 8)
    assert out.loc[cell, "a"] == 1 and out.loc[cell, "b"] == 2 and out["a"].sum() == 2


def test_raster_to_cells_conserves_total_and_zeroes_nan_and_negative():
    rng = np.random.default_rng(0)
    values = rng.uniform(0, 5, size=(60, 80))
    values[0, 0], values[1, 1] = np.nan, -3.0
    res = 0.0025  # ~275 m pixels over a ~16 x 22 km window
    sums = raster_to_cells(values, west=78.40, north=17.45, res_x=res, res_y=res, resolution=8)
    clean = np.nan_to_num(values.copy())
    clean[clean < 0] = 0
    assert abs(sums.sum() - clean.sum()) < 1e-6
    # every pixel centre lands in the cell it was assigned to
    cell = h3.latlng_to_cell(17.45 - 0.5 * res, 78.40 + 2.5 * res, 8)
    assert cell in sums.index


def test_raster_to_cells_reindexes_to_requested_cells():
    cells = {h3.latlng_to_cell(0.0, 0.0, 8)}
    sums = raster_to_cells(np.zeros((2, 2)), 10.0, 10.0, 0.001, 0.001, 8, cells)
    assert list(sums.index) == sorted(cells) and sums.iloc[0] == 0.0


def test_disk_cells_area_matches_radius_and_buffer_grows():
    cells = disk_cells(18.5204, 73.8567, 10.0, 8)
    area = sum(h3.cell_area(c, unit="km^2") for c in cells)
    assert abs(area - np.pi * 100) / (np.pi * 100) < 0.05
    assert buffer_cells(cells, 1) > cells
