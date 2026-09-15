import h3
import numpy as np
import pytest

from planner.coverage import brand_slug, coverage_table, nearest_store_km
from planner.reach import haversine_m

CENTER = h3.latlng_to_cell(17.385, 78.4867, 8)
RING = sorted(h3.grid_ring(CENTER, 1))
AREA = {CENTER, *RING}
OUTSIDE = h3.latlng_to_cell(17.385, 78.70, 8)
BRANDS = ["Blinkit", "Zepto", "Swiggy Instamart"]


def test_brand_slug_is_column_safe():
    assert brand_slug("Swiggy Instamart") == "swiggy_instamart"
    assert brand_slug("Blinkit") == "blinkit"


def test_counts_stores_per_brand_and_ignores_cells_outside_area():
    store_cells = {
        ("Blinkit", "b1"): {CENTER, RING[0], OUTSIDE},
        ("Blinkit", "b2"): {CENTER},
        ("Zepto", "z1"): {CENTER, RING[1]},
    }
    table = coverage_table(store_cells, AREA, BRANDS).set_index("h3")
    assert OUTSIDE not in table.index
    assert table.loc[CENTER, "stores_blinkit"] == 2
    assert table.loc[CENTER, "stores_zepto"] == 1
    assert table.loc[CENTER, "stores_total"] == 3
    assert table.loc[CENTER, "brands_covering"] == 2
    assert table.loc[RING[0], "brands_covering"] == 1


def test_uncovered_hexes_are_zero_filled_and_flagged():
    table = coverage_table({("Zepto", "z1"): {CENTER}}, AREA, BRANDS).set_index("h3")
    assert len(table) == len(AREA)
    uncovered = table.drop(index=CENTER)
    assert (uncovered["stores_total"] == 0).all() and not uncovered["covered_any"].any()
    assert (uncovered[["stores_blinkit", "stores_zepto", "stores_swiggy_instamart"]] == 0).all().all()
    assert table.loc[CENTER, "covered_any"]


def test_unknown_brands_are_skipped():
    table = coverage_table({("Amazon Now", "a1"): {CENTER}}, AREA, BRANDS)
    assert not table["covered_any"].any()


def test_nearest_store_km_matches_haversine_and_takes_minimum():
    hex_lat, hex_lng = np.array([17.385]), np.array([78.4867])
    store_lat, store_lng = np.array([17.40, 17.50]), np.array([78.50, 78.60])
    expected = min(haversine_m(17.385, 78.4867, la, ln) for la, ln in zip(store_lat, store_lng)) / 1000
    assert nearest_store_km(hex_lat, hex_lng, store_lat, store_lng)[0] == pytest.approx(expected, rel=1e-9)


def test_nearest_store_km_is_per_hex():
    hex_lat, hex_lng = np.array([17.40, 17.50]), np.array([78.50, 78.60])
    out = nearest_store_km(hex_lat, hex_lng, np.array([17.40, 17.50]), np.array([78.50, 78.60]))
    assert out == pytest.approx([0.0, 0.0], abs=1e-9)


def test_nearest_store_km_without_stores_is_infinite():
    out = nearest_store_km(np.array([17.4]), np.array([78.5]), np.array([]), np.array([]))
    assert np.isinf(out).all()
