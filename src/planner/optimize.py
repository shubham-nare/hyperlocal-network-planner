"""Capacitated maximal-covering site selection with a break-even floor per new site.

Existing stores stay open. Each hex's orders can be split across any open store that reaches it (up to store
capacity), which is what makes cannibalisation explicit: a new store only adds value where demand is out of reach
or existing stores are full, and ties are broken towards existing stores so shifted orders show up as such.
"""
from __future__ import annotations

import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pulp


@dataclass(frozen=True)
class Site:
    site_id: str
    reach: frozenset[str]
    existing: bool = False


@dataclass
class Solution:
    status: str
    opened: list[str]
    served_total: float
    store_orders: dict[str, float] = field(default_factory=dict)
    hex_served: dict[str, float] = field(default_factory=dict)
    new_site_hex_orders: dict[str, dict[str, float]] = field(default_factory=dict)


def useful_candidates(sites: Sequence[Site], demand: Mapping[str, float], baseline: Solution, capacity: float,
                      tol: float = 1e-6) -> set[str]:
    """New sites that can add orders over the existing-only baseline.

    A site whose reach only holds fully served demand from stores with spare capacity can merely shift orders, so it
    is dropped. Heuristic when several new sites interact through chains of full stores, but it keeps every site that
    touches unserved demand or a full store.
    """
    full_hexes = {h for s in sites if s.existing and baseline.store_orders.get(s.site_id, 0) >= capacity - tol for h in s.reach}
    open_hexes = {h for h, d in demand.items() if d - baseline.hex_served.get(h, 0) > tol}
    return {s.site_id for s in sites if not s.existing and s.reach & (open_hexes | full_hexes)}


def solve_network(
    demand: Mapping[str, float],
    sites: Sequence[Site],
    capacity: float,
    breakeven: float,
    max_new: int,
    candidates: set[str] | None = None,
    force_open: set[str] | None = None,
    existing_preference: float = 1e-3,
    time_limit_s: int = 300,
    mip_gap: float = 0.005,
) -> Solution:
    """Maximise orders served by existing + at most `max_new` new sites.

    `candidates` restricts which new sites may open (default: all non-existing sites); `force_open` pins some open.
    """
    force_open = force_open or set()
    new_sites = [s for s in sites if not s.existing and (candidates is None or s.site_id in candidates)]
    if not force_open <= {s.site_id for s in new_sites}:
        raise ValueError("force_open must be a subset of the candidate sites")
    active = [s for s in sites if s.existing] + new_sites

    prob = pulp.LpProblem("network", pulp.LpMaximize)
    y = {s.site_id: prob.add_variable(f"y_{i}", cat="Binary") for i, s in enumerate(new_sites)}
    x: dict[tuple[str, str], pulp.LpVariable] = {}
    by_hex: dict[str, list[pulp.LpVariable]] = {}
    by_site: dict[str, list[pulp.LpVariable]] = {s.site_id: [] for s in active}
    n = 0
    for s in active:
        for h in s.reach:
            if demand.get(h, 0) > 0:
                var = prob.add_variable(f"x_{n}", lowBound=0)
                n += 1
                x[(h, s.site_id)] = var
                by_hex.setdefault(h, []).append(var)
                by_site[s.site_id].append(var)

    prob += (pulp.lpSum(x.values())
             + existing_preference * pulp.lpSum(v for s in active if s.existing for v in by_site[s.site_id]))
    for h, vars_ in by_hex.items():
        prob += pulp.lpSum(vars_) <= demand[h]
    for s in active:
        load = pulp.lpSum(by_site[s.site_id])
        if s.existing:
            prob += load <= capacity
        else:
            prob += load <= capacity * y[s.site_id]
            prob += load >= breakeven * y[s.site_id]
    if y:
        prob += pulp.lpSum(y.values()) <= max_new
    for sid in force_open:
        prob += y[sid] == 1

    with warnings.catch_warnings():
        # PuLP 3.3 flags its bundled CBC as deprecated in favour of a separately installed one; bundled is what we ship.
        warnings.filterwarnings("ignore", message="PULP_CBC_CMD is deprecated", category=DeprecationWarning)
        solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=time_limit_s, gapRel=mip_gap)
    prob.solve(solver)
    if prob.sol_status not in (pulp.LpSolutionOptimal, pulp.LpSolutionIntegerFeasible):
        return Solution(status=pulp.LpStatus[prob.status], opened=[], served_total=0.0)
    opened = sorted(sid for sid, var in y.items() if (var.value() or 0) > 0.5)
    store_orders = {sid: sum(v.value() or 0 for v in vars_) for sid, vars_ in by_site.items()
                    if sid not in y or sid in opened}
    hex_served = {h: sum(v.value() or 0 for v in vars_) for h, vars_ in by_hex.items()}
    new_site_hex_orders: dict[str, dict[str, float]] = {sid: {} for sid in opened}
    for (h, sid), var in x.items():
        if sid in new_site_hex_orders and (var.value() or 0) > 1e-9:
            new_site_hex_orders[sid][h] = var.value()
    status = "Optimal" if prob.sol_status == pulp.LpSolutionOptimal else "Feasible (time limit)"
    return Solution(status=status, opened=opened, served_total=sum(hex_served.values()), store_orders=store_orders,
                    hex_served=hex_served, new_site_hex_orders=new_site_hex_orders)
