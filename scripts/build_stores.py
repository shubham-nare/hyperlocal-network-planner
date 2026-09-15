"""Standardise the third-party darkstores snapshot and clip stores / Zepto zones to each city's study area.

Source: GitHub jatin-dot-py/darkstores (unlicensed; README says coordinates were scraped from the apps'
public-facing APIs, Mar 2026). Raw files stay in gitignored data/raw/; only derived per-city layers are written.
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import yaml

from planner.stores import load_stores, load_zepto_zones

RAW = Path("data/raw/darkstores")


def main() -> None:
    cfg = yaml.safe_load(open("config/cities.yaml", encoding="utf-8"))
    res = cfg["defaults"]["h3_resolution"]
    sha = (RAW / "_commit_sha.txt").read_text(encoding="utf-8").strip()
    source = f"github.com/jatin-dot-py/darkstores@{sha[:7]} (unlicensed third-party snapshot, scraped Mar 2026)"

    stores = load_stores(RAW)
    stores["source"] = source
    zones = load_zepto_zones(RAW)
    zones["source"] = source

    for city in cfg["cities"]:
        area = gpd.read_file(f"data/processed/{city}_study_area_r{res}.gpkg").geometry.union_all()
        inside = stores[stores.within(area)].copy()
        inside.to_file(f"data/processed/{city}_stores.gpkg", driver="GPKG")

        zepto_ids = set(inside.loc[inside["brand"] == "Zepto", "store_id"])
        city_zones = zones[zones["store_id"].isin(zepto_ids)].copy()
        city_zones.to_file(f"data/processed/{city}_zepto_zones.gpkg", driver="GPKG")

        blinkit_acc = inside.loc[inside["brand"] == "Blinkit", "accuracy_m"]
        print(f"{city}: {len(inside)} stores {inside['brand'].value_counts().to_dict()} | "
              f"{len(city_zones)} Zepto zones | Blinkit accuracy median {blinkit_acc.median():.0f} m, "
              f"p90 {blinkit_acc.quantile(0.9):.0f} m")


if __name__ == "__main__":
    main()
