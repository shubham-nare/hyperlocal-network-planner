import h3
import numpy as np
import pandas as pd
import pytest

from planner.revealed_demand import (
    LADDER, STRUCTURAL, FittedModel, build_city_data, fit, greedy_place, haversine_km, make_terms,
    negative_log_pseudolikelihood, random_recall, reach_matrix, recall_within, structural_gain, top_k,
    uncovered_gain,
)

RES = 8
CENTRE = (17.40, 78.45)
RADIUS_KM = 1.625


def _synthetic_city(seed: int, rings: int = 14, buffer: int = 3):
    rng = np.random.default_rng(seed)
    centre = h3.latlng_to_cell(*CENTRE, RES)
    cells = sorted(h3.grid_disk(centre, rings + buffer))
    study = set(h3.grid_disk(centre, rings))
    # spatially smooth features so demand has structure a catchment can see
    ll = np.array([h3.cell_to_latlng(c) for c in cells])
    f1 = np.sin(ll[:, 0] * 90) + np.cos(ll[:, 1] * 70) + 0.3 * rng.normal(size=len(cells))
    f2 = rng.normal(size=len(cells))
    features = pd.DataFrame({"h3": cells, "in_study_area": [c in study for c in cells], "f1": f1, "f2": f2})
    return features


def _empty_data(features, brands=("A", "B", "C")):
    stores = pd.DataFrame({"brand": [], "lat": [], "lng": []})
    return build_city_data("synth", features, stores, RADIUS_KM, ("f1", "f2"), (), brands)


def _gibbs(data, theta, gamma, lam, alpha, brands, sweeps, seed):
    """Sample networks from the model's own conditionals (so pseudo-likelihood is consistent)."""
    rng = np.random.default_rng(seed)
    study = data.study_idx
    for b in brands:
        data.stores[b][:] = 0
    q = np.exp(data.z @ theta)
    reach = data.reach.tocsr()
    for _ in range(sweeps):
        for b in brands:
            comp = sum((data.stores[c] for c in brands if c != b), np.zeros(len(data.cells)))
            comp_cov = reach @ comp
            own = data.stores[b]
            for i in rng.permutation(study):
                own[i] = 0
                own_cov = reach @ own
                nbrs = reach.indices[reach.indptr[i]:reach.indptr[i + 1]]
                v = np.sum(q[nbrs] * (1 + own_cov[nbrs]) ** (-gamma) * (1 + comp_cov[nbrs]) ** (-lam))
                p = 1 / (1 + np.exp(-(alpha + np.log(v))))
                own[i] = float(rng.random() < p)
    return data


def test_haversine_known_distance():
    # 1 degree of latitude ~ 111.2 km
    assert haversine_km(17.0, 78.0, 18.0, 78.0) == pytest.approx(111.2, rel=0.01)


def test_reach_matrix_is_symmetric_with_diagonal_and_respects_radius():
    cells = sorted(h3.grid_disk(h3.latlng_to_cell(*CENTRE, RES), 5))
    a = reach_matrix(cells, RADIUS_KM)
    assert (a != a.T).nnz == 0
    assert np.all(a.diagonal() == 1)
    ll = np.array([h3.cell_to_latlng(c) for c in cells])
    i, j = a.nonzero()
    assert haversine_km(ll[i, 0], ll[i, 1], ll[j, 0], ll[j, 1]).max() <= RADIUS_KM + 1e-9
    # and nothing within the radius is missed
    d = haversine_km(ll[:, None, 0], ll[:, None, 1], ll[None, :, 0], ll[None, :, 1])
    assert a.nnz == int((d <= RADIUS_KM + 1e-9).sum())


def test_build_city_data_counts_stores_per_cell_and_drops_outside():
    features = _synthetic_city(0, rings=4, buffer=1)
    cell = features.loc[features["in_study_area"], "h3"].iloc[0]
    lat, lng = h3.cell_to_latlng(cell)
    stores = pd.DataFrame({"brand": ["A", "A", "B", "A"], "lat": [lat, lat, lat, 0.0], "lng": [lng, lng, lng, 0.0]})
    data = build_city_data("x", features, stores, RADIUS_KM, ("f1", "f2"), (), ("A", "B"))
    k = data.cells.index(cell)
    assert data.stores["A"][k] == 2 and data.stores["A"].sum() == 2  # the (0,0) store is outside
    assert data.stores["B"][k] == 1
    assert list(data.occupied("A")) == [k]
    assert np.allclose(data.z.mean(axis=0), 0, atol=1e-9)


@pytest.mark.parametrize("spec", LADDER, ids=lambda s: s.name)
def test_gradient_matches_finite_differences(spec):
    data = _gibbs(_empty_data(_synthetic_city(1, rings=6)), np.array([0.8, -0.4]), 1.0, 0.5, -2.0, ("A", "B", "C"), 3, 1)
    terms = [make_terms(data, b, [c for c in "ABC" if c != b], k, spec) for k, b in enumerate("ABC")]
    rng = np.random.default_rng(3)
    x = np.concatenate([rng.normal(scale=0.3, size=2), [0.7 if spec.own_spacing else 0.0, 0.4 if spec.competition else 0.0],
                        rng.normal(-2, 0.2, size=3)])
    _, g = negative_log_pseudolikelihood(x, terms, spec, ridge=0.5)
    eps = 1e-6
    for k in range(len(x)):
        if (k == 2 and not spec.own_spacing) or (k == 3 and not spec.competition):
            continue
        up, dn = x.copy(), x.copy()
        up[k] += eps
        dn[k] -= eps
        num = (negative_log_pseudolikelihood(up, terms, spec, 0.5)[0] - negative_log_pseudolikelihood(dn, terms, spec, 0.5)[0]) / (2 * eps)
        assert g[k] == pytest.approx(num, rel=1e-4, abs=1e-5)


def test_fit_recovers_parameters_from_networks_simulated_by_the_model():
    true_theta, true_gamma, true_lam = np.array([1.0, -0.5]), 1.5, 0.6
    datasets = {}
    for s in range(3):
        d = _gibbs(_empty_data(_synthetic_city(10 + s)), true_theta, true_gamma, true_lam, -2.5, ("A", "B", "C"), 8, s)
        d.city = f"c{s}"
        datasets[d.city] = d
    model = fit(datasets, {c: ("A", "B", "C") for c in datasets}, ridge=0.0)
    assert model.converged
    assert model.theta == pytest.approx(true_theta, abs=0.3)
    assert model.gamma == pytest.approx(true_gamma, abs=0.6)
    assert model.lam == pytest.approx(true_lam, abs=0.4)


def test_independent_model_is_plain_logistic_on_own_features():
    data = _gibbs(_empty_data(_synthetic_city(2, rings=8)), np.array([1.0, 0.0]), 1.0, 0.0, -2.0, ("A",), 4, 2)
    model = fit({"synth": data}, {"synth": ("A",)}, spec=LADDER[0], ridge=0.0)
    from sklearn.linear_model import LogisticRegression
    study = data.study_idx
    y = (data.stores["A"][study] > 0).astype(int)
    ref = LogisticRegression(C=1e9, max_iter=5000).fit(data.z[study], y)
    assert model.theta == pytest.approx(ref.coef_[0], abs=1e-3)


def _model(theta, gamma, lam=0.0):
    return FittedModel(spec=STRUCTURAL, feature_names=("f1", "f2"), theta=np.asarray(theta, float), gamma=gamma,
                       lam=lam, alpha=np.zeros(1), groups=[], neg_loglik=0.0, n_obs=0, converged=True)


def _mean_nearest_km(data, idx):
    d = haversine_km(data.lat[idx][:, None], data.lng[idx][:, None], data.lat[idx][None], data.lng[idx][None])
    np.fill_diagonal(d, np.inf)
    return d.min(axis=1).mean()


def test_greedy_with_spacing_spreads_stores_but_independent_ranking_clusters():
    data = _empty_data(_synthetic_city(4))
    # one broad demand peak: ranking hexes independently piles stores onto it
    data.z[:, 0] = -haversine_km(data.lat, data.lng, *CENTRE)
    data.z[:, 1] = 0.0
    no_comp = np.zeros(len(data.cells))
    k = 8
    spaced = greedy_place(data, k, structural_gain(_model([0.7, 0.0], gamma=3.0), data, no_comp))
    unspaced = greedy_place(data, k, structural_gain(_model([0.7, 0.0], gamma=0.0), data, no_comp))
    clustered = top_k(data, data.z[:, 0], k)
    assert len(set(spaced)) == k and all(data.in_study[i] for i in spaced)
    assert _mean_nearest_km(data, spaced) > 1.5 * _mean_nearest_km(data, clustered)
    assert _mean_nearest_km(data, spaced) > 1.5 * _mean_nearest_km(data, unspaced)


def test_competitor_term_pushes_placement_away_from_or_towards_competitors():
    data = _empty_data(_synthetic_city(7))
    data.z[:, :] = 0.0  # flat demand: only the competitor term differentiates sites
    rival = np.zeros(len(data.cells))
    rival[data.study_idx[:40]] = 1
    comp_cov = data.reach @ rival

    def mean_comp_cov(lam):
        chosen = greedy_place(data, 6, structural_gain(_model([0.0, 0.0], gamma=1.0, lam=lam), data, comp_cov))
        return comp_cov[chosen].mean()

    assert mean_comp_cov(2.0) < mean_comp_cov(0.0) < mean_comp_cov(-2.0)


def test_uncovered_gain_never_double_covers_until_it_must():
    data = _empty_data(_synthetic_city(5, rings=10))
    chosen = greedy_place(data, 5, uncovered_gain(np.exp(data.z[:, 0])))
    d = haversine_km(data.lat[chosen][:, None], data.lng[chosen][:, None], data.lat[chosen][None], data.lng[chosen][None])
    np.fill_diagonal(d, np.inf)
    assert d.min() > RADIUS_KM  # catchments of the first few stores don't overlap on a big enough map


def test_recall_within_and_random_baseline():
    data = _empty_data(_synthetic_city(6, rings=6))
    study = data.study_idx
    actual = list(study[:5])
    assert recall_within(data, actual, actual, 0.1) == 1.0
    assert recall_within(data, [], actual, 1.0) == 0.0
    assert np.isnan(recall_within(data, actual, [], 1.0))
    r = random_recall(data, 5, actual, 1.0, draws=50)
    assert 0.0 <= r <= 1.0


def test_conditional_log_odds_matches_the_likelihood_and_whitespace_excludes_occupied():
    from planner.revealed_demand import conditional_log_odds, whitespace
    datasets = {"synth": _gibbs(_empty_data(_synthetic_city(8, rings=8)), np.array([0.8, 0.0]), 1.5, 0.3, -2.0,
                                ("A", "B", "C"), 4, 8)}
    model = fit(datasets, {"synth": ("A", "B", "C")})
    data = datasets["synth"]
    lo = conditional_log_odds(model, data, "A", ("B", "C"))
    y = (data.stores["A"][data.study_idx] > 0).astype(float)
    # the likelihood the fit minimised, recomputed from the exposed log-odds (ridge added back)
    per_brand = []
    for b in ("A", "B", "C"):
        l = conditional_log_odds(model, data, b, [c for c in "ABC" if c != b])
        yb = (data.stores[b][data.study_idx] > 0).astype(float)
        per_brand.append(-np.sum(yb * l - np.logaddexp(0, l)))
    assert sum(per_brand) + 0.5 * model.theta @ model.theta == pytest.approx(model.neg_loglik, rel=1e-6)
    ws = whitespace(model, data, "A", ("B", "C"), n=5)
    assert len(ws) == 5 and ws["probability"].is_monotonic_decreasing
    occupied = {data.cells[i] for i in data.occupied("A")}
    assert not occupied & set(ws["h3"])
    d = haversine_km(ws["lat"].to_numpy()[:, None], ws["lng"].to_numpy()[:, None], ws["lat"].to_numpy()[None], ws["lng"].to_numpy()[None])
    np.fill_diagonal(d, np.inf)
    assert d.min() > 1.5  # one gap is not listed twice
    assert lo.shape == y.shape
