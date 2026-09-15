"""Build the serviceability validation sample and the local keyboard-driven checker page.

Place names come from OpenStreetMap Nominatim reverse geocoding, cached and paced at 1 request/second per its
usage policy. The checker never contacts Blinkit/Zepto/Instamart/Amazon; a person does each lookup in the apps.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import geopandas as gpd
import h3
import pandas as pd
import requests
import yaml

from planner.validation_sample import add_demand_tiers, check_points_from_sheet, stratified_sample

APPS = ["Blinkit", "Zepto", "Swiggy Instamart", "Amazon Now"]
CACHE = Path("data/interim/reverse_geocode_cache.json")
TEMPLATE = Path("app/checker_template.html")
HEADERS = {"User-Agent": "HyperlocalNetworkPlanner/0.1 (student research project)"}


def place_label(lat: float, lng: float, cache: dict[str, str]) -> str:
    key = f"{lat:.5f},{lng:.5f}"
    if key not in cache:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lng, "format": "jsonv2", "zoom": 17, "addressdetails": 1},
            headers=HEADERS, timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        addr = body.get("address", {})
        parts = [addr.get(k) for k in ("road", "neighbourhood", "suburb", "city_district", "city", "town", "village")]
        cache[key] = ", ".join(dict.fromkeys(p for p in parts if p)) or body.get("display_name", "")
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(1.1)  # Nominatim usage policy: at most 1 request per second
    return cache[key]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="include every check point instead of a stratified sample")
    parser.add_argument("--per-stratum", type=int, default=7, help="points per (city, demand tier) when sampling")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    cfg = yaml.safe_load(open("config/cities.yaml", encoding="utf-8"))
    res = cfg["defaults"]["h3_resolution"]

    frames = []
    for city in cfg["cities"]:
        sheet = pd.read_csv(f"reports/serviceability_sheet_{city}.csv")
        points = check_points_from_sheet(sheet, city)
        points["h3"] = [h3.latlng_to_cell(lat, lng, res) for lat, lng in zip(points["lat"], points["lng"])]
        demand = gpd.read_file(f"data/processed/{city}_demand_r{res}.gpkg")[["h3", "demand_index", "in_core"]]
        frames.append(points.merge(pd.DataFrame(demand), on="h3", how="left"))
    points = pd.concat(frames, ignore_index=True)
    missing = int(points["demand_index"].isna().sum())
    points = points.dropna(subset=["demand_index"])

    chosen = add_demand_tiers(points) if args.all else stratified_sample(points, args.per_stratum, args.seed)
    chosen = chosen.reset_index(drop=True)
    chosen["id"] = [f"{c[:3].upper()}-{i + 1:03d}" for i, c in enumerate(chosen["city"])]

    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    chosen["label"] = [place_label(lat, lng, cache) for lat, lng in zip(chosen["lat"], chosen["lng"])]
    chosen.to_csv("data/processed/validation_sample.csv", index=False, encoding="utf-8")

    records = [
        {"id": r["id"], "city": r["city"], "pincode": int(r["pincode"]), "office": r["office"],
         "point_type": r["point_type"], "demand_tier": int(r["demand_tier"]), "lat": float(r["lat"]),
         "lng": float(r["lng"]), "h3": r["h3"], "demand_index": round(float(r["demand_index"]), 1),
         "in_core": bool(r["in_core"]), "label": r["label"]}
        for r in chosen.to_dict("records")
    ]
    template = TEMPLATE.read_text(encoding="utf-8")
    # "</" is escaped so a place name can never close the <script> tag.
    html = (template
            .replace("/*__POINTS__*/[]", json.dumps(records, ensure_ascii=False).replace("</", "<\\/"))
            .replace("/*__APPS__*/[]", json.dumps(APPS)))
    out = Path("reports/serviceability_checker.html")
    out.write_text(html, encoding="utf-8")

    by_stratum = chosen.groupby(["city", "demand_tier"]).size().to_dict()
    print(f"{len(chosen)} check points ({'all' if args.all else f'{args.per_stratum} per city x demand tier'}) | "
          f"dropped {missing} without a demand index | per stratum {by_stratum}")
    print(f"sample -> data/processed/validation_sample.csv | checker -> {out} (open it in a browser)")


if __name__ == "__main__":
    main()
