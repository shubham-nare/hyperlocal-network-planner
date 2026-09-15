"""Store unit economics v0: per-order trend, calibrated store P&L, break-even orders/day per city, sensitivity.

Calibration: fixed cost per store (city rent + other fixed) is an input; variable cost per order is then solved so
the model reproduces Blinkit's disclosed contribution-level cost pool at the disclosed average throughput.
"""
from __future__ import annotations

import itertools

import matplotlib
import numpy as np
import pandas as pd
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from planner.economics import (DAYS_PER_MONTH, Quarter, breakeven_orders_per_day, calibrate_variable_cost,  # noqa: E402
                               daily_rent_inr, derived_rent_cr, per_order, store_contribution_per_day)

CITY_COLORS = {"hyderabad": "#1f77b4", "bengaluru": "#d62728", "pune": "#2ca02c"}


def main() -> None:
    cfg = yaml.safe_load(open("config/economics.yaml", encoding="utf-8"))
    quarters = {k: Quarter(**v) for k, v in cfg["quarters"].items()}

    trend = pd.DataFrame({k: per_order(q) for k, q in quarters.items()}).T.round(1)
    print("Blinkit per-order economics (INR/order; disclosed lines, derived per order):")
    print(trend.to_string())

    names = list(quarters)
    print("\nDerived quick-commerce rent (segment result - Adjusted EBITDA):")
    for i, (name, q) in enumerate(quarters.items()):
        if q.segment_result_cr is None or i == 0:
            continue
        avg_stores = (quarters[names[i - 1]].stores_end + q.stores_end) / 2
        rent = derived_rent_cr(q)
        per_store_month = rent * 1e7 / avg_stores / 3
        print(f"  {name}: INR {rent:,.0f} Cr | avg stores {avg_stores:,.0f} | INR {per_store_month / 1e5:.2f} lakh/store/month "
              f"(incl. warehouses) | INR {rent * 1e7 / (q.orders_mn * 1e6):.1f}/order")

    cal_name = cfg["calibration_quarter"]
    cal_q = quarters[cal_name]
    cal = per_order(cal_q)
    prev_stores = quarters[names[names.index(cal_name) - 1]].stores_end
    rent_nat_day = derived_rent_cr(cal_q) * 1e7 / ((prev_stores + cal_q.stores_end) / 2) / (3 * DAYS_PER_MONTH)
    other_fixed = cfg["store"]["other_fixed_cost_per_day_inr"]
    fixed_nat = rent_nat_day + other_fixed
    variable = calibrate_variable_cost(cal["contribution_costs"], fixed_nat, cal["orders_per_store_day"])
    gp = cal["gross_profit"]
    print(f"\nCalibration ({cal_name}): throughput {cal['orders_per_store_day']:,.0f} orders/day | cost pool INR "
          f"{cal['contribution_costs']:.1f}/order | fixed INR {fixed_nat:,.0f}/day (derived rent {rent_nat_day:,.0f} + "
          f"assumed other {other_fixed:,}) -> variable INR {variable:.1f}/order | unit margin INR {gp - variable:.1f}/order")
    steady_orders = cfg["steady_state"]["nov_per_store_day_inr"] / cal["naov"]
    print(f"Steady-state guidance INR {cfg['steady_state']['nov_per_store_day_inr']:,}/day -> {steady_orders:,.0f} orders/day "
          f"at current NAOV")

    size = cfg["store"]["size_sqft"]
    print(f"\nBreak-even (store contribution = 0), {size:,} sq ft store:")
    rows = []
    for city, c in cfg["cities"].items():
        lo, hi = c["rent_range"]
        be = {label: breakeven_orders_per_day(gp, variable, daily_rent_inr(size, r) + other_fixed)
              for label, r in (("low", lo), ("mid", c["rent_per_sqft_month_inr"]), ("high", hi))}
        fixed_mid = daily_rent_inr(size, c["rent_per_sqft_month_inr"]) + other_fixed
        at_avg = store_contribution_per_day(cal["orders_per_store_day"], gp, variable, fixed_mid)
        print(f"  {city}: {be['mid']:,.0f} orders/day (rent range {be['low']:,.0f}-{be['high']:,.0f}) | "
              f"{be['mid'] / cal['orders_per_store_day']:.0%} of national avg throughput | "
              f"contribution at avg throughput INR {at_avg / 1e5 * DAYS_PER_MONTH:.1f} lakh/month")

        s = cfg["sensitivity"]
        for sqft, other, shift in itertools.product(s["size_sqft"], s["other_fixed_cost_per_day_inr"], s["variable_cost_shift_inr"]):
            for rent_label, rent in (("low", lo), ("mid", c["rent_per_sqft_month_inr"]), ("high", hi)):
                fixed = daily_rent_inr(sqft, rent) + other
                # Re-calibrate for each other-fixed assumption so every scenario still reproduces the disclosed cost pool.
                v = calibrate_variable_cost(cal["contribution_costs"], rent_nat_day + other, cal["orders_per_store_day"]) + shift
                rows.append({"city": city, "size_sqft": sqft, "rent_case": rent_label, "rent_per_sqft_month_inr": rent,
                             "other_fixed_cost_per_day_inr": other, "variable_cost_shift_inr": shift,
                             "fixed_cost_per_day_inr": round(fixed), "variable_cost_per_order_inr": round(v, 1),
                             "breakeven_orders_per_day": round(breakeven_orders_per_day(gp, v, fixed))})
    sens = pd.DataFrame(rows)
    out_csv = "reports/unit_economics_sensitivity.csv"
    sens.to_csv(out_csv, index=False)
    for city in cfg["cities"]:
        sc = sens[sens["city"] == city]
        print(f"  {city}: break-even across {len(sc)} scenarios {sc['breakeven_orders_per_day'].min():,}-"
              f"{sc['breakeven_orders_per_day'].max():,} (median {sc['breakeven_orders_per_day'].median():,.0f})")
    base = sens[(sens["size_sqft"] == size) & (sens["rent_case"] == "mid")]
    print("\nBreak-even orders/day, mid rent, by other-fixed cost (rows) x variable-cost shift (cols):")
    for city in cfg["cities"]:
        pivot = base[base["city"] == city].pivot(index="other_fixed_cost_per_day_inr", columns="variable_cost_shift_inr",
                                                 values="breakeven_orders_per_day")
        print(f"  {city}\n{pivot.to_string()}")

    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.linspace(0, 2600, 200)
    for city, c in cfg["cities"].items():
        fixed = daily_rent_inr(size, c["rent_per_sqft_month_inr"]) + other_fixed
        # Dashed so a city with identical inputs (Pune = Hyderabad rent) doesn't hide the line beneath it.
        ax.plot(x, store_contribution_per_day(x, gp, variable, fixed) * DAYS_PER_MONTH / 1e5, color=CITY_COLORS[city],
                linestyle="--" if city == "pune" else "-",
                label=f"{city.title()} (break-even {breakeven_orders_per_day(gp, variable, fixed):,.0f})")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.axvline(cal["orders_per_store_day"], color="grey", linestyle="--", linewidth=1)
    ax.text(cal["orders_per_store_day"], ax.get_ylim()[1] * 0.9, f" {cal_name} avg", color="grey", fontsize=8)
    ax.axvline(steady_orders, color="grey", linestyle=":", linewidth=1)
    ax.text(steady_orders, ax.get_ylim()[1] * 0.8, " steady-state guidance", color="grey", fontsize=8)
    ax.set_xlabel("Orders per day per store")
    ax.set_ylabel("Store contribution (INR lakh / month)")
    ax.set_title(f"Dark-store contribution vs throughput ({size:,} sq ft, mid rent; calibrated to Blinkit {cal_name})")
    ax.legend(fontsize=8)
    png = "reports/unit_economics_breakeven.png"
    fig.savefig(png, dpi=130, bbox_inches="tight")
    print(f"\n-> {out_csv} ({len(sens)} rows) | {png}")


if __name__ == "__main__":
    main()
