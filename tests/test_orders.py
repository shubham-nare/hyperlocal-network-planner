import pandas as pd
import pytest

from planner.orders import adoption_index, adoption_multiplier, calibrate_orders_per_weight, order_weights

IDX = pd.Series([10.0, 30.0, 80.0])
POP = pd.Series([1000.0, 2000.0, 3000.0])


def test_multiplier_has_city_mean_one_and_spans_population_to_proportional():
    for e in (0.0, 0.5, 1.0):
        assert adoption_multiplier(IDX, e).mean() == pytest.approx(1.0)
    assert (adoption_multiplier(IDX, 0.0) == 1.0).all()
    assert adoption_multiplier(IDX, 1.0).tolist() == pytest.approx((IDX / IDX.mean()).tolist())
    with pytest.raises(ValueError):
        adoption_multiplier(IDX, 1.5)


def test_order_weights_scale_population():
    assert order_weights(POP, IDX, 0.0).tolist() == POP.tolist()


def test_calibration_puts_all_brand_orders_on_served_hexes():
    weights = order_weights(POP, IDX, 0.5)
    served = pd.Series([True, True, False])
    rate = calibrate_orders_per_weight(weights, served, observed_stores=9, snapshot_completeness=0.9,
                                       orders_per_store_day=1500)
    assert (weights[served] * rate).sum() == pytest.approx(9 / 0.9 * 1500)


def test_calibration_rejects_bad_inputs():
    served = pd.Series([False, False, False])
    with pytest.raises(ValueError):
        calibrate_orders_per_weight(POP, served, 5, 0.9, 1500)
    with pytest.raises(ValueError):
        calibrate_orders_per_weight(POP, ~served, 5, 0.0, 1500)


def test_adoption_index_is_weighted_mean_of_percentiles_and_rejects_density():
    hexes = pd.DataFrame({"office_pct": [0.0, 1.0], "food_retail_pct": [1.0, 0.5]})
    got = adoption_index(hexes, {"office": 0.1, "food_retail": 0.3})
    assert got.tolist() == pytest.approx([75.0, 62.5])
    with pytest.raises(ValueError):
        adoption_index(hexes.assign(density_per_km2_pct=0.5), {"density_per_km2": 0.5, "office": 0.5})


def test_adoption_index_rejects_missing_columns():
    hexes = pd.DataFrame({"office_pct": [0.0, 1.0]})
    with pytest.raises(ValueError, match="missing required columns"):
        adoption_index(hexes, {"office": 0.1, "food_retail": 0.3})

