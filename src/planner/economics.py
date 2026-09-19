"""Dark-store unit economics calibrated to Blinkit's disclosed per-order economics.

Eternal's Contribution already deducts actual store and warehouse rent (before Ind AS 116), last mile, packaging,
subsidies etc., so the store P&L here stops at contribution and never subtracts rent a second time.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

CRORE = 1e7
MILLION = 1e6
DAYS_PER_MONTH = 365 / 12


@dataclass(frozen=True)
class Quarter:
    nov_cr: float
    gross_profit_cr: float
    contribution_cr: float
    adjusted_ebitda_cr: float
    orders_mn: float
    nov_per_store_day_inr: float
    stores_end: int
    segment_result_cr: float | None = None


def per_order(q: Quarter) -> dict[str, float]:
    """INR per order for each disclosed line, plus the cost pools between them and implied orders/day per store."""
    orders = q.orders_mn * MILLION
    naov = q.nov_cr * CRORE / orders
    gross_profit = q.gross_profit_cr * CRORE / orders
    contribution = q.contribution_cr * CRORE / orders
    ebitda = q.adjusted_ebitda_cr * CRORE / orders
    return {
        "naov": naov,
        "gross_profit": gross_profit,
        "contribution_costs": gross_profit - contribution,
        "contribution": contribution,
        "overhead": contribution - ebitda,
        "adjusted_ebitda": ebitda,
        "orders_per_store_day": q.nov_per_store_day_inr / naov,
    }


def derived_rent_cr(q: Quarter) -> float:
    """Ind AS 116 rent paid by the segment: segment result (= EBITDA + SBP) minus Adjusted EBITDA (= EBITDA + SBP - rent)."""
    if q.segment_result_cr is None:
        raise ValueError("segment result not disclosed for this quarter")
    return q.segment_result_cr - q.adjusted_ebitda_cr


def daily_rent_inr(size_sqft: float, rent_per_sqft_month_inr: float) -> float:
    return size_sqft * rent_per_sqft_month_inr / DAYS_PER_MONTH


def calibrate_variable_cost(contribution_costs_per_order: float, fixed_cost_per_day: float, orders_per_day: float) -> float:
    """Variable cost per order that makes fixed + variable reproduce the disclosed cost pool at the disclosed throughput."""
    variable = contribution_costs_per_order - fixed_cost_per_day / orders_per_day
    if variable < 0:
        raise ValueError("fixed costs exceed the disclosed contribution cost pool at this throughput")
    return variable


def store_contribution_per_day(orders: float, gross_profit_per_order: float, variable_cost_per_order: float,
                               fixed_cost_per_day: float) -> float:
    return orders * (gross_profit_per_order - variable_cost_per_order) - fixed_cost_per_day


def breakeven_orders_per_day(gross_profit_per_order: float, variable_cost_per_order: float, fixed_cost_per_day: float) -> float:
    """Orders/day at which store contribution is zero; inf when each order loses money before fixed costs."""
    unit_margin = gross_profit_per_order - variable_cost_per_order
    return math.inf if unit_margin <= 0 else fixed_cost_per_day / unit_margin


def calibrated_national_economics(econ: dict) -> dict[str, float]:
    """Derive gross-profit and variable-cost per order from config/economics.yaml.

    Single source of truth for this derivation: derive the national average rent/day from
    disclosed segment results, then solve for the variable cost that makes fixed + variable
    reproduce the disclosed contribution-cost pool at the disclosed throughput. Using
    ``contribution_costs`` directly as "variable cost" double-counts rent, since Contribution
    already deducts it -- the exact bug this function exists to make impossible to repeat in a
    second caller (build_unit_economics.py's own calibration is the original; build_scenarios.py
    and the API both call this instead of re-deriving it).
    """
    quarter_names = list(econ["quarters"])
    cal_name = econ["calibration_quarter"]
    cal_q = Quarter(**econ["quarters"][cal_name])
    prev_q = Quarter(**econ["quarters"][quarter_names[quarter_names.index(cal_name) - 1]])
    calib = per_order(cal_q)
    other_fixed = econ["store"]["other_fixed_cost_per_day_inr"]
    rent_nat_day = derived_rent_cr(cal_q) * CRORE / ((prev_q.stores_end + cal_q.stores_end) / 2) / (3 * DAYS_PER_MONTH)
    variable_cost_per_order = calibrate_variable_cost(calib["contribution_costs"], rent_nat_day + other_fixed, calib["orders_per_store_day"])
    return {
        "gross_profit_per_order": calib["gross_profit"],
        "variable_cost_per_order": variable_cost_per_order,
        "other_fixed_cost_per_day": other_fixed,
    }
