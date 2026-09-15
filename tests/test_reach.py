import h3
import networkx as nx
import pytest

from planner.reach import (
    NodeLocator,
    fill_holes,
    haversine_m,
    isochrone_cells,
    nearest_node,
    radius_cells,
    reachable_nodes,
    ride_budget_m,
    road_cells,
    road_filled_cells,
)

LAT = 17.385
STEP_DEG = 0.001  # ~106 m of longitude at this latitude
STEP_M = 106.0


def _line_graph():
    """Nodes 0-4 on an east-west two-way street; node 5 joins node 4 only via a one-way edge 5 -> 4."""
    g = nx.MultiDiGraph()
    for i in range(5):
        g.add_node(i, x=78.40 + i * STEP_DEG, y=LAT)
    for i in range(4):
        g.add_edge(i, i + 1, length=STEP_M)
        g.add_edge(i + 1, i, length=STEP_M)
    g.add_node(5, x=78.40 + 4 * STEP_DEG, y=LAT + STEP_DEG)
    g.add_edge(5, 4, length=STEP_M)
    return g


def test_ride_budget_subtracts_picking_time():
    assert ride_budget_m(10, 2.5, 18) == pytest.approx(2250.0)
    assert ride_budget_m(2, 2.5, 18) == 0.0


def test_nearest_node_picks_closest():
    assert nearest_node(_line_graph(), LAT + 0.0001, 78.40 + 2.1 * STEP_DEG) == 2


def test_reachable_nodes_respect_distance_cutoff():
    reach = reachable_nodes(_line_graph(), 0, budget_m=250)
    assert set(reach) == {0, 1, 2}


def test_one_way_street_is_not_traversed_backwards():
    reach = reachable_nodes(_line_graph(), 0, budget_m=10_000)
    assert 4 in reach and 5 not in reach


def test_isochrone_cells_are_cells_of_reachable_nodes():
    g = _line_graph()
    # 10 min promise, 2.5 min picking, 2 km/h -> 250 m budget, i.e. nodes 0-2 only.
    cells = isochrone_cells(g, LAT, 78.40, promise_min=10, picking_min=2.5, speed_kmph=2, resolution=10)
    expected = {h3.latlng_to_cell(LAT, 78.40 + i * STEP_DEG, 10) for i in range(3)}
    assert cells == expected


def test_haversine_one_degree_of_latitude_is_about_111_km():
    assert haversine_m(17.0, 78.0, 18.0, 78.0) == pytest.approx(111_195, rel=0.001)


def test_radius_cells_keep_only_cells_within_radius_and_include_centre():
    lat, lng, radius = 17.385, 78.4867, 1_500
    cells = radius_cells(lat, lng, radius, 9)
    assert h3.latlng_to_cell(lat, lng, 9) in cells
    assert all(haversine_m(lat, lng, *h3.cell_to_latlng(c)) <= radius for c in cells)
    # ~pi * 1.5^2 km2 / ~0.105 km2 per res-9 hex ~= 67 cells
    assert 50 <= len(cells) <= 90


def test_radius_cells_miss_nothing_inside_radius():
    lat, lng, radius = 17.385, 78.4867, 1_500
    cells = radius_cells(lat, lng, radius, 9)
    nearby = h3.grid_disk(h3.latlng_to_cell(lat, lng, 9), 20)
    inside = {c for c in nearby if haversine_m(lat, lng, *h3.cell_to_latlng(c)) <= radius}
    assert inside == cells


def test_fill_holes_adds_surrounded_cell_but_not_edge_cell():
    center = h3.latlng_to_cell(17.385, 78.4867, 9)
    ring = set(h3.grid_ring(center, 1))
    assert center in fill_holes(ring)
    lone = next(iter(ring))
    assert fill_holes({lone, center}) == {lone, center}


def test_node_locator_matches_nearest_node():
    g = _line_graph()
    locator = NodeLocator(g)
    for lat, lng in ((LAT, 78.40), (LAT + 0.0003, 78.40 + 3.2 * STEP_DEG), (LAT + STEP_DEG, 78.40 + 4 * STEP_DEG)):
        assert locator.nearest(lat, lng) == nearest_node(g, lat, lng)


def test_road_filled_cells_contain_road_cells():
    g = _line_graph()
    locator = NodeLocator(g)
    road = road_cells(g, locator, LAT, 78.40, 250, 10)
    assert road <= road_filled_cells(g, locator, LAT, 78.40, 250, 10)
