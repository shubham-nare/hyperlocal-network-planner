import duckdb
import pytest

from planner.simulation import SimulationConfig, duckdb_funnel_by_variant, generate_simulated_events, write_simulated_events


def test_simulated_events_are_deterministic_and_explicitly_labelled():
    config = SimulationConfig(users_per_variant=50, seed=99)
    first = generate_simulated_events(config)
    second = generate_simulated_events(config)
    assert first.equals(second)
    assert set(first.data_origin) == {"simulated"}
    assert set(first.variant) == {"control", "treatment"}
    assert set(first.event_name) >= {"serviceability_check", "browse", "order_completed"}


def test_duckdb_funnel_preserves_the_treatment_serviceability_difference():
    events = generate_simulated_events(SimulationConfig(users_per_variant=10_000, seed=5))
    metrics = duckdb_funnel_by_variant(events).set_index("variant")
    assert metrics.loc["treatment", "eligible_users"] > metrics.loc["control", "eligible_users"]
    assert metrics.loc["control", "eta_breach_rate"] < metrics.loc["treatment", "eta_breach_rate"]


def test_simulated_events_persist_to_duckdb(tmp_path):
    events = generate_simulated_events(SimulationConfig(users_per_variant=20))
    database = tmp_path / "events.duckdb"
    assert write_simulated_events(events, database) == len(events)
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM simulated_product_events").fetchone()[0] == len(events)
    with pytest.raises(ValueError, match="simulated"):
        write_simulated_events(events.assign(data_origin="observed"), database)
