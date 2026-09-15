import h3
import pandas as pd
import pytest

from planner.cloud_kitchen import diversified_shortlist, opportunity_index


def _hexes():
    origin = h3.latlng_to_cell(17.4, 78.5, 8)
    cells = list(h3.grid_disk(origin, 2))
    return pd.DataFrame({
        "h3": cells,
        "density_per_km2": range(1, len(cells) + 1),
        "food_retail": range(len(cells), 0, -1),
        "office": [1] * len(cells),
    })


def test_opportunity_index_is_bounded_and_uses_weights():
    hexes = _hexes()
    score = opportunity_index(hexes, {"density_per_km2": 0.8, "food_retail": 0.2, "office": 0.1})
    assert score.between(0, 100).all()
    assert score.idxmax() == hexes["density_per_km2"].idxmax()


def test_diversified_shortlist_separates_selected_cells():
    hexes = _hexes()
    score = opportunity_index(hexes, {"density_per_km2": 1})
    picks = diversified_shortlist(hexes, score, n=3, separation_rings=1)
    assert len(picks) == 3
    assert all(b not in h3.grid_disk(a, 1) for i, a in enumerate(picks.h3) for b in picks.h3.iloc[i + 1:])


def test_opportunity_index_rejects_missing_feature():
    with pytest.raises(ValueError, match="missing"):
        opportunity_index(_hexes(), {"not_a_feature": 1})
