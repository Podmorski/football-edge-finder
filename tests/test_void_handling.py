"""Tests for void handling in stake-back markets (X No Bet).

A void outcome returns the stake (odds 1.00), so it carries no binary label.
The model probability used for calibration must therefore be CONDITIONAL on
not-void: ``p_cond = p_win / (1 - p_void)``. Using the raw ``p_win`` makes
X No Bet look badly miscalibrated (its slope was 1.281).
"""

from __future__ import annotations

import numpy as np
import pytest

from core.half_model import (
    Anchor,
    batch_market_probs,
    grids_to_flat,
    joint_grid,
    market_masks,
)
from core.market_code import VOID, WIN, direct_markets


def _no_bet_markets():
    return [m for m in direct_markets() if m.family == "NO_BET"]


def test_x_no_bet_voids_on_a_draw_and_wins_otherwise():
    by_code = {m.code: m for m in _no_bet_markets()}
    ft = by_code["XNB FT 1"]
    assert ft.outcome(0, 0, 0, 0) == VOID          # FT draw
    assert ft.outcome(0, 0, 1, 0) == WIN           # home wins
    assert ft.outcome(0, 0, 0, 1) == 0 or ft.outcome(0, 0, 0, 1) == "lose"
    h1 = by_code["XNB 1. Pol. 1"]
    assert h1.outcome(0, 0, 2, 0) == VOID          # 1H draw
    assert h1.outcome(1, 0, 1, 0) == WIN


def test_no_bet_void_mass_is_nonzero():
    anchor = Anchor(lam=1.5, mu=1.2, residual=0.0)
    grid = joint_grid(anchor, None, 6, fixed_share=0.5, use_state=False)
    masks = market_masks(_no_bet_markets(), max_half=6)
    probs = batch_market_probs(grids_to_flat([grid]), masks)
    for market in _no_bet_markets():
        p_win, p_void = probs[(market.family, market.code)]
        assert p_void[0] > 0.05, f"{market.code} should have real void mass"
        assert p_win[0] + p_void[0] <= 1.0 + 1e-9


def test_conditional_probability_is_used_for_calibration():
    """p_cond = p_win / (1 - p_void) must exceed the raw p_win."""
    anchor = Anchor(lam=1.5, mu=1.2, residual=0.0)
    grid = joint_grid(anchor, None, 6, fixed_share=0.5, use_state=False)
    masks = market_masks(_no_bet_markets(), max_half=6)
    probs = batch_market_probs(grids_to_flat([grid]), masks)
    for market in _no_bet_markets():
        p_win, p_void = probs[(market.family, market.code)]
        p_cond = p_win[0] / (1 - p_void[0])
        assert p_cond > p_win[0], f"{market.code}: conditional must exceed raw"
        assert p_cond <= 1.0 + 1e-9


def test_symmetric_no_bet_pairs_conditional_probs_sum_to_one():
    """XNB 1 and XNB 2 are complements once voids are removed."""
    anchor = Anchor(lam=1.4, mu=1.3, residual=0.0)
    grid = joint_grid(anchor, None, 6, fixed_share=0.5, use_state=False)
    masks = market_masks(_no_bet_markets(), max_half=6)
    probs = batch_market_probs(grids_to_flat([grid]), masks)
    for period in ("FT", "1. Pol.", "2. Pol."):
        a = probs[("NO_BET", f"XNB {period} 1")]
        b = probs[("NO_BET", f"XNB {period} 2")]
        cond_a = a[0][0] / (1 - a[1][0])
        cond_b = b[0][0] / (1 - b[1][0])
        assert cond_a + cond_b == pytest.approx(1.0, abs=1e-9), period


def test_calibration_artifact_uses_conditional_probabilities():
    """The saved calibration must show NO_BET centred near 0.5, not ~0.33."""
    from pathlib import Path

    path = Path("data/predictions/derived_markets_calibration.parquet")
    if not path.exists():
        pytest.skip("calibration artifact not built")
    import pandas as pd

    df = pd.read_parquet(path)
    nb = df[df["family"] == "NO_BET"]
    if nb.empty:
        pytest.skip("no NO_BET rows")
    assert abs(nb["p_model"].mean() - 0.5) < 0.05, (
        f"NO_BET mean p_model {nb['p_model'].mean():.4f} is not conditional"
    )
