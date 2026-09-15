"""Streamlit decision dashboard for the Hyperlocal Network Planner.

Run from the repository root:
    .venv\\Scripts\\streamlit.exe run app/app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# ``streamlit run app/app.py`` puts app/ (not src/) on sys.path.
sys.path.insert(0, str(ROOT / "src"))

import geopandas as gpd
import h3
import pandas as pd
import pydeck as pdk
import streamlit as st
import yaml

from planner.cloud_kitchen import diversified_shortlist, opportunity_index
from planner.coverage import brand_slug
from planner.economics import Quarter, per_order
from planner.optimize import Site, solve_network, useful_candidates
from planner.orders import adoption_index, calibrate_orders_per_weight, order_weights
from planner.reach import radius_cells, ride_budget_m
from planner.stores import load_stores


def read_yaml(name: str) -> dict:
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def load_city_data(city: str) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    config = read_yaml("cities.yaml")
    res = config["defaults"]["h3_resolution"]
    coverage = gpd.read_file(ROOT / "data" / "processed" / f"{city}_coverage_radius_r{res}.gpkg")
    pins = gpd.read_file(ROOT / "data" / "processed" / f"{city}_hex_pincode_r{res}.gpkg")
    cols = ["h3", "pincode", "pincode_office", "pincode_district"]
    coverage = coverage.merge(pins[cols], on="h3", how="left")
    stores = gpd.read_file(ROOT / "data" / "processed" / f"{city}_stores.gpkg")
    return coverage, stores


@st.cache_data(show_spinner=False)
def model_constants() -> dict:
    cities = read_yaml("cities.yaml")
    econ = read_yaml("economics.yaml")
    network = read_yaml("network.yaml")
    demand = read_yaml("demand.yaml")
    quarter_name = network["orders"]["calibration_quarter"]
    quarter = Quarter(**econ["quarters"][quarter_name])
    snapshot = load_stores(ROOT / "data" / "raw" / "darkstores")
    brand = network["brand"]
    return {
        "cities": cities,
        "network": network,
        "demand": demand,
        "brand": brand,
        "slug": brand_slug(brand),
        "orders_per_store_day": per_order(quarter)["orders_per_store_day"],
        "snapshot_completeness": (snapshot["brand"] == brand).sum() / quarter.stores_end,
        "default_capacity": int(round(econ["steady_state"]["nov_per_store_day_inr"] / per_order(quarter)["naov"] / 100) * 100),
        "breakeven": pd.read_csv(ROOT / "reports" / "unit_economics_sensitivity.csv").groupby("city")["breakeven_orders_per_day"].median().to_dict(),
    }


def point_frame(hexes: pd.DataFrame, value: pd.Series, colour: str = "score") -> pd.DataFrame:
    points = hexes[["h3"]].copy()
    lat_lng = points["h3"].map(h3.cell_to_latlng)
    points[["lat", "lng"]] = pd.DataFrame(lat_lng.tolist(), index=points.index)
    points["score"] = value.to_numpy()
    # A visible but restrained green-to-gold scale for the map.
    normal = (points["score"] - points["score"].min()) / max(points["score"].max() - points["score"].min(), 1e-9)
    points["r"] = (30 + 210 * normal).astype(int)
    points["g"] = (80 + 130 * normal).astype(int)
    points["b"] = (140 - 95 * normal).astype(int)
    return points


def deck(points: pd.DataFrame, stores: gpd.GeoDataFrame, proposals: pd.DataFrame | None, city: str) -> pdk.Deck:
    layers = [pdk.Layer(
        "ScatterplotLayer", points, get_position="[lng, lat]", get_fill_color="[r, g, b, 150]",
        get_radius=300, radius_min_pixels=2, radius_max_pixels=12, pickable=True,
    )]
    if len(stores):
        store_points = stores[["brand", "lat", "lng"]].copy()
        palette = {"Blinkit": [22, 119, 255], "Zepto": [121, 42, 199]}
        store_points["colour"] = store_points["brand"].map(lambda brand: palette.get(brand, [255, 94, 31]))
        layers.append(pdk.Layer("ScatterplotLayer", store_points, get_position="[lng, lat]", get_fill_color="colour",
                                get_radius=100, radius_min_pixels=3, pickable=True))
    if proposals is not None and len(proposals):
        layers.append(pdk.Layer("ScatterplotLayer", proposals, get_position="[lng, lat]", get_fill_color=[255, 200, 0],
                                get_line_color=[30, 30, 30], stroked=True, get_radius=500, radius_min_pixels=6, pickable=True))
    view = pdk.ViewState(latitude=float(points.lat.mean()), longitude=float(points.lng.mean()), zoom=10.5)
    return pdk.Deck(layers=layers, initial_view_state=view,
                    tooltip={"text": "{score:.1f}"}, map_style="light")


def fast_candidates(sites: list[Site], demand: dict[str, float], baseline, capacity: float, limit: int = 250) -> set[str]:
    """Keep a transparent shortlist for interactive solve time; full CLI keeps every useful cell."""
    useful = useful_candidates(sites, demand, baseline, capacity)
    unserved = {h: max(demand[h] - baseline.hex_served.get(h, 0), 0) for h in demand}
    score = {s.site_id: sum(unserved.get(h, 0) for h in s.reach) for s in sites if s.site_id in useful}
    return set(sorted(score, key=score.get, reverse=True)[:limit])


def dark_store_result(city: str, elasticity: float, growth: float, capacity: float, max_new: int) -> dict:
    constants = model_constants()
    cov, stores = load_city_data(city)
    own = stores[stores["brand"] == constants["brand"]]
    non_density = {k: v for k, v in constants["demand"]["weights"].items() if k != "density_per_km2"}
    cov["adoption_index"] = adoption_index(cov, non_density)
    weights = order_weights(cov["population"], cov["adoption_index"], elasticity)
    served = cov[f"stores_{constants['slug']}"] > 0
    rate = calibrate_orders_per_weight(weights, served, len(own), constants["snapshot_completeness"], constants["orders_per_store_day"])
    cov["latent_orders"] = weights * rate * growth
    demand = dict(zip(cov["h3"], cov["latent_orders"]))
    ccfg = constants["cities"]
    res = ccfg["defaults"]["h3_resolution"]
    city_cfg = ccfg["cities"][city]
    budget = ride_budget_m(ccfg["defaults"]["delivery_promise_min"], ccfg["defaults"]["picking_time_min"], city_cfg["reach_speed_kmph"]["radius"])
    area = set(cov["h3"])
    sites = [Site(f"store:{s.store_id}", frozenset(radius_cells(s.lat, s.lng, budget, res) & area), existing=True)
             for s in own.itertuples()]
    sites += [Site(f"hex:{cell}", frozenset(radius_cells(*h3.cell_to_latlng(cell), budget, res) & area)) for cell in cov["h3"]]
    existing = [s for s in sites if s.existing]
    base = solve_network(demand, existing, capacity, constants["breakeven"][city], max_new=0, time_limit_s=30)
    candidates = fast_candidates(sites, demand, base, capacity)
    solution = solve_network(demand, sites, capacity, constants["breakeven"][city], max_new=max_new,
                             candidates=candidates, time_limit_s=60, mip_gap=0.01)
    rows = []
    for rank, site_id in enumerate(solution.opened, 1):
        cell = site_id.removeprefix("hex:")
        row = cov.loc[cov.h3 == cell].iloc[0]
        lat, lng = h3.cell_to_latlng(cell)
        site_orders = solution.store_orders[site_id]
        rows.append({"rank": rank, "locality": row.pincode_office, "pincode": row.pincode, "lat": lat, "lng": lng,
                     "orders_per_day": round(site_orders), "break_even_cover": round(site_orders / constants["breakeven"][city], 1)})
    proposals = pd.DataFrame(rows)
    cov["unserved_orders"] = cov["latent_orders"] - cov["h3"].map(base.hex_served).fillna(0)
    return {"coverage": cov, "stores": stores, "proposals": proposals, "base": base, "solution": solution,
            "total": sum(demand.values()), "budget": budget, "breakeven": constants["breakeven"][city],
            "candidate_count": len(candidates)}


def cloud_kitchen_view(city: str) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    cov, _ = load_city_data(city)
    cfg = read_yaml("cloud_kitchen.yaml")
    score = opportunity_index(cov, cfg["weights"])
    cov["cloud_kitchen_score"] = score
    picks = diversified_shortlist(cov, score, n=10, separation_rings=cfg["minimum_separation_rings"])
    lat_lng = picks.h3.map(h3.cell_to_latlng)
    picks[["lat", "lng"]] = pd.DataFrame(lat_lng.tolist(), index=picks.index)
    picks["locality"] = picks["pincode_office"]
    columns = ["locality", "pincode", "lat", "lng", "cloud_kitchen_score", "population", "food_retail", "office", "education"]
    return cov, pd.DataFrame(picks[columns])


def main() -> None:
    st.set_page_config(page_title="Hyperlocal Network Planner", page_icon="🗺️", layout="wide")
    st.title("Hyperlocal Network Planner")
    st.caption("Decision support for quick-commerce expansion. Public data and assumptions guide scouting; they do not replace field diligence.")
    constants = model_constants()
    city = st.sidebar.selectbox("City", list(constants["cities"]["cities"]), format_func=str.title)
    mode = st.sidebar.radio("Mode", ["Dark-store simulator", "Cloud-kitchen discovery"])

    if mode == "Cloud-kitchen discovery":
        st.subheader(f"{city.title()} cloud-kitchen opportunity clusters")
        st.info("Exploratory only: the score combines population density, food/retail POIs, offices, education, and apartments. It is not a meal-order forecast or investment recommendation.")
        cov, picks = cloud_kitchen_view(city)
        points = point_frame(cov, cov.cloud_kitchen_score)
        st.pydeck_chart(deck(points, gpd.GeoDataFrame(), picks, city))
        st.dataframe(picks.rename(columns={"cloud_kitchen_score": "opportunity score"}), hide_index=True, use_container_width=True)
        return

    st.sidebar.subheader("Scenario inputs")
    elasticity = st.sidebar.slider("POI adoption elasticity", 0.0, 1.0, float(constants["network"]["orders"]["adoption_elasticity"]), 0.1,
                                   help="0 = population only; 1 = fully scaled by the POI adoption index.")
    growth = st.sidebar.slider("Demand growth multiplier", 0.5, 2.0, float(constants["network"]["orders"]["growth_multiplier"]), 0.1)
    capacity = st.sidebar.slider("Store capacity (orders/day)", 1200, 3500, int(round(constants["default_capacity"])), 100)
    max_new = st.sidebar.select_slider("New stores to recommend", options=[5, 10, 20, 30], value=10)
    st.sidebar.caption("The interactive run screens to the 250 strongest candidate cells for responsiveness. The command-line optimiser remains the full-network run.")
    run = st.button("Run scenario", type="primary")
    if not run:
        st.info("Set assumptions, then run a scenario. The defaults reproduce the calibrated base case as closely as the interactive candidate screen allows.")
        return
    with st.spinner("Optimising capacity-limited demand allocation…"):
        result = dark_store_result(city, elasticity, growth, capacity, max_new)
    base, sol, total = result["base"], result["solution"], result["total"]
    incremental = sol.served_total - base.served_total
    a, b, c, d = st.columns(4)
    a.metric("Incremental orders/day", f"{incremental:,.0f}")
    b.metric("Demand served", f"{base.served_total / total:.1%}", f"{sol.served_total / total - base.served_total / total:+.1%}")
    c.metric("Break-even floor", f"{result['breakeven']:,.0f}/day")
    d.metric("Calibrated reach", f"{result['budget'] / 1000:.3g} km")
    st.caption(f"Solver: {sol.status}. Screened {result['candidate_count']:,} candidate cells before the interactive solve.")
    score = result["coverage"]["unserved_orders"]
    st.pydeck_chart(deck(point_frame(result["coverage"], score), result["stores"], result["proposals"], city))
    st.subheader("Recommended areas")
    st.dataframe(result["proposals"], hide_index=True, use_container_width=True)
    st.warning("Review permits, micro-market rent, rider supply, competition, and true local demand before opening a site. The store snapshot is from March 2026 and undercounts current networks.")


if __name__ == "__main__":
    main()
