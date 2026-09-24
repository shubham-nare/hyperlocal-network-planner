import h3
import numpy as np
import pytest

from planner.optimize import Site, solve_network
from planner.revealed_demand import reach_matrix
from planner.rollout import (
    Economics, ServiceNetwork, build_prior, greedy_plan, most_informative_store, observation_model, observe,
    posterior_mean, posterior_samples, realised_value, screen_candidates, trigger_threshold,
)

RADIUS_KM = 1.625


def _city(rings=8, n_existing=6, seed=0, capacity=900.0):
    rng = np.random.default_rng(seed)
    cells = sorted(h3.grid_disk(h3.latlng_to_cell(17.40, 78.45, 8), rings))
    reach = reach_matrix(cells, RADIUS_KM)
    existing = rng.choice(len(cells), size=n_existing, replace=False)
    demand = rng.gamma(2.0, 60.0, size=len(cells))
    latlng = np.array([h3.cell_to_latlng(c) for c in cells])
    return cells, ServiceNetwork(reach, existing, capacity), demand, latlng


def test_served_equals_v1_lp_optimum():
    cells, net, demand, _ = _city()
    new = [3, 40, 90]
    sites = [Site(f"s{k}", frozenset(cells[j] for j in net.reach[i].indices), existing=True)
             for k, i in enumerate(net.stores(new))]
    lp = solve_network(dict(zip(cells, demand)), sites, net.capacity, breakeven=0, max_new=0)
    assert net.served(demand, new) == pytest.approx(lp.served_total, abs=0.5)


def test_served_is_monotone_and_submodular():
    _, net, demand, _ = _city(seed=1)
    rng = np.random.default_rng(2)
    for _ in range(20):
        b = list(rng.choice(net.n_cells, size=6, replace=False))
        a = b[:3]
        c = int(rng.integers(net.n_cells))
        fa, fb = net.served(demand, a), net.served(demand, b)
        assert fb >= fa - 1e-6
        assert net.served(demand, a + [c]) - fa >= net.served(demand, b + [c]) - fb - 0.2  # 0.1-order rounding


def test_lazy_greedy_matches_naive_greedy():
    _, net, demand, _ = _city(seed=3)
    rng = np.random.default_rng(4)
    samples = demand * rng.lognormal(0, 0.4, size=(5, net.n_cells))
    econ = Economics(margin_per_order=45.0, fixed_per_day=12000.0, capex=2.5e6)
    cands = list(range(0, net.n_cells, 3))
    lazy = [p.site for p in greedy_plan(net, samples, cands, 5, econ, 365)]
    reach_demand = np.asarray(net.reach[cands] @ samples.mean(axis=0)).ravel()
    bonus = dict(zip(cands, 1e-6 * reach_demand / reach_demand.max()))
    naive, current = [], np.array([net.served(d) for d in samples])
    for _ in range(5):
        gains = {c: np.mean([net.served(d, naive + [c]) for d in samples]) - current.mean() for c in cands if c not in naive}
        best = max(gains, key=lambda c: gains[c] + bonus[c])
        if econ.site_value(gains[best], 365) <= 0:
            break
        naive.append(best)
        current = np.array([net.served(d, naive) for d in samples])
    assert lazy == naive


def test_greedy_opens_nothing_when_nothing_pays_back():
    _, net, demand, _ = _city()
    econ = Economics(margin_per_order=45.0, fixed_per_day=12000.0, capex=1e12)
    assert greedy_plan(net, demand, range(net.n_cells), 5, econ, 365) == []


def test_screen_candidates_keeps_the_best_single_additions():
    _, net, demand, _ = _city(seed=5)
    kept = screen_candidates(net, demand, list(range(net.n_cells)), keep=4)
    gains = [net.served(demand, [c]) for c in range(net.n_cells)]
    assert sorted(gains[c] for c in kept) == sorted(sorted(gains)[-4:])


def test_realised_value_accounting():
    _, net, demand, _ = _city(seed=6)
    econ = Economics(margin_per_order=40.0, fixed_per_day=10000.0, capex=1e6)
    base = net.served(demand)
    w1, w2 = [5, 60], [100]
    out = realised_value(net, demand, econ, w1, w2, horizon_days=1000, wave2_day=100)
    s1, s12 = net.served(demand, w1), net.served(demand, w1 + w2)
    expected = 40 * (100 * (s1 - base) + 900 * (s12 - base)) - 10000 * (2 * 1000 + 900) - 3e6
    assert out["value_inr"] == pytest.approx(expected)
    assert out["stores_opened"] == 3
    now = realised_value(net, demand, econ, w1 + w2, [], horizon_days=1000, wave2_day=100)
    assert now["value_inr"] == pytest.approx(40 * 1000 * (s12 - base) - 10000 * 3000 - 3e6)


def _prior(latlng, n, sigma_field=0.5):
    return build_prior(np.full(n, np.log(100.0)), latlng[:, 0], latlng[:, 1], sigma_level=0.1,
                       sigma_field=sigma_field, length_km=2.0)


def test_prior_is_mean_preserving():
    _, net, _, latlng = _city(rings=4)
    prior = _prior(latlng, net.n_cells, sigma_field=0.7)
    draws = np.exp(prior.sample(20000, np.random.default_rng(0)))
    assert draws.mean(axis=0).mean() == pytest.approx(100.0, rel=0.02)


def test_prior_covariance_decays_with_distance():
    _, net, _, latlng = _city(rings=5)
    prior = _prior(latlng, net.n_cells)
    d = np.hypot(latlng[:, 0] - latlng[0, 0], latlng[:, 1] - latlng[0, 1])
    near, far = np.argsort(d)[1], np.argsort(d)[-1]
    assert prior.cov[0, near] > prior.cov[0, far] > 0


def test_linearised_observation_is_exact_at_the_prior_mean():
    _, net, _, latlng = _city(rings=5)
    prior = _prior(latlng, net.n_cells)
    model = observation_model(net, [10, 20], [10, 20], prior.mu, noise_sd=0.0)
    z = observe(model, prior.mu, np.random.default_rng(0))
    assert z == pytest.approx(model.c)
    assert model.w.sum(axis=1) == pytest.approx(np.ones(2))


def test_posterior_learns_from_a_high_observation_and_samples_match_the_mean():
    _, net, _, latlng = _city(rings=6)
    prior = _prior(latlng, net.n_cells)
    rng = np.random.default_rng(1)
    model = observation_model(net, [15], [15], prior.mu, noise_sd=0.05)
    z = model.c + 0.6  # demand around the store came in ~80% above the prior
    mean = posterior_mean(prior, model, z)
    reach = net.reach[15].indices
    assert (mean[reach] - prior.mu[reach]).mean() > 0.4
    far = np.argmax(np.hypot(latlng[:, 0] - latlng[15, 0], latlng[:, 1] - latlng[15, 1]))
    assert abs(mean[far] - prior.mu[far]) < (mean[reach] - prior.mu[reach]).mean()  # learning is local
    draws = posterior_samples(prior, model, z, prior.sample(4000, rng), rng)
    assert draws.mean(axis=0)[reach] == pytest.approx(mean[reach], abs=0.03)
    # posterior variance near the store shrinks
    assert draws[:, reach].var(axis=0).mean() < 0.5 * prior.cov[reach, reach].mean()


def test_trigger_threshold_brackets_the_decision():
    _, net, _, latlng = _city(rings=7, n_existing=2, seed=7)
    prior = _prior(latlng, net.n_cells, sigma_field=0.6)
    rng = np.random.default_rng(3)
    draws = prior.sample(60, rng)
    wave1 = [20]
    model = observation_model(net, wave1, wave1, prior.mu, noise_sd=0.1)
    site = int(net.reach[20].indices[-1])  # a neighbour sharing much of the catchment
    econ = Economics(margin_per_order=45.0, fixed_per_day=9000.0, capex=1.5e6)
    k = most_informative_store(prior, model, net, site)
    assert k == 0
    thr, rule = trigger_threshold(net, prior, model, draws, wave1, site, k, econ, 900, np.random.default_rng(5))
    assert rule in {"open if above", "open regardless", "don't open", "signal lowers value"}
    if rule == "open if above":
        assert np.exp(model.c[0] - 3.5 * 1) < thr < np.exp(model.c[0] + 3.5)
