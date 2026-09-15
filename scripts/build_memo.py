"""Expansion memo per city (markdown) from the optimiser, scenario and hold-out outputs in reports/."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from planner.coverage import nearest_store_km
from planner.reach import haversine_m

SCENARIOS = {"e0": "Adoption elasticity 0 (population only)", "e1": "Adoption elasticity 1 (fully POI-driven)",
             "g15": "Demand growth x1.5", "cap1600": "Store capacity 1,600 orders/day",
             "cap3000": "Store capacity 3,000 orders/day"}
ROBUST_KM = 1.0


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def robust_areas(runs: dict[str, pd.DataFrame], km: float) -> pd.DataFrame:
    """Group proposed sites from all runs into areas (greedy, strongest site first) and count runs per area.

    Individual picks swap between near-equal hexes run to run, so recurrence across scenarios is the stable signal.
    """
    pts = pd.concat([df.assign(run=tag) for tag, df in runs.items()], ignore_index=True)
    centres: list[tuple[float, float]] = []
    area = pd.Series(-1, index=pts.index)
    for i, r in pts.sort_values("incremental_orders_per_day", ascending=False).iterrows():
        dists = [haversine_m(r["lat"], r["lng"], la, ln) / 1000 for la, ln in centres]
        if dists and min(dists) <= km:
            area[i] = int(np.argmin(dists))
        else:
            centres.append((r["lat"], r["lng"]))
            area[i] = len(centres) - 1
    pts["area"] = area
    g = pts.groupby("area").agg(
        runs=("run", "nunique"), locality=("locality", lambda s: s.str.title().mode().iat[0]),
        pincode=("pincode", lambda s: s.mode().iat[0]), lat=("lat", "median"), lng=("lng", "median"),
        median_incremental=("incremental_orders_per_day", "median"), new_cov=("new_coverage_orders", "sum"),
        site_orders=("site_orders_per_day", "sum"), competitors=("competitor_stores_reaching_hex", "median"))
    g["new_coverage_share"] = g["new_cov"] / g["site_orders"]
    return g.sort_values(["runs", "median_incremental"], ascending=False).reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="hyderabad")
    args = parser.parse_args()
    city = args.city
    base = pd.read_csv(f"reports/network_{city}_base.csv")

    robust = np.zeros(len(base), dtype=int)
    scen_rows = []
    runs = {"base": base}
    for tag, label in SCENARIOS.items():
        path = Path(f"reports/network_{city}_{tag}.csv")
        if not path.exists():
            continue
        s = pd.read_csv(path)
        runs[tag] = s
        d = nearest_store_km(base["lat"].to_numpy(), base["lng"].to_numpy(), s["lat"].to_numpy(), s["lng"].to_numpy())
        robust += d <= ROBUST_KM
        scen_rows.append({"Scenario": label, "Incremental orders/day (top 10)": f"{s['incremental_orders_per_day'].sum():,}",
                          f"Base sites kept within {ROBUST_KM:g} km": f"{int((d <= ROBUST_KM).sum())}/{len(base)}"})
    n_scen = len(scen_rows)

    table = base.assign(
        Site=base["rank"], Locality=base["locality"].str.title(), Pincode=base["pincode"],
        **{"Lat, Lng": base["lat"].map("{:.5f}".format) + ", " + base["lng"].map("{:.5f}".format),
           "Incremental orders/day": base["incremental_orders_per_day"].map("{:,}".format),
           "New coverage / capacity relief": base["new_coverage_orders"].map("{:,}".format) + " / "
           + base["capacity_relief_orders"].map("{:,}".format),
           "Competitor stores reaching": base["competitor_stores_reaching_hex"],
           "Robust (scenarios)": [f"{r}/{n_scen}" for r in robust]},
    )[["Site", "Locality", "Pincode", "Lat, Lng", "Incremental orders/day", "New coverage / capacity relief",
       "Competitor stores reaching", "Robust (scenarios)"]]

    n_runs = len(runs)
    core_min = max(2, round(n_runs * 2 / 3))
    areas = robust_areas(runs, ROBUST_KM)
    core = areas[areas["runs"] >= core_min]
    curve_path = Path(f"reports/network_{city}_base_curve.csv")
    total_line = ""
    if curve_path.exists():
        curve = pd.read_csv(curve_path).set_index("max_new_sites")
        if 10 in curve.index:
            total_line = (f"- Under the base scenario, 10 new sites add **{curve.loc[10, 'incremental_orders_per_day']:,} "
                          f"orders/day**, lifting served demand from {curve.loc[0, 'served_share']:.1%} to "
                          f"{curve.loc[10, 'served_share']:.1%}.")

    parts = [f"# {city.title()}: where Blinkit should open its next 10 dark stores (memo v1)", ""]
    core_list = ", ".join(f"**{r.locality}** ({r.pincode})" for r in core.itertuples()) or "none"
    parts += ["## Answer", "",
              f"- **Core picks** (proposed in at least {core_min} of {n_runs} model runs across scenarios): {core_list}.",
              *([total_line] if total_line else []),
              f"- In that base solution, {base['new_coverage_orders'].sum():,} site orders/day come from areas no Blinkit "
              f"store reaches today and {base['capacity_relief_orders'].sum():,} relieve stores already at capacity.",
              "- Picks outside the core move with assumptions (store capacity above all). Treat them as areas to scout, "
              "not addresses.", ""]
    shown = areas[areas["runs"] >= 2].head(15)
    area_table = pd.DataFrame({
        "Area": shown["locality"], "Pincode": shown["pincode"],
        "Lat, Lng": shown["lat"].map("{:.4f}".format) + ", " + shown["lng"].map("{:.4f}".format),
        "Runs proposing it": shown["runs"].map(lambda r: f"{r}/{n_runs}"),
        "Median incremental orders/day": shown["median_incremental"].map("{:,.0f}".format),
        "New-coverage share": shown["new_coverage_share"].map("{:.0%}".format),
        "Competitor stores (median)": shown["competitors"].map("{:g}".format)})
    parts += [f"## Robust areas (sites within {ROBUST_KM:g} km grouped across all {n_runs} runs)", "", md_table(area_table), ""]
    parts += ["## Base-scenario solution (10 sites)", "", md_table(table), "",
              f"Robust = number of alternative scenarios that still place a site within {ROBUST_KM:g} km.", ""]
    if scen_rows:
        parts += ["## Scenarios", "", md_table(pd.DataFrame(scen_rows)), ""]

    hv = Path(f"reports/holdout_validation_{city}.csv")
    if not hv.exists():
        hv = Path("reports/holdout_validation.csv")
    if hv.exists():
        v = pd.read_csv(hv)
        v = v[(v["city"] == city) & (v["within_km"] == 1.5)]
        if len(v):
            summ = v.groupby("method")[["recall", "precision", "median_km_true_to_pred"]].mean()
            summ = summ.sort_values("recall", ascending=False).reset_index()
            summ["recall"] = summ["recall"].map("{:.0%}".format)
            summ["precision"] = summ["precision"].map("{:.0%}".format)
            summ["median_km_true_to_pred"] = summ["median_km_true_to_pred"].map("{:.2f}".format)
            parts += ["## Does the model find where Blinkit actually builds? (hold-out validation)", "",
                      "20% of real Blinkit stores are hidden, 5 times; each method proposes the same number of sites. "
                      "Recall = hidden stores with a proposed site within 1.5 km.", "", md_table(summ), ""]

    parts += ["## Method (one paragraph)", "",
              "Latent orders/day per H3 hex = population × a POI-based adoption multiplier, calibrated so hexes Blinkit "
              "covers today carry its disclosed throughput (Eternal Q4 FY26: 1,462 orders/day/store; snapshot store "
              "completeness 87%). A capacitated maximal-covering model (PuLP/CBC) keeps existing stores open, adds up "
              "to N sites that must clear the city's break-even orders/day (Week 3 unit economics), and lets hex demand "
              "split across any store within the calibrated 10-minute radius. Per-site gains are leave-one-out.", ""]
    parts += ["## Caveats", "",
              "- Store locations are a third-party March 2026 snapshot (unlicensed, ~87% complete); some 'capacity "
              "relief' may be stores missing from it.",
              "- One national capacity and throughput for every store; no city-specific order value or margins.",
              "- Adoption multiplier weights are assumptions (swept in Scenarios); OpenStreetMap POI coverage varies by area.",
              "- Competitor share is not modelled in demand; competitor presence is shown for context only.", "",
              f"![Map](network_{city}_base.png)", ""]
    out = f"reports/expansion_memo_{city}.md"
    Path(out).write_text("\n".join(parts), encoding="utf-8")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
