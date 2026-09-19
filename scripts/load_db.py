"""Load already-computed, already-validated project outputs into PostgreSQL.

This does not compute anything new -- it reads the same GeoPackage/CSV files every
other script in this project reads, and copies them into tables the API can query
quickly. The real work (demand modeling, optimization, validation) happened earlier and
is unchanged; this script only changes where the results live.
"""
from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from planner.db import Base, get_engine
from planner.db_models import Hex, RecommendedSite, StoreRecord

CITIES = ("hyderabad", "bengaluru", "pune")


def load_hexes(session: Session, city: str) -> int:
    demand = gpd.read_file(f"data/processed/{city}_demand_r8.gpkg")
    centroids = demand.to_crs(demand.estimate_utm_crs()).centroid.to_crs("EPSG:4326")
    rows = []
    for row, centroid in zip(demand.itertuples(), centroids):
        rows.append(Hex(
            h3=row.h3, city=city, lat=centroid.y, lng=centroid.x, population=float(row.population),
            density_per_km2=float(row.density_per_km2), demand_index=float(row.demand_index),
            office=float(row.office), education=float(row.education), food_retail=float(row.food_retail),
            residential_highrise=float(row.residential_highrise), in_core=bool(row.in_core),
            geometry_geojson=json.loads(gpd.GeoSeries([row.geometry], crs=demand.crs).to_json())["features"][0]["geometry"],
        ))
    session.add_all(rows)
    return len(rows)


def load_stores(session: Session, city: str) -> int:
    stores = gpd.read_file(f"data/processed/{city}_stores.gpkg")
    rows = [StoreRecord(city=city, brand=r.brand, store_id=str(r.store_id), lat=float(r.lat), lng=float(r.lng),
                        label=getattr(r, "label", None))
            for r in stores.itertuples()]
    session.add_all(rows)
    return len(rows)


def load_recommended_sites(session: Session, city: str, scenario_tag: str = "base") -> int:
    table = pd.read_csv(f"reports/network_{city}_{scenario_tag}.csv")
    rows = [RecommendedSite(
        city=city, scenario_tag=scenario_tag, rank=int(r.rank), h3=str(r.h3), lat=float(r.lat), lng=float(r.lng),
        locality=r.locality if pd.notna(r.locality) else None, pincode=str(r.pincode) if pd.notna(r.pincode) else None,
        demand_index=float(r.demand_index), site_orders_per_day=float(r.site_orders_per_day),
        incremental_orders_per_day=float(r.incremental_orders_per_day), new_coverage_orders=float(r.new_coverage_orders),
        capacity_relief_orders=float(r.capacity_relief_orders), breakeven_cover=float(r.breakeven_cover),
        competitor_stores_reaching_hex=int(r.competitor_stores_reaching_hex),
    ) for r in table.itertuples()]
    session.add_all(rows)
    return len(rows)


def main() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for table in (Hex, StoreRecord, RecommendedSite):
            session.execute(text(f"TRUNCATE TABLE {table.__tablename__} RESTART IDENTITY CASCADE"))
        session.commit()
        for city in CITIES:
            n_hex = load_hexes(session, city)
            n_store = load_stores(session, city)
            n_site = load_recommended_sites(session, city)
            print(f"{city}: {n_hex} hexes, {n_store} stores, {n_site} recommended sites")
        session.commit()
    print("-> loaded into", get_engine().url.render_as_string(hide_password=True))


if __name__ == "__main__":
    main()
