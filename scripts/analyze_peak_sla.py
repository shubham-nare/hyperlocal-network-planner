"""Peak-hour delivery promise on the real Blinkit networks (see src/planner/peak_sla.py).

For each city: load each existing store with its calibrated served orders (v1's capacitated
assignment), then compare four ways of rostering riders across the day:

- util80:      riders hour by hour at 80% utilisation (the usual rule of thumb)
- erlang95:    riders hour by hour from the queue model, just enough for 95% on-time
- same_budget: util80's rider-hours, re-spread by the queue model to maximise on-time orders

and a network what-if: the rollout plan's wave-1 stores added (reports/rollout_plan.csv).

    PYTHONPATH=src python scripts/analyze_peak_sla.py

Outputs: reports/peak_sla_summary.csv, peak_sla_hourly.csv, peak_sla_rosters.csv,
peak_sla_network_whatif.csv, peak_sla_pooling.csv, peak_sla_hex_{city}.csv.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from planner.city_model import city_inputs, load_config
from planner.open_data import label_places
from planner.peak_sla import (
    DeliveryParams, evaluate, hex_on_time, hourly_profile, staff_budget, staff_erlang, staff_utilisation, store_loads,
    with_orders,
)

CITIES = ("hyderabad", "bengaluru", "pune")
EVENING_SHARES = (0.35, 0.45)   # 0.35: the one public figure found (secondary); 0.45: sensitivity
PEAK_HOUR = 20                  # 8-9 pm, the template's busiest hour
QUIET_HOUR = 15                 # 3-4 pm


def policies(loads, shares, p: DeliveryParams) -> dict[str, np.ndarray]:
    util = staff_utilisation(loads, shares, 0.8)
    return {
        "util80": util,
        "erlang95": staff_erlang(loads, shares, p.on_time_target),
        "same_budget": staff_budget(loads, shares, int(util.sum())),
    }


def at_risk_share(loads, staff, shares, n_cells, hour: int, threshold=0.8) -> float:
    """Share of that hour's orders coming from hexes where fewer than ``threshold`` arrive on time."""
    ok, orders = hex_on_time(loads, staff, shares, hour, n_cells)
    has = orders > 0
    return float(orders[has & (ok < threshold)].sum() / orders[has].sum())


HOUR_BANDS = {"night 0-6": range(0, 7), "day 7-18": range(7, 19), "evening 19-22": range(19, 23), "late 23": range(23, 24)}


def late_breakdown(loads, staff, shares, p: DeliveryParams, radius_km: float, speed_kmph: float) -> dict[str, float]:
    """Late orders/day split by hour band, by how far out the order is, and by store size."""
    out = {f"late_{k}": 0.0 for k in HOUR_BANDS}
    out.update({"late_outer_ring": 0.0, "late_inner": 0.0, "late_small_stores": 0.0, "late_large_stores": 0.0})
    outer_min_slack = (p.promise_min - p.pick_min) - 0.8 * radius_km / (speed_kmph / 60)  # beyond 80% of the radius
    median_orders = np.median([s.orders_per_day for s in loads if s.orders_per_day > 0])
    for i, s in enumerate(loads):
        if s.orders_per_day <= 0:
            continue
        outer = s.slack_min < outer_min_slack
        for h in range(24):
            late = s.weights * shares[h] * (1 - s.hex_on_time(int(staff[i, h]), shares[h]))
            band = next(k for k, r in HOUR_BANDS.items() if h in r)
            out[f"late_{band}"] += late.sum()
            out["late_outer_ring"] += late[outer].sum()
            out["late_inner"] += late[~outer].sum()
            out["late_small_stores" if s.orders_per_day < median_orders else "late_large_stores"] += late.sum()
    return out


def main() -> None:
    cfg = load_config()
    p = DeliveryParams()
    summary, hourly, rosters, whatif, pooling = [], [], [], [], []
    for city in CITIES:
        t0 = time.time()
        ci = city_inputs(city, cfg)
        orders = np.exp(ci.mu) - 1.0                      # v1's calibrated expected orders/day per hex
        flows = ci.net.assignment(orders, lat=ci.lat, lng=ci.lng)
        cells = ci.net.stores()
        loads = store_loads(flows, cells, ci.lat, ci.lng, ci.speed_kmph, p)
        served = sum(s.orders_per_day for s in loads)
        cycles = np.array([s.mean_cycle_min for s in loads if s.orders_per_day > 0])
        print(f"\n== {city}: {len(loads)} Blinkit stores serving {served:,.0f} orders/day | reach {ci.radius_km:.3f} km "
              f"at {ci.speed_kmph} km/h | mean rider cycle {np.median(cycles):.1f} min (median store) "
              f"-> {60 / np.median(cycles):.1f} orders per busy rider-hour", flush=True)

        # robustness: every store at the brand's disclosed average throughput, own distance mix kept
        uniform = [with_orders(s, cfg["orders_per_store_day"]) for s in loads]
        cases = [(ev, "demand map", loads) for ev in EVENING_SHARES] + [(EVENING_SHARES[0], "disclosed average", uniform)]
        for ev, load_model, case_loads in cases:
            shares = hourly_profile(ev)
            main_case = load_model == "demand map"
            for name, staff in policies(case_loads, shares, p).items():
                if not main_case:
                    r = evaluate(case_loads, shares, staff, ci.speed_kmph, p)
                    tot = sum(s.orders_per_day for s in case_loads)
                    summary.append({
                        "city": city, "evening_share": ev, "load_model": load_model, "policy": name, "orders_per_day": tot,
                        "on_time_day": r["on_time_day"], "on_time_evening": r["on_time_evening"],
                        "on_time_8pm": float(r["on_time_by_hour"][PEAK_HOUR]), "late_orders_per_day": r["late_orders_per_day"],
                        "rider_hours_per_day": r["rider_hours"], "rider_hours_per_order": r["rider_hours_per_order"],
                        "rider_cost_inr_per_order": r["rider_hours"] * p.rider_cost_per_hour / tot,
                        "median_reach_km_8pm": float(np.median(r["reach_km_peak"])),
                        "median_reach_km_3pm": float(np.median(r["reach_km_quiet"])),
                        **late_breakdown(case_loads, staff, shares, p, ci.radius_km, ci.speed_kmph),
                    })
                    continue
                r = evaluate(loads, shares, staff, ci.speed_kmph, p)
                summary.append({
                    "city": city, "evening_share": ev, "load_model": load_model, "policy": name, "orders_per_day": served,
                    "on_time_day": r["on_time_day"], "on_time_evening": r["on_time_evening"],
                    "on_time_8pm": float(r["on_time_by_hour"][PEAK_HOUR]), "late_orders_per_day": r["late_orders_per_day"],
                    "rider_hours_per_day": r["rider_hours"], "rider_hours_per_order": r["rider_hours_per_order"],
                    "rider_cost_inr_per_order": r["rider_hours"] * p.rider_cost_per_hour / served,
                    "median_reach_km_8pm": float(np.median(r["reach_km_peak"])),
                    "median_reach_km_3pm": float(np.median(r["reach_km_quiet"])),
                    "share_8pm_orders_in_hexes_below_80pct": at_risk_share(loads, staff, shares, len(ci.cells), PEAK_HOUR),
                    "share_3pm_orders_in_hexes_below_80pct": at_risk_share(loads, staff, shares, len(ci.cells), QUIET_HOUR),
                    **late_breakdown(loads, staff, shares, p, ci.radius_km, ci.speed_kmph),
                })
                hourly += [{"city": city, "evening_share": ev, "policy": name, "hour": h, "share_of_day": shares[h],
                            "on_time": float(r["on_time_by_hour"][h]), "riders": int(staff[:, h].sum())} for h in range(24)]
                if ev == EVENING_SHARES[0] and name == "erlang95":
                    for i, (s, sid) in enumerate(zip(loads, ci.existing_store_ids)):
                        rosters.append({"city": city, "store_id": sid, "h3": ci.cells[s.cell], "lat": ci.lat[s.cell],
                                        "lng": ci.lng[s.cell], "orders_per_day": s.orders_per_day,
                                        "peak_riders": int(staff[i].max()), "rider_hours": int(staff[i].sum()),
                                        **{f"h{h:02d}": int(staff[i, h]) for h in range(24)}})
                        if s.orders_per_day > 0:
                            pooling.append({"city": city, "store_id": sid, "orders_per_day": s.orders_per_day,
                                            "mean_cycle_min": s.mean_cycle_min,
                                            "rider_hours_per_order": staff[i].sum() / s.orders_per_day,
                                            "offered_rider_hours_per_order": s.mean_cycle_min / 60})
                if ev == EVENING_SHARES[0] and name == "util80":
                    ok8, o8 = hex_on_time(loads, staff, shares, PEAK_HOUR, len(ci.cells))
                    ok3, o3 = hex_on_time(loads, staff, shares, QUIET_HOUR, len(ci.cells))
                    pd.DataFrame({"h3": ci.cells, "lat": ci.lat, "lng": ci.lng, "on_time_8pm": ok8, "orders_8pm": o8,
                                  "on_time_3pm": ok3, "orders_3pm": o3}).dropna().to_csv(f"reports/peak_sla_hex_{city}.csv", index=False)

        # network what-if: add the rollout plan's wave-1 stores
        shares = hourly_profile(EVENING_SHARES[0])
        plan = pd.read_csv("reports/rollout_plan.csv")
        index = {c: k for k, c in enumerate(ci.cells)}
        wave1 = [index[h] for h in plan[(plan["city"] == city) & (plan["wave"] == 1)]["h3"] if h in index]
        for label, new in (("current network", []), (f"+ {len(wave1)} wave-1 stores", wave1)):
            fl = ci.net.assignment(orders, new, lat=ci.lat, lng=ci.lng)
            ld = store_loads(fl, ci.net.stores(new), ci.lat, ci.lng, ci.speed_kmph, p)
            tot = sum(s.orders_per_day for s in ld)
            # one-way ride minutes = promise - pick - slack; to km at the calibrated speed
            ride_min = sum(float((p.promise_min - p.pick_min - s.slack_min) @ s.weights) for s in ld if s.orders_per_day > 0)
            trip_km = ride_min / tot * ci.speed_kmph / 60
            row = {"city": city, "network": label, "stores": len(ld), "orders_per_day": tot, "mean_trip_km": trip_km}
            for name in ("util80", "erlang95"):
                staff = staff_utilisation(ld, shares, 0.8) if name == "util80" else staff_erlang(ld, shares, p.on_time_target)
                r = evaluate(ld, shares, staff, ci.speed_kmph, p)
                row[f"{name}_on_time_evening"] = r["on_time_evening"]
                row[f"{name}_rider_hours_per_order"] = r["rider_hours_per_order"]
            whatif.append(row)
        print(f"   done in {time.time() - t0:.0f}s", flush=True)

    out = pd.DataFrame(summary)
    out.to_csv("reports/peak_sla_summary.csv", index=False)
    pd.DataFrame(hourly).to_csv("reports/peak_sla_hourly.csv", index=False)
    ros = pd.DataFrame(rosters)
    label_frames = [label_places(ros[ros["city"] == c], c) for c in CITIES]
    pd.concat(label_frames).to_csv("reports/peak_sla_rosters.csv", index=False)
    pd.DataFrame(whatif).to_csv("reports/peak_sla_network_whatif.csv", index=False)
    pd.DataFrame(pooling).to_csv("reports/peak_sla_pooling.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print("\n" + out.drop(columns=["orders_per_day"]).round(3).to_string(index=False))
        print("\n" + pd.DataFrame(whatif).round(3).to_string(index=False))


if __name__ == "__main__":
    main()
