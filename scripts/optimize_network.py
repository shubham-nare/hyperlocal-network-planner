"""Week 4: where should the brand open its next N dark stores in a city?

Latent orders/day per hex are calibrated to the brand's disclosed throughput on the hexes it already covers; existing
stores stay open; new sites must clear the city's Week 3 break-even and share capacity-limited demand with existing
stores, so cannibalisation is measured, not ignored.
"""
from __future__ import annotations

import argparse
import time

import geopandas as gpd
import h3
import matplotlib
import pandas as pd
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from planner.coverage import brand_slug  # noqa: E402
from planner.economics import Quarter, per_order  # noqa: E402
from planner.optimize import Site, solve_network, useful_candidates  # noqa: E402
from planner.orders import adoption_index, calibrate_orders_per_weight, order_weights  # noqa: E402
from planner.reach import radius_cells, ride_budget_m  # noqa: E402
from planner.stores import load_stores  # noqa: E402


def load_config(args: argparse.Namespace) -> dict:
    cities = yaml.safe_load(open("config/cities.yaml", encoding="utf-8"))
    econ = yaml.safe_load(open("config/economics.yaml", encoding="utf-8"))
    net = yaml.safe_load(open("config/network.yaml", encoding="utf-8"))
    brand = net["brand"]
    q_name = net["orders"]["calibration_quarter"]
    q = Quarter(**econ["quarters"][q_name])
    cal = per_order(q)
    snapshot_national = int((load_stores("data/raw/darkstores")["brand"] == brand).sum())
    sens = pd.read_csv("reports/unit_economics_sensitivity.csv")
    demand_weights = yaml.safe_load(open("config/demand.yaml", encoding="utf-8"))["weights"]
    return {
        "adoption_weights": {k: w for k, w in demand_weights.items() if k != "density_per_km2"},
        "cities": cities, "net": net, "brand": brand, "slug": brand_slug(brand), "quarter": q_name,
        "orders_per_store_day": cal["orders_per_store_day"],
        "completeness": snapshot_national / q.stores_end, "snapshot_national": snapshot_national, "disclosed_stores": q.stores_end,
        "capacity": args.capacity or econ["steady_state"]["nov_per_store_day_inr"] / cal["naov"],
        "breakeven": sens.groupby("city")["breakeven_orders_per_day"].median().to_dict(),
        "elasticity": net["orders"]["adoption_elasticity"] if args.elasticity is None else args.elasticity,
        "growth": args.growth or net["orders"]["growth_multiplier"],
    }


def city_inputs(city: str, c: dict) -> tuple[gpd.GeoDataFrame, dict[str, float], list[Site], float]:
    res = c["cities"]["defaults"]["h3_resolution"]
    cov = gpd.read_file(f"data/processed/{city}_coverage_radius_r{res}.gpkg")
    pct_cols = [f"{k}_pct" for k in c["adoption_weights"]]
    pins = gpd.read_file(f"data/processed/{city}_hex_pincode_r{res}.gpkg")[["h3", "pincode", "pincode_office", "pincode_district", *pct_cols]]
    cov = cov.merge(pins, on="h3", how="left")
    stores = gpd.read_file(f"data/processed/{city}_stores.gpkg")
    own = stores[stores["brand"] == c["brand"]]

    # Population already carries density, so adoption uses only the non-density features of the demand index.
    cov["adoption_index"] = adoption_index(cov, c["adoption_weights"])
    weights = order_weights(cov["population"], cov["adoption_index"], c["elasticity"])
    served = cov[f"stores_{c['slug']}"] > 0
    rate = calibrate_orders_per_weight(weights, served, len(own), c["completeness"], c["orders_per_store_day"])
    cov["latent_orders"] = weights * rate * c["growth"]
    demand = dict(zip(cov["h3"], cov["latent_orders"]))

    d = c["cities"]["defaults"]
    budget = ride_budget_m(d["delivery_promise_min"], d["picking_time_min"], c["cities"]["cities"][city]["reach_speed_kmph"]["radius"])
    area = set(cov["h3"])
    sites = [Site(f"store:{s.store_id}", frozenset(radius_cells(s.lat, s.lng, budget, res) & area), existing=True)
             for s in own.itertuples()]
    for cell in cov["h3"]:
        lat, lng = h3.cell_to_latlng(cell)
        sites.append(Site(f"hex:{cell}", frozenset(radius_cells(lat, lng, budget, res) & area)))
    return cov, demand, sites, budget


def plot(city: str, c: dict, cov: gpd.GeoDataFrame, stores: gpd.GeoDataFrame, sites: pd.DataFrame, tag: str) -> str:
    fig, ax = plt.subplots(figsize=(8, 8))
    cov.plot(ax=ax, column="unserved_orders", cmap="Reds", linewidth=0, legend=True,
             legend_kwds={"label": "Unserved latent orders/day (current network)", "shrink": 0.6})
    own = stores[stores["brand"] == c["brand"]]
    own.plot(ax=ax, color="#555555", markersize=5, label=f"{c['brand']} stores in snapshot ({len(own)})")
    ax.scatter(sites["lng"], sites["lat"], marker="*", s=160, color="#f2c100", edgecolor="black", linewidth=0.6, zorder=5,
               label=f"Proposed sites ({len(sites)})")
    for r in sites.itertuples():
        ax.annotate(str(r.rank), (r.lng, r.lat), xytext=(4, 4), textcoords="offset points", fontsize=8, weight="bold")
    ax.legend(loc="lower left", fontsize=8)
    ax.set_title(f"{city.title()}: next {len(sites)} {c['brand']} dark stores ({tag})")
    ax.set_axis_off()
    out = f"reports/network_{city}_{tag}.png"
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", help="one city from config/cities.yaml (default: all)")
    parser.add_argument("--elasticity", type=float)
    parser.add_argument("--growth", type=float)
    parser.add_argument("--capacity", type=float)
    parser.add_argument("--curve", action="store_true", help="also solve every max_new_sites value in config")
    parser.add_argument("--tag", default="base")
    args = parser.parse_args()
    c = load_config(args)
    net = c["net"]
    print(f"{c['brand']} calibration ({c['quarter']}): {c['orders_per_store_day']:,.0f} orders/day/store | snapshot "
          f"completeness {c['snapshot_national']:,}/{c['disclosed_stores']:,} = {c['completeness']:.1%} | capacity "
          f"{c['capacity']:,.0f}/day | elasticity {c['elasticity']} | growth x{c['growth']}")

    cities = [args.city] if args.city else list(c["cities"]["cities"])
    for city in cities:
        t = time.time()
        cov, demand, sites, budget = city_inputs(city, c)
        be = c["breakeven"][city]
        total = sum(demand.values())
        existing = [s for s in sites if s.existing]
        base = solve_network(demand, existing, c["capacity"], be, max_new=0)
        loads = pd.Series(base.store_orders)
        print(f"\n== {city} | reach {budget:,.0f} m | break-even {be:,.0f}/day | {len(existing)} existing, "
              f"{len(sites) - len(existing)} candidate sites ==")
        cands = useful_candidates(sites, demand, base, c["capacity"])
        existing_reach = set().union(*(s.reach for s in existing))
        print(f"  latent demand {total:,.0f} orders/day | served now {base.served_total:,.0f} ({base.served_total / total:.1%}) | "
              f"store load median {loads.median():,.0f}, at capacity {(loads >= c['capacity'] - 1).sum()} stores | "
              f"useful candidates {len(cands)}")

        if args.curve:
            curve = [{"max_new_sites": 0, "status": base.status, "incremental_orders_per_day": 0, "served_share": base.served_total / total}]
            for n in net["max_new_sites"]:
                t_n = time.time()
                sol = solve_network(demand, sites, c["capacity"], be, max_new=n, candidates=cands)
                new_orders = sum(sol.store_orders[s] for s in sol.opened)
                inc = sol.served_total - base.served_total
                cannibalised = max(new_orders - inc, 0) / new_orders if new_orders else 0
                print(f"  N={n:>2}: {sol.status} | opened {len(sol.opened)} | +{inc:,.0f} orders/day "
                      f"({inc / total:+.1%} of demand) | new-store orders {new_orders:,.0f}, cannibalised "
                      f"{cannibalised:.0%} | {time.time() - t_n:.0f}s")
                curve.append({"max_new_sites": n, "status": sol.status, "incremental_orders_per_day": round(inc),
                              "served_share": round(sol.served_total / total, 4), "cannibalised_share": round(cannibalised, 3)})
            pd.DataFrame(curve).to_csv(f"reports/network_{city}_{args.tag}_curve.csv", index=False)

        n = net["memo_sites"]
        sol = solve_network(demand, sites, c["capacity"], be, max_new=n, candidates=cands)
        cov["served_base"] = cov["h3"].map(base.hex_served).fillna(0)
        cov["unserved_orders"] = cov["latent_orders"] - cov["served_base"]
        by_h3 = cov.set_index("h3")
        rows = []
        for sid in sol.opened:
            others = set(sol.opened) - {sid}
            loo = solve_network(demand, sites, c["capacity"], be, max_new=len(others), candidates=others, force_open=others)
            cell = sid.removeprefix("hex:")
            lat, lng = h3.cell_to_latlng(cell)
            reach = next(s.reach for s in sites if s.site_id == sid)
            r = by_h3.loc[cell]
            site_orders, inc = sol.store_orders[sid], sol.served_total - loo.served_total
            # New coverage = orders from hexes no existing store reaches; the rest relieves full stores or shifts orders.
            new_cov = sum(q for h, q in sol.new_site_hex_orders[sid].items() if h not in existing_reach)
            rows.append({
                "h3": cell, "lat": round(lat, 5), "lng": round(lng, 5), "pincode": r["pincode"], "locality": r["pincode_office"],
                "district": r["pincode_district"], "demand_index": round(r["demand_index"], 1),
                "adoption_index": round(r["adoption_index"], 1),
                "site_orders_per_day": round(site_orders), "incremental_orders_per_day": round(inc),
                "new_coverage_orders": round(new_cov), "capacity_relief_orders": round(site_orders - new_cov),
                "cannibalised_share": round(max(site_orders - inc, 0) / site_orders, 2) if site_orders else None,
                "breakeven_cover": round(site_orders / be, 2),
                "pop_in_reach_uncovered_by_brand": round(by_h3.loc[list(reach)].query(f"stores_{c['slug']} == 0")["population"].sum()),
                "competitor_stores_reaching_hex": int(r["stores_zepto"] + r["stores_swiggy_instamart"]),
            })
        table = pd.DataFrame(rows).sort_values(["incremental_orders_per_day", "new_coverage_orders"], ascending=False)
        table.insert(0, "rank", range(1, len(table) + 1))
        out_csv = f"reports/network_{city}_{args.tag}.csv"
        table.to_csv(out_csv, index=False)
        inc_total = sol.served_total - base.served_total
        print(f"  memo N={n}: {sol.status} | +{inc_total:,.0f} orders/day ({inc_total / total:+.1%}) | "
              f"served {sol.served_total / total:.1%}")
        print(table.drop(columns=["h3", "district"]).to_string(index=False))
        png = plot(city, c, cov, gpd.read_file(f"data/processed/{city}_stores.gpkg"), table, args.tag)
        print(f"  -> {out_csv} | {png} | {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
