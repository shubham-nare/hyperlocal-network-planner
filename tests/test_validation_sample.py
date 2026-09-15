import pandas as pd

from planner.validation_sample import add_demand_tiers, check_points_from_sheet, stratified_sample


def test_check_points_parse_both_columns_and_skip_blanks():
    sheet = pd.DataFrame({
        "pincode": [500001, 500002],
        "office": ["A", "B"],
        "check_point_high_demand": ["17.40000, 78.40000", "17.50000, 78.50000"],
        "check_point_low_demand": ["17.41000, 78.41000", None],
    })
    pts = check_points_from_sheet(sheet, "hyderabad")
    assert len(pts) == 3
    assert set(pts["point_type"]) == {"high_demand", "low_demand"}
    assert pts.loc[0, "lat"] == 17.4 and pts["city"].eq("hyderabad").all()


def _points():
    a = pd.DataFrame({"city": "a", "pincode": range(30), "demand_index": [float(i) for i in range(30)]})
    b = pd.DataFrame({"city": "b", "pincode": range(2), "demand_index": [5.0, 9.0]})
    return pd.concat([a, b], ignore_index=True)


def test_tiers_are_within_city_and_ordered_by_demand():
    tiered = add_demand_tiers(_points())
    a = tiered[tiered["city"] == "a"]
    by_tier = a.groupby("demand_tier")["demand_index"]
    assert set(a["demand_tier"]) == {0, 1, 2}
    assert by_tier.max()[0] < by_tier.min()[2]
    assert (tiered.loc[tiered["city"] == "b", "demand_tier"] == 0).all()


def test_stratified_sample_caps_each_stratum_and_tolerates_small_ones():
    sample = stratified_sample(_points(), per_stratum=4)
    assert sample[sample["city"] == "a"].groupby("demand_tier").size().tolist() == [4, 4, 4]
    assert len(sample[sample["city"] == "b"]) == 2


def test_stratified_sample_is_reproducible():
    assert stratified_sample(_points(), 4, seed=7).equals(stratified_sample(_points(), 4, seed=7))
