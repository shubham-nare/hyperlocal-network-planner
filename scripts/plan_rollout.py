"""Staged rollout plans under demand uncertainty, and what staging is worth (see src/planner/rollout.py).

For each city (brand = config/network.yaml, i.e. Blinkit, as in v1):

1. Latent orders/day per hex, calibrated exactly as v1's optimize_network.py does (population x
   adoption multiplier, scaled so the hexes the brand already covers carry its disclosed orders),
   on the Overture + Meta HRSL features from build_open_features.py.
2. A Gaussian prior on log demand around that estimate (level + elasticity tilt + spatial field).
3. A paired simulation: many "true" cities drawn from the prior; every policy faces the same ones.
4. The recommended rollout for the real city: wave 1, and wave-2 sites with trigger rules.

    PYTHONPATH=src python scripts/plan_rollout.py [--worlds 100] [--sigmas 0.25 0.5 0.75] [--city pune]

Every number labelled "assumption" below is swept or stated in the write-up; none is sourced.
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import time
from dataclasses import dataclass

import h3
import numpy as np
import pandas as pd

from planner.city_model import CityInputs, city_inputs, load_config
from planner.open_data import label_places
from planner.rollout import (
    build_prior, greedy_plan, most_informative_store, observation_model,
    observe, posterior_mean, posterior_samples, realised_value, screen_candidates, trigger_threshold,
)

CITIES = ("hyderabad", "bengaluru", "pune")


@dataclass(frozen=True)
class Setting:
    max_new: int = 40              # assumption: budget of up to 40 new stores per city over the horizon
    commit_prob: float = 0.9       # assumption: open now only sites that pay back in >= 90% of demand samples
    horizon_days: float = 3 * 365  # assumption: 3-year evaluation horizon, undiscounted
    wave2_day: float = 91          # assumption: 8 weeks of wave-1 data + ~5 weeks to fit out wave 2
    obs_noise: float = 0.2         # assumption: log-sd of an 8-week demand read incl. new-store ramp-up
    sigma_level: float = 0.15      # assumption: city-wide demand level error (log-sd)
    sigma_tilt: float = 0.5        # assumption: weight on v1's elasticity tilt (e=1 vs e=0.5)
    length_km: float = 2.0         # assumption: spatial correlation length of local demand error
    samples: int = 24              # demand samples the planner averages over
    candidates: int = 120          # candidate sites kept after screening


# --------------------------------------------------------------------------------------------
# Policies, simulated against the same worlds
# --------------------------------------------------------------------------------------------

_G: dict = {}   # per-process state for the worker pool (fork start method: inherited, not pickled)


def _prepare(ci: CityInputs, s: Setting, sigma: float, true_sigma: float | None, true_length: float | None, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    prior = build_prior(ci.mu, ci.lat, ci.lng, s.sigma_level, sigma, s.length_km, ci.tilt, s.sigma_tilt)
    truth_prior = prior if true_sigma is None else build_prior(
        ci.mu, ci.lat, ci.lng, s.sigma_level, true_sigma, true_length or s.length_km, ci.tilt, s.sigma_tilt)
    draws = prior.sample(s.samples, rng)
    study = np.flatnonzero(ci.in_study)
    screen = screen_candidates(ci.net, np.exp(prior.sample(16, rng)), list(study), s.candidates)
    point = greedy_plan(ci.net, np.exp(ci.mu), screen, s.max_new, ci.planner_econ, s.horizon_days)
    robust = greedy_plan(ci.net, np.exp(draws), screen, s.max_new, ci.planner_econ, s.horizon_days)
    committed = [p.site for p in robust if p.prob_positive >= s.commit_prob]
    return {"ci": ci, "s": s, "prior": prior, "truth_prior": truth_prior, "draws": draws, "screen": screen,
            "point": [p.site for p in point], "robust": [p.site for p in robust],
            "committed": committed, "deferred": [p.site for p in robust if p.site not in set(committed)],
            "point_plan": point, "robust_plan": robust}


def _world(w: int) -> tuple[list[dict], list[int]]:
    g = _G
    ci, s, prior = g["ci"], g["s"], g["prior"]
    rng = np.random.default_rng(g["seed"] * 100_003 + w)
    truth_x = g["truth_prior"].sample(1, rng)[0]
    truth = np.exp(truth_x)
    econ = ci.econ_scenarios[int(rng.integers(len(ci.econ_scenarios)))]
    remaining = s.horizon_days - s.wave2_day

    def staged(learn: str) -> tuple[list[int], list[int]]:
        w1 = g["committed"]
        if learn == "none":
            return w1, g["deferred"]
        model = observation_model(ci.net, w1, w1, prior.mu, s.obs_noise)
        z = observe(model, truth_x, rng)
        if learn == "robust":
            post = np.exp(posterior_samples(prior, model, z, g["draws"], rng))
        else:
            post = np.exp(posterior_mean(prior, model, z))
        plan = greedy_plan(ci.net, post, g["screen"], s.max_new - len(w1), ci.planner_econ, remaining, base_new=w1)
        return w1, [p.site for p in plan]

    oracle_econ = econ
    policies = {
        "v1_point_all_now": (g["point"], []),
        "robust_all_now": (g["robust"], []),
        "staged_no_learning": staged("none"),
        "staged_point_learning": staged("point"),
        "staged_robust_learning": staged("robust"),
        "oracle_all_now": ([p.site for p in greedy_plan(ci.net, truth, g["screen"], s.max_new, oracle_econ, s.horizon_days)], []),
    }
    rows = []
    for name, (w1, w2) in policies.items():
        out = realised_value(ci.net, truth, econ, w1, w2, s.horizon_days, s.wave2_day)
        rows.append({"world": w, "policy": name, "wave1_sites": len(w1), "wave2_sites": len(w2), **out})
    return rows, policies["staged_robust_learning"][1]


def simulate(ci: CityInputs, s: Setting, sigma: float, worlds: int, seed: int, processes: int,
             true_sigma: float | None = None, true_length: float | None = None) -> tuple[pd.DataFrame, dict, list[list[int]]]:
    _G.clear()
    _G.update(_prepare(ci, s, sigma, true_sigma, true_length, seed))
    _G["seed"] = seed
    with mp.get_context("fork").Pool(processes) as pool:
        results = pool.map(_world, range(worlds))
    rows = [r for rs, _ in results for r in rs]
    wave2 = [w2 for _, w2 in results]
    frame = pd.DataFrame(rows)
    oracle = frame[frame["policy"] == "oracle_all_now"].set_index("world")["value_inr"]
    frame["regret_inr"] = frame["world"].map(oracle) - frame["value_inr"]
    return frame, dict(_G), wave2


def summarise(frame: pd.DataFrame, rng: np.random.Generator, boot: int = 2000) -> pd.DataFrame:
    """Per policy: mean/P10 value, regret, regretted stores; paired gain vs v1's point plan with a
    bootstrap 90% interval over worlds (all policies face the same worlds)."""
    wide = frame.pivot(index="world", columns="policy", values="value_inr")
    rows = []
    for policy, f in frame.groupby("policy"):
        diff = (wide[policy] - wide["v1_point_all_now"]).to_numpy()
        means = [rng.choice(diff, size=len(diff)).mean() for _ in range(boot)]
        rows.append({
            "policy": policy, "mean_value_cr": f["value_inr"].mean() / 1e7, "p10_value_cr": f["value_inr"].quantile(0.1) / 1e7,
            "mean_regret_cr": f["regret_inr"].mean() / 1e7, "mean_stores": f["stores_opened"].mean(),
            "share_value_negative": float((f["value_inr"] < 0).mean()),
            "gain_vs_v1_cr": diff.mean() / 1e7, "gain_ci_low_cr": np.quantile(means, 0.05) / 1e7,
            "gain_ci_high_cr": np.quantile(means, 0.95) / 1e7, "share_worlds_better_than_v1": float((diff > 0).mean()),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------------
# The recommended rollout for the real city
# --------------------------------------------------------------------------------------------

def rollout_plan(ci: CityInputs, g: dict, wave2_draws: list[list[int]], rng: np.random.Generator) -> pd.DataFrame:
    s, prior = g["s"], g["prior"]
    w1_plan = [p for p in g["robust_plan"] if p.site in set(g["committed"])]
    w1 = [p.site for p in w1_plan]
    rows = []
    for k, p in enumerate(w1_plan):
        rows.append({"wave": 1, "rank": k + 1, "cell": p.site, "expected_incremental_orders_per_day": p.expected_incremental_orders,
                     "expected_value_cr": p.expected_value_inr / 1e7, "prob_pays_back": p.prob_positive,
                     "rule": "open now", "trigger_store": "", "trigger_orders_per_day": np.nan,
                     "expected_signal_orders_per_day": np.nan, "wave2_pick_share": np.nan,
                     "mean_stores_when_opened": np.nan, "zone_r7": h3.cell_to_parent(ci.cells[p.site], 7)})
    # Wave 2 is decided by zone (H3 res-7, ~5 km2): sites that fill to capacity are interchangeable, so
    # simulated worlds pick different but equivalent hexes. A zone is listed if wave 2 opens a store in
    # it in >= 20% of worlds; its representative site is the zone's most-picked hex.
    zone_of = {c: h3.cell_to_parent(ci.cells[c], 7) for picks in wave2_draws for c in picks}
    zone_hits: dict[str, int] = {}
    zone_stores: dict[str, int] = {}
    site_counts = pd.Series([c for picks in wave2_draws for c in picks]).value_counts()
    for picks in wave2_draws:
        zones = [zone_of[c] for c in picks]
        for z in set(zones):
            zone_hits[z] = zone_hits.get(z, 0) + 1
            zone_stores[z] = zone_stores.get(z, 0) + zones.count(z)
    model = observation_model(ci.net, w1, w1, prior.mu, s.obs_noise)
    days = s.horizon_days - s.wave2_day
    trigger_draws = prior.sample(48, rng)
    listed = sorted((z for z, n in zone_hits.items() if n / len(wave2_draws) >= 0.2), key=lambda z: -zone_hits[z])
    for rank, zone in enumerate(listed, start=1):
        cell = int(next(c for c in site_counts.index if zone_of[c] == zone))
        k = most_informative_store(prior, model, ci.net, cell)
        thr, rule = trigger_threshold(ci.net, prior, model, trigger_draws, w1, cell, k, ci.planner_econ, days, rng)
        rows.append({"wave": 2, "rank": rank, "cell": cell, "expected_incremental_orders_per_day": np.nan,
                     "expected_value_cr": np.nan, "prob_pays_back": np.nan, "rule": rule,
                     "trigger_store": f"wave-1 #{k + 1}", "trigger_orders_per_day": thr,
                     "expected_signal_orders_per_day": float(model.expected_orders()[k]),
                     "wave2_pick_share": zone_hits[zone] / len(wave2_draws),
                     "mean_stores_when_opened": zone_stores[zone] / zone_hits[zone], "zone_r7": zone})
    plan = pd.DataFrame(rows)
    plan["h3"] = [ci.cells[c] for c in plan["cell"]]
    plan["lat"], plan["lng"] = ci.lat[plan["cell"]], ci.lng[plan["cell"]]
    plan = label_places(plan, ci.city)
    names = {f"wave-1 #{k + 1}": plan.loc[(plan["wave"] == 1) & (plan["rank"] == k + 1), "place"].iloc[0] for k in range(len(w1))}
    plan["trigger_store"] = plan["trigger_store"].map(lambda t: f"{t} ({names[t]})" if t in names else t)
    return plan.drop(columns="cell").assign(city=ci.city)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds", type=int, default=100)
    ap.add_argument("--sigmas", type=float, nargs="+", default=[0.25, 0.5, 0.75])
    ap.add_argument("--city", choices=CITIES)
    ap.add_argument("--processes", type=int, default=mp.cpu_count())
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--skip-misspecified", action="store_true")
    args = ap.parse_args()
    s = Setting()
    cfg = load_config()
    rng = np.random.default_rng(args.seed)
    cities = [args.city] if args.city else list(CITIES)
    summaries, plans, per_world = [], [], []
    for city in cities:
        ci = city_inputs(city, cfg)
        print(f"\n== {city}: {len(ci.cells)} cells ({int(ci.in_study.sum())} in study area), {ci.n_existing} existing "
              f"{cfg['brand']} stores | latent demand {np.exp(ci.mu).sum() - len(ci.mu):,.0f} orders/day | capacity "
              f"{ci.net.capacity:,.0f}/store/day | planner margin INR {ci.planner_econ.margin_per_order:.1f}/order, fixed "
              f"INR {ci.planner_econ.fixed_per_day:,.0f}/day, capex INR {ci.planner_econ.capex / 1e7:.2f} Cr", flush=True)
        configs = [(sig, None, None, f"sigma={sig}") for sig in args.sigmas]
        if not args.skip_misspecified and city == "hyderabad":
            configs.append((0.5, 0.75, 1.0, "misspecified: planner sigma=0.5/2km, truth sigma=0.75/1km"))
        for sig, true_sig, true_len, label in configs:
            t0 = time.time()
            frame, g, wave2 = simulate(ci, s, sig, args.worlds, args.seed, args.processes, true_sig, true_len)
            summ = summarise(frame, rng).assign(city=city, scenario=label, sigma=sig)
            summaries.append(summ)
            per_world.append(frame.assign(city=city, scenario=label))
            print(f"  [{label}] {args.worlds} worlds in {time.time() - t0:.0f}s | point plan {len(g['point'])} sites, "
                  f"robust plan {len(g['robust'])} sites, committed now {len(g['committed'])}, deferred {len(g['deferred'])}")
            with pd.option_context("display.width", 220, "display.max_columns", 20):
                print(summ.drop(columns=["city", "scenario", "sigma"]).round(3).to_string(index=False), flush=True)
            if label == "sigma=0.5":
                plan = rollout_plan(ci, g, wave2, rng)
                plans.append(plan)
                with pd.option_context("display.width", 250, "display.max_columns", 30):
                    print(plan[["wave", "rank", "place", "expected_incremental_orders_per_day", "prob_pays_back",
                                "wave2_pick_share", "mean_stores_when_opened", "rule", "trigger_store", "trigger_orders_per_day",
                                "expected_signal_orders_per_day"]].round(2).to_string(index=False), flush=True)
    suffix = "" if not args.city else f"_{args.city}"
    pd.concat(summaries).to_csv(f"reports/rollout_simulation_summary{suffix}.csv", index=False)
    pd.concat(per_world).to_csv(f"reports/rollout_simulation_worlds{suffix}.csv", index=False)
    if plans:
        pd.concat(plans).to_csv(f"reports/rollout_plan{suffix}.csv", index=False)


if __name__ == "__main__":
    main()
