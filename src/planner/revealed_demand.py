"""Revealed demand: recover the demand map implied by where operators actually put their stores.

Blinkit, Zepto and Instamart each site stores using order data nobody outside can see. Their
networks are therefore evidence about that demand -- but only if you model how a network is
built. Phase 1 (``ml_demand.py``) asked "does this hex have a store?" hex by hex, and got R2 ~ 0.
A hex with excellent demand frequently has *no* store precisely because a sibling store 1.5 km
away already covers it, so an independent-hex model reads deliberate spacing as noise.

This module treats each brand's network as the output of a coverage-maximising operator and asks
which demand weights make the observed network look like a good one. The model (an
auto-logistic / spatial-entry model, estimated by pseudo-likelihood):

    logit P(brand b has a store in hex i | the rest of every network)
        = alpha[b, city] + log V_bi

    V_bi = sum_{j within reach of i}  q_j * (1 + own_bj(-i))^(-gamma) * (1 + comp_bj)^(-lambda)
    q_j  = exp(theta . z_j)            (latent demand from public features z_j)

- ``own_bj(-i)``: how many of b's *other* stores already reach hex j (cannibalisation).
- ``comp_bj``: how many competitor stores reach hex j.
- ``theta`` is the recovered demand map; ``gamma`` > 0 means operators space their own stores
  out; ``lambda`` > 0 means they avoid competitors, < 0 means they co-locate with them.
- Odds proportional to marginal catchment value is the local-optimality condition of a
  covering problem, softened so that it can be fitted: this is inverse optimisation in
  likelihood form.

What it is not: no order data exists here, so ``q`` is demand *as revealed by operator
behaviour*, not measured demand. If operators are systematically wrong somewhere, so is ``q``.
The test that matters is out-of-sample: hide a brand (or a city), re-place its network with the
fitted model, and measure how close the placed network lands to the real one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable, Mapping, Sequence

import h3
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import minimize

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1, lng1, lat2, lng2) -> np.ndarray:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dlat, dlng = p2 - p1, np.radians(np.asarray(lng2) - np.asarray(lng1))
    a = np.sin(dlat / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def reach_matrix(cells: Sequence[str], radius_km: float) -> sparse.csr_matrix:
    """Symmetric 0/1 matrix: 1 where hex centres are within ``radius_km`` (diagonal included)."""
    index = {c: k for k, c in enumerate(cells)}
    res = h3.get_resolution(cells[0])
    spacing = h3.average_hexagon_edge_length(res, unit="km") * np.sqrt(3)
    k = int(np.ceil(radius_km / spacing)) + 1
    centres = [h3.cell_to_latlng(c) for c in cells]
    rows, cols = [], []
    for a, cell in enumerate(cells):
        near = [index[n] for n in h3.grid_disk(cell, k) if n in index]
        la, ln = centres[a]
        d = haversine_km(la, ln, np.array([centres[b][0] for b in near]), np.array([centres[b][1] for b in near]))
        for b, dist in zip(near, d):
            if dist <= radius_km + 1e-9:
                rows.append(a)
                cols.append(b)
    return sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(cells), len(cells)))


@dataclass
class CityData:
    """Everything the model needs for one city, over *context* cells (study area + buffer ring)."""
    city: str
    cells: list[str]
    lat: np.ndarray
    lng: np.ndarray
    in_study: np.ndarray            # bool, len(cells)
    z: np.ndarray                   # (n_cells, n_features), standardised within city
    feature_names: tuple[str, ...]
    reach: sparse.csr_matrix        # (n_cells, n_cells)
    stores: dict[str, np.ndarray]   # brand -> store count per cell
    raw: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)

    @property
    def study_idx(self) -> np.ndarray:
        return np.flatnonzero(self.in_study)

    def occupied(self, brand: str) -> np.ndarray:
        """Study-area cell indices where ``brand`` has at least one store."""
        idx = self.study_idx
        return idx[self.stores[brand][idx] > 0]


def standardise(features: pd.DataFrame, log_columns: Sequence[str]) -> np.ndarray:
    """log1p the count-like columns, then z-score every column within the city (constant -> 0)."""
    x = features.astype(float).copy()
    for col in log_columns:
        x[col] = np.log1p(x[col].clip(lower=0))
    sd = x.std(ddof=0).replace(0, 1.0)
    return ((x - x.mean()) / sd).to_numpy(dtype=float, copy=True)


def build_city_data(city: str, features: pd.DataFrame, stores: pd.DataFrame, radius_km: float,
                    feature_columns: Sequence[str], log_columns: Sequence[str], brands: Sequence[str]) -> CityData:
    """``features``: one row per context cell with ``h3``, ``in_study_area`` and the feature columns.
    ``stores``: one row per real store with ``brand``, ``lat``, ``lng`` (stores outside the context
    cells are dropped; they cannot reach the study area when the buffer is wider than the reach)."""
    features = features.sort_values("h3").reset_index(drop=True)
    cells = features["h3"].tolist()
    res = h3.get_resolution(cells[0])
    index = {c: k for k, c in enumerate(cells)}
    counts = {}
    for brand in brands:
        sub = stores[stores["brand"] == brand]
        m = np.zeros(len(cells))
        for la, ln in zip(sub["lat"], sub["lng"]):
            k = index.get(h3.latlng_to_cell(la, ln, res))
            if k is not None:
                m[k] += 1
        counts[brand] = m
    latlng = np.array([h3.cell_to_latlng(c) for c in cells])
    return CityData(
        city=city, cells=cells, lat=latlng[:, 0], lng=latlng[:, 1],
        in_study=features["in_study_area"].to_numpy(bool),
        z=standardise(features[list(feature_columns)], [c for c in log_columns if c in feature_columns]),
        feature_names=tuple(feature_columns), reach=reach_matrix(cells, radius_km), stores=counts, raw=features,
    )


COUNT_COLUMNS = ("density_per_km2", "office", "education", "food_retail", "residential_highrise", "buildings")


def load_features(city: str, source: str = "open", processed_dir: str = "data/processed") -> pd.DataFrame:
    """Per-hex features for one city plus ``distance_to_center_km`` (population-weighted centre).

    ``open``: the Overture + Meta HRSL parquet from build_open_features.py (study area + buffer ring).
    ``v1``: the original WorldPop/OSM ``{city}_demand_r8.gpkg`` (study area only).
    """
    if source == "open":
        df = pd.read_parquet(f"{processed_dir}/{city}_open_features_r8.parquet")
    else:
        import geopandas as gpd
        df = pd.DataFrame(gpd.read_file(f"{processed_dir}/{city}_demand_r8.gpkg").drop(columns="geometry"))
        df["in_study_area"] = True
        df["lat"], df["lng"] = zip(*df["h3"].map(h3.cell_to_latlng))
    study = df[df["in_study_area"]]
    w = study["population"].clip(lower=0)
    centre = (np.average(study["lat"], weights=w), np.average(study["lng"], weights=w))
    df["distance_to_center_km"] = haversine_km(df["lat"].to_numpy(), df["lng"].to_numpy(), *centre)
    return df


def feature_columns(df: pd.DataFrame) -> tuple[str, ...]:
    return tuple(c for c in COUNT_COLUMNS if c in df.columns) + ("distance_to_center_km",)


# --------------------------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelSpec:
    """Which pieces of the structural model are switched on (the ablation ladder).

    - ``catchment=False``: V_i = q_i, i.e. plain logistic regression on the hex's own features
      (the Phase 1 "independent hex" view, in likelihood form).
    - ``catchment=True`` only: demand anywhere in reach counts, no interaction between stores.
    - ``+ own_spacing``: gamma (cannibalisation of a brand's own stores).
    - ``+ competition``: lambda (reaction to competitor coverage).
    - ``demand_features=False``: theta pinned at 0 -- spacing and competitors only, no public
      demand features. The control for "is the model just copying competitors?".
    """
    name: str
    catchment: bool = True
    own_spacing: bool = True
    competition: bool = True
    demand_features: bool = True


STRUCTURAL = ModelSpec("structural")
LADDER = (
    ModelSpec("own_hex_logit", catchment=False, own_spacing=False, competition=False),
    ModelSpec("catchment", own_spacing=False, competition=False),
    ModelSpec("catchment+spacing", competition=False),
    ModelSpec("spacing+competition_no_features", demand_features=False),
    STRUCTURAL,
)


@dataclass
class Terms:
    """Pseudo-likelihood terms for one (brand, city): one row per study-area cell."""
    city: str
    brand: str
    group: int                      # index into alpha
    rows: np.ndarray                # study-area cell indices
    y: np.ndarray                   # 1 if the brand has a store there
    m: np.ndarray                   # the brand's store count at that cell (removed from own coverage)
    own_cov: np.ndarray             # per context cell: brand's stores reaching it (all of them)
    comp_cov: np.ndarray            # per context cell: visible competitor stores reaching it
    reach_rows: sparse.csr_matrix   # reach restricted to ``rows`` (or identity rows if no catchment)
    z: np.ndarray                   # city features


def make_terms(data: CityData, brand: str, competitors: Sequence[str], group: int, spec: ModelSpec) -> Terms:
    rows = data.study_idx
    m_all = data.stores[brand]
    comp_m = sum((data.stores[c] for c in competitors), np.zeros(len(data.cells)))
    if spec.catchment:
        reach_rows = data.reach[rows]
        own_cov, comp_cov = data.reach @ m_all, data.reach @ comp_m
    else:
        reach_rows = sparse.csr_matrix((np.ones(len(rows)), (np.arange(len(rows)), rows)), shape=(len(rows), len(data.cells)))
        own_cov, comp_cov = m_all.copy(), comp_m.copy()
    return Terms(city=data.city, brand=brand, group=group, rows=rows, y=(m_all[rows] > 0).astype(float),
                 m=m_all[rows], own_cov=own_cov, comp_cov=comp_cov, reach_rows=reach_rows, z=data.z)


@dataclass
class FittedModel:
    spec: ModelSpec
    feature_names: tuple[str, ...]
    theta: np.ndarray
    gamma: float
    lam: float
    alpha: np.ndarray
    groups: list[tuple[str, str]]   # (city, brand) per alpha entry
    neg_loglik: float
    n_obs: int
    converged: bool

    def coefficients(self) -> pd.Series:
        vals = dict(zip(self.feature_names, self.theta))
        if self.spec.own_spacing:
            vals["gamma_own_spacing"] = self.gamma
        if self.spec.competition:
            vals["lambda_competition"] = self.lam
        return pd.Series(vals)


def _eta_and_grad_parts(t: Terms, theta: np.ndarray, gamma: float, lam: float, spec: ModelSpec, need_grad: bool):
    """Return log V for each term row, and (optionally) dlogV/dtheta, dlogV/dgamma, dlogV/dlambda."""
    q = np.exp(np.clip(t.z @ theta, -50, 50))
    comp_w = (1.0 + t.comp_cov) ** (-lam) if spec.competition else np.ones_like(q)
    log_v = np.empty(len(t.rows))
    d_theta = np.empty((len(t.rows), len(theta))) if need_grad else None
    d_gamma = np.zeros(len(t.rows)) if need_grad else None
    d_lam = np.zeros(len(t.rows)) if need_grad else None
    # own coverage excluding the brand's own stores at i: own_cov_j - m_i for every j reached from i
    for mval in np.unique(t.m) if spec.own_spacing else [None]:
        sel = np.flatnonzero(t.m == mval) if mval is not None else np.arange(len(t.rows))
        if spec.own_spacing:
            base = np.maximum(1.0 + t.own_cov - mval, 1.0)
            own_w = base ** (-gamma)
        else:
            base, own_w = None, 1.0
        wq = q * own_w * comp_w
        r = t.reach_rows[sel]
        v = r @ wq
        log_v[sel] = np.log(v)
        if need_grad:
            d_theta[sel] = (r @ (wq[:, None] * t.z)) / v[:, None]
            if spec.own_spacing:
                d_gamma[sel] = (r @ (wq * -np.log(base))) / v
            if spec.competition:
                d_lam[sel] = (r @ (wq * -np.log1p(t.comp_cov))) / v
    return log_v, d_theta, d_gamma, d_lam


def _unpack(params: np.ndarray, p: int, spec: ModelSpec):
    theta = params[:p]
    gamma = params[p] if spec.own_spacing else 0.0
    lam = params[p + 1] if spec.competition else 0.0
    return theta, gamma, lam, params[p + 2:]


def negative_log_pseudolikelihood(params: np.ndarray, terms: Sequence[Terms], spec: ModelSpec, ridge: float,
                                  weights: Sequence[np.ndarray] | None = None) -> tuple[float, np.ndarray]:
    p = terms[0].z.shape[1]
    theta, gamma, lam, alpha = _unpack(params, p, spec)
    nll, grad = 0.0, np.zeros_like(params)
    for k, t in enumerate(terms):
        w = np.ones(len(t.rows)) if weights is None else weights[k]
        log_v, d_theta, d_gamma, d_lam = _eta_and_grad_parts(t, theta, gamma, lam, spec, need_grad=True)
        eta = alpha[t.group] + log_v
        nll -= float(np.sum(w * (t.y * eta - np.logaddexp(0.0, eta))))
        resid = w * (1.0 / (1.0 + np.exp(-eta)) - t.y)       # d nll / d eta
        grad[:p] += d_theta.T @ resid
        if spec.own_spacing:
            grad[p] += d_gamma @ resid
        if spec.competition:
            grad[p + 1] += d_lam @ resid
        grad[p + 2 + t.group] += resid.sum()
    nll += 0.5 * ridge * float(theta @ theta)
    grad[:p] += ridge * theta
    return nll, grad


def fit(datasets: Mapping[str, CityData], brands_by_city: Mapping[str, Sequence[str]],
        competitors_by_city: Mapping[str, Sequence[str]] | None = None, spec: ModelSpec = STRUCTURAL,
        ridge: float = 1.0, weights: Mapping[tuple[str, str], np.ndarray] | None = None) -> FittedModel:
    """Maximum pseudo-likelihood over every (city, brand) in ``brands_by_city``.

    ``competitors_by_city`` lists which brands count as visible competitors in each city (default:
    the same brands being fitted). Leaving a brand out of both is how a leave-one-brand-out fold
    hides it completely: it is neither a target nor anyone's competitor during fitting.
    """
    competitors_by_city = competitors_by_city or brands_by_city
    terms, groups = [], []
    for city, brands in brands_by_city.items():
        for brand in brands:
            comps = [b for b in competitors_by_city[city] if b != brand]
            terms.append(make_terms(datasets[city], brand, comps, len(groups), spec))
            groups.append((city, brand))
    p = terms[0].z.shape[1]
    base_rate = np.array([np.clip(t.y.mean(), 1e-3, 1 - 1e-3) for t in terms])
    x0 = np.concatenate([np.zeros(p), [0.0, 0.0], np.log(base_rate / (1 - base_rate))])
    w = [weights[(t.city, t.brand)] for t in terms] if weights else None
    theta_bound = (None, None) if spec.demand_features else (0.0, 0.0)
    bounds = [theta_bound] * p + [(-5.0, 10.0) if spec.own_spacing else (0.0, 0.0),
                                   (-5.0, 10.0) if spec.competition else (0.0, 0.0)] + [(None, None)] * len(terms)
    res = minimize(negative_log_pseudolikelihood, x0, args=(terms, spec, ridge, w), jac=True, method="L-BFGS-B",
                   bounds=bounds, options={"maxiter": 2000})
    theta, gamma, lam, alpha = _unpack(res.x, p, spec)
    return FittedModel(spec=spec, feature_names=datasets[next(iter(datasets))].feature_names, theta=theta.copy(),
                       gamma=float(gamma), lam=float(lam), alpha=alpha.copy(), groups=groups, neg_loglik=float(res.fun),
                       n_obs=int(sum(len(t.rows) for t in terms)), converged=bool(res.success))


def conditional_log_odds(model: FittedModel, data: CityData, brand: str, competitors: Sequence[str]) -> np.ndarray:
    """Fitted logit P(brand has a store in each study cell | everything else), in ``data.study_idx`` order.

    Uses the fitted intercept for (city, brand) when that pair was in the fit, else the mean
    intercept: the intercept only shifts every cell equally, so rankings never depend on it.
    """
    t = make_terms(data, brand, competitors, 0, model.spec)
    log_v, *_ = _eta_and_grad_parts(t, model.theta, model.gamma, model.lam, model.spec, need_grad=False)
    key = (data.city, brand)
    alpha = model.alpha[model.groups.index(key)] if key in model.groups else float(np.mean(model.alpha))
    return alpha + log_v


def whitespace(model: FittedModel, data: CityData, brand: str, competitors: Sequence[str], n: int = 10,
               min_separation_km: float = 1.5) -> pd.DataFrame:
    """Study cells without a ``brand`` store, ranked by how strongly the fitted model expects one there.

    Read as "where everyone else's networks say demand is, and this brand has left a gap" --
    a model output, not a validated forecast of future openings (that needs a later snapshot).
    Listed gaps are at least ``min_separation_km`` apart, so one gap is not listed several times.
    """
    log_odds = conditional_log_odds(model, data, brand, competitors)
    study = data.study_idx
    comp = sum((data.stores[c] for c in competitors), np.zeros(len(data.cells)))
    frame = pd.DataFrame({
        "city": data.city, "brand": brand, "h3": [data.cells[i] for i in study], "lat": data.lat[study],
        "lng": data.lng[study], "probability": 1 / (1 + np.exp(-log_odds)),
        "own_stores_in_reach": (data.reach @ data.stores[brand])[study],
        "competitor_stores_in_reach": (data.reach @ comp)[study],
        "has_store": data.stores[brand][study] > 0,
    })
    ranked = frame[~frame["has_store"]].drop(columns="has_store").sort_values("probability", ascending=False)
    # neighbouring hexes share a catchment and would list one gap several times: keep distinct gaps
    kept: list[int] = []
    for idx, row in ranked.iterrows():
        if all(haversine_km(row["lat"], row["lng"], ranked.at[k, "lat"], ranked.at[k, "lng"]) > min_separation_km for k in kept):
            kept.append(idx)
            if len(kept) == n:
                break
    return ranked.loc[kept].reset_index(drop=True)


# --------------------------------------------------------------------------------------------
# Placement: rebuild a network from a demand map, one store at a time
# --------------------------------------------------------------------------------------------

def greedy_place(data: CityData, k: int, gain: Callable[[np.ndarray], np.ndarray],
                 initial_own: np.ndarray | None = None) -> list[int]:
    """Pick ``k`` distinct study-area cells, each time the one with the highest marginal ``gain``.

    ``gain(own_cov)`` returns, per context cell j, the value a new store gets from covering j given
    how many of the brand's stores already cover it. The marginal value of a candidate i is then
    the reach-weighted sum of that. One store per hex: the target is occupied hexes.
    """
    own = np.zeros(len(data.cells)) if initial_own is None else initial_own.astype(float).copy()
    study = data.study_idx
    reach_study = data.reach[study]
    chosen: list[int] = []
    available = np.ones(len(study), dtype=bool)
    for _ in range(min(k, len(study))):
        value = reach_study @ gain(data.reach @ own)
        value[~available] = -np.inf
        pick = int(np.argmax(value))
        available[pick] = False
        chosen.append(int(study[pick]))
        own[study[pick]] += 1
    return chosen


def structural_gain(model: FittedModel, data: CityData, competitor_cov: np.ndarray) -> Callable[[np.ndarray], np.ndarray]:
    q = np.exp(np.clip(data.z @ model.theta, -50, 50))
    comp_w = (1.0 + competitor_cov) ** (-model.lam) if model.spec.competition else 1.0
    if not model.spec.catchment:
        raise ValueError("the own-hex model has no catchment to place against; rank it with top_k")
    if model.spec.own_spacing:
        return lambda own_cov: q * comp_w * (1.0 + own_cov) ** (-model.gamma)
    return lambda own_cov: q * comp_w


def uncovered_gain(demand: np.ndarray) -> Callable[[np.ndarray], np.ndarray]:
    """Classic max-coverage: only demand no own store reaches yet counts (the v1 engine's logic)."""
    return lambda own_cov: np.where(own_cov > 0, 0.0, demand)


def top_k(data: CityData, scores: np.ndarray, k: int) -> list[int]:
    """Independent-hex placement: the ``k`` highest-scoring study-area cells, no spacing."""
    study = data.study_idx
    order = np.argsort(-scores[study], kind="stable")
    return [int(study[i]) for i in order[:k]]


# --------------------------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------------------------

def recall_within(data: CityData, predicted: Sequence[int], actual: Sequence[int], km: float) -> float:
    """Share of real occupied hexes with a predicted hex centre within ``km`` (the v1 holdout metric)."""
    if len(actual) == 0:
        return float("nan")
    if len(predicted) == 0:
        return 0.0
    pred, act = np.asarray(predicted), np.asarray(actual)
    d = haversine_km(data.lat[act][:, None], data.lng[act][:, None], data.lat[pred][None, :], data.lng[pred][None, :])
    return float((d.min(axis=1) <= km).mean())


def random_recall(data: CityData, k: int, actual: Sequence[int], km: float, draws: int = 200, seed: int = 0) -> float:
    rng = np.random.default_rng(seed)
    study = data.study_idx
    return float(np.mean([recall_within(data, rng.choice(study, size=k, replace=False), actual, km) for _ in range(draws)]))
