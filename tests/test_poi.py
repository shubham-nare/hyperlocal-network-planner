import pandas as pd

from planner.poi import classify, query_tags

CATEGORIES = {
    "office": {"office": True, "building": ["office"]},
    "food_retail": {"amenity": ["cafe"], "shop": ["mall"]},
    "residential_highrise": {"building": ["apartments"]},
}


def test_query_tags_unions_values_and_true_wins():
    tags = query_tags(CATEGORIES | {"any_building": {"building": True}})
    assert tags["office"] is True
    assert tags["building"] is True
    assert tags["amenity"] == ["cafe"]


def test_query_tags_merges_lists_across_categories():
    assert query_tags(CATEGORIES)["building"] == ["apartments", "office"]


def test_classify_flags_every_matching_category():
    features = pd.DataFrame({
        "office": [None, "it", None, None],
        "building": ["office", None, "apartments", None],
        "amenity": [None, None, None, "cafe"],
    })
    flags = classify(features, CATEGORIES)
    assert flags["office"].tolist() == [True, True, False, False]
    assert flags["residential_highrise"].tolist() == [False, False, True, False]
    assert flags["food_retail"].tolist() == [False, False, False, True]


def test_classify_ignores_tag_columns_missing_from_data():
    flags = classify(pd.DataFrame({"amenity": ["cafe"]}), CATEGORIES)
    assert flags.loc[0, "food_retail"] and not flags.loc[0, "office"]
