"""Coverage-gap map v0: which study-area hexes existing dark stores reach, per brand, and where demand is unserved.

Store locations are a third-party Mar-2026 snapshot (github.com/jatin-dot-py/darkstores, unlicensed), so coverage
is a lower bound on today's. Reach = calibrated radius by default, gap-filled road network as a scenario
(both validated against Zepto delivery zones, see scripts/validate_reach_zepto.py).
"""
from __future__ import annotations

import argparse
import time

import geopandas as gpd
import matplotlib
import osmnx as ox
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from planner.coverage import brand_slug, coverage_table, nearest_store_km  # noqa: E402
from planner.reach import NodeLocator, radius_cells, ride_budget_m, road_filled_cells  # noqa: E402

BRANDS = ["Blinkit", "Zepto", "Swiggy Instamart"]
NEAR_MISS_KM = 0.5
BRAND_COLORS = {"Blinkit": "#f2c100", "Zepto": "#7b2cbf", "Swiggy Instamart": "#fc8019"}


def store_reach(stores: gpd.GeoDataFrame, method: str, budget_m: float, res: int, city: str) -> dict:
    if method == "radius":
        return {(s.brand, s.store_id): radius_cells(s.lat, s.lng, budget_m, res) for s in stores.itertuples()}
    graph = ox.load_graphml(f"data/interim/{city}_drive.graphml")
    locator = NodeLocator(graph)
    return {(s.brand, s.store_id): road_filled_cells(graph, locator, s.lat, s.lng, budget_m, res)
            for s in stores.itertuples()}


def plot(city: str, method: str, cov: gpd.GeoDataFrame, stores: gpd.GeoDataFrame) -> str:
    fig, ax = plt.subplots(figsize=(8, 8))
    cov[cov["covered_any"]].plot(ax=ax, color="#d9d9d9", linewidth=0)
    gaps = cov[~cov["covered_any"]]
    if len(gaps):
        gaps.plot(ax=ax, column="demand_index", cmap="magma_r", linewidth=0, legend=True,
                  legend_kwds={"label": "Demand index of UNCOVERED hexes", "shrink": 0.6})
    for brand, color in BRAND_COLORS.items():
        pts = stores[stores["brand"] == brand]
        if len(pts):
            pts.plot(ax=ax, color=color, markersize=6, label=f"{brand} ({len(pts)})")
    ax.legend(loc="lower left", fontsize=8, title="Stores (Mar-2026 snapshot)", title_fontsize=8)
    ax.set_title(f"{city.title()}: coverage gaps ({method} reach); grey = covered by >=1 brand")
    ax.set_axis_off()
    out = f"reports/coverage_gaps_{city}_{method}.png"
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", help="one city from config/cities.yaml (default: all)")
    parser.add_argument("--method", choices=["radius", "road_filled", "both"], default="both")
    args = parser.parse_args()

    cfg = yaml.safe_load(open("config/cities.yaml", encoding="utf-8"))
    d = cfg["defaults"]
    res = d["h3_resolution"]
    methods = ["radius", "road_filled"] if args.method == "both" else [args.method]
    cities = [args.city] if args.city else list(cfg["cities"])

    for city in cities:
        demand = gpd.read_file(f"data/processed/{city}_demand_r{res}.gpkg")[["h3", "population", "demand_index", "geometry"]]
        stores = gpd.read_file(f"data/processed/{city}_stores.gpkg")
        area_cells = set(demand["h3"])

        centroids = demand.to_crs(demand.estimate_utm_crs()).centroid.to_crs("EPSG:4326")
        hex_lat, hex_lng = centroids.y.to_numpy(), centroids.x.to_numpy()
        for brand in BRANDS:
            sb = stores[stores["brand"] == brand]
            demand[f"nearest_km_{brand_slug(brand)}"] = nearest_store_km(
                hex_lat, hex_lng, sb["lat"].to_numpy(), sb["lng"].to_numpy())
        demand["nearest_km_any"] = demand[[f"nearest_km_{brand_slug(b)}" for b in BRANDS]].min(axis=1)
        radius_km = ride_budget_m(d["delivery_promise_min"], d["picking_time_min"],
                                  cfg["cities"][city]["reach_speed_kmph"]["radius"]) / 1000
        # Grading by distance beyond the calibrated radius: a binary cutoff turns "just outside" into false gaps.
        demand["gap_km_beyond_radius"] = (demand["nearest_km_any"] - radius_km).clip(lower=0)
        for method in methods:
            t = time.time()
            speed = cfg["cities"][city]["reach_speed_kmph"][method]
            budget = ride_budget_m(d["delivery_promise_min"], d["picking_time_min"], speed)
            reach = store_reach(stores, method, budget, res, city)
            table = coverage_table(reach, area_cells, BRANDS)
            cov = demand.merge(table, on="h3", how="left")
            cov.to_file(f"data/processed/{city}_coverage_{method}_r{res}.gpkg", driver="GPKG")
            png = plot(city, method, cov, stores)

            pop = cov["population"].sum()
            covered_pop = cov.loc[cov["covered_any"], "population"].sum() / pop
            per_brand = {b: cov.loc[cov[f"stores_{brand_slug(b)}"] > 0, "population"].sum() / pop for b in BRANDS}
            print(f"\n== {city} | {method} | {speed:g} km/h -> {budget:,.0f} m | {time.time() - t:.0f}s ==")
            print(f"  hexes covered by >=1 brand: {cov['covered_any'].mean():.1%} | population covered: {covered_pop:.1%}")
            print("  population covered per brand: " + " | ".join(f"{b} {v:.1%}" for b, v in per_brand.items()))
            print(f"  population in hexes covered by all 3 brands: {cov.loc[cov['brands_covering'] == 3, 'population'].sum() / pop:.1%}")
            gaps = cov[~cov["covered_any"]]
            near = gaps[gaps["gap_km_beyond_radius"] <= NEAR_MISS_KM]
            real = gaps[gaps["gap_km_beyond_radius"] > NEAR_MISS_KM]
            print(f"  uncovered hexes {len(gaps)}: near-miss (<= {NEAR_MISS_KM} km beyond radius) {len(near)} "
                  f"({near['population'].sum() / pop:.1%} of pop) | real gaps {len(real)} ({real['population'].sum() / pop:.1%} of pop)")
            for r in real.nlargest(5, "demand_index").itertuples():
                lat, lng = r.geometry.centroid.y, r.geometry.centroid.x
                print(f"  top real gap: {r.h3} | demand {r.demand_index:.1f} | pop {r.population:,.0f} | "
                      f"nearest store {r.nearest_km_any:.2f} km | {lat:.5f}, {lng:.5f}")
            print(f"  -> data/processed/{city}_coverage_{method}_r{res}.gpkg | {png}")


if __name__ == "__main__":
    main()
