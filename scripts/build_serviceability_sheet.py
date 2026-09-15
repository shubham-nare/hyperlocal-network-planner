"""Per city: assign demand hexes to pincode polygons and write the manual serviceability checklist."""
from __future__ import annotations

import geopandas as gpd
import h3
import yaml

from planner.pincodes import assign_hexes_to_pincodes, load_boundaries

BOUNDARIES = "data/raw/pincode_boundaries/india_pincodes.shp"
CHECK_COLUMNS = ["blinkit_serviceable", "zepto_serviceable", "instamart_serviceable", "checked_by", "checked_on", "notes"]


def _latlng_text(cell: str) -> str:
    lat, lng = h3.cell_to_latlng(cell)
    return f"{lat:.5f}, {lng:.5f}"


def main() -> None:
    cfg = yaml.safe_load(open("config/cities.yaml", encoding="utf-8"))
    res = cfg["defaults"]["h3_resolution"]
    boundaries = load_boundaries(BOUNDARIES)

    for city in cfg["cities"]:
        demand = gpd.read_file(f"data/processed/{city}_demand_r{res}.gpkg")
        assigned = assign_hexes_to_pincodes(demand, boundaries)
        assigned.to_file(f"data/processed/{city}_hex_pincode_r{res}.gpkg", driver="GPKG")

        sheet = (
            assigned.groupby("pincode")
            .agg(
                office=("pincode_office", "first"),
                district=("pincode_district", "first"),
                hexes=("h3", "size"),
                population=("population", "sum"),
                mean_demand_index=("demand_index", "mean"),
                hexes_by_nearest=("pincode_by_nearest", "sum"),
            )
            .reset_index()
            .sort_values("population", ascending=False)
        )
        sheet["population"] = sheet["population"].round().astype(int)
        sheet["mean_demand_index"] = sheet["mean_demand_index"].round(1)

        # Apps decide serviceability by distance from a dark store, not per pincode, so each check uses a fixed point.
        by_pin = assigned.groupby("pincode")["demand_index"]
        best_hex = assigned.loc[by_pin.idxmax(), ["pincode", "h3"]].set_index("pincode")["h3"]
        worst_hex = assigned.loc[by_pin.idxmin(), ["pincode", "h3"]].set_index("pincode")["h3"]
        sheet["check_point_high_demand"] = sheet["pincode"].map(best_hex).map(_latlng_text)
        sheet["check_point_low_demand"] = [
            _latlng_text(worst_hex[pin]) if n >= 10 else "" for pin, n in zip(sheet["pincode"], sheet["hexes"])
        ]
        for column in CHECK_COLUMNS:
            sheet[column] = ""
        out = f"reports/serviceability_sheet_{city}.csv"
        sheet.to_csv(out, index=False, encoding="utf-8")

        top20_share = sheet.head(20)["population"].sum() / sheet["population"].sum()
        print(f"{city}: {len(sheet)} pincodes | {len(assigned):,} hexes ({int(assigned['pincode_by_nearest'].sum())} assigned by nearest) | "
              f"top 20 pincodes = {top20_share:.0%} of population | sheet {out}")


if __name__ == "__main__":
    main()
