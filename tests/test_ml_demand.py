import h3
import numpy as np
import pandas as pd
import pytest

from planner.ml_demand import FEATURE_COLUMNS, assemble_city_frame, leave_one_city_out, naive_mean_baseline

CENTER = {"hyd": (17.4, 78.5), "blr": (12.97, 77.6), "pun": (18.52, 73.85)}


def _synthetic_demand(city: str, n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    lat0, lng0 = CENTER[city]
    cells = list(h3.grid_disk(h3.latlng_to_cell(lat0, lng0, 8), 12))[:n]
    return pd.DataFrame({
        "h3": cells, "population": rng.integers(500, 15000, len(cells)),
        "density_per_km2": rng.integers(500, 20000, len(cells)),
        "office": rng.integers(0, 20, len(cells)), "education": rng.integers(0, 5, len(cells)),
        "food_retail": rng.integers(0, 15, len(cells)), "residential_highrise": rng.integers(0, 30, len(cells)),
        "in_core": rng.integers(0, 2, len(cells)),
    })


def _synthetic_stores(demand: pd.DataFrame, seed: int) -> pd.DataFrame:
    # Stores appear more often in high-population hexes, so a real model should beat the mean baseline.
    rng = np.random.default_rng(seed)
    rows = []
    for _, row in demand.iterrows():
        n_stores = rng.poisson(row["population"] / 4000)
        lat, lng = h3.cell_to_latlng(row["h3"])
        for _ in range(min(n_stores, 6)):
            rows.append({"lat": lat + rng.normal(0, 1e-4), "lng": lng + rng.normal(0, 1e-4)})
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["lat", "lng"])


def _frames():
    return {
        city: assemble_city_frame(city, demand := _synthetic_demand(city, 150, i), _synthetic_stores(demand, i + 100))
        for i, city in enumerate(CENTER)
    }


def test_assemble_city_frame_has_every_feature_and_a_sane_target():
    demand = _synthetic_demand("hyd", 50, 1)
    stores = _synthetic_stores(demand, 1)
    frame = assemble_city_frame("hyd", demand, stores)
    for col in FEATURE_COLUMNS:
        assert col in frame.columns and frame[col].notna().all()
    assert (frame["store_count"] >= 0).all()
    assert np.allclose(frame["log1p_store_count"], np.log1p(frame["store_count"]))
    assert (frame["distance_to_center_km"] >= 0).all()


def test_leave_one_city_out_requires_at_least_two_cities():
    with pytest.raises(ValueError, match="two cities"):
        leave_one_city_out({"only_one": _synthetic_demand("hyd", 10, 1)})


def test_leave_one_city_out_produces_one_result_per_held_out_city_and_ranked_importances():
    frames = _frames()
    results, importances = leave_one_city_out(frames)
    assert {r.held_out_city for r in results} == set(frames)
    for r in results:
        assert r.n_test == len(frames[r.held_out_city])
        assert r.n_train == sum(len(f) for city, f in frames.items() if city != r.held_out_city)
    assert list(importances.index) == sorted(importances.index, key=lambda f: -importances.loc[f, "mean_gain_share"])
    assert set(importances.index) == set(FEATURE_COLUMNS)


def test_model_beats_the_naive_mean_baseline_on_synthetic_signal():
    # Stores were generated FROM population in the synthetic fixture, so a real model must
    # do better than "predict the training mean everywhere" -- this is the honest bar the
    # real three-city run also has to clear, checked here where the ground truth is known.
    frames = _frames()
    model_results, _ = leave_one_city_out(frames)
    baseline_results = naive_mean_baseline(frames)
    model_rmse = {r.held_out_city: r.rmse_log for r in model_results}
    baseline_rmse = {r.held_out_city: r.rmse_log for r in baseline_results}
    better_in = sum(model_rmse[c] < baseline_rmse[c] for c in frames)
    assert better_in >= 2, f"model beat the mean baseline in only {better_in}/3 held-out cities"
