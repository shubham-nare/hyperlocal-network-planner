"""Counterfactual scenario engine: rent shocks, competitor entry, capex-constrained
portfolios, and "does the recommendation survive" checks.

This is deliberately not a new model. Every scenario here composes functions already
built and validated elsewhere in this project (economics.py's break-even math, huff.py's
demand allocation, optimize.py's site solver, interventions.py's comparator) with a
perturbed input. A scenario's output is only ever a recomputation through those existing,
real functions -- nothing here introduces a new number from nowhere.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from planner.economics import breakeven_orders_per_day, daily_rent_inr
from planner.huff import allocate_demand, choice_probability_matrix, pairwise_distance_km
from planner.interventions import InterventionAssumptions, MicroMarketState, compare_interventions
from planner.optimize import Site, solve_network


@dataclass(frozen=True)
class RentShockResult:
    city: str
    shock_pct: float
    baseline_rent_per_sqft_month: float
    shocked_rent_per_sqft_month: float
    baseline_breakeven_orders_per_day: float
    shocked_breakeven_orders_per_day: float
    breakeven_increase_pct: float


def rent_shock(
    *, city: str, rent_per_sqft_month: float, size_sqft: float, other_fixed_cost_per_day: float,
    gross_profit_per_order: float, variable_cost_per_order: float, shock_pct: float,
) -> RentShockResult:
    """Re-derive break-even orders/day under a rent shock, via the same economics.py formulas
    the base model already uses -- a shock is just a different rent input, not a new model.
    """
    if shock_pct <= -1:
        raise ValueError("shock_pct must be greater than -1 (rent cannot go negative)")
    baseline_fixed = daily_rent_inr(size_sqft, rent_per_sqft_month) + other_fixed_cost_per_day
    baseline_be = breakeven_orders_per_day(gross_profit_per_order, variable_cost_per_order, baseline_fixed)
    shocked_rent = rent_per_sqft_month * (1 + shock_pct)
    shocked_fixed = daily_rent_inr(size_sqft, shocked_rent) + other_fixed_cost_per_day
    shocked_be = breakeven_orders_per_day(gross_profit_per_order, variable_cost_per_order, shocked_fixed)
    increase_pct = (shocked_be - baseline_be) / baseline_be if np.isfinite(baseline_be) and baseline_be else float("inf")
    return RentShockResult(city, shock_pct, rent_per_sqft_month, shocked_rent, baseline_be, shocked_be, increase_pct)


@dataclass(frozen=True)
class CompetitorEntryResult:
    our_site_label: str
    competitor_distance_km: float
    our_demand_before: float
    our_demand_after: float
    demand_lost: float
    demand_lost_share: float


def competitor_entry_impact(
    demand_per_hex: np.ndarray, hex_lat: np.ndarray, hex_lng: np.ndarray,
    network_lat: np.ndarray, network_lng: np.ndarray, network_labels: list[str], our_site_label: str,
    competitor_lat: float, competitor_lng: float, **huff_kwargs,
) -> CompetitorEntryResult:
    """How much demand ``our_site_label`` loses to a new competitor opening nearby.

    Reuses huff.py's allocation directly, run twice (before/after adding the competitor
    to the choice set) -- the same mechanism evaluate_candidate_site already uses for our
    own new sites, just pointed at a competitor's location instead.
    """
    if our_site_label not in network_labels:
        raise ValueError(f"{our_site_label!r} is not in network_labels")
    idx = network_labels.index(our_site_label)
    before = allocate_demand(demand_per_hex, choice_probability_matrix(hex_lat, hex_lng, network_lat, network_lng, **huff_kwargs))
    all_lat, all_lng = np.append(network_lat, competitor_lat), np.append(network_lng, competitor_lng)
    after = allocate_demand(demand_per_hex, choice_probability_matrix(hex_lat, hex_lng, all_lat, all_lng, **huff_kwargs))
    lost = float(before[idx] - after[idx])
    distance = float(pairwise_distance_km(np.array([network_lat[idx]]), np.array([network_lng[idx]]),
                                          np.array([competitor_lat]), np.array([competitor_lng]))[0, 0])
    return CompetitorEntryResult(our_site_label, distance, float(before[idx]), float(after[idx]),
                                 lost, lost / before[idx] if before[idx] > 0 else 0.0)


def recommendation_survives_competitor_entry(
    state: MicroMarketState, incremental_orders_after_entry: float,
    assumptions: InterventionAssumptions = InterventionAssumptions(),
) -> tuple[str, str]:
    """Re-run the real intervention comparator with the post-entry incremental-orders figure
    substituted in, and report whether the top recommendation changes. Not a new scoring
    rule -- the same compare_interventions used everywhere else in this project.
    """
    baseline_top = compare_interventions(state, assumptions)[0].intervention
    shocked_state = MicroMarketState(**{**state.__dict__, "new_store_incremental_orders_per_day": incremental_orders_after_entry})
    shocked_top = compare_interventions(shocked_state, assumptions)[0].intervention
    return baseline_top, shocked_top


@dataclass(frozen=True)
class CapexPortfolioResult:
    city: str
    capex_budget_cr: float
    capex_per_store_cr: float
    affordable_sites: int
    sites_opened: int
    incremental_orders_per_day: float
    solver_status: str


def capex_constrained_portfolio(
    demand: dict[str, float], sites: list[Site], capacity: float, breakeven: float,
    capex_budget_cr: float, capex_per_store_cr: float, city: str = "", **solve_kwargs,
) -> CapexPortfolioResult:
    """Translate a rupee capex budget into a site count, then run the real optimizer.

    This is the "portfolio decision" scenario: it does not add a new optimization model,
    it computes how many sites a budget affords and calls solve_network exactly as
    scripts/optimize_network.py already does.
    """
    if capex_per_store_cr <= 0:
        raise ValueError("capex_per_store_cr must be positive")
    if capex_budget_cr < 0:
        raise ValueError("capex_budget_cr must be non-negative")
    affordable = int(capex_budget_cr // capex_per_store_cr)
    baseline = [s for s in sites if s.existing]
    base_served = solve_network(demand, baseline, capacity, breakeven, max_new=0).served_total
    solution = solve_network(demand, sites, capacity, breakeven, max_new=affordable, **solve_kwargs)
    return CapexPortfolioResult(city, capex_budget_cr, capex_per_store_cr, affordable, len(solution.opened),
                                solution.served_total - base_served, solution.status)
