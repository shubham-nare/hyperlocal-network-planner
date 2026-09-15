"""Demand index v0 per city: OSM POIs + WorldPop density on each city's final study-area hexes."""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from planner.demand import count_by_hex, demand_index, demand_index_log  # noqa: E402
from planner.poi import fetch_pois  # noqa: E402


def _plot(city: str, hexes: gpd.GeoDataFrame) -> str:
    fig, ax = plt.subplots(figsize=(8, 8))
    hexes.plot(ax=ax, column="demand_index", cmap="viridis", linewidth=0, legend=True,
               legend_kwds={"label": "Demand index v0 (0-100, within-city)", "shrink": 0.6})
    ax.set_title(f"{city.title()}: demand index v0")
    ax.set_axis_off()
    out = f"reports/demand_{city}.png"
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-pois", action="store_true", help="re-download OSM POIs even if cached")
    parser.add_argument("--city", help="run a single city from config/cities.yaml")
    args = parser.parse_args()

    cities = yaml.safe_load(open("config/cities.yaml", encoding="utf-8"))
    dcfg = yaml.safe_load(open("config/demand.yaml", encoding="utf-8"))
    res = cities["defaults"]["h3_resolution"]
    categories = dcfg["poi_categories"]
    weights = dcfg["weights"]

    for city in [args.city] if args.city else list(cities["cities"]):
        area = gpd.read_file(f"data/processed/{city}_study_area_r{res}.gpkg")
        cache = Path(f"data/interim/{city}_poi.gpkg")
        if cache.exists() and not args.refresh_pois:
            pois = gpd.read_file(cache)
        else:
            pois = fetch_pois(area.geometry.union_all(), categories)
            pois.to_file(cache, driver="GPKG")

        hexes = demand_index(count_by_hex(pois, area, list(categories)), weights)
        for name, scenario in dcfg.get("scenarios", {}).items():
            if scenario["method"] != "log_minmax_smoothed":
                raise ValueError(f"unknown scenario method {scenario['method']!r} for {name}")
            hexes[f"demand_index_{name}"] = demand_index_log(
                hexes, scenario["weights"], clip_quantile=scenario.get("density_clip_quantile", 0.99)
            )
        hexes.to_file(f"data/processed/{city}_demand_r{res}.gpkg", driver="GPKG")
        png = _plot(city, hexes)

        top = hexes.nlargest(max(1, len(hexes) // 10), "demand_index")
        poi_totals = {c: int(hexes[c].sum()) for c in categories}
        # Spearman = Pearson on ranks; avoids a scipy dependency for one diagnostic.
        corr = hexes["demand_index"].rank().corr(hexes["density_per_km2_pct"].rank())
        print(f"\n== {city}: {len(hexes):,} hexes | POIs {poi_totals} | map {png}")
        print(f"   top-10% hexes hold {top['population'].sum() / hexes['population'].sum():.1%} of population "
              f"and {top['office'].sum() / max(poi_totals['office'], 1):.1%} of offices | "
              f"spearman(index, density pct) = {corr:.2f}")


if __name__ == "__main__":
    main()
