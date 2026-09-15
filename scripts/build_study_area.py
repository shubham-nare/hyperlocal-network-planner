"""Final study area per city: core + contiguous dense hexes (config threshold), with highway ribbons trimmed."""
from __future__ import annotations

import geopandas as gpd
import matplotlib
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from planner.grid import cells_to_gdf  # noqa: E402
from planner.population import hex_population  # noqa: E402
from planner.study_area import candidate_cells, grow_dense_area, trim_ribbons  # noqa: E402

RASTER = "data/raw/ind_pop_2026_CN_100m_R2025A_v1.tif"
COLORS = {"outside": "#eeeeee", "trimmed": "#fcae91", "added": "#3182bd", "core": "#08306b"}


def _plot(city: str, cands: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame, core: set[str], grown: set[str],
          final: set[str], threshold: int) -> str:
    zone = cands["h3"].map(lambda c: "core" if c in core else "added" if c in final else "trimmed" if c in grown else "outside")
    fig, ax = plt.subplots(figsize=(8, 8))
    for name, color in COLORS.items():
        sub = cands[zone == name]
        if len(sub):
            sub.plot(ax=ax, color=color, linewidth=0)
    boundary.boundary.plot(ax=ax, color="#e6550d", linewidth=1.2)
    ax.legend(handles=[Patch(color=COLORS["core"], label="Core (municipal)"),
                       Patch(color=COLORS["added"], label=f"Added (>= {threshold:,}/km2, kept)"),
                       Patch(color=COLORS["trimmed"], label="Trimmed ribbons"),
                       Patch(color="#e6550d", label="Core boundary")], loc="lower left", fontsize=8)
    ax.set_title(f"{city.title()}: final study area")
    ax.set_axis_off()
    out = f"reports/study_area_final_{city}.png"
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    cfg = yaml.safe_load(open("config/cities.yaml", encoding="utf-8"))
    res = cfg["defaults"]["h3_resolution"]
    sa = cfg["defaults"]["study_area"]
    for city in cfg["cities"]:
        core = set(gpd.read_file(f"data/interim/{city}_h3_r{res}.gpkg")["h3"])
        boundary = gpd.read_file(f"data/interim/{city}_boundary.gpkg")
        cands = hex_population(cells_to_gdf(candidate_cells(core, sa["max_rings"])), RASTER)
        density = dict(zip(cands["h3"], cands["density_per_km2"]))

        grown = grow_dense_area(core, density, sa["min_density_per_km2"], sa["max_rings"])
        final = trim_ribbons(grown, core, sa["ribbon_min_neighbours"])

        area = cands[cands["h3"].isin(final)].copy()
        area["in_core"] = area["h3"].isin(core)
        area.to_file(f"data/processed/{city}_study_area_r{res}.gpkg", driver="GPKG")

        trimmed = grown - final
        trimmed_pop = cands.loc[cands["h3"].isin(trimmed), "population"].sum()
        png = _plot(city, cands, boundary, core, grown, final, sa["min_density_per_km2"])
        print(f"{city}: core {len(core):,} | grown {len(grown):,} | trimmed {len(trimmed):,} hexes "
              f"({trimmed_pop:,.0f} people) | final {len(final):,} hexes, {area['area_km2'].sum():,.0f} km2, "
              f"pop {area['population'].sum():,.0f} | map {png}")


if __name__ == "__main__":
    main()
