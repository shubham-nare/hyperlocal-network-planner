"""Per-city inputs shared by the network studies: cells, the brand's existing network, calibrated
orders/day per hex, and store economics.

Orders are calibrated exactly as v1's scripts/optimize_network.py does (population x adoption
multiplier, scaled so the hexes the brand already covers carry its disclosed orders), on the
Overture + Meta HRSL features written by scripts/build_open_features.py. Economics come from the
Week-3 sensitivity table (81 scenarios per city).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import h3
import numpy as np
import pandas as pd
import yaml

from planner.demand import demand_index
from planner.economics import Quarter, per_order
from planner.orders import adoption_index, adoption_multiplier, calibrate_orders_per_weight, order_weights
from planner.reach import ride_budget_m
from planner.revealed_demand import reach_matrix
from planner.rollout import Economics, ServiceNetwork
from planner.stores import load_stores

ADOPTION_FEATURES = ("office", "education", "food_retail", "residential_highrise")


@dataclass
class CityInputs:
    city: str
    cells: list[str]
    lat: np.ndarray
    lng: np.ndarray
    in_study: np.ndarray
    net: ServiceNetwork
    mu: np.ndarray
    tilt: np.ndarray
    econ_scenarios: list[Economics]
    planner_econ: Economics
    n_existing: int
    radius_km: float = 0.0          # calibrated 10-minute reach (straight line)
    speed_kmph: float = 0.0         # the calibrated straight-line speed behind that reach
    existing_store_ids: list[str] = field(default_factory=list)


def city_inputs(city: str, cfg: dict) -> CityInputs:
    feats = pd.read_parquet(f"data/processed/{city}_open_features_r8.parquet").sort_values("h3").reset_index(drop=True)
    cells = feats["h3"].tolist()
    index = {c: k for k, c in enumerate(cells)}
    d = cfg["cities"]["defaults"]
    speed = cfg["cities"]["cities"][city]["reach_speed_kmph"]["radius"]
    radius_km = ride_budget_m(d["delivery_promise_min"], d["picking_time_min"], speed) / 1000
    reach = reach_matrix(cells, radius_km)
    own = cfg["stores"][cfg["stores"]["brand"] == cfg["brand"]]
    own_cells = [(h3.latlng_to_cell(a, b, 8), sid) for a, b, sid in zip(own["lat"], own["lng"], own["store_id"])]
    existing = [index[k] for k, _ in own_cells if k in index]
    existing_ids = [sid for k, sid in own_cells if k in index]

    # v1's order calibration (scripts/optimize_network.py), unchanged in logic
    ranked = demand_index(feats, {f: 1.0 for f in ADOPTION_FEATURES})   # adds the <feature>_pct columns
    adoption = adoption_index(ranked, {f: w for f, w in cfg["adoption_weights"].items()})
    served = np.asarray(reach[existing].sum(axis=0)).ravel() > 0
    weights = order_weights(feats["population"], adoption, cfg["elasticity"])
    rate = calibrate_orders_per_weight(weights, pd.Series(served), len(existing), cfg["completeness"], cfg["orders_per_store_day"])
    orders = (weights * rate).to_numpy()
    mu = np.log(orders + 1.0)
    tilt = np.log(adoption_multiplier(adoption, 1.0).to_numpy()) - np.log(adoption_multiplier(adoption, 0.5).to_numpy())

    sens = cfg["sensitivity"][cfg["sensitivity"]["city"] == city]
    scen = [Economics(cfg["gross_profit_per_order"] - r.variable_cost_per_order_inr, r.fixed_cost_per_day_inr, cfg["capex"])
            for r in sens.itertuples()]
    # guard: each scenario's margin must reproduce that scenario's break-even from the Week 3 table
    implied = np.array([e.fixed_per_day / e.margin_per_order for e in scen])
    if np.abs(implied - sens["breakeven_orders_per_day"].to_numpy()).max() > 1.5:
        raise ValueError(f"{city}: margins don't reproduce the sensitivity table's break-even")
    planner = Economics(float(np.mean([e.margin_per_order for e in scen])), float(np.mean([e.fixed_per_day for e in scen])),
                        cfg["capex"])
    latlng = np.array([h3.cell_to_latlng(c) for c in cells])
    return CityInputs(city, cells, latlng[:, 0], latlng[:, 1], feats["in_study_area"].to_numpy(bool),
                      ServiceNetwork(reach, existing, cfg["capacity"]), mu, tilt, scen, planner, len(existing),
                      radius_km, speed, existing_ids)


def load_config() -> dict:
    cities = yaml.safe_load(open("config/cities.yaml", encoding="utf-8"))
    econ = yaml.safe_load(open("config/economics.yaml", encoding="utf-8"))
    net = yaml.safe_load(open("config/network.yaml", encoding="utf-8"))
    demand_weights = yaml.safe_load(open("config/demand.yaml", encoding="utf-8"))["weights"]
    stores = load_stores("data/raw/darkstores")
    brand = net["brand"]
    orders_q = Quarter(**econ["quarters"][net["orders"]["calibration_quarter"]])     # as v1's optimiser
    orders_cal = per_order(orders_q)
    margin_q = per_order(Quarter(**econ["quarters"][econ["calibration_quarter"]]))  # as the sensitivity table
    return {
        "cities": cities, "brand": brand, "stores": stores,
        "adoption_weights": {k: w for k, w in demand_weights.items() if k != "density_per_km2"},
        "elasticity": net["orders"]["adoption_elasticity"],
        "orders_per_store_day": orders_cal["orders_per_store_day"],
        "completeness": int((stores["brand"] == brand).sum()) / orders_q.stores_end,
        "capacity": econ["steady_state"]["nov_per_store_day_inr"] / orders_cal["naov"],
        "gross_profit_per_order": margin_q["gross_profit"],
        "capex": float(econ["steady_state"]["capex_per_store_inr"]),
        "sensitivity": pd.read_csv("reports/unit_economics_sensitivity.csv"),
    }
