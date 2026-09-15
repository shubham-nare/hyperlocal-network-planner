import pytest

from planner.optimize import Site, solve_network, useful_candidates


def sites(*specs):
    return [Site(sid, frozenset(reach), existing) for sid, reach, existing in specs]


def test_opens_site_for_unserved_demand():
    s = sites(("E", {"A"}, True), ("C1", {"B"}, False))
    sol = solve_network({"A": 50, "B": 80}, s, capacity=100, breakeven=30, max_new=5)
    assert sol.opened == ["C1"]
    assert sol.served_total == pytest.approx(130)
    assert sol.store_orders == pytest.approx({"E": 50, "C1": 80})


def test_skips_site_below_breakeven():
    s = sites(("E", {"A"}, True), ("C1", {"B"}, False))
    sol = solve_network({"A": 50, "B": 20}, s, capacity=100, breakeven=30, max_new=5)
    assert sol.opened == [] and sol.served_total == pytest.approx(50)
    assert "C1" not in sol.store_orders


def test_capacity_binds_and_existing_store_is_filled_first():
    s = sites(("E", {"A"}, True), ("C1", {"A"}, False))
    sol = solve_network({"A": 100}, s, capacity=60, breakeven=10, max_new=5)
    assert sol.opened == ["C1"]
    assert sol.served_total == pytest.approx(100)
    assert sol.store_orders == pytest.approx({"E": 60, "C1": 40})


def test_no_new_site_when_existing_store_has_spare_capacity():
    s = sites(("E", {"A"}, True), ("C1", {"A"}, False))
    sol = solve_network({"A": 50}, s, capacity=100, breakeven=10, max_new=5)
    assert sol.opened == [] and sol.store_orders == pytest.approx({"E": 50})


def test_max_new_keeps_the_largest_gain():
    s = sites(("C1", {"B"}, False), ("C2", {"C"}, False))
    sol = solve_network({"B": 80, "C": 50}, s, capacity=100, breakeven=10, max_new=1)
    assert sol.opened == ["C1"] and sol.served_total == pytest.approx(80)


def test_demand_shared_by_overlapping_sites_is_served_once():
    s = sites(("C1", {"A", "B"}, False), ("C2", {"B", "C"}, False))
    sol = solve_network({"A": 40, "B": 40, "C": 40}, s, capacity=1000, breakeven=10, max_new=2)
    assert sol.served_total == pytest.approx(120)


def test_candidates_and_force_open():
    s = sites(("C1", {"B"}, False), ("C2", {"C"}, False))
    sol = solve_network({"B": 80, "C": 50}, s, capacity=100, breakeven=10, max_new=1, candidates={"C2"}, force_open={"C2"})
    assert sol.opened == ["C2"]
    with pytest.raises(ValueError):
        solve_network({"B": 80}, s, capacity=100, breakeven=10, max_new=1, candidates={"C2"}, force_open={"C1"})


def test_useful_candidates_keep_unserved_or_full_store_areas_only():
    s = sites(("E1", {"A"}, True), ("E2", {"B"}, True),
              ("C_full", {"A"}, False), ("C_spare", {"B"}, False), ("C_gap", {"C"}, False), ("C_none", {"D"}, False))
    demand = {"A": 150, "B": 50, "C": 30}
    base = solve_network(demand, [x for x in s if x.existing], capacity=100, breakeven=10, max_new=0)
    assert useful_candidates(s, demand, base, capacity=100) == {"C_full", "C_gap"}
