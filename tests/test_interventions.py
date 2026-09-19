import pytest

from planner.interventions import InterventionAssumptions, MicroMarketState, compare_interventions


def _state(**changes):
    base = dict(
        city="pune", micro_market="kothrud", latent_orders_per_day=4_000, unserved_orders_per_day=1_500,
        served_share=0.60, nearby_capacity_utilisation=0.94, nearby_capacity_orders_per_day=6_000,
        new_store_incremental_orders_per_day=1_100, new_store_break_even_orders_per_day=500,
        eta_breach_rate=0.06, assortment_fit_score=0.70,
    )
    base.update(changes)
    return MicroMarketState(**base)


def test_comparator_ranks_store_when_demand_pressure_and_economics_are_strong():
    options = compare_interventions(_state())
    assert options[0].intervention == "open_dark_store"
    assert options[0].expected_incremental_orders_per_day == 1_100
    assert "break-even coverage" in options[0].guardrails


def test_comparator_penalises_a_store_that_fails_break_even():
    options = {option.intervention: option for option in compare_interventions(_state(new_store_incremental_orders_per_day=300))}
    assert options["open_dark_store"].confidence == "low"
    assert options["open_dark_store"].score < options["add_operating_capacity"].score


def test_eta_promise_is_not_offered_without_an_eta_measurement():
    options = compare_interventions(_state(eta_breach_rate=None))
    assert "faster_eta_promise" not in {option.intervention for option in options}


def test_invalid_inputs_fail_loudly():
    with pytest.raises(ValueError, match="served_share"):
        compare_interventions(_state(served_share=1.2))
    with pytest.raises(ValueError, match="positive"):
        compare_interventions(_state(new_store_break_even_orders_per_day=0))
    with pytest.raises(ValueError):
        compare_interventions(_state(), InterventionAssumptions(zone_extension_capture_rate=1.1))
