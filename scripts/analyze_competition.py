"""Competitor-response game on each city (see src/planner/competition.py).

Leader = config/network.yaml's brand (Blinkit); followers = Zepto and Swiggy Instamart, responding in
that order. For each city:

1. Market: every brand's real stores (darkstores snapshot), Huff shares across brands, category
   demand calibrated so the leader's share reproduces v1's calibrated orders.
2. Follower models: rational (maximise own served orders) and behavioural (each brand's revealed-
   demand model, fitted on all three cities).
3. Leader plans (k new stores): naive (competitors frozen), aware of rational followers, aware of
   behavioural followers.
4. Every plan scored under every follower model, as the *increment* over the leader doing nothing
   while competitors still expand: V_R(P) = leader(P + R(P)) - leader(nothing + R(nothing)).

    PYTHONPATH=src python scripts/analyze_competition.py [--k 10] [--beta 2.0] [--followers-per 10]
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import time

import h3
import numpy as np
import pandas as pd

from planner.city_model import city_inputs, load_config
from planner.competition import (
    Market, behavioural_response, calibrate_category_demand, huff_weights, leader_plan, rational_response, regret_table,
    screen, sequential_response,
)
from planner.open_data import label_places
from planner.revealed_demand import COUNT_COLUMNS, build_city_data, feature_columns, fit, haversine_km, load_features

CITIES = ("hyderabad", "bengaluru", "pune")
BRANDS = ("Blinkit", "Zepto", "Swiggy Instamart")
HORIZON_DAYS = 3 * 365


def fit_behavioural_models(cfg: dict) -> tuple[dict, dict]:
    datasets = {}
    d = cfg["cities"]["defaults"]
    from planner.reach import ride_budget_m
    for city in CITIES:
        feats = load_features(city, "open")
        radius = ride_budget_m(d["delivery_promise_min"], d["picking_time_min"],
                               cfg["cities"]["cities"][city]["reach_speed_kmph"]["radius"]) / 1000
        datasets[city] = build_city_data(city, feats, cfg["stores"], radius, feature_columns(feats), COUNT_COLUMNS, BRANDS)
    models = {b: fit(datasets, {c: (b,) for c in CITIES}, {c: BRANDS for c in CITIES}) for b in BRANDS}
    return datasets, models


def run_city(args: tuple) -> dict:
    city, k, beta, per_follower, cfg, data, models = args
    t0 = time.time()
    ci = city_inputs(city, cfg)
    index = {c: i for i, c in enumerate(ci.cells)}
    assert list(data.cells) == ci.cells, "revealed-demand cells must match city_model cells"
    existing = {}
    for b in BRANDS:
        own = cfg["stores"][cfg["stores"]["brand"] == b]
        existing[b] = np.array([index[c] for c in (h3.latlng_to_cell(a, g, 8) for a, g in zip(own["lat"], own["lng"]))
                                if c in index], dtype=int)
    weights = huff_weights(ci.lat, ci.lng, ci.net.reach, beta)
    orders = np.exp(ci.mu) - 1.0
    probe = Market(ci.net.reach, weights, existing, orders, ci.net.capacity)
    shares0 = probe.shares()
    demand = calibrate_category_demand(orders, shares0[BRANDS[0]])
    market = Market(ci.net.reach, weights, existing, demand, ci.net.capacity)
    check = market.served(BRANDS[0]) - ci.net.served(orders)

    leader, followers = BRANDS[0], list(BRANDS[1:])
    study = [int(i) for i in np.flatnonzero(ci.in_study)]
    lead_c = screen(market, leader, study, 40)
    fol_c = {f: screen(market, f, study, 60) for f in followers}
    responses = {
        "frozen": None,
        "rational": sequential_response(followers, lambda f, st: rational_response(market, f, per_follower, fol_c[f], st)),
        "behavioural": sequential_response(followers, lambda f, st: behavioural_response(data, models[f], f, per_follower,
                                                                                         BRANDS, st)),
    }
    plans = {
        "naive": leader_plan(market, leader, lead_c, k),
        "aware_rational": leader_plan(market, leader, lead_c, k, responses["rational"]),
        "aware_behavioural": leader_plan(market, leader, lead_c, k, responses["behavioural"]),
    }
    t_plans = time.time() - t0

    margin = ci.planner_econ.margin_per_order
    rows, sites = [], []
    for rname, resp in responses.items():
        reply0 = resp({leader: []}) if resp else {}
        base = market.served_all(reply0)
        for pname, plan in plans.items():
            mine = [p.site for p in plan]
            reply = resp({leader: mine}) if resp else {}
            after = market.served_all({leader: mine, **reply})
            inc = after[leader] - base[leader]
            # pre-emption: how many of the leader's sites sit on a spot followers would otherwise have taken
            taken0 = [c for picks in reply0.values() for c in picks]
            preempt = sum(bool(taken0) and haversine_km(ci.lat[s], ci.lng[s], ci.lat[taken0], ci.lng[taken0]).min() <= 1.0
                          for s in mine)
            near_rivals = sum(int(any(haversine_km(ci.lat[s], ci.lng[s], ci.lat[c], ci.lng[c]) <= ci.radius_km
                                      for picks in reply.values() for c in picks)) for s in mine)
            rows.append({"city": city, "follower_model": rname, "plan": pname, "leader_sites": len(mine),
                         "leader_incremental_orders": inc, "leader_incremental_value_cr": inc * margin * HORIZON_DAYS / 1e7,
                         "followers_orders_change": sum(after[f] - base[f] for f in followers),
                         "leader_share_of_served": after[leader] / sum(after.values()),
                         "sites_preempting_rivals": preempt, "sites_with_rival_entry_in_reach": near_rivals})
            if rname == "frozen" or rname == pname.replace("aware_", ""):
                for rank, s in enumerate(mine, start=1):
                    sites.append({"city": city, "plan": pname, "rank": rank, "h3": ci.cells[s], "lat": ci.lat[s], "lng": ci.lng[s],
                                  "rival_stores_in_reach_now": int(sum((np.asarray(market.reach[s].toarray()).ravel()[existing[f]] > 0).sum()
                                                                       for f in followers)),
                                  "leader_share_in_own_hex_now": float(shares0[leader][s])})
    print(f"  {city}: plans in {t_plans:.0f}s, calibration check {check:+.2f} orders/day", flush=True)
    return {"rows": rows, "sites": sites}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--followers-per", type=int, default=10)
    ap.add_argument("--beta", type=float, default=2.0)
    ap.add_argument("--city", choices=CITIES)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()
    cfg = load_config()
    t0 = time.time()
    datasets, models = fit_behavioural_models(cfg)
    for b, m in models.items():
        print(f"behavioural model {b}: gamma {m.gamma:.2f}, lambda {m.lam:.2f} (converged {m.converged})")
    print(f"fitted in {time.time() - t0:.0f}s")
    cities = [args.city] if args.city else list(CITIES)
    jobs = [(c, args.k, args.beta, args.followers_per, cfg, datasets[c], models) for c in cities]
    with mp.get_context("fork").Pool(min(len(jobs), mp.cpu_count())) as pool:
        results = pool.map(run_city, jobs)
    rows = pd.DataFrame([r for res in results for r in res["rows"]])
    sites = pd.DataFrame([s for res in results for s in res["sites"]])
    sites = pd.concat([label_places(sites[sites["city"] == c], c) for c in cities])
    tag = args.tag
    rows.to_csv(f"reports/competition_summary{tag}.csv", index=False)
    regret = []
    for city, g in rows.groupby("city"):
        values = {p: dict(zip(f["follower_model"], f["leader_incremental_orders"])) for p, f in g.groupby("plan")}
        for plan, r in regret_table(values).items():
            regret.append({"city": city, "plan": plan, **{f"regret_{k}": v for k, v in r.items()}})
    regret = pd.DataFrame(regret)
    regret.to_csv(f"reports/competition_regret{tag}.csv", index=False)
    sites.to_csv(f"reports/competition_sites{tag}.csv", index=False)
    with pd.option_context("display.width", 250, "display.max_columns", 20):
        print(rows.round(3).to_string(index=False))
        print(regret.round(0).to_string(index=False))


if __name__ == "__main__":
    main()
