"""Tests for the combo market menu.

The key property: every combo is a **grid-cell sum** (a true joint probability),
so it can never exceed either of its single legs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core import walkforward as wf

MARKETS_PATH = wf.PRED_DIR / f"{wf.Config(xi=0.002, covid_mode='exclude_after', newcomer='newcomer_prior').config_id}_markets.parquet"


@pytest.fixture(scope="module")
def grid_markets():
    ratings = {"A": (0.35, -0.25), "B": (-0.15, 0.15)}
    model = wf.model_from_ratings(ratings, 0.22, -0.012)
    grid = model.predict("A", "B")
    return grid, wf.markets_from_grid(grid)


def test_combo_columns_are_grid_cell_sums(grid_markets):
    grid, mk = grid_markets
    g = grid.grid
    i, j = np.indices(g.shape)
    total = i + j
    btts = (i >= 1) & (j >= 1)

    expected = {
        "p_home": i > j,
        "p_draw": i == j,
        "p_away": i < j,
        "p_dc_1x": i >= j,
        "p_dc_12": i != j,
        "p_dc_x2": i <= j,
        "p_over15": total >= 2,
        "p_under15": total < 2,
        "p_over25": total >= 3,
        "p_under25": total < 3,
        "p_over35": total >= 4,
        "p_under35": total < 4,
        "p_btts": btts,
        "p_btts_no": ~btts,
        "p_under25_btts_no": (total <= 2) & ~btts,
        "p_over25_btts_yes": (total >= 3) & btts,
        "p_home_under35": (i > j) & (total <= 3),
        "p_away_under35": (i < j) & (total <= 3),
        "p_home_btts_no": (i > j) & ~btts,
        "p_draw_under25": (i == j) & (total <= 2),
        "p_home_or_draw_under25": (i >= j) & (total <= 2),
        "p_home_over15": (i > j) & (total >= 2),
    }
    for key, mask in expected.items():
        assert mk[key] == pytest.approx(float(g[mask].sum()), abs=1e-12), key


def test_complements_sum_to_one(grid_markets):
    _, mk = grid_markets
    for a, b in (("p_home", None), ("p_over15", "p_under15"), ("p_over25", "p_under25"),
                 ("p_over35", "p_under35"), ("p_btts", "p_btts_no")):
        if b is None:
            assert mk["p_home"] + mk["p_draw"] + mk["p_away"] == pytest.approx(1.0, abs=1e-12)
        else:
            assert mk[a] + mk[b] == pytest.approx(1.0, abs=1e-12), a


def test_double_chance_identities(grid_markets):
    _, mk = grid_markets
    assert mk["p_dc_1x"] == pytest.approx(mk["p_home"] + mk["p_draw"], abs=1e-12)
    assert mk["p_dc_12"] == pytest.approx(mk["p_home"] + mk["p_away"], abs=1e-12)
    assert mk["p_dc_x2"] == pytest.approx(mk["p_draw"] + mk["p_away"], abs=1e-12)


def test_combo_never_exceeds_either_leg(grid_markets):
    _, mk = grid_markets
    pairs = [
        ("p_under25_btts_no", "p_under25", "p_btts_no"),
        ("p_over25_btts_yes", "p_over25", "p_btts"),
        ("p_home_under35", "p_home", "p_under35"),
        ("p_away_under35", "p_away", "p_under35"),
        ("p_home_btts_no", "p_home", "p_btts_no"),
        ("p_draw_under25", "p_draw", "p_under25"),
        ("p_home_or_draw_under25", "p_dc_1x", "p_under25"),
        ("p_home_over15", "p_home", "p_over15"),
    ]
    for combo, leg_a, leg_b in pairs:
        assert mk[combo] <= mk[leg_a] + 1e-12, combo
        assert mk[combo] <= mk[leg_b] + 1e-12, combo


@pytest.mark.skipif(not MARKETS_PATH.exists(), reason="markets artifact not built")
def test_real_artifact_combos_never_exceed_legs():
    frame = pd.read_parquet(MARKETS_PATH)
    pairs = [
        ("p_under25_btts_no", "p_under25", "p_btts_no"),
        ("p_over25_btts_yes", "p_over25", "p_btts"),
        ("p_home_under35", "p_home", "p_under35"),
        ("p_away_under35", "p_away", "p_under35"),
        ("p_home_btts_no", "p_home", "p_btts_no"),
        ("p_draw_under25", "p_draw", "p_under25"),
        ("p_home_or_draw_under25", "p_dc_1x", "p_under25"),
        ("p_home_over15", "p_home", "p_over15"),
    ]
    for combo, leg_a, leg_b in pairs:
        assert (frame[combo] <= frame[leg_a] + 1e-12).all(), combo
        assert (frame[combo] <= frame[leg_b] + 1e-12).all(), combo
    # singles must be proper probabilities
    for column in ("p_home", "p_draw", "p_away", "p_over25", "p_btts"):
        assert frame[column].between(0, 1).all(), column