"""Validate Huff allocation against real Zepto delivery zones (same data Week 2 used).

Ground truth: for a hex whose centroid falls inside exactly one Zepto store's real zone
polygon, that store is the "true" primary server. (Hexes in zero or 2+ overlapping zones
are excluded -- overlaps have no unambiguous single ground-truth answer.) For each such
hex, compute the Huff model's argmax store across all of that city's Zepto stores within
a calibrated reach cutoff, and check whether it matches. Compared against a naive
nearest-store baseline to see whether the distance-decay weighting adds anything over
simply picking the closest store -- reported honestly either way, the way the reach-model
validation in Week 2 found radius and road-network reach were statistically tied.

IMPORTANT caveat found while building this: with attractiveness held uniform (the only
honest choice given no real per-store attractiveness data), argmax(1/distance^decay) is
mathematically always the nearest store, for ANY positive decay value -- raising a
strictly-decreasing function to a positive power never changes its ranking. So argmax
accuracy cannot test decay sensitivity at all under this model; it only tests whether
Huff's use of a reach cutoff and distance floor differs from plain nearest-store. Decay
sensitivity is tested separately below with log-loss, which depends on the full
probability spread, not just the top pick.
"""
from __future__ import annotations

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import yaml

from planner.huff import choice_probability_matrix, pairwise_distance_km
from planner.reach import ride_budget_m

CITIES = ("hyderabad", "bengaluru", "pune")
DECAY_VALUES = (1.0, 2.0, 3.0)


def ground_truth_hexes(city: str, res: int) -> pd.DataFrame:
    """Hexes whose centroid falls in exactly one Zepto zone, labeled with that store_id."""
    zones = gpd.read_file(f"data/processed/{city}_zepto_zones.gpkg")
    demand = gpd.read_file(f"data/processed/{city}_demand_r8.gpkg")[["h3", "geometry"]]
    centroids = demand.to_crs(demand.estimate_utm_crs()).centroid.to_crs("EPSG:4326")
    points = gpd.GeoDataFrame({"h3": demand["h3"]}, geometry=centroids, crs="EPSG:4326")
    joined = gpd.sjoin(points, zones[["store_id", "geometry"]], how="inner", predicate="within")
    unambiguous = joined.groupby("h3").filter(lambda g: len(g) == 1)
    out = unambiguous[["h3", "store_id"]].rename(columns={"store_id": "true_store_id"})
    out["lat"] = out["h3"].map(lambda c: h3.cell_to_latlng(c)[0])
    out["lng"] = out["h3"].map(lambda c: h3.cell_to_latlng(c)[1])
    return out.reset_index(drop=True)


def main() -> None:
    cities_cfg = yaml.safe_load(open("config/cities.yaml", encoding="utf-8"))
    defaults = cities_cfg["defaults"]
    res = defaults["h3_resolution"]
    rows = []
    for city in CITIES:
        stores = gpd.read_file(f"data/processed/{city}_stores.gpkg")
        zepto = stores[stores["brand"] == "Zepto"].reset_index(drop=True)
        truth = ground_truth_hexes(city, res)
        speed = cities_cfg["cities"][city]["reach_speed_kmph"]["radius"]
        budget_km = ride_budget_m(defaults["delivery_promise_min"], defaults["picking_time_min"], speed) / 1000

        distances = pairwise_distance_km(truth["lat"].to_numpy(), truth["lng"].to_numpy(),
                                         zepto["lat"].to_numpy(), zepto["lng"].to_numpy())
        nearest_idx = distances.argmin(axis=1)
        nearest_correct = (zepto["store_id"].to_numpy()[nearest_idx] == truth["true_store_id"].to_numpy()).mean()

        store_ids = zepto["store_id"].to_numpy()
        true_idx_per_hex = np.array([np.where(store_ids == t)[0][0] for t in truth["true_store_id"]])
        for decay in DECAY_VALUES:
            probs = choice_probability_matrix(truth["lat"].to_numpy(), truth["lng"].to_numpy(),
                                              zepto["lat"].to_numpy(), zepto["lng"].to_numpy(),
                                              distance_decay=decay, max_distance_km=budget_km)
            has_choice = probs.sum(axis=1) > 0
            predicted_idx = probs.argmax(axis=1)
            predicted_store = store_ids[predicted_idx]
            correct = (predicted_store[has_choice] == truth["true_store_id"].to_numpy()[has_choice])
            # Log-loss (only over hexes where the true store is actually within reach, since
            # argmax accuracy already separately captures the "no store in reach at all" failure
            # mode) is what actually tests decay sensitivity: a lower value means the model puts
            # more probability mass on the real server, not just ranks it first.
            true_prob = probs[np.arange(len(truth)), true_idx_per_hex]
            true_in_reach = true_prob > 0
            log_loss = float(-np.log(true_prob[true_in_reach]).mean()) if true_in_reach.any() else float("nan")
            rows.append({"city": city, "distance_decay": decay, "n_ground_truth_hexes": len(truth),
                        "n_with_a_store_in_reach": int(has_choice.sum()),
                        "n_true_store_in_reach": int(true_in_reach.sum()),
                        "huff_argmax_accuracy": round(correct.mean(), 4) if len(correct) else float("nan"),
                        "huff_log_loss_on_true_store": round(log_loss, 4),
                        "nearest_store_baseline_accuracy": round(nearest_correct, 4)})
        print(f"{city}: {len(truth)} unambiguous ground-truth hexes ({len(zepto)} Zepto stores, "
              f"reach cutoff {budget_km:.2f} km)")

    table = pd.DataFrame(rows)
    print("\n=== Huff vs. nearest-store baseline, by decay parameter ===")
    print(table.to_string(index=False))

    argmax_within_city = table.groupby("city")["huff_argmax_accuracy"].nunique()
    print(f"\nArgmax accuracy is identical across all decay values within each city (confirming the "
          f"invariance noted above): {(argmax_within_city == 1).all()}")

    pooled_baseline = (table.drop_duplicates("city")["nearest_store_baseline_accuracy"]
                      * table.drop_duplicates("city")["n_with_a_store_in_reach"]).sum() / table.drop_duplicates("city")["n_with_a_store_in_reach"].sum()
    pooled_huff = (table.drop_duplicates("city")["huff_argmax_accuracy"]
                  * table.drop_duplicates("city")["n_with_a_store_in_reach"]).sum() / table.drop_duplicates("city")["n_with_a_store_in_reach"].sum()
    print(f"Pooled Huff argmax accuracy (any decay): {pooled_huff:.4f} | pooled nearest-store baseline: {pooled_baseline:.4f}")

    pooled_log_loss = table.groupby("distance_decay").apply(
        lambda g: (g["huff_log_loss_on_true_store"] * g["n_true_store_in_reach"]).sum() / g["n_true_store_in_reach"].sum(),
        include_groups=False)
    print(f"\nPooled log-loss by decay (lower = more probability mass correctly placed on the real "
          f"server, not just ranked first): {pooled_log_loss.round(4).to_dict()}")
    best_decay = pooled_log_loss.idxmin()
    print(f"Best-fitting decay on this data: {best_decay:g} (log-loss {pooled_log_loss[best_decay]:.4f}) -- "
          f"fit to this one dataset with one brand, not an independently calibrated constant; treat as a "
          f"sensitivity range to expose in the app, not a fact to hardcode.")

    table.to_csv("reports/huff_validation_zepto.csv", index=False)
    print("\n-> reports/huff_validation_zepto.csv")


if __name__ == "__main__":
    main()
