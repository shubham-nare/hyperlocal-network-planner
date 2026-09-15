from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping

import h3


def candidate_cells(core_cells: Iterable[str], max_rings: int) -> set[str]:
    candidates: set[str] = set()
    for cell in core_cells:
        candidates.update(h3.grid_disk(cell, max_rings))
    return candidates


def grow_dense_area(
    core_cells: Iterable[str],
    density_by_cell: Mapping[str, float],
    min_density: float,
    max_rings: int,
) -> set[str]:
    """Core cells plus neighbouring cells reachable from the core through cells at or above min_density.

    Growth is breadth-first, so only cells contiguous with the core are added; max_rings caps how many
    hex steps outside the core the area can extend.
    """
    selected = set(core_cells)
    frontier = deque((cell, 0) for cell in selected)
    while frontier:
        cell, ring = frontier.popleft()
        if ring >= max_rings:
            continue
        for neighbour in h3.grid_ring(cell, 1):
            if neighbour in selected:
                continue
            if density_by_cell.get(neighbour, 0.0) >= min_density:
                selected.add(neighbour)
                frontier.append((neighbour, ring + 1))
    return selected


def trim_ribbons(area_cells: Iterable[str], core_cells: Iterable[str], min_neighbours: int = 3) -> set[str]:
    """Drop non-core cells with fewer than min_neighbours in-area neighbours until stable, then keep only
    cells still connected to the core, so thin highway ribbons and anything hanging off them are removed."""
    core = set(core_cells)
    area = set(area_cells) | core
    while True:
        drop = {c for c in area - core if sum(n in area for n in h3.grid_ring(c, 1)) < min_neighbours}
        if not drop:
            break
        area -= drop
    return _connected_to_core(area, core)


def _connected_to_core(area: set[str], core: set[str]) -> set[str]:
    reached = set(core)
    frontier = deque(reached)
    while frontier:
        cell = frontier.popleft()
        for neighbour in h3.grid_ring(cell, 1):
            if neighbour in area and neighbour not in reached:
                reached.add(neighbour)
                frontier.append(neighbour)
    return reached
