import numpy as np
import pytest

from planner.huff import allocate_demand, choice_probability_matrix, evaluate_candidate_site, pairwise_distance_km


def test_pairwise_distance_matches_known_haversine_value():
    # Roughly 111 km per degree of latitude at the equator.
    dist = pairwise_distance_km(np.array([0.0]), np.array([0.0]), np.array([1.0]), np.array([0.0]))
    assert dist[0, 0] == pytest.approx(111.19, abs=0.5)


def test_probabilities_sum_to_one_when_a_store_is_in_range():
    probs = choice_probability_matrix(np.array([17.40]), np.array([78.50]),
                                      np.array([17.40, 17.41]), np.array([78.50, 78.50]))
    assert probs.sum() == pytest.approx(1.0)


def test_closer_store_gets_a_higher_probability():
    probs = choice_probability_matrix(np.array([17.400]), np.array([78.500]),
                                      np.array([17.401, 17.420]), np.array([78.500, 78.500]))
    assert probs[0, 0] > probs[0, 1]


def test_higher_attractiveness_increases_a_tied_distance_stores_share():
    probs = choice_probability_matrix(np.array([17.40]), np.array([78.50]),
                                      np.array([17.41, 17.39]), np.array([78.50, 78.50]),
                                      attractiveness=np.array([3.0, 1.0]))
    assert probs[0, 0] > probs[0, 1]


def test_higher_distance_decay_sharpens_the_split_toward_the_closer_store():
    hex_lat, hex_lng = np.array([17.400]), np.array([78.500])
    store_lat, store_lng = np.array([17.401, 17.420]), np.array([78.500, 78.500])
    mild = choice_probability_matrix(hex_lat, hex_lng, store_lat, store_lng, distance_decay=1.0)
    sharp = choice_probability_matrix(hex_lat, hex_lng, store_lat, store_lng, distance_decay=4.0)
    assert sharp[0, 0] > mild[0, 0]


def test_max_distance_km_excludes_far_stores_and_zeroes_the_row_if_none_qualify():
    probs = choice_probability_matrix(np.array([17.40]), np.array([78.50]),
                                      np.array([17.60]), np.array([78.50]), max_distance_km=5.0)
    assert probs[0, 0] == 0.0


def test_no_stores_returns_an_empty_but_correctly_shaped_matrix():
    probs = choice_probability_matrix(np.array([17.40, 17.41]), np.array([78.5, 78.5]), np.array([]), np.array([]))
    assert probs.shape == (2, 0)


def test_rejects_non_positive_decay_or_attractiveness():
    with pytest.raises(ValueError, match="distance_decay"):
        choice_probability_matrix(np.array([17.4]), np.array([78.5]), np.array([17.4]), np.array([78.5]), distance_decay=0)
    with pytest.raises(ValueError, match="attractiveness"):
        choice_probability_matrix(np.array([17.4]), np.array([78.5]), np.array([17.4]), np.array([78.5]),
                                  attractiveness=np.array([-1.0]))


def test_allocate_demand_is_probability_weighted_sum():
    probs = np.array([[0.75, 0.25], [0.5, 0.5]])
    demand = np.array([100.0, 40.0])
    received = allocate_demand(demand, probs)
    assert received == pytest.approx([0.75 * 100 + 0.5 * 40, 0.25 * 100 + 0.5 * 40])


def test_candidate_far_from_everything_takes_its_own_demand_with_no_cannibalization():
    # A hard max_distance_km cutoff matters here: without one, Huff normalizes probability
    # among whatever stores exist regardless of absolute distance, so a lone store 300km
    # away would still show as "serving" a hex it could never actually deliver to. Every
    # other reach calculation in this project applies a calibrated cutoff for the same
    # reason; this test does too, rather than exercising an unrealistic unbounded case.
    hex_lat, hex_lng = np.array([17.40, 20.00]), np.array([78.50, 80.00])
    demand = np.array([100.0, 50.0])
    result = evaluate_candidate_site(demand, hex_lat, hex_lng, np.array([17.40]), np.array([78.50]), 20.00, 80.00,
                                     max_distance_km=2.0)
    assert result["candidate_gross_demand"] == pytest.approx(50.0, rel=0.05)
    assert result["cannibalized_from_existing"] == pytest.approx(0.0, abs=0.5)
    assert result["cannibalization_rate"] == pytest.approx(0.0, abs=0.02)


def test_candidate_next_to_an_existing_store_cannibalizes_most_of_its_gross_demand():
    hex_lat, hex_lng = np.array([17.400]), np.array([78.500])
    demand = np.array([100.0])
    result = evaluate_candidate_site(demand, hex_lat, hex_lng, np.array([17.401]), np.array([78.500]), 17.402, 78.500)
    assert result["cannibalization_rate"] > 0.3
    assert result["net_incremental_demand"] < result["candidate_gross_demand"]
