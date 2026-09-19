"""Run the counterfactual scenarios on real project data (Hyderabad) and report real numbers.

Reuses the same city-loading logic as optimize_network.py. Nothing here is invented --
every figure traces to config/economics.yaml, the real store snapshot, or a computation
already validated elsewhere in this project.
"""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import h3
import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from optimize_network import city_inputs, load_config  # noqa: E402

from planner.economics import calibrated_national_economics  # noqa: E402
from planner.huff import pairwise_distance_km  # noqa: E402
from planner.scenarios import capex_constrained_portfolio, competitor_entry_impact, rent_shock  # noqa: E402


def main() -> None:
    class Args:
        elasticity = None
        growth = None
        capacity = None
    c = load_config(Args())
    city = "hyderabad"
    econ = yaml.safe_load(open("config/economics.yaml", encoding="utf-8"))
    national = calibrated_national_economics(econ)
    other_fixed = national["other_fixed_cost_per_day"]
    variable_cost_per_order = national["variable_cost_per_order"]

    print("=== Scenario 1: rent shock ===")
    for shock in (0.25, -0.20):
        result = rent_shock(city=city, rent_per_sqft_month=econ["cities"][city]["rent_per_sqft_month_inr"],
                            size_sqft=econ["store"]["size_sqft"], other_fixed_cost_per_day=other_fixed,
                            gross_profit_per_order=national["gross_profit_per_order"], variable_cost_per_order=variable_cost_per_order,
                            shock_pct=shock)
        print(f"  rent {shock:+.0%}: Rs.{result.baseline_rent_per_sqft_month:.0f} -> Rs.{result.shocked_rent_per_sqft_month:.0f}/sqft/month | "
              f"break-even {result.baseline_breakeven_orders_per_day:.0f} -> {result.shocked_breakeven_orders_per_day:.0f} orders/day "
              f"({result.breakeven_increase_pct:+.1%})")

    print("\n=== Scenario 2: competitor entry near a real recommended site ===")
    cov, demand, sites, budget_m = city_inputs(city, c)
    import pandas as pd
    top_site = pd.read_csv(f"reports/network_{city}_base.csv").iloc[0]
    our_lat, our_lng = top_site["lat"], top_site["lng"]
    print(f"  our site: {top_site['locality']} ({top_site['pincode']}) at {our_lat:.5f},{our_lng:.5f}, "
        f"currently {top_site['site_orders_per_day']:.0f} orders/day")
    demand_arr = cov["h3"].map(demand).fillna(0).to_numpy()
    hex_lat_lng = cov["h3"].map(h3.cell_to_latlng)
    hex_lat, hex_lng = np.array([ll[0] for ll in hex_lat_lng]), np.array([ll[1] for ll in hex_lat_lng])
    own_stores = gpd.read_file(f"data/processed/{city}_stores.gpkg")
    own_stores = own_stores[own_stores["brand"] == c["brand"]]
    network_lat = np.append(own_stores["lat"].to_numpy(), our_lat)
    network_lng = np.append(own_stores["lng"].to_numpy(), our_lng)
    network_labels = [f"store:{sid}" for sid in own_stores["store_id"]] + ["our_site"]
    reach_km = budget_m / 1000  # the same calibrated radius the optimizer and Huff validation both use
    for offset_m, label in ((300, "300m away"), (800, "800m away"), (2000, "2km away")):
        offset_deg = offset_m / 111_000
        result = competitor_entry_impact(demand_arr, hex_lat, hex_lng, network_lat, network_lng, network_labels, "our_site",
                                         our_lat + offset_deg, our_lng, max_distance_km=reach_km)
        print(f"  competitor {label} (actual distance {result.competitor_distance_km:.2f} km): our demand "
              f"{result.our_demand_before:.0f} -> {result.our_demand_after:.0f} orders/day "
              f"({result.demand_lost_share:+.1%} lost)")

    print("\n=== Scenario 3: capex-constrained portfolio ===")
    capex_per_store_cr = econ["steady_state"]["capex_per_store_inr"] / 1e7
    breakeven = c["breakeven"][city]
    for budget_cr in (5, 15, 25, 50):
        result = capex_constrained_portfolio(demand, sites, c["capacity"], breakeven, budget_cr, capex_per_store_cr, city=city, time_limit_s=60)
        print(f"  budget Rs.{budget_cr} Cr -> affords {result.affordable_sites} sites | solver opened {result.sites_opened} "
            f"({result.solver_status}) | +{result.incremental_orders_per_day:,.0f} orders/day")


if __name__ == "__main__":
    main()
