import heapq

import h3
import numpy as np
import pytest
from scipy import sparse

from planner.peak_sla import (
    EVENING, DeliveryParams, erlang_c, evaluate, hex_on_time, hourly_profile, min_riders, staff_budget, staff_erlang,
    staff_utilisation, store_loads, wait_quantile, wait_tail, with_orders,
)


def test_erlang_c_known_values():
    assert erlang_c(1, 0.6) == pytest.approx(0.6)          # M/M/1: P(wait) = utilisation
    assert erlang_c(2, 1.0) == pytest.approx(1 / 3)
    assert erlang_c(5, 5.0) == 1.0                         # unstable
    assert erlang_c(3, 0.0) == 0.0
    # more servers at the same load always means less waiting
    assert erlang_c(60, 50.0) < erlang_c(55, 50.0) < erlang_c(52, 50.0)


def test_wait_tail_matches_mm1_closed_form():
    lam, mu = 0.6, 1.0
    t = np.array([0.0, 0.5, 2.0])
    assert wait_tail(t, 1, lam, mu) == pytest.approx(0.6 * np.exp(-(mu - lam) * t))
    assert np.all(wait_tail(t, 1, 1.2, mu) == 1.0)


def _simulate_mmc(c, lam, mu, n, seed):
    rng = np.random.default_rng(seed)
    arrivals = np.cumsum(rng.exponential(1 / lam, n))
    services = rng.exponential(1 / mu, n)
    free = [0.0] * c
    heapq.heapify(free)
    waits = np.empty(n)
    for k, (a, s) in enumerate(zip(arrivals, services)):
        t_free = heapq.heappop(free)
        start = max(a, t_free)
        waits[k] = start - a
        heapq.heappush(free, start + s)
    return waits[n // 10:]


def test_wait_tail_matches_a_simulated_mmc_queue():
    c, lam, mu = 4, 3.2, 1.0
    waits = _simulate_mmc(c, lam, mu, 300_000, 0)
    for t in (0.0, 0.3, 1.0):
        assert (waits > t).mean() == pytest.approx(float(wait_tail(t, c, lam, mu)), abs=0.01)


def test_wait_quantile_inverts_the_tail():
    c, lam, mu, scv = 6, 5.0, 1.0, 0.5
    w = wait_quantile(0.9, c, lam, mu, scv)
    assert float(wait_tail(w, c, lam, mu, scv)) == pytest.approx(0.1)
    assert wait_quantile(0.9, 20, 5.0, 1.0) == 0.0            # rarely waits: the 90th percentile is zero
    assert wait_quantile(0.9, 5, 5.0, 1.0) == np.inf


def test_hourly_profile_sums_to_one_and_hits_the_evening_share():
    for ev in (0.35, 0.45):
        sh = hourly_profile(ev)
        assert sh.sum() == pytest.approx(1.0)
        assert sh[list(EVENING)].sum() == pytest.approx(ev)
        assert int(np.argmax(sh)) in EVENING


def _loads(n_stores=3, seed=0):
    rng = np.random.default_rng(seed)
    cells = sorted(h3.grid_disk(h3.latlng_to_cell(17.40, 78.45, 8), 6))
    latlng = np.array([h3.cell_to_latlng(c) for c in cells])
    stores = rng.choice(len(cells), n_stores, replace=False)
    rows, cols, vals = [], [], []
    for k, s in enumerate(stores):
        d = np.hypot(latlng[:, 0] - latlng[s, 0], latlng[:, 1] - latlng[s, 1]) * 111
        near = np.flatnonzero(d <= 1.6)
        rows += [k] * len(near)
        cols += list(near)
        vals += list(rng.uniform(20, 200, len(near)))
    flows = sparse.csr_matrix((vals, (rows, cols)), shape=(n_stores, len(cells)))
    return store_loads(flows, stores, latlng[:, 0], latlng[:, 1], 13.0, DeliveryParams()), latlng


def test_store_loads_distance_mix_and_zero_wait_ceiling():
    loads, _ = _loads()
    s = loads[0]
    assert s.orders_per_day == pytest.approx(s.weights.sum())
    assert 2 * 0.32 / (13 / 60) + 2.0 <= s.mean_cycle_min < 2 * 1.6 / (13 / 60) + 2.0
    # with an enormous fleet nobody waits: on-time = share of orders whose ride fits the promise
    assert s.on_time(10_000, 0.1) == pytest.approx(float((s.slack_min >= 0) @ s.weights / s.weights.sum()))


def test_min_riders_is_the_smallest_fleet_hitting_the_target():
    loads, _ = _loads()
    s, share = loads[1], 0.1
    c = min_riders(s, share, 0.9)
    assert s.on_time(c, share) >= 0.9 - 1e-9
    assert c == 1 or s.on_time(c - 1, share) < 0.9


def test_budget_staffing_beats_the_utilisation_rule_at_equal_rider_hours():
    loads, _ = _loads(n_stores=4, seed=2)
    shares = hourly_profile(0.35)
    rule = staff_utilisation(loads, shares)
    budget = staff_budget(loads, shares, int(rule.sum()))
    assert budget.sum() == rule.sum()
    p = DeliveryParams()
    assert evaluate(loads, shares, budget, 13.0, p)["on_time_day"] >= evaluate(loads, shares, rule, 13.0, p)["on_time_day"]


def test_evaluate_small_fleets_lose_reach_and_erlang_hits_target():
    loads, latlng = _loads(seed=3)
    shares = hourly_profile(0.35)
    p = DeliveryParams()
    util = evaluate(loads, shares, staff_utilisation(loads, shares), 13.0, p)
    # the same 80% utilisation is far safer with a big peak fleet than with a small afternoon one
    assert np.median(util["reach_km_peak"]) >= np.median(util["reach_km_quiet"])
    erl = evaluate(loads, shares, staff_erlang(loads, shares, 0.95), 13.0, p)
    ceiling = np.mean([float((s.slack_min >= 0) @ s.weights / s.weights.sum()) for s in loads])
    assert erl["on_time_day"] >= min(0.95, ceiling) - 0.01
    staff = staff_utilisation(loads, shares)
    ok, orders = hex_on_time(loads, staff, shares, 20, len(latlng))
    assert np.nanmax(ok) <= 1.0 and orders.sum() == pytest.approx(sum(s.orders_per_day for s in loads) * shares[20])


def test_with_orders_rescales_volume_but_keeps_the_distance_mix():
    loads, _ = _loads()
    s = loads[0]
    t = with_orders(s, 1463.0)
    assert t.orders_per_day == pytest.approx(1463.0) and t.weights.sum() == pytest.approx(1463.0)
    assert t.mean_cycle_min == s.mean_cycle_min
    assert t.on_time(10_000, 0.1) == pytest.approx(s.on_time(10_000, 0.1))
