import numpy as np
import pytest

from planner.interventions import MicroMarketState
from planner.optimize import Site
from planner.scenarios import (CompetitorEntryResult, capex_constrained_portfolio, competitor_entry_impact,
                               recommendation_survives_competitor_entry, rent_shock)


def test_rent_shock_increases_breakeven_and_reports_the_real_percentages():
    result = rent_shock(city="pune", rent_per_sqft_month=90, size_sqft=4000, other_fixed_cost_per_day=8000,
                        gross_profit_per_order=142.3, variable_cost_per_order=102.2, shock_pct=0.25)
    assert result.shocked_rent_per_sqft_month == pytest.approx(112.5)
    assert result.shocked_breakeven_orders_per_day > result.baseline_breakeven_orders_per_day
    assert result.breakeven_increase_pct > 0


def test_rent_shock_rejects_rent_going_negative():
    with pytest.raises(ValueError, match="shock_pct"):
        rent_shock(city="pune", rent_per_sqft_month=90, size_sqft=4000, other_fixed_cost_per_day=8000,
                  gross_profit_per_order=142.3, variable_cost_per_order=102.2, shock_pct=-1.5)


def test_a_rent_cut_lowers_breakeven():
    result = rent_shock(city="pune", rent_per_sqft_month=90, size_sqft=4000, other_fixed_cost_per_day=8000,
                        gross_profit_per_order=142.3, variable_cost_per_order=102.2, shock_pct=-0.20)
    assert result.shocked_breakeven_orders_per_day < result.baseline_breakeven_orders_per_day
    assert result.breakeven_increase_pct < 0


def test_competitor_entry_costs_our_site_demand_and_reports_real_distance():
    demand = np.array([100.0, 100.0])
    hex_lat, hex_lng = np.array([17.400, 17.410]), np.array([78.500, 78.500])
    network_lat, network_lng = np.array([17.401]), np.array([78.500])
    result = competitor_entry_impact(demand, hex_lat, hex_lng, network_lat, network_lng, ["our_store"], "our_store",
                                     17.402, 78.500, max_distance_km=5.0)
    assert isinstance(result, CompetitorEntryResult)
    assert result.demand_lost > 0
    assert result.our_demand_after < result.our_demand_before
    assert result.competitor_distance_km == pytest.approx(0.111, abs=0.01)


def test_a_distant_competitor_takes_no_demand():
    demand = np.array([100.0])
    result = competitor_entry_impact(demand, np.array([17.400]), np.array([78.500]), np.array([17.401]), np.array([78.500]),
                                     ["our_store"], "our_store", 20.0, 80.0, max_distance_km=2.0)
    assert result.demand_lost == pytest.approx(0.0, abs=1e-6)


def test_competitor_entry_rejects_an_unknown_site_label():
    with pytest.raises(ValueError, match="our_store"):
        competitor_entry_impact(np.array([1.0]), np.array([17.4]), np.array([78.5]), np.array([17.4]), np.array([78.5]),
                                ["someone_else"], "our_store", 17.41, 78.5)


def _state(**changes):
    base = dict(city="pune", micro_market="kothrud", latent_orders_per_day=4_000, unserved_orders_per_day=1_500,
               served_share=0.60, nearby_capacity_utilisation=0.94, nearby_capacity_orders_per_day=6_000,
               new_store_incremental_orders_per_day=1_100, new_store_break_even_orders_per_day=500,
               eta_breach_rate=0.06, assortment_fit_score=0.70)
    base.update(changes)
    return MicroMarketState(**base)


def test_recommendation_can_flip_after_a_severe_enough_competitor_entry():
    state = _state()
    baseline_top, shocked_top = recommendation_survives_competitor_entry(state, incremental_orders_after_entry=50.0)
    assert baseline_top == "open_dark_store"
    assert shocked_top != "open_dark_store"


def test_recommendation_is_unchanged_by_a_negligible_competitor_entry():
    state = _state()
    baseline_top, shocked_top = recommendation_survives_competitor_entry(state, incremental_orders_after_entry=1_099.0)
    assert baseline_top == shocked_top == "open_dark_store"


def test_capex_constrained_portfolio_translates_budget_into_a_site_count():
    demand = {"a": 3000.0, "b": 3000.0}
    sites = [Site("hex:a", frozenset({"a"})), Site("hex:b", frozenset({"b"}))]
    result = capex_constrained_portfolio(demand, sites, capacity=2000, breakeven=500,
                                         capex_budget_cr=3.0, capex_per_store_cr=2.5, city="pune")
    assert result.affordable_sites == 1
    assert result.sites_opened <= 1
    assert result.incremental_orders_per_day >= 0


def test_capex_constrained_portfolio_rejects_bad_inputs():
    with pytest.raises(ValueError, match="capex_per_store_cr"):
        capex_constrained_portfolio({}, [], 100, 10, capex_budget_cr=5, capex_per_store_cr=0)
    with pytest.raises(ValueError, match="capex_budget_cr"):
        capex_constrained_portfolio({}, [], 100, 10, capex_budget_cr=-1, capex_per_store_cr=2.5)


def test_zero_budget_affords_no_sites():
    demand = {"a": 3000.0}
    sites = [Site("hex:a", frozenset({"a"}))]
    result = capex_constrained_portfolio(demand, sites, capacity=2000, breakeven=500, capex_budget_cr=0, capex_per_store_cr=2.5)
    assert result.affordable_sites == 0
    assert result.sites_opened == 0
    assert result.incremental_orders_per_day == 0
