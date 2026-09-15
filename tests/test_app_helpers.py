from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import h3
import pandas as pd
import pytest

from app.app import fast_candidates, point_frame
from planner.optimize import Site, Solution


def test_point_frame_structure_and_coordinates():
    origin = h3.latlng_to_cell(17.4, 78.5, 8)
    cells = list(h3.grid_disk(origin, 2))[:5]
    hexes = pd.DataFrame({"h3": cells})
    scores = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0])

    df = point_frame(hexes, scores)

    assert set(df.columns) == {"h3", "lat", "lng", "score", "r", "g", "b"}
    assert len(df) == len(cells)
    assert df["score"].tolist() == scores.tolist()

    for row in df.itertuples():
        expected_lat, expected_lng = h3.cell_to_latlng(row.h3)
        assert row.lat == pytest.approx(expected_lat)
        assert row.lng == pytest.approx(expected_lng)


def test_point_frame_color_scale_and_uniform_scores():
    origin = h3.latlng_to_cell(17.4, 78.5, 8)
    cells = list(h3.grid_disk(origin, 2))[:3]
    hexes = pd.DataFrame({"h3": cells})

    # Variable scores: min gets lowest red/green, max gets highest red/green
    df = point_frame(hexes, pd.Series([0.0, 50.0, 100.0]))
    assert df.loc[0, "r"] == 30 and df.loc[0, "g"] == 80 and df.loc[0, "b"] == 140
    assert df.loc[2, "r"] == 240 and df.loc[2, "g"] == 210 and df.loc[2, "b"] == 45

    # Uniform scores: should not raise ZeroDivisionError and RGB remains valid
    uniform = point_frame(hexes, pd.Series([42.0, 42.0, 42.0]))
    assert len(uniform) == len(cells)
    assert (uniform["r"].between(0, 255)).all()
    assert (uniform["g"].between(0, 255)).all()
    assert (uniform["b"].between(0, 255)).all()


def test_fast_candidates_ranks_and_limits_candidates():
    # Setup 4 cells with different unserved demand
    # cell_0: unserved 500, cell_1: unserved 300, cell_2: unserved 100, cell_3: 0 (fully served)
    demand = {"cell_0": 500.0, "cell_1": 300.0, "cell_2": 100.0, "cell_3": 50.0}
    baseline = Solution(
        status="Optimal",
        opened=["store:existing"],
        served_total=50.0,
        store_orders={"store:existing": 50.0},
        hex_served={"cell_3": 50.0},  # cell_3 is fully served
    )

    sites = [
        Site("store:existing", frozenset(["cell_3"]), existing=True),
        Site("hex:site_high", frozenset(["cell_0"])),   # unserved 500
        Site("hex:site_mid", frozenset(["cell_1"])),    # unserved 300
        Site("hex:site_low", frozenset(["cell_2"])),    # unserved 100
        Site("hex:site_zero", frozenset(["cell_3"])),   # reaches only fully served demand
    ]

    # Limit to top 2: should pick site_high and site_mid
    top2 = fast_candidates(sites, demand, baseline, capacity=1000.0, limit=2)
    assert top2 == {"hex:site_high", "hex:site_mid"}

    # Limit to top 1: should pick site_high
    top1 = fast_candidates(sites, demand, baseline, capacity=1000.0, limit=1)
    assert top1 == {"hex:site_high"}

    # Limit larger than useful count: returns all useful candidates (excluding existing & site_zero)
    all_useful = fast_candidates(sites, demand, baseline, capacity=1000.0, limit=10)
    assert all_useful == {"hex:site_high", "hex:site_mid", "hex:site_low"}
    assert "store:existing" not in all_useful
    assert "hex:site_zero" not in all_useful
