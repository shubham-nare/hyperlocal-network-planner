"""Peak-hour delivery promise: why a "10-minute" catchment shrinks at 8 pm, and how many riders fix it.

v1's reach model gives each store a fixed radius: the distance a rider covers in the promise minus
picking time (10 - 2.5 = 7.5 min at the calibrated speed). That silently assumes a rider is free
the moment an order is packed. At the evening peak they are not: orders queue for riders, and
every minute of queueing is a minute less of riding. A hex at the edge of the radius is only on
time if the wait is exactly zero.

The model here, per store and hour:

- Orders arrive at rate lambda (the store's daily orders x the hour's share of the day).
- A rider trip is out-and-back plus handover: cycle = 2 d / v + handover, so the service rate is
  mu = 1 / E[cycle] over the store's own mix of order distances.
- Riders are c parallel servers: an M/G/c queue, with the M/M/c (Erlang-C) probability of waiting
  and an Allen-Cunneen scaling of the conditional wait for the cycle-time variability:
      P(W > t) = C(c, a) * exp(-(c mu - lambda) t / k),   a = lambda / mu,   k = (1 + scv) / 2
- An order to a hex at distance d is on time if  pick + W + d / v <= promise, i.e. W <= slack(d).

Hourly demand shares, handover time, cycle variability and rider cost are labelled assumptions
(see the write-up); the store loads, distances and speeds are the calibrated v1 ones.
"""
from __future__ import annotations

import heapq
import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy import sparse

from planner.revealed_demand import haversine_km

# Assumption: a quick-commerce day, shaped to the two public anchors we have (Blinkit's 6-9 pm
# peak window; "7-10 pm ~ 35% of orders"). Hour h covers h:00-h:59. Rescaled by hourly_profile().
_TEMPLATE = np.array([1.2, 0.5, 0.2, 0.1, 0.1, 0.3, 1.5, 3.5, 4.5, 4.5, 4.0, 4.0,
                      4.5, 4.5, 4.0, 4.0, 4.5, 5.5, 7.0, 9.0, 10.0, 9.5, 6.0, 3.0])
EVENING = (19, 20, 21)            # 7-10 pm
WITHIN_HEX_KM = 0.32              # mean distance from a res-8 hex centre to a point in it


def hourly_profile(evening_share: float = 0.35) -> np.ndarray:
    """24 hourly shares of daily orders, with 7-10 pm carrying ``evening_share`` of the day."""
    if not 0 < evening_share < 1:
        raise ValueError("evening_share must be in (0, 1)")
    shares = _TEMPLATE / _TEMPLATE.sum()
    ev = np.zeros(24, dtype=bool)
    ev[list(EVENING)] = True
    shares[ev] *= evening_share / shares[ev].sum()
    shares[~ev] *= (1 - evening_share) / shares[~ev].sum()
    return shares


# --------------------------------------------------------------------------------------------
# Queueing
# --------------------------------------------------------------------------------------------

def erlang_c(c: int, a: float) -> float:
    """Probability an arrival waits in M/M/c with offered load ``a`` (= lambda/mu). 1 if unstable."""
    if a <= 0:
        return 0.0
    if c <= a:
        return 1.0
    b = 1.0
    for k in range(1, c + 1):          # Erlang-B recursion: numerically stable for large c
        b = a * b / (k + a * b)
    return c * b / (c - a * (1 - b))


def wait_tail(t: np.ndarray | float, c: int, lam: float, mu: float, scv: float = 1.0) -> np.ndarray:
    """P(wait > t) in minutes, M/G/c with the Allen-Cunneen scaling of the conditional wait."""
    t = np.asarray(t, dtype=float)
    if lam <= 0:
        return np.zeros_like(t)
    if c * mu <= lam:
        return np.ones_like(t)
    k = (1.0 + scv) / 2.0
    return erlang_c(c, lam / mu) * np.exp(-(c * mu - lam) * np.maximum(t, 0.0) / k)


def wait_quantile(q: float, c: int, lam: float, mu: float, scv: float = 1.0) -> float:
    """The q-quantile of the wait (minutes); inf when the queue is unstable."""
    if lam <= 0:
        return 0.0
    if c * mu <= lam:
        return math.inf
    pw = erlang_c(c, lam / mu)
    if pw <= 1 - q:
        return 0.0
    return math.log(pw / (1 - q)) * (1.0 + scv) / 2.0 / (c * mu - lam)


# --------------------------------------------------------------------------------------------
# Stores
# --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class DeliveryParams:
    promise_min: float = 10.0
    pick_min: float = 2.5          # config/cities.yaml picking_time_min (assumption there too)
    handover_min: float = 2.0      # assumption: parking, building access, handover, per trip
    extra_scv: float = 0.25        # assumption: trip-level variability on top of the distance mix
    on_time_target: float = 0.95   # assumption: the service level staffing aims for
    rider_cost_per_hour: float = 120.0  # assumption: INR; ~3-4 orders/h x INR 25-50/order (secondary)


@dataclass
class StoreLoad:
    """One store's daily orders and the distance mix they come from."""
    cell: int
    orders_per_day: float
    slack_min: np.ndarray      # per served hex: promise - pick - ride time (may be <= 0)
    weights: np.ndarray        # orders/day from each of those hexes
    hex_idx: np.ndarray        # which cells
    mean_cycle_min: float
    scv: float

    @property
    def mu(self) -> float:
        return 1.0 / self.mean_cycle_min

    def lam(self, share: float) -> float:
        return self.orders_per_day * share / 60.0      # orders per minute in that hour

    def on_time(self, c: int, share: float) -> float:
        """Order-weighted share delivered within the promise in an hour with ``share`` of daily orders."""
        if self.orders_per_day <= 0:
            return 1.0
        ok = np.where(self.slack_min >= 0, 1.0 - wait_tail(self.slack_min, c, self.lam(share), self.mu, self.scv), 0.0)
        return float(ok @ self.weights / self.weights.sum())

    def hex_on_time(self, c: int, share: float) -> np.ndarray:
        return np.where(self.slack_min >= 0, 1.0 - wait_tail(self.slack_min, c, self.lam(share), self.mu, self.scv), 0.0)

    def offered_load(self, share: float) -> float:
        return self.lam(share) / self.mu


def with_orders(load: StoreLoad, orders_per_day: float) -> StoreLoad:
    """The same store and distance mix, carrying a different daily volume (for load-pattern checks)."""
    if load.orders_per_day <= 0:
        return load
    return StoreLoad(load.cell, orders_per_day, load.slack_min, load.weights * orders_per_day / load.orders_per_day,
                     load.hex_idx, load.mean_cycle_min, load.scv)


def store_loads(flows: sparse.csr_matrix, store_cells: Sequence[int], lat: np.ndarray, lng: np.ndarray,
                speed_kmph: float, p: DeliveryParams) -> list[StoreLoad]:
    """Build each store's load from served-order flows (rows = stores, columns = cells)."""
    flows = sparse.csr_matrix(flows)
    v = speed_kmph / 60.0                                   # km per minute
    loads = []
    for k, cell in enumerate(store_cells):
        row = flows.getrow(k)
        idx, w = row.indices, row.data
        if len(idx) == 0:
            loads.append(StoreLoad(int(cell), 0.0, np.zeros(0), np.zeros(0), idx, 2 * WITHIN_HEX_KM / v + p.handover_min, p.extra_scv))
            continue
        d = np.maximum(haversine_km(lat[cell], lng[cell], lat[idx], lng[idx]), WITHIN_HEX_KM)
        ride = d / v
        cycle = 2 * ride + p.handover_min
        mean = float(np.average(cycle, weights=w))
        var = float(np.average((cycle - mean) ** 2, weights=w))
        loads.append(StoreLoad(int(cell), float(w.sum()), p.promise_min - p.pick_min - ride, w, idx, mean,
                               var / mean ** 2 + p.extra_scv))
    return loads


# --------------------------------------------------------------------------------------------
# Staffing policies: riders per store per hour, shape (n_stores, 24)
# --------------------------------------------------------------------------------------------

def staff_utilisation(loads: list[StoreLoad], shares: np.ndarray, utilisation: float = 0.8) -> np.ndarray:
    """Hour-by-hour riders at a fixed target utilisation -- the common rule of thumb."""
    return np.array([[max(1, math.ceil(s.offered_load(sh) / utilisation)) for sh in shares] for s in loads])


def min_riders(s: StoreLoad, share: float, target: float, c_max: int = 500) -> int:
    """Fewest riders for which the store's order-weighted on-time share reaches ``target`` that hour
    (or the best achievable if distance alone makes the target impossible)."""
    if s.orders_per_day <= 0 or share <= 0:
        return 1
    ceiling = float((s.slack_min >= 0) @ s.weights / s.weights.sum())   # on-time with zero wait
    goal = min(target, ceiling - 1e-9)
    c = max(1, math.floor(s.offered_load(share)) + 1)
    while c < c_max and s.on_time(c, share) < goal:
        c += 1
    return c


def staff_erlang(loads: list[StoreLoad], shares: np.ndarray, target: float) -> np.ndarray:
    """Hour-by-hour riders from the queue model, just enough to hit ``target`` on-time."""
    return np.array([[min_riders(s, sh, target) for sh in shares] for s in loads])


def staff_budget(loads: list[StoreLoad], shares: np.ndarray, rider_hours: int) -> np.ndarray:
    """Spend a fixed rider-hour budget where it buys the most on-time orders (greedy on marginal
    gain; on-time orders are concave in riders once the queue is stable)."""
    staff = np.array([[max(1, math.floor(s.offered_load(sh)) + 1) if s.orders_per_day > 0 else 1 for sh in shares]
                      for s in loads])
    if staff.sum() > rider_hours:
        raise ValueError("budget below the minimum stable staffing")

    def gain(i: int, h: int) -> float:
        s, sh, c = loads[i], shares[h], staff[i, h]
        orders = s.orders_per_day * sh
        return orders * (s.on_time(c + 1, sh) - s.on_time(c, sh))

    heap = [(-gain(i, h), i, h) for i in range(len(loads)) for h in range(24)]
    heapq.heapify(heap)
    left = rider_hours - int(staff.sum())
    while left > 0 and heap:
        _, i, h = heapq.heappop(heap)
        staff[i, h] += 1
        left -= 1
        heapq.heappush(heap, (-gain(i, h), i, h))
    return staff


# --------------------------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------------------------

def evaluate(loads: list[StoreLoad], shares: np.ndarray, staff: np.ndarray, speed_kmph: float, p: DeliveryParams,
             quantile: float = 0.9) -> dict:
    """On-time shares (day, evening, per hour), rider-hours, and the reach each store keeps at a
    given wait quantile (the distance still on time for ``quantile`` of orders)."""
    orders = np.array([[s.orders_per_day * sh for sh in shares] for s in loads])
    on_time = np.array([[s.on_time(int(staff[i, h]), shares[h]) for h in range(24)] for i, s in enumerate(loads)])
    v = speed_kmph / 60.0
    budget = p.promise_min - p.pick_min

    def reach(i: int, h: int) -> float:
        s = loads[i]
        w = wait_quantile(quantile, int(staff[i, h]), s.lam(shares[h]), s.mu, s.scv)
        return max(0.0, (budget - w) * v) if math.isfinite(w) else 0.0

    peak_hour = int(np.argmax(shares))
    quiet_hour = 15
    ev = list(EVENING)
    return {
        "on_time_day": float((on_time * orders).sum() / orders.sum()),
        "on_time_evening": float((on_time[:, ev] * orders[:, ev]).sum() / orders[:, ev].sum()),
        "on_time_by_hour": (on_time * orders).sum(axis=0) / orders.sum(axis=0),
        "late_orders_per_day": float(((1 - on_time) * orders).sum()),
        "rider_hours": int(staff.sum()),
        "rider_hours_per_order": float(staff.sum() / orders.sum()),
        "reach_km_peak": np.array([reach(i, peak_hour) for i in range(len(loads))]),
        "reach_km_quiet": np.array([reach(i, quiet_hour) for i in range(len(loads))]),
        "store_on_time": on_time,
    }


def hex_on_time(loads: list[StoreLoad], staff: np.ndarray, shares: np.ndarray, hour: int, n_cells: int) -> tuple[np.ndarray, np.ndarray]:
    """Per-cell on-time share and orders in ``hour`` (order-weighted across the stores serving it)."""
    ok = np.zeros(n_cells)
    orders = np.zeros(n_cells)
    for i, s in enumerate(loads):
        if len(s.hex_idx) == 0:
            continue
        o = s.weights * shares[hour]
        np.add.at(ok, s.hex_idx, o * s.hex_on_time(int(staff[i, hour]), shares[hour]))
        np.add.at(orders, s.hex_idx, o)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(orders > 0, ok / orders, np.nan), orders
