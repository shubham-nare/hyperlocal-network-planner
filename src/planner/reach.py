from __future__ import annotations

import math

import h3
import networkx as nx
import numpy as np
import osmnx as ox
from shapely.geometry.base import BaseGeometry


def load_drive_graph(polygon: BaseGeometry) -> nx.MultiDiGraph:
    return ox.graph_from_polygon(polygon, network_type="drive", simplify=True)


def nearest_node(graph: nx.MultiDiGraph, lat: float, lng: float) -> int:
    # Equirectangular distance is accurate at city scale and avoids osmnx's scikit-learn dependency.
    nodes = list(graph.nodes)
    ys = np.array([graph.nodes[n]["y"] for n in nodes])
    xs = np.array([graph.nodes[n]["x"] for n in nodes])
    dx = (xs - lng) * math.cos(math.radians(lat))
    dy = ys - lat
    return nodes[int(np.argmin(dx * dx + dy * dy))]


def ride_budget_m(promise_min: float, picking_min: float, speed_kmph: float) -> float:
    return max(promise_min - picking_min, 0.0) * speed_kmph * 1000 / 60


def reachable_nodes(graph: nx.MultiDiGraph, source: int, budget_m: float) -> dict[int, float]:
    # Directed search from the store, so one-way streets are respected on the outbound trip.
    return nx.single_source_dijkstra_path_length(graph, source, cutoff=budget_m, weight="length")


class NodeLocator:
    """Nearest graph node with coordinate arrays built once, for many lookups on the same graph."""

    def __init__(self, graph: nx.MultiDiGraph):
        self.nodes = list(graph.nodes)
        self.ys = np.array([graph.nodes[n]["y"] for n in self.nodes])
        self.xs = np.array([graph.nodes[n]["x"] for n in self.nodes])

    def nearest(self, lat: float, lng: float) -> int:
        dx = (self.xs - lng) * math.cos(math.radians(lat))
        dy = self.ys - lat
        return self.nodes[int(np.argmin(dx * dx + dy * dy))]


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


def radius_cells(lat: float, lng: float, radius_m: float, resolution: int) -> set[str]:
    center = h3.latlng_to_cell(lat, lng, resolution)
    # Rings are ~1.73 edge lengths apart, so stepping by 1.5 edges over-covers; the distance filter trims it.
    k = math.ceil(radius_m / (h3.average_hexagon_edge_length(resolution, unit="m") * 1.5)) + 1
    return {c for c in h3.grid_disk(center, k) if haversine_m(lat, lng, *h3.cell_to_latlng(c)) <= radius_m}


def fill_holes(cells: set[str], min_neighbours: int = 4) -> set[str]:
    """Add cells surrounded by reachable cells; node-based coverage misses hexes that contain no drive node."""
    candidates = {n for c in cells for n in h3.grid_ring(c, 1) if n not in cells}
    return cells | {n for n in candidates if sum(m in cells for m in h3.grid_ring(n, 1)) >= min_neighbours}


def road_cells(graph: nx.MultiDiGraph, locator: NodeLocator, lat: float, lng: float, budget_m: float,
               resolution: int) -> set[str]:
    reach = reachable_nodes(graph, locator.nearest(lat, lng), budget_m)
    return {h3.latlng_to_cell(graph.nodes[n]["y"], graph.nodes[n]["x"], resolution) for n in reach}


def road_filled_cells(graph: nx.MultiDiGraph, locator: NodeLocator, lat: float, lng: float, budget_m: float,
                      resolution: int) -> set[str]:
    return fill_holes(road_cells(graph, locator, lat, lng, budget_m, resolution))


def isochrone_cells(
    graph: nx.MultiDiGraph,
    lat: float,
    lng: float,
    promise_min: float,
    picking_min: float,
    speed_kmph: float,
    resolution: int,
) -> set[str]:
    """H3 cells containing at least one road node reachable within the delivery promise (node-based approximation)."""
    source = nearest_node(graph, lat, lng)
    reach = reachable_nodes(graph, source, ride_budget_m(promise_min, picking_min, speed_kmph))
    return {h3.latlng_to_cell(graph.nodes[n]["y"], graph.nodes[n]["x"], resolution) for n in reach}
