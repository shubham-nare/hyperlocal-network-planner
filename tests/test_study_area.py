import h3

from planner.study_area import candidate_cells, grow_dense_area, trim_ribbons

CORE = h3.latlng_to_cell(17.385, 78.4867, 8)
RING1 = set(h3.grid_ring(CORE, 1))
RING2 = set(h3.grid_ring(CORE, 2))


def test_dense_neighbours_are_added_and_sparse_ones_are_not():
    dense = next(iter(RING1))
    density = {c: 0.0 for c in RING1} | {dense: 5000.0}
    area = grow_dense_area([CORE], density, min_density=3000.0, max_rings=3)
    assert area == {CORE, dense}


def test_dense_cells_cut_off_by_a_sparse_ring_are_not_added():
    density = {c: 0.0 for c in RING1} | {c: 9000.0 for c in RING2}
    area = grow_dense_area([CORE], density, min_density=3000.0, max_rings=3)
    assert area == {CORE}


def test_growth_stops_at_max_rings():
    density = {c: 9000.0 for c in RING1 | RING2}
    area = grow_dense_area([CORE], density, min_density=3000.0, max_rings=1)
    assert area == {CORE} | RING1


def test_density_exactly_at_threshold_counts_as_dense():
    density = {c: 3000.0 for c in RING1}
    area = grow_dense_area([CORE], density, min_density=3000.0, max_rings=1)
    assert area == {CORE} | RING1


def test_candidate_cells_include_core_and_all_rings_up_to_max():
    assert candidate_cells([CORE], 2) == {CORE} | RING1 | RING2


BIG_CORE = set(h3.grid_disk(CORE, 2))
FAR = next(iter(h3.grid_ring(CORE, 10)))
PATH = h3.grid_path_cells(CORE, FAR)


def _on_path(lo, hi):
    return {c for c in PATH if lo <= h3.grid_distance(CORE, c) <= hi}


def test_trim_removes_one_hex_wide_ribbon():
    ribbon = _on_path(3, 8)
    assert trim_ribbons(BIG_CORE | ribbon, BIG_CORE) == BIG_CORE


def test_trim_keeps_solid_lobe_touching_core():
    lobe_center = next(iter(_on_path(3, 3)))
    lobe = set(h3.grid_disk(lobe_center, 1)) - BIG_CORE
    assert trim_ribbons(BIG_CORE | lobe, BIG_CORE) == BIG_CORE | lobe


def test_trim_drops_blob_left_disconnected_after_ribbon_is_pruned():
    ribbon = _on_path(3, 7)
    blob = set(h3.grid_disk(next(iter(_on_path(9, 9))), 1))
    assert trim_ribbons(BIG_CORE | ribbon | blob, BIG_CORE) == BIG_CORE
