import math

import pytest

from planner.economics import (DAYS_PER_MONTH, Quarter, breakeven_orders_per_day, calibrate_variable_cost,
                               daily_rent_inr, derived_rent_cr, per_order, store_contribution_per_day)

Q1FY27 = Quarter(nov_cr=17132, gross_profit_cr=4710, contribution_cr=907, adjusted_ebitda_cr=102, orders_mn=331.0,
                 nov_per_store_day_inr=827000, stores_end=2443, segment_result_cr=365)


def test_per_order_matches_disclosed_naov_and_chains_cost_pools():
    p = per_order(Q1FY27)
    assert p["naov"] == pytest.approx(518, abs=0.5)
    assert p["gross_profit"] - p["contribution_costs"] == pytest.approx(p["contribution"])
    assert p["contribution"] - p["overhead"] == pytest.approx(p["adjusted_ebitda"])
    assert p["orders_per_store_day"] == pytest.approx(827000 / p["naov"])


def test_derived_rent_is_segment_result_minus_adjusted_ebitda():
    assert derived_rent_cr(Q1FY27) == 263
    with pytest.raises(ValueError):
        derived_rent_cr(Quarter(1, 1, 1, 1, 1, 1, 1))


def test_daily_rent():
    assert daily_rent_inr(4000, 90) == pytest.approx(360000 / DAYS_PER_MONTH)


def test_calibration_reproduces_disclosed_contribution_at_disclosed_throughput():
    p = per_order(Q1FY27)
    orders, fixed = p["orders_per_store_day"], 20000
    variable = calibrate_variable_cost(p["contribution_costs"], fixed, orders)
    got = store_contribution_per_day(orders, p["gross_profit"], variable, fixed)
    assert got == pytest.approx(orders * p["contribution"])


def test_calibration_rejects_fixed_costs_above_cost_pool():
    with pytest.raises(ValueError):
        calibrate_variable_cost(100, fixed_cost_per_day=200_000, orders_per_day=1000)


def test_breakeven_zeroes_contribution():
    be = breakeven_orders_per_day(142, 100, 21000)
    assert be == pytest.approx(500)
    assert store_contribution_per_day(be, 142, 100, 21000) == pytest.approx(0, abs=1e-6)


def test_breakeven_is_infinite_without_unit_margin():
    assert math.isinf(breakeven_orders_per_day(100, 100, 1000))
    assert math.isinf(breakeven_orders_per_day(90, 100, 1000))
