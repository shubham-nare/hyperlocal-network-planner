"""Train and evaluate the LightGBM store-siting model on the real three-city data.

See src/planner/ml_demand.py for what this predicts and why leave-one-city-out is the
validation method. This script prints real, computed numbers -- nothing here is a target
or an assumption.
"""
from __future__ import annotations

import geopandas as gpd
import pandas as pd

from planner.ml_demand import assemble_city_frame, leave_one_city_out, naive_mean_baseline

CITIES = ("hyderabad", "bengaluru", "pune")


def main() -> None:
    frames = {}
    for city in CITIES:
        demand = gpd.read_file(f"data/processed/{city}_demand_r8.gpkg")
        stores = gpd.read_file(f"data/processed/{city}_stores.gpkg")
        frames[city] = assemble_city_frame(city, demand, stores)
        print(f"{city}: {len(frames[city])} hexes, {int(frames[city]['store_count'].sum())} real stores placed, "
              f"{(frames[city]['store_count'] > 0).mean():.1%} of hexes have at least one")

    print("\n=== Leave-one-city-out: LightGBM vs. naive mean baseline ===")
    model_results, importances = leave_one_city_out(frames)
    baseline_results = naive_mean_baseline(frames)
    rows = []
    for m, b in zip(sorted(model_results, key=lambda r: r.held_out_city), sorted(baseline_results, key=lambda r: r.held_out_city)):
        rows.append({"held_out_city": m.held_out_city, "n_train": m.n_train, "n_test": m.n_test,
                    "model_rmse_log": round(m.rmse_log, 4), "baseline_rmse_log": round(b.rmse_log, 4),
                    "model_r2_log": round(m.r2_log, 4), "model_mae_count": round(m.mae_count, 3),
                    "baseline_mae_count": round(b.mae_count, 3)})
    table = pd.DataFrame(rows)
    print(table.to_string(index=False))
    beats_baseline = (table["model_rmse_log"] < table["baseline_rmse_log"]).sum()
    print(f"\nModel beats the naive mean baseline (lower RMSE in log-space) in {beats_baseline}/3 held-out cities.")

    print("\n=== Feature importance (mean gain share across the 3 folds) ===")
    print(importances.to_string())

    out = "reports/ml_demand_leave_one_city_out.csv"
    table.to_csv(out, index=False)
    importances.to_csv("reports/ml_demand_feature_importance.csv")
    print(f"\n-> {out}\n-> reports/ml_demand_feature_importance.csv")


if __name__ == "__main__":
    main()
