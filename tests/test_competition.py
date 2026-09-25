import h3
import numpy as np
import pandas as pd
import pytest

from planner.competition import (
    Market, behavioural_response, calibrate_category_demand, huff_weights, leader_plan, rational_response, screen,
    sequential_response,
)
from planner.revealed_demand import STRUCTURAL, FittedModel, build_city_data, reach_matrix

RADIUS = 1.625


def _market(seed=0, rings=7, stores=(6, 5, 4), capacity=1500.0):
    rng = np.random.default_rng(seed)
    cells = sorted(h3.grid_disk(h3.latlng_to_cell(17.40, 78.45, 8), rings))
    ll = np.array([h3.cell_to_latlng(c) for c in cells])
    reach = reach_matrix(cells, RADIUS)
    existing = {b: rng.choice(len(cells), n, replace=False) for b, n in zip(("L", "F1", "F2"), stores)}
    demand = rng.gamma(2.0, 150.0, len(cells))
    return cells, ll, Market(reach, huff_weights(ll[:, 0], ll[:, 1], reach), existing, demand, capacity)


def test_shares_sum_to_one_where_served_and_closer_store_wins():
    _, ll, m = _market()
    sh = m.shares()
    total = sum(sh.values())
    served = total > 0
    assert np.allclose(total[served], 1.0) and np.all(total[~served] == 0)
    # a brand with a store *in* the hex beats a rival whose only store is a ring away
    cell = int(m.existing["L"][0])
    assert sh["L"][cell] >= max(sh["F1"][cell], sh["F2"][cell])


def test_calibration_reproduces_the_leaders_orders():
    _, _, m = _market(seed=1)
    orders = np.random.default_rng(1).gamma(2.0, 80.0, len(m.category_demand))
    share = m.shares()["L"]
    demand = calibrate_category_demand(orders, share)
    covered = share > 0
    assert demand[covered] * share[covered] == pytest.approx(orders[covered])
    assert np.all(demand >= orders - 1e-9)


def test_competitor_entry_never_raises_the_leaders_orders_and_own_entry_never_lowers_them():
    _, _, m = _market(seed=2)
    base = m.served("L")
    rng = np.random.default_rng(3)
    for _ in range(10):
        c = int(rng.integers(len(m.category_demand)))
        assert m.served("L", {"F1": [c]}) <= base + 1e-6
        assert m.served("L", {"L": [c]}) >= base - 0.2


def test_rational_response_improves_the_followers_orders():
    _, _, m = _market(seed=4)
    cands = screen(m, "F1", list(range(len(m.category_demand))), 25)
    picks = rational_response(m, "F1", 3, cands, {"L": [10]})
    assert 0 < len(picks) <= 3 and len(set(picks)) == len(picks)
    assert m.served("F1", {"L": [10], "F1": picks}) > m.served("F1", {"L": [10]})


def test_sequential_response_lets_later_followers_see_earlier_ones():
    _, _, m = _market(seed=5)
    cands = list(range(len(m.category_demand)))
    seen = []

    def one(brand, state):
        seen.append((brand, {b: list(v) for b, v in state.items()}))
        return [cands[len(seen)]]

    out = sequential_response(["F1", "F2"], one)({"L": [0]})
    assert out == {"F1": [cands[1]], "F2": [cands[2]]}
    assert seen[1][1]["F1"] == [cands[1]]


def test_naive_leader_plan_is_greedy_on_own_orders():
    _, _, m = _market(seed=6)
    cands = screen(m, "L", list(range(len(m.category_demand))), 15)
    plan = leader_plan(m, "L", cands, 3)
    assert [p.response for p in plan] == [{}, {}, {}]
    assert plan[0].leader_orders_after == pytest.approx(max(m.served("L", {"L": [c]}) for c in cands))
    assert plan[-1].leader_orders_after >= plan[0].leader_orders_after - 1e-6


def test_response_aware_leader_does_at_least_as_well_under_that_response_on_step_one():
    _, _, m = _market(seed=7)
    all_cells = list(range(len(m.category_demand)))
    cands = screen(m, "L", all_cells, 12)
    f_cands = {f: screen(m, f, all_cells, 15) for f in ("F1", "F2")}
    resp = sequential_response(["F1", "F2"], lambda f, st: rational_response(m, f, 2, f_cands[f], st))
    naive = leader_plan(m, "L", cands, 1)
    aware = leader_plan(m, "L", cands, 1, resp)

    def after(site):
        mine = {"L": [site]}
        return m.served("L", {**mine, **resp(mine)})

    assert after(aware[0].site) >= after(naive[0].site) - 1e-6


def test_behavioural_response_follows_the_fitted_model():
    cells, ll, m = _market(seed=8)
    feats = pd.DataFrame({"h3": cells, "in_study_area": True, "f1": np.random.default_rng(8).normal(size=len(cells))})
    stores = pd.DataFrame([{"brand": b, "lat": ll[c, 0], "lng": ll[c, 1]} for b, cs in m.existing.items() for c in cs])
    data = build_city_data("x", feats, stores, RADIUS, ("f1",), (), ("L", "F1", "F2"))
    attract = FittedModel(STRUCTURAL, ("f1",), np.zeros(1), gamma=3.0, lam=-3.0, alpha=np.zeros(1), groups=[],
                          neg_loglik=0.0, n_obs=0, converged=True)
    target = 5
    near = behavioural_response(data, attract, "F1", 1, ("L", "F1", "F2"), {"L": [target] * 6})
    d = np.hypot(*(ll[near[0]] - ll[target])) * 111
    assert d <= RADIUS  # a co-locating follower moves next to the leader's new cluster
