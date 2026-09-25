"""Does modelling how networks are *built* recover real demand better than ranking hexes one by one?

Hide real dark-store networks, re-place them from a demand map, and measure how close the placed
network lands to the real one (recall within 0.5 / 1.0 / 1.5 km -- 0.5 km is effectively the same
hex, 1.5 km is v1's holdout metric). Three protocols, strictest last:

- leave-one-brand-out (LOBO): fit on the other two brands in all cities, place the hidden brand.
- leave-one-city-out (LOCO): fit on the other two cities, place every brand in the hidden city.
- leave-brand-and-city-out (LOBCO): the hidden brand and the hidden city both never seen in fitting.

Competitor stores that are public (the other brands' real locations in the target city) are
used at placement time, exactly as a real entrant could use them. Every method places the same
number of stores the brand really has in that city, so recall and precision coincide by design.

    PYTHONPATH=src python scripts/validate_revealed_demand.py [--source open|v1] [--bootstrap 100]

``--source open`` (default) reads the Overture + Meta HRSL features from build_open_features.py;
``--source v1`` reads the original WorldPop/OSM ``{city}_demand_r8.gpkg`` layers (no buffer ring).
"""
from __future__ import annotations

import argparse
import time

import h3
import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml

from planner.demand import demand_index
from planner.open_data import label_places
from planner.reach import ride_budget_m
from planner.revealed_demand import (
    COUNT_COLUMNS, LADDER, feature_columns, load_features, CityData, build_city_data, fit, greedy_place, random_recall,
    recall_within, structural_gain, top_k, uncovered_gain, whitespace,
)
from planner.stores import load_stores

CITIES = ("hyderabad", "bengaluru", "pune")
BRANDS = ("Blinkit", "Zepto", "Swiggy Instamart")
DISTANCES_KM = (0.5, 1.0, 1.5)
LGB_PARAMS = {"n_estimators": 200, "num_leaves": 15, "min_child_samples": 20, "learning_rate": 0.05,
              "random_state": 7, "verbosity": -1}


def index_demand(data: CityData, weights: dict[str, float]) -> np.ndarray:
    """The v1 hand-weighted percentile demand index (config/demand.yaml), computed on these features."""
    raw = data.raw[[c for c in weights if c in data.raw.columns]].copy()
    return demand_index(raw, {k: v for k, v in weights.items() if k in raw.columns})["demand_index"].to_numpy()


def lgb_scores(datasets: dict[str, CityData], train: dict[str, tuple[str, ...]], target: CityData) -> np.ndarray:
    xs, ys = [], []
    for city, brands in train.items():
        d = datasets[city]
        for b in brands:
            xs.append(d.z[d.study_idx])
            ys.append((d.stores[b][d.study_idx] > 0).astype(int))
    model = lgb.LGBMClassifier(**LGB_PARAMS).fit(np.vstack(xs), np.concatenate(ys))
    return model.predict_proba(target.z)[:, 1]


def evaluate_fold(protocol: str, datasets: dict[str, CityData], train: dict[str, tuple[str, ...]],
                  targets: list[tuple[str, str]], index_weights: dict[str, float]) -> list[dict]:
    """Fit every method on ``train`` and place each (city, brand) in ``targets``."""
    fitted = {spec.name: fit(datasets, train, spec=spec) for spec in LADDER}
    lgb_cache: dict[str, np.ndarray] = {}
    rows = []
    for city, brand in targets:
        data = datasets[city]
        actual = data.occupied(brand)
        k = len(actual)
        comp = sum((data.stores[b] for b in BRANDS if b != brand), np.zeros(len(data.cells)))
        comp_cov = data.reach @ comp
        if city not in lgb_cache:
            lgb_cache[city] = lgb_scores(datasets, train, data)
        placements = {
            "demand_index_max_coverage": greedy_place(data, k, uncovered_gain(index_demand(data, index_weights))),
            "lightgbm_top_k": top_k(data, lgb_cache[city], k),
            "own_hex_logit_top_k": top_k(data, data.z @ fitted["own_hex_logit"].theta, k),
        }
        # "copy the competitors": max-coverage over hexes weighted by public competitor store counts
        placements["competitor_max_coverage"] = greedy_place(data, k, uncovered_gain(comp + 1e-6 * index_demand(data, index_weights)))
        for name in ("catchment", "catchment+spacing", "spacing+competition_no_features", "structural"):
            placements[f"{name}_greedy"] = greedy_place(data, k, structural_gain(fitted[name], data, comp_cov))
        for method, chosen in placements.items():
            rows.append({"protocol": protocol, "city": city, "brand": brand, "method": method, "k": k,
                         **{f"recall_{d}km": recall_within(data, chosen, actual, d) for d in DISTANCES_KM}})
        rows.append({"protocol": protocol, "city": city, "brand": brand, "method": "random", "k": k,
                     **{f"recall_{d}km": random_recall(data, k, actual, d) for d in DISTANCES_KM}})
    return rows


def pooled(results: pd.DataFrame) -> pd.DataFrame:
    """Recall pooled over real stores (k-weighted), like v1's pooled holdout numbers."""
    cols = [f"recall_{d}km" for d in DISTANCES_KM]
    g = results.groupby(["protocol", "method"])
    out = g.apply(lambda f: pd.Series({c: np.average(f[c], weights=f["k"]) for c in cols}), include_groups=False)
    out["n_targets"] = g.size()
    for d in (0.5, 1.5):
        wins = results.pivot_table(index=["protocol", "city", "brand"], columns="method", values=f"recall_{d}km")
        out[f"beats_index_{d}km"] = [
            int((wins.loc[p, m] > wins.loc[p, "demand_index_max_coverage"]).sum()) if m != "demand_index_max_coverage" else np.nan
            for p, m in out.index
        ]
    return out.reset_index()


def block_bootstrap(datasets: dict[str, CityData], reps: int, seed: int = 7) -> pd.DataFrame:
    """Per-brand structural fits with spatial block-bootstrap intervals (blocks = H3 res-6 parents,
    ~36 km2, resampled within each city) -- neighbouring hexes are not independent evidence."""
    rng = np.random.default_rng(seed)
    rows = []
    for brand in BRANDS:
        train = {c: (brand,) for c in datasets}
        comps = {c: BRANDS for c in datasets}
        point = fit(datasets, train, comps)
        draws = []
        for _ in range(reps):
            weights = {}
            for city, d in datasets.items():
                parents = np.array([h3.cell_to_parent(d.cells[i], 6) for i in d.study_idx])
                uniq = np.unique(parents)
                counts = pd.Series(rng.choice(uniq, size=len(uniq), replace=True)).value_counts()
                weights[(city, brand)] = pd.Series(parents).map(counts).fillna(0).to_numpy(float)
            draws.append(fit(datasets, train, comps, weights=weights).coefficients())
        draws = pd.DataFrame(draws)
        for name, value in point.coefficients().items():
            rows.append({"brand": brand, "parameter": name, "estimate": value,
                         "ci_low": draws[name].quantile(0.05), "ci_high": draws[name].quantile(0.95)})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("open", "v1"), default="open")
    ap.add_argument("--bootstrap", type=int, default=100)
    args = ap.parse_args()

    cfg = yaml.safe_load(open("config/cities.yaml", encoding="utf-8"))
    d = cfg["defaults"]
    index_weights = yaml.safe_load(open("config/demand.yaml", encoding="utf-8"))["weights"]
    stores = load_stores("data/raw/darkstores")
    datasets = {}
    for city in CITIES:
        feats = load_features(city, args.source)
        radius_km = ride_budget_m(d["delivery_promise_min"], d["picking_time_min"],
                                  cfg["cities"][city]["reach_speed_kmph"]["radius"]) / 1000
        datasets[city] = build_city_data(city, feats, stores, radius_km, feature_columns(feats),
                                         COUNT_COLUMNS, BRANDS)
        occ = {b: len(datasets[city].occupied(b)) for b in BRANDS}
        print(f"{city}: {int(datasets[city].in_study.sum())} study hexes, reach {radius_km:.3f} km, "
              f"occupied hexes {occ}")
    features = datasets[CITIES[0]].feature_names
    print(f"features: {features} (source={args.source})")

    t0 = time.time()
    rows = []
    for brand in BRANDS:
        others = tuple(b for b in BRANDS if b != brand)
        rows += evaluate_fold("leave_one_brand_out", datasets, {c: others for c in CITIES},
                              [(c, brand) for c in CITIES], index_weights)
    for city in CITIES:
        train_cities = {c: BRANDS for c in CITIES if c != city}
        rows += evaluate_fold("leave_one_city_out", {c: datasets[c] for c in CITIES}, train_cities,
                              [(city, b) for b in BRANDS], index_weights)
        for brand in BRANDS:
            others = tuple(b for b in BRANDS if b != brand)
            rows += evaluate_fold("leave_brand_and_city_out", datasets, {c: others for c in CITIES if c != city},
                                  [(city, brand)], index_weights)
    results = pd.DataFrame(rows)
    print(f"folds done in {time.time() - t0:.0f}s")

    suffix = "" if args.source == "open" else "_v1"
    results.to_csv(f"reports/revealed_demand_folds{suffix}.csv", index=False)
    summary = pooled(results)
    summary.to_csv(f"reports/revealed_demand_summary{suffix}.csv", index=False)
    with pd.option_context("display.width", 220, "display.max_columns", 20):
        print(summary.round(3).to_string(index=False))
        key = ["random", "demand_index_max_coverage", "competitor_max_coverage", "lightgbm_top_k",
               "spacing+competition_no_features_greedy", "structural_greedy"]
        strict = results[(results["protocol"] == "leave_brand_and_city_out") & results["method"].isin(key)]
        for d in (0.5, 1.5):
            print(f"\nleave-brand-and-city-out, recall within {d} km, per target:")
            print(strict.pivot_table(index=["city", "brand", "k"], columns="method", values=f"recall_{d}km")[key]
                  .round(3).to_string())

    full = fit(datasets, {c: BRANDS for c in CITIES})
    print("\npooled structural fit (all brands, all cities):")
    print(full.coefficients().round(3).to_string(), "| converged", full.converged)
    gaps = pd.concat([label_places(whitespace(full, datasets[c], b, [o for o in BRANDS if o != b], n=10), c, args.source)
                      for c in CITIES for b in BRANDS], ignore_index=True)
    gaps.to_csv(f"reports/revealed_demand_whitespace{suffix}.csv", index=False)
    print("\nwhitespace (top 3 per brand-city; full top 10 in the CSV):")
    print(gaps.groupby(["city", "brand"]).head(3).round(3).to_string(index=False))
    if args.bootstrap:
        t1 = time.time()
        coef = block_bootstrap(datasets, args.bootstrap)
        coef.to_csv(f"reports/revealed_demand_brand_coefficients{suffix}.csv", index=False)
        print(f"\nper-brand coefficients, 90% spatial block-bootstrap intervals ({args.bootstrap} reps, "
              f"{time.time() - t1:.0f}s):")
        print(coef.pivot(index="parameter", columns="brand", values="estimate").round(3).to_string())
        print(coef.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
