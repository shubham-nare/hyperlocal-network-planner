import json

import pytest
from shapely.geometry import Point

from planner.stores import load_stores, load_zepto_zones

ZONE = [[12.90, 77.60], [12.90, 77.62], [12.92, 77.62], [12.92, 77.60], [12.90, 77.60]]


def _write(tmp_path, blinkit=None, swiggy=None, zepto=None):
    (tmp_path / "blinkit.json").write_text(json.dumps(blinkit if blinkit is not None else [
        {"id": "1", "accuracy": "43", "coordinates": [12.91, 77.61]}]), encoding="utf-8")
    (tmp_path / "swiggy.json").write_text(json.dumps(swiggy if swiggy is not None else [
        {"id": "2", "locality": "Koramangala", "coordinates": [12.93, 77.62]}]), encoding="utf-8")
    (tmp_path / "zepto.json").write_text(json.dumps(zepto if zepto is not None else [
        {"id": "z1", "name": "BLR-Test", "lat": "12.91", "lng": "77.61", "city": "Bengaluru",
         "state": "Karnataka", "zone": ZONE}]), encoding="utf-8")
    return tmp_path


def test_load_stores_standardises_brands_and_puts_lng_on_x(tmp_path):
    stores = load_stores(_write(tmp_path)).set_index("brand")
    assert set(stores.index) == {"Blinkit", "Swiggy Instamart", "Zepto"}
    blinkit = stores.loc["Blinkit"]
    assert blinkit.geometry.x == pytest.approx(77.61) and blinkit.geometry.y == pytest.approx(12.91)
    assert blinkit["accuracy_m"] == 43.0
    assert stores.loc["Swiggy Instamart", "label"] == "Koramangala"
    assert stores.loc["Zepto", "lat"] == pytest.approx(12.91)


def test_lng_first_pair_fails_loudly(tmp_path):
    raw = _write(tmp_path, blinkit=[{"id": "1", "accuracy": "5", "coordinates": [77.61, 12.91]}])
    with pytest.raises(ValueError, match="blinkit.json"):
        load_stores(raw)


def test_zepto_zone_polygon_uses_lng_lat_and_contains_its_store(tmp_path):
    zones = load_zepto_zones(_write(tmp_path))
    poly = zones.geometry.iloc[0]
    minx, miny, maxx, maxy = poly.bounds
    assert (minx, miny, maxx, maxy) == pytest.approx((77.60, 12.90, 77.62, 12.92))
    assert poly.contains(Point(77.61, 12.91))
    assert zones.loc[0, "store_id"] == "z1" and zones.loc[0, "city"] == "Bengaluru"
