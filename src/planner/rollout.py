"""Staged rollout under demand uncertainty: a rollout *policy*, not a ranked list.

v1 answers "which 10 sites?" from one point estimate of demand and opens them as if the estimate
were true. Real expansion teams don't do that: capex is irreversible, the demand map is a proxy,
and the first stores they open *tell them* what demand actually is. This module plans that way:

1. **Uncertainty.** True log orders/day per hex = v1's calibrated estimate + a Gaussian error made
   of a city-wide level error, an elasticity tilt (v1's 0-1 adoption-elasticity range), and a
   spatially correlated local error. The magnitudes are labelled assumptions, swept in the study.
2. **Money, not coverage.** A plan is worth (network-incremental orders x margin) - fixed cost -
   capex over the horizon. Orders a new store takes from an existing one earn nothing, and a site
   that doesn't pay back is not opened, so the plan size is chosen, not fixed.
3. **Served orders** are the same capacitated assignment v1's MIP uses (each hex's orders split
   across any open store within reach, up to store capacity) solved as a max-flow, which is exact
   for that LP and fast enough to evaluate thousands of times.
4. **Robust choice.** Sites are picked greedily on *expected* value over demand samples (sample
   average approximation). Served orders are submodular in the set of open stores, so lazy
   greedy gives the same picks as plain greedy.
5. **Learning.** Each wave-1 store reveals noisy demand in its catchment. A linearised Gaussian
   update (exact conditioning of the prior, via Matheron's rule for samples) carries that
   information to nearby candidates through the spatial correlation, and wave 2 is re-planned.

Nothing here is order data: the prior is v1's demand model, and the "truth" in any simulation is
drawn from an assumed error model. What the simulation measures is the value of the *decision
process* under stated uncertainty, not a forecast.
"""
from __future__ import annotations

import heapq
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from scipy import sparse
from scipy.optimize import linprog
from scipy.sparse.csgraph import maximum_flow

from planner.revealed_demand import haversine_km

FLOW_SCALE = 10          # max-flow needs integers: 0.1 orders/day resolution
_INF_CAP = 2 ** 30


# --------------------------------------------------------------------------------------------
# Served orders
# --------------------------------------------------------------------------------------------

@dataclass
class ServiceNetwork:
    """Cells, which cells a store in each cell reaches, the brand's existing stores, store capacity.

    ``existing`` holds one cell index per existing store (repeats allowed: two stores in one hex are
    two stores). New stores are placed at cell centres.
    """
    reach: sparse.csr_matrix
    existing: np.ndarray
    capacity: float

    def __post_init__(self):
        self.reach = sparse.csr_matrix(self.reach)
        self.existing = np.asarray(self.existing, dtype=int)
        self._rows = [self.reach.indices[self.reach.indptr[i]:self.reach.indptr[i + 1]] for i in range(self.reach.shape[0])]

    @property
    def n_cells(self) -> int:
        return self.reach.shape[0]

    def stores(self, new: Sequence[int] = ()) -> np.ndarray:
        return np.concatenate([self.existing, np.asarray(list(new), dtype=int)])

    def _max_flow(self, demand: np.ndarray, stores: np.ndarray):
        rows = [self._rows[s] for s in stores]
        lens = np.fromiter((len(r) for r in rows), dtype=int, count=len(rows))
        hex_idx = np.concatenate(rows)
        used, hex_local = np.unique(hex_idx, return_inverse=True)
        n_s, n_u = len(stores), len(used)
        sink = 1 + n_s + n_u
        src = np.concatenate([np.zeros(n_s, int), 1 + np.repeat(np.arange(n_s), lens), 1 + n_s + np.arange(n_u)])
        dst = np.concatenate([1 + np.arange(n_s), 1 + n_s + hex_local, np.full(n_u, sink)])
        cap = np.concatenate([np.full(n_s, round(self.capacity * FLOW_SCALE)), np.full(len(hex_idx), _INF_CAP),
                              np.round(np.asarray(demand)[used] * FLOW_SCALE)]).astype(np.int32)
        graph = sparse.csr_matrix((cap, (src, dst)), shape=(sink + 1, sink + 1))
        return maximum_flow(graph, 0, sink), used, n_s, n_u

    def served(self, demand: np.ndarray, new: Sequence[int] = ()) -> float:
        """Max orders/day the existing + ``new`` stores can serve (the capacitated assignment optimum)."""
        stores = self.stores(new)
        if len(stores) == 0:
            return 0.0
        result, *_ = self._max_flow(demand, stores)
        return result.flow_value / FLOW_SCALE

    def assignment(self, demand: np.ndarray, new: Sequence[int] = (), lat: np.ndarray | None = None,
                   lng: np.ndarray | None = None) -> sparse.csr_matrix:
        """Orders/day each store (row, in ``stores(new)`` order) serves from each cell (column).

        The served-orders optimum's split across overlapping stores is not unique, and max-flow's
        own split is arbitrary (it can leave one of two overlapping stores nearly empty). Given cell
        coordinates, the split is instead the one that serves the same maximum total with the least
        total delivery distance -- i.e. orders go to the nearest store with capacity, as dispatch does.
        """
        stores = self.stores(new)
        if len(stores) == 0:
            return sparse.csr_matrix((0, self.n_cells))
        result, used, n_s, n_u = self._max_flow(demand, stores)
        if lat is None or lng is None:
            block = sparse.csr_matrix(result.flow)[1:1 + n_s, 1 + n_s:1 + n_s + n_u].tocoo()
            keep = block.data > 0
            return sparse.csr_matrix((block.data[keep] / FLOW_SCALE, (block.row[keep], used[block.col[keep]])),
                                     shape=(n_s, self.n_cells))
        demand = np.asarray(demand, dtype=float)
        rows = [self._rows[s] for s in stores]
        store_of = np.repeat(np.arange(n_s), [len(r) for r in rows])
        cell_of = np.concatenate(rows)
        keep = demand[cell_of] > 0
        store_of, cell_of = store_of[keep], cell_of[keep]
        dist = haversine_km(lat[stores[store_of]], lng[stores[store_of]], lat[cell_of], lng[cell_of])
        n_e = len(cell_of)
        cells_used, cell_row = np.unique(cell_of, return_inverse=True)
        a_ub = sparse.vstack([
            sparse.csr_matrix((np.ones(n_e), (cell_row, np.arange(n_e))), shape=(len(cells_used), n_e)),   # per-cell demand
            sparse.csr_matrix((np.ones(n_e), (store_of, np.arange(n_e))), shape=(n_s, n_e)),                # per-store capacity
            sparse.csr_matrix(-np.ones((1, n_e))),                                                         # serve the optimum
        ]).tocsr()
        b_ub = np.concatenate([demand[cells_used], np.full(n_s, self.capacity), [-(result.flow_value / FLOW_SCALE - 0.5)]])
        lp = linprog(dist, A_ub=a_ub, b_ub=b_ub, bounds=(0, None), method="highs")
        if not lp.success:
            raise RuntimeError(f"min-distance assignment failed: {lp.message}")
        x = lp.x
        nz = x > 1e-6
        return sparse.csr_matrix((x[nz], (store_of[nz], cell_of[nz])), shape=(n_s, self.n_cells))

    def open_counts(self, new: Sequence[int] = ()) -> np.ndarray:
        """How many open stores reach each cell."""
        stores = self.stores(new)
        return np.asarray(self.reach[stores].sum(axis=0)).ravel() if len(stores) else np.zeros(self.n_cells)


# --------------------------------------------------------------------------------------------
# Economics
# --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Economics:
    """Per-store economics for one scenario. ``margin`` = gross profit - variable cost, INR/order."""
    margin_per_order: float
    fixed_per_day: float
    capex: float

    def site_value(self, incremental_orders_per_day: float, days: float) -> float:
        return self.margin_per_order * incremental_orders_per_day * days - self.fixed_per_day * days - self.capex


def realised_value(net: ServiceNetwork, demand: np.ndarray, econ: Economics, wave1: Sequence[int],
                   wave2: Sequence[int], horizon_days: float, wave2_day: float) -> dict[str, float]:
    """INR value of a two-wave rollout against one realised demand map (wave 2 opens at ``wave2_day``)."""
    base = net.served(demand)
    s1 = net.served(demand, wave1)
    s12 = net.served(demand, list(wave1) + list(wave2)) if len(wave2) else s1
    order_days = wave2_day * (s1 - base) + (horizon_days - wave2_day) * (s12 - base) if len(wave2) else horizon_days * (s1 - base)
    store_days = len(wave1) * horizon_days + len(wave2) * (horizon_days - wave2_day)
    value = econ.margin_per_order * order_days - econ.fixed_per_day * store_days - econ.capex * (len(wave1) + len(wave2))
    return {"value_inr": value, "incremental_orders_per_day": s12 - base, "stores_opened": len(wave1) + len(wave2)}


# --------------------------------------------------------------------------------------------
# Planning: greedy on expected value over demand samples
# --------------------------------------------------------------------------------------------

@dataclass
class PlannedSite:
    site: int
    expected_incremental_orders: float   # orders/day added to the network, averaged over samples
    expected_value_inr: float            # over the remaining horizon, planner's economics
    prob_positive: float                 # share of samples in which this addition pays back


def greedy_plan(net: ServiceNetwork, demand_samples: np.ndarray, candidates: Sequence[int], max_new: int,
                econ: Economics, horizon_days: float, base_new: Sequence[int] = ()) -> list[PlannedSite]:
    """Add sites one at a time, each with the highest expected value, while that value is positive.

    ``demand_samples`` is (n_samples, n_cells) orders/day. Lazy evaluation: a candidate's previous
    expected gain is an upper bound on its current gain (served orders are submodular in the set of
    open stores), so only candidates that could still be best are re-evaluated.
    """
    samples = np.atleast_2d(demand_samples)
    base = list(base_new)
    current = np.array([net.served(d, base) for d in samples])
    pool = [c for c in dict.fromkeys(candidates) if c not in set(base)]
    # Tie-break: sites that fill to capacity add exactly the same orders in every sample, which is
    # common. Among ties prefer more demand within reach (more upside if demand beats the estimate).
    # A per-site constant keeps lazy evaluation valid.
    reach_demand = np.asarray(net.reach[pool] @ samples.mean(axis=0)).ravel() if pool else np.array([])
    bonus = dict(zip(pool, 1e-6 * reach_demand / max(reach_demand.max(initial=0.0), 1.0)))
    heap = [(-np.inf, k, c) for k, c in enumerate(pool)]
    heapq.heapify(heap)
    chosen: list[PlannedSite] = []
    while len(chosen) < max_new and heap:
        while True:
            _, order, c = heapq.heappop(heap)
            trial = np.array([net.served(d, base + [p.site for p in chosen] + [c]) for d in samples])
            gain = float((trial - current).mean())
            key = gain + bonus[c]
            if not heap or key >= -heap[0][0]:
                break
            heapq.heappush(heap, (-key, order, c))
        value = econ.site_value(gain, horizon_days)
        if value <= 0:
            break
        per_sample = econ.margin_per_order * (trial - current) * horizon_days - econ.fixed_per_day * horizon_days - econ.capex
        chosen.append(PlannedSite(c, gain, value, float((per_sample > 0).mean())))
        current = trial
    return chosen


def screen_candidates(net: ServiceNetwork, demand_samples: np.ndarray, cells: Sequence[int], keep: int) -> list[int]:
    """The ``keep`` cells with the highest expected single-site gain over the existing network."""
    samples = np.atleast_2d(demand_samples)
    base = np.array([net.served(d) for d in samples])
    gains = np.array([np.mean([net.served(d, [c]) for d in samples]) - base.mean() for c in cells])
    order = np.argsort(-gains, kind="stable")[:keep]
    return [int(cells[i]) for i in order]


# --------------------------------------------------------------------------------------------
# Demand uncertainty and learning
# --------------------------------------------------------------------------------------------

@dataclass
class DemandPrior:
    """Gaussian prior on log orders/day per cell: mean ``mu``, covariance ``cov``."""
    mu: np.ndarray
    cov: np.ndarray
    chol: np.ndarray = field(repr=False)

    def sample(self, n: int, rng: np.random.Generator) -> np.ndarray:
        return self.mu + rng.standard_normal((n, len(self.mu))) @ self.chol.T


def build_prior(estimate_log: np.ndarray, lat: np.ndarray, lng: np.ndarray, sigma_level: float, sigma_field: float,
                length_km: float, tilt: np.ndarray | None = None, sigma_tilt: float = 0.0,
                jitter: float = 1e-8) -> DemandPrior:
    """log demand = mu + level + tilt_coef * tilt + field; field has an exponential spatial kernel.

    Mean-preserving: ``mu`` is set so that E[demand] per cell equals exp(``estimate_log``), i.e. the
    point estimate stays the *expected* demand (v1 calibrates mean orders to disclosed totals).
    Centring the log on the estimate instead would quietly inflate expected demand by
    exp(variance / 2) and bias every uncertainty-aware plan towards opening more stores.
    """
    d = haversine_km(lat[:, None], lng[:, None], lat[None, :], lng[None, :])
    cov = sigma_level ** 2 + sigma_field ** 2 * np.exp(-d / length_km)
    if tilt is not None and sigma_tilt > 0:
        cov = cov + sigma_tilt ** 2 * np.outer(tilt, tilt)
    cov[np.diag_indices_from(cov)] += jitter
    mu = np.asarray(estimate_log, float) - 0.5 * np.diag(cov)
    return DemandPrior(mu=mu, cov=cov, chol=np.linalg.cholesky(cov))


@dataclass
class ObservationModel:
    """z_s = log(sum_h a_sh * demand_h) + noise, linearised as z ~ c + W (x - mu).

    ``a_sh`` = 1 / (open stores reaching h) for h in the store's reach: the demand *directed at* the
    store -- its orders plus orders it lost to capacity, which operators see as sessions/unserviced
    carts. Linearisation is at the prior mean (delta method); any error from it only hurts the
    learning policy, because every policy is scored against the true, non-linearised demand.
    """
    a: sparse.csr_matrix
    w: np.ndarray
    c: np.ndarray
    noise_sd: float

    def expected_orders(self) -> np.ndarray:
        return np.exp(self.c)


def observation_model(net: ServiceNetwork, open_new: Sequence[int], observed: Sequence[int], mu: np.ndarray,
                      noise_sd: float) -> ObservationModel:
    counts = np.maximum(net.open_counts(open_new), 1.0)
    a = sparse.csr_matrix(net.reach[list(observed)].multiply(1.0 / counts[None, :]))
    m = np.exp(mu)
    y = a @ m
    w = a.multiply(m[None, :]).toarray() / y[:, None]
    return ObservationModel(a=a, w=w, c=np.log(y), noise_sd=noise_sd)


def observe(model: ObservationModel, true_log_demand: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    return np.log(model.a @ np.exp(true_log_demand)) + rng.normal(0, model.noise_sd, size=len(model.c))


def _gain(prior: DemandPrior, model: ObservationModel) -> np.ndarray:
    s = model.w @ prior.cov @ model.w.T + model.noise_sd ** 2 * np.eye(len(model.c))
    return np.linalg.solve(s, model.w @ prior.cov).T            # (n_cells, n_obs)


def posterior_mean(prior: DemandPrior, model: ObservationModel, z: np.ndarray) -> np.ndarray:
    return prior.mu + _gain(prior, model) @ (z - model.c)


def posterior_samples(prior: DemandPrior, model: ObservationModel, z: np.ndarray, prior_draws: np.ndarray,
                      rng: np.random.Generator) -> np.ndarray:
    """Exact posterior draws for the linearised model via Matheron's rule, reusing prior draws."""
    k = _gain(prior, model)
    eta = rng.normal(0, model.noise_sd, size=(len(prior_draws), len(z)))
    simulated = model.c + (prior_draws - prior.mu) @ model.w.T + eta
    return prior_draws + (z - simulated) @ k.T


# --------------------------------------------------------------------------------------------
# Trigger rules for conditional wave-2 sites
# --------------------------------------------------------------------------------------------

def most_informative_store(prior: DemandPrior, model: ObservationModel, net: ServiceNetwork, site: int) -> int:
    """Index (into the observed stores) whose signal is most correlated with demand in ``site``'s reach."""
    reach = net.reach[site].toarray().ravel()
    v = reach * np.exp(prior.mu)
    v = v / v.sum()
    cov_zv = model.w @ prior.cov @ v
    var_z = np.einsum("ij,jk,ik->i", model.w, prior.cov, model.w) + model.noise_sd ** 2
    corr = cov_zv / np.sqrt(var_z * (v @ prior.cov @ v))
    return int(np.argmax(corr))


def trigger_threshold(net: ServiceNetwork, prior: DemandPrior, model: ObservationModel, prior_draws: np.ndarray,
                      open_new: Sequence[int], site: int, store_k: int, econ: Economics, days: float,
                      rng: np.random.Generator, z_sd_range: float = 3.0, iters: int = 12) -> tuple[float | None, str]:
    """Observed demand at wave-1 store ``store_k`` (orders/day) above which opening ``site`` has
    positive expected value, other wave-1 stores observed at their expected values.

    Returns (threshold, "open if above") -- or (None, "open regardless" / "don't open") when the
    decision doesn't flip inside +-``z_sd_range`` standard deviations of the signal.
    """
    s = model.w @ prior.cov @ model.w.T + model.noise_sd ** 2 * np.eye(len(model.c))
    sd = float(np.sqrt(s[store_k, store_k]))
    seed = int(rng.integers(1 << 31))

    def expected_value(z_k: float) -> float:
        z = model.c.copy()
        z[store_k] = z_k
        draws = np.exp(posterior_samples(prior, model, z, prior_draws, np.random.default_rng(seed)))
        gain = np.mean([net.served(d, list(open_new) + [site]) - net.served(d, open_new) for d in draws])
        return econ.site_value(gain, days)

    lo, hi = model.c[store_k] - z_sd_range * sd, model.c[store_k] + z_sd_range * sd
    v_lo, v_hi = expected_value(lo), expected_value(hi)
    if v_lo > 0 and v_hi > 0:
        return None, "open regardless"
    if v_lo <= 0 and v_hi <= 0:
        return None, "don't open"
    if v_lo > 0 >= v_hi:
        return None, "signal lowers value"   # non-monotone / inverse relation: no simple rule
    for _ in range(iters):
        mid = (lo + hi) / 2
        if expected_value(mid) > 0:
            hi = mid
        else:
            lo = mid
    return float(np.exp(hi)), "open if above"
