import geopandas as gpd
import h3
from shapely.geometry import box

from planner.grid import cells_to_gdf
from planner.pincodes import assign_hexes_to_pincodes

CENTER = h3.latlng_to_cell(17.385, 78.4867, 8)
DISK = sorted(h3.grid_disk(CENTER, 1))
FAR = h3.latlng_to_cell(17.385, 78.70, 8)  # ~22 km east, outside both polygons


def _split_lng():
    lngs = sorted({round(h3.cell_to_latlng(c)[1], 6) for c in DISK})
    mid = len(lngs) // 2
    return (lngs[mid - 1] + lngs[mid]) / 2  # halfway between centroid columns, far from any centroid


def _boundaries(split):
    return gpd.GeoDataFrame(
        {"pincode": [500001, 500002], "officename": ["West S.O", "East S.O"], "district": ["Hyderabad", "Hyderabad"]},
        geometry=[box(78.44, 17.34, split, 17.43), box(split, 17.34, 78.53, 17.43)],
        crs="EPSG:4326",
    )


def test_hexes_take_the_polygon_containing_their_centroid():
    split = _split_lng()
    out = assign_hexes_to_pincodes(cells_to_gdf(DISK), _boundaries(split)).set_index("h3")
    for cell in DISK:
        expected = 500001 if h3.cell_to_latlng(cell)[1] < split else 500002
        assert out.loc[cell, "pincode"] == expected
        assert not out.loc[cell, "pincode_by_nearest"]


def test_hex_outside_all_polygons_takes_nearest_and_is_flagged():
    out = assign_hexes_to_pincodes(cells_to_gdf(DISK + [FAR]), _boundaries(_split_lng())).set_index("h3")
    assert out.loc[FAR, "pincode"] == 500002
    assert out.loc[FAR, "pincode_by_nearest"]
    assert out.loc[FAR, "pincode_office"] == "East S.O"


def test_every_hex_gets_a_pincode_and_row_order_is_preserved():
    hexes = cells_to_gdf(DISK + [FAR])
    out = assign_hexes_to_pincodes(hexes, _boundaries(_split_lng()))
    assert out["pincode"].notna().all()
    assert out["h3"].tolist() == hexes["h3"].tolist()
