"""LightGBM store-siting model: a second, genuinely different demand signal.

This is NOT a replacement for the v1/v2 percentile demand index, and it does not predict
"true" customer demand -- no order or revenue data exists in this repository. It predicts
where existing operators physically placed stores (Blinkit/Zepto/Instamart, March 2026
snapshot), learned from public population/POI features. That is a real, standard
site-selection technique (learn from where similar operators already located), but it
carries a real limitation stated plainly here: existing placements reflect each company's
own historical real-estate and strategic choices, which is correlated with genuine demand
but is not identical to it. Feature importances describe what predicts *existing store
placement*, not proven customer demand.

Validation is leave-one-city-out: train on two cities, predict the third's real store
locations, repeat for each holdout city. This is a harder, more honest test than a random
split, and matches how the rest of this project validates against real, held-out things.
"""
from __future__ import annotations

from dataclasses import dataclass

import h3
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error

FEATURE_COLUMNS = (
    "population", "density_per_km2", "office", "education", "food_retail",
    "residential_highrise", "in_core", "distance_to_center_km",
)
TARGET_COLUMN = "log1p_store_count"


def _haversine_km(lat1: np.ndarray, lng1: np.ndarray, lat2: float, lng2: float) -> np.ndarray:
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dlat, dlng = np.radians(lat2 - lat1), np.radians(lng2 - lng1)
    a = np.sin(dlat / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlng / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def assemble_city_frame(city: str, demand: pd.DataFrame, stores: pd.DataFrame) -> pd.DataFrame:
    """Join real per-hex features to a real physical-store-count target for one city.

    ``stores`` must have ``lat``/``lng`` for each real store; the target is how many
    physical stores (any brand) fall in each hex, not how many stores can *reach* it by
    delivery radius -- that reach-based count is what the existing coverage layer already
    predicts deterministically, so using it as an ML target would be circular.
    """
    frame = demand.copy()
    store_hexes = pd.Series([h3.latlng_to_cell(lat, lng, 8) for lat, lng in zip(stores["lat"], stores["lng"])])
    counts = store_hexes.value_counts()
    frame["store_count"] = frame["h3"].map(counts).fillna(0).astype(int)
    frame[TARGET_COLUMN] = np.log1p(frame["store_count"])
    lat_lng = frame["h3"].map(h3.cell_to_latlng)
    frame["lat"] = lat_lng.map(lambda ll: ll[0])
    frame["lng"] = lat_lng.map(lambda ll: ll[1])
    # Population-weighted centroid as a simple, dependency-free "city center" proxy.
    weights = frame["population"].clip(lower=0)
    center_lat = float(np.average(frame["lat"], weights=weights)) if weights.sum() > 0 else float(frame["lat"].mean())
    center_lng = float(np.average(frame["lng"], weights=weights)) if weights.sum() > 0 else float(frame["lng"].mean())
    frame["distance_to_center_km"] = _haversine_km(frame["lat"].to_numpy(), frame["lng"].to_numpy(), center_lat, center_lng)
    frame["in_core"] = frame["in_core"].astype(int)
    frame["city"] = city
    return frame


@dataclass(frozen=True)
class CityFoldResult:
    held_out_city: str
    n_train: int
    n_test: int
    rmse_log: float
    mae_log: float
    r2_log: float
    rmse_count: float
    mae_count: float


def leave_one_city_out(frames: dict[str, pd.DataFrame], params: dict | None = None) -> tuple[list[CityFoldResult], pd.DataFrame]:
    """Train on all cities but one, evaluate on the held-out city's real store locations.

    Returns per-city fold results plus the pooled feature-importance table (mean gain
    across the three fold-specific models, so the reported ranking isn't just one fold's
    idiosyncrasy).
    """
    if len(frames) < 2:
        raise ValueError("need at least two cities to hold one out")
    default_params = {"objective": "regression", "n_estimators": 200, "num_leaves": 15,
                      "min_child_samples": 20, "learning_rate": 0.05, "random_state": 7, "verbosity": -1}
    params = {**default_params, **(params or {})}
    results: list[CityFoldResult] = []
    importances: list[pd.Series] = []
    for held_out in frames:
        train = pd.concat([f for city, f in frames.items() if city != held_out], ignore_index=True)
        test = frames[held_out]
        model = lgb.LGBMRegressor(**params)
        model.fit(train[list(FEATURE_COLUMNS)], train[TARGET_COLUMN])
        pred_log = model.predict(test[list(FEATURE_COLUMNS)])
        pred_count = np.expm1(np.clip(pred_log, 0, None))
        actual_log, actual_count = test[TARGET_COLUMN].to_numpy(), test["store_count"].to_numpy()
        results.append(CityFoldResult(
            held_out_city=held_out, n_train=len(train), n_test=len(test),
            rmse_log=root_mean_squared_error(actual_log, pred_log), mae_log=mean_absolute_error(actual_log, pred_log),
            r2_log=r2_score(actual_log, pred_log), rmse_count=root_mean_squared_error(actual_count, pred_count),
            mae_count=mean_absolute_error(actual_count, pred_count),
        ))
        importances.append(pd.Series(model.feature_importances_, index=FEATURE_COLUMNS, name=held_out))
    importance_table = pd.concat(importances, axis=1)
    importance_table["mean_gain_share"] = importance_table.div(importance_table.sum(axis=0), axis=1).mean(axis=1)
    return results, importance_table.sort_values("mean_gain_share", ascending=False)


def naive_mean_baseline(frames: dict[str, pd.DataFrame]) -> list[CityFoldResult]:
    """Predict the training cities' mean for every held-out hex -- the bar a real model must clear."""
    results = []
    for held_out in frames:
        train = pd.concat([f for city, f in frames.items() if city != held_out], ignore_index=True)
        test = frames[held_out]
        mean_log = train[TARGET_COLUMN].mean()
        pred_log = np.full(len(test), mean_log)
        pred_count = np.expm1(pred_log)
        actual_log, actual_count = test[TARGET_COLUMN].to_numpy(), test["store_count"].to_numpy()
        results.append(CityFoldResult(
            held_out_city=held_out, n_train=len(train), n_test=len(test),
            rmse_log=root_mean_squared_error(actual_log, pred_log), mae_log=mean_absolute_error(actual_log, pred_log),
            r2_log=r2_score(actual_log, pred_log) if len(test) > 1 else float("nan"),
            rmse_count=root_mean_squared_error(actual_count, pred_count), mae_count=mean_absolute_error(actual_count, pred_count),
        ))
    return results
