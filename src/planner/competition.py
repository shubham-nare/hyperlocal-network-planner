"""Competitor response: which new sites still pay once Zepto and Instamart react?

v1 and the rollout planner pick sites as if competitors stand still. They don't: all three
operators are expanding in the same cities, and the revealed-demand study found they *co-locate*
(lambda ~ -2.9). This module plays the expansion as a leader-follower (Stackelberg) game on one city:

- **Market.** Category demand in each hex is split across every brand's stores in reach by a Huff
  rule, weight 1 / max(d, 0.32 km)^beta -- the repo's validated huff.py form, applied across brands
  (the cross-brand use is an assumption: huff.py was validated on which *Zepto* store serves a hex).
  Each store serves at most ``capacity`` orders/day of its brand's share (max-flow, as in v1).
- **Calibration.** Category demand is backed out so that, with today's networks, the leader's
  share of it equals v1's calibrated orders for the leader in every hex it covers (and its average
  share elsewhere). The game changes the leader's orders only through changes in share.
- **Leader** adds ``k`` stores; **followers** each respond with their own stores after seeing them.
  Two follower models: *rational* (greedily maximise own served orders) and *behavioural* (place
  where the brand's fitted revealed-demand model says it would -- see revealed_demand.py).
- **Leader strategies:** *naive* (greedy on own orders, competitors frozen) vs *response-aware*
  (greedy where each candidate is scored after the anticipated follower response).

It measures strategy under stated assumptions, not a forecast of what Zepto will do.
"""
from __future__ import annotations

import heapq
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
from scipy import sparse

from planner.revealed_demand import CityData, FittedModel, greedy_place, haversine_km, structural_gain
from planner.rollout import ServiceNetwork

WITHIN_HEX_KM = 0.32   # mean distance from a res-8 hex centre to a point in it (floor for Huff distances)

Added = Mapping[str, Sequence[int]]


def huff_weights(lat: np.ndarray, lng: np.ndarray, reach: sparse.csr_matrix, beta: float = 2.0,
                 min_km: float = WITHIN_HEX_KM) -> sparse.csr_matrix:
    """Sparse (store cell x demand cell) Huff weights 1 / max(d, min_km)^beta on the reach pattern."""
    coo = sparse.coo_matrix(reach)
    d = np.maximum(haversine_km(lat[coo.row], lng[coo.row], lat[coo.col], lng[coo.col]), min_km)
    return sparse.csr_matrix((d ** -beta, (coo.row, coo.col)), shape=reach.shape)


@dataclass
class Market:
    """One city: every brand's stores, Huff weights, category demand and store capacity."""
    reach: sparse.csr_matrix
    weights: sparse.csr_matrix
    existing: dict[str, np.ndarray]           # brand -> one cell index per existing store
    category_demand: np.ndarray
    capacity: float
    nets: dict[str, ServiceNetwork] = field(init=False, repr=False)
    _base: dict[str, np.ndarray] = field(init=False, repr=False)

    def __post_init__(self):
        self.nets = {b: ServiceNetwork(self.reach, cells, self.capacity) for b, cells in self.existing.items()}
        self._base = {b: self._pull(cells) for b, cells in self.existing.items()}

    @property
    def brands(self) -> list[str]:
        return list(self.existing)

    def _pull(self, cells: Sequence[int]) -> np.ndarray:
        cells = np.asarray(list(cells), dtype=int)
        return np.asarray(self.weights[cells].sum(axis=0)).ravel() if len(cells) else np.zeros(self.weights.shape[1])

    def shares(self, added: Added | None = None) -> dict[str, np.ndarray]:
        """Each brand's share of category demand per cell (0 where no store of any brand reaches)."""
        added = added or {}
        pulls = {b: self._base[b] + self._pull(added.get(b, ())) for b in self.brands}
        total = sum(pulls.values())
        with np.errstate(invalid="ignore", divide="ignore"):
            return {b: np.where(total > 0, pull / total, 0.0) for b, pull in pulls.items()}

    def served(self, brand: str, added: Added | None = None, shares: Mapping[str, np.ndarray] | None = None) -> float:
        """Orders/day ``brand`` serves: its demand share, capped by its stores' capacity."""
        added = added or {}
        shares = shares or self.shares(added)
        return self.nets[brand].served(self.category_demand * shares[brand], added.get(brand, ()))

    def served_all(self, added: Added | None = None) -> dict[str, float]:
        sh = self.shares(added)
        return {b: self.served(b, added, sh) for b in self.brands}


def calibrate_category_demand(leader_orders: np.ndarray, leader_share: np.ndarray) -> np.ndarray:
    """Category demand such that leader_share x demand = the leader's calibrated orders.

    Where the leader has no store in reach its calibrated orders are what it *would* get, so they
    are grossed up by its average share where it does operate.
    """
    covered = leader_share > 0
    typical = float(np.average(leader_share[covered], weights=leader_orders[covered])) if covered.any() else 1.0
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(covered, leader_orders / np.where(covered, leader_share, 1.0), leader_orders / typical)


# --------------------------------------------------------------------------------------------
# Followers
# --------------------------------------------------------------------------------------------

def rational_response(market: Market, brand: str, n: int, candidates: Sequence[int], added: Added) -> list[int]:
    """``brand`` adds ``n`` stores, each maximising its own served orders given everything else.

    Lazy greedy (a candidate's last gain is used as a bound). With market shares the objective is
    not exactly submodular, so this is a heuristic best response, stated as such.
    """
    chosen: list[int] = []

    def with_me(extra: list[int]) -> dict[str, list[int]]:
        out = {b: list(v) for b, v in added.items()}
        out[brand] = list(added.get(brand, ())) + extra
        return out

    current = market.served(brand, with_me([]))
    heap = [(-np.inf, k, c) for k, c in enumerate(candidates)]
    heapq.heapify(heap)
    while len(chosen) < n and heap:
        while True:
            _, order, c = heapq.heappop(heap)
            value = market.served(brand, with_me(chosen + [c]))
            gain = value - current
            if not heap or gain >= -heap[0][0] - 1e-9:
                break
            heapq.heappush(heap, (-gain, order, c))
        if gain <= 0:
            break
        chosen.append(c)
        current = value
    return chosen


def behavioural_response(data: CityData, model: FittedModel, brand: str, n: int, all_brands: Sequence[str],
                         added: Added) -> list[int]:
    """``brand`` adds ``n`` stores where its fitted revealed-demand model expects them, given every
    brand's current stores plus the ``added`` ones (so co-location with new rivals is included)."""
    comp = sum((data.stores[b] for b in all_brands if b != brand), np.zeros(len(data.cells)))
    for b, cells in added.items():
        if b != brand:
            np.add.at(comp, np.asarray(list(cells), dtype=int), 1.0)
    own = data.stores[brand].copy()
    np.add.at(own, np.asarray(list(added.get(brand, ())), dtype=int), 1.0)
    return greedy_place(data, n, structural_gain(model, data, data.reach @ comp), initial_own=own)


Response = Callable[[Added], dict[str, list[int]]]


def sequential_response(followers: Sequence[str], respond_one: Callable[[str, Added], list[int]]) -> Response:
    """Followers respond one after another, each seeing the leader's and earlier followers' stores."""
    def respond(added: Added) -> dict[str, list[int]]:
        state = {b: list(v) for b, v in added.items()}
        out: dict[str, list[int]] = {}
        for f in followers:
            picks = respond_one(f, state)
            out[f] = picks
            state[f] = list(state.get(f, ())) + picks
        return out
    return respond


# --------------------------------------------------------------------------------------------
# Leader
# --------------------------------------------------------------------------------------------

@dataclass
class LeaderPick:
    site: int
    leader_orders_after: float     # leader's served orders/day with this plan (after response, if any)
    response: dict[str, list[int]]


def leader_plan(market: Market, leader: str, candidates: Sequence[int], k: int,
                response: Response | None = None) -> list[LeaderPick]:
    """Greedy leader: each step adds the candidate with the highest leader orders, where a candidate
    is scored *after* ``response`` to the plan-so-far plus that candidate (naive when ``response`` is
    None, i.e. competitors frozen)."""
    plan: list[LeaderPick] = []

    def score(c: int) -> tuple[float, dict[str, list[int]]]:
        mine = [p.site for p in plan] + [c]
        reply = response({leader: mine}) if response else {}
        return market.served(leader, {leader: mine, **reply}), reply

    for _ in range(k):
        pool = [c for c in candidates if c not in {p.site for p in plan}]
        if not pool:
            break
        results = [score(c) for c in pool]
        best = int(np.argmax([r[0] for r in results]))
        plan.append(LeaderPick(pool[best], results[best][0], results[best][1]))
    return plan


def screen(market: Market, brand: str, cells: Sequence[int], keep: int, added: Added | None = None) -> list[int]:
    """The ``keep`` cells with the highest single-store gain in ``brand``'s served orders."""
    added = added or {}
    base = market.served(brand, added)
    gains = []
    for c in cells:
        a = {b: list(v) for b, v in added.items()}
        a[brand] = list(a.get(brand, ())) + [c]
        gains.append(market.served(brand, a) - base)
    order = np.argsort(-np.asarray(gains), kind="stable")[:keep]
    return [int(cells[i]) for i in order]
