"""Hold-out validation: hide 20% of the brand's real stores, ask the optimiser for the same number of new sites,
and measure how many hidden stores get a proposed site nearby, against naive baselines with the same N.

Demand is calibrated with all stores (only the scalar orders-per-weight rate sees them), so leakage is minimal.
"""
from __future__ import annotations

import argparse
import time

import geopandas as gpd
import h3
import numpy as np
import pandas as pd

from optimize_network import city_inputs, load_config
from planner.holdout import holdout_split, match_metrics
from planner.optimize import solve_network, useful_candidates

RANDOM_DRAWS = 20


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", help="one city from config/cities.yaml (default: all)")
    parser.add_argument("--elasticity", type=float)
    parser.add_argument("--growth", type=float)
    parser.add_argument("--capacity", type=float)
    args = parser.parse_args()
    c = load_config(args)
    v = c["net"]["validation"]
    rng = np.random.default_rng(v["seed"])

    rows = []
    for city in [args.city] if args.city else list(c["cities"]["cities"]):
        cov, demand, sites, _ = city_inputs(city, c)
        be = c["breakeven"][city]
        stores = gpd.read_file(f"data/processed/{city}_stores.gpkg")
        coords = {f"store:{s.store_id}": (s.lat, s.lng) for s in stores[stores["brand"] == c["brand"]].itertuples()}
        existing_ids = [s.site_id for s in sites if s.existing]
        hex_lat, hex_lng = map(np.array, zip(*(h3.cell_to_latlng(h) for h in cov["h3"])))
        pop_p = (cov["population"] / cov["population"].sum()).to_numpy()

        for r in range(v["repeats"]):
            t = time.time()
            _, held = holdout_split(existing_ids, v["holdout_share"], rng)
            held_set = set(held)
            sites_r = [s for s in sites if s.site_id not in held_set]
            base = solve_network(demand, [s for s in sites_r if s.existing], c["capacity"], be, max_new=0)
            cands = useful_candidates(sites_r, demand, base, c["capacity"])
            sol = solve_network(demand, sites_r, c["capacity"], be, max_new=len(held), candidates=cands)
            t_lat, t_lng = map(np.array, zip(*(coords[s] for s in held)))

            def score(method: str, cells: list[str]) -> None:
                p_lat, p_lng = (map(np.array, zip(*(h3.cell_to_latlng(h) for h in cells)))) if cells else (np.array([]), np.array([]))
                for km in (1.0, v["match_km"]):
                    m = match_metrics(t_lat, t_lng, p_lat, p_lng, km)
                    rows.append({"city": city, "repeat": r, "method": method, "within_km": km, "n_held": len(held),
                                 "n_proposed": len(cells), **m})

            score("optimiser", [s.removeprefix("hex:") for s in sol.opened])
            unserved = (cov["h3"].map(demand) - cov["h3"].map(base.hex_served).fillna(0)).to_numpy()
            score("top_unserved_hexes", cov["h3"].to_numpy()[np.argsort(-unserved)[:len(held)]].tolist())
            score("top_demand_index", cov.nlargest(len(held), "demand_index")["h3"].tolist())
            for _ in range(RANDOM_DRAWS):
                idx = rng.choice(len(cov), size=len(held), replace=False, p=pop_p)
                score("random_pop_weighted", cov["h3"].to_numpy()[idx].tolist())
            print(f"{city} repeat {r}: held {len(held)} | opened {len(sol.opened)} ({sol.status}) | {time.time() - t:.0f}s", flush=True)

    df = pd.DataFrame(rows)
    out = "reports/holdout_validation.csv" if not args.city else f"reports/holdout_validation_{args.city}.csv"
    df.to_csv(out, index=False)
    summary = (df.groupby(["city", "within_km", "method"])[["recall", "precision", "median_km_true_to_pred"]]
               .mean().round(3))
    print("\nMean over repeats (random baseline also over draws):")
    print(summary.to_string())
    print(f"-> {out}")


if __name__ == "__main__":
    main()
