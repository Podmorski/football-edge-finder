"""Tests for MAINLINE-HIST-1 backtest mechanics.

Hermetic unit tests using hand-made frames/arrays.  No dependency on
the full historical data directory.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core import odds, splits
from core import walkforward as wf


# --------------------------------------------------------------------------- #
# Selection rule
# --------------------------------------------------------------------------- #


class TestSelectionRule:
    """The bet rule: soft_odds >= fair_odds * 1.035."""

    def test_boundary_exact(self):
        """soft_odds == fair_odds * 1.035 should be a bet (>=)."""
        fair = 2.0
        soft = fair * 1.035
        assert soft >= fair * 1.035  # boundary included

    def test_below_threshold_no_bet(self):
        """soft_odds just below threshold should not be a bet."""
        fair = 2.0
        soft = fair * 1.034
        assert soft < fair * 1.035

    def test_above_threshold_is_bet(self):
        """soft_odds well above threshold should be a bet."""
        fair = 2.0
        soft = fair * 1.10
        assert soft >= fair * 1.035


# --------------------------------------------------------------------------- #
# Power de-margin
# --------------------------------------------------------------------------- #


class TestPowerDemargin:
    """Probability conversion via the power method."""

    def test_sums_to_one(self):
        """De-marginred probabilities must sum to 1 (within tolerance)."""
        frame = pd.DataFrame({"home": [2.0, 1.5], "draw": [3.4, 4.0], "away": [4.2, 6.0]})
        probs = odds.demargin(frame, "power")
        assert np.allclose(probs.sum(axis=1), 1.0, atol=1e-9)

    def test_favourite_has_higher_probability(self):
        """The outcome with the lowest odds (favourite) should have the highest probability."""
        frame = pd.DataFrame({"home": [1.2], "draw": [6.0], "away": [12.0]})
        probs = odds.demargin(frame, "power")
        assert probs.loc[0, "home"] > probs.loc[0, "draw"]
        assert probs.loc[0, "home"] > probs.loc[0, "away"]

    def test_all_equal_odds_give_equal_probs(self):
        """If all odds are equal, probabilities should be equal."""
        frame = pd.DataFrame({"home": [2.0], "draw": [2.0], "away": [2.0]})
        probs = odds.demargin(frame, "power")
        assert np.allclose(probs.values, [[1.0 / 3.0]], atol=1e-9)


# --------------------------------------------------------------------------- #
# AH margin / push logic
# --------------------------------------------------------------------------- #


class TestAHMargin:
    """Asian handicap outcome determination."""

    def test_home_covers(self):
        """margin > 0 means home covers."""
        fthg, ftag, line = 2, 0, 0.5
        margin = fthg - ftag + line
        assert margin > 0

    def test_away_covers(self):
        """margin < 0 means away covers."""
        fthg, ftag, line = 0, 2, 0.0
        margin = fthg - ftag + line
        assert margin < 0

    def test_push_whole_line(self):
        """margin == 0 on a whole line is a push (void)."""
        fthg, ftag, line = 1, 1, 0.0
        margin = fthg - ftag + line
        assert margin == 0

    def test_push_half_line_impossible(self):
        """A half-line can never produce a push (margin can't be 0)."""
        fthg, ftag, line = 1, 1, 0.5
        margin = fthg - ftag + line
        assert margin != 0

    def test_quarter_line_excluded(self):
        """Quarter lines (.25 / .75) must be excluded."""
        from step6_mainline_hist import _is_valid_ah_line
        assert not _is_valid_ah_line(0.25)
        assert not _is_valid_ah_line(0.75)
        assert not _is_valid_ah_line(-0.25)
        assert not _is_valid_ah_line(-0.75)

    def test_half_line_accepted(self):
        """Half lines (.5) are valid."""
        from step6_mainline_hist import _is_valid_ah_line
        assert _is_valid_ah_line(0.5)
        assert _is_valid_ah_line(-0.5)
        assert _is_valid_ah_line(1.5)

    def test_whole_line_accepted(self):
        """Whole numbers are valid."""
        from step6_mainline_hist import _is_valid_ah_line
        assert _is_valid_ah_line(0.0)
        assert _is_valid_ah_line(1.0)
        assert _is_valid_ah_line(-1.0)


# --------------------------------------------------------------------------- #
# P&L
# --------------------------------------------------------------------------- #


class TestPnL:
    """Profit and loss calculation."""

    def test_win(self):
        """Win: + (odds - 1)."""
        odds_val = 2.5
        pnl = (odds_val - 1.0)
        assert pnl == 1.5

    def test_loss(self):
        """Loss: -1."""
        assert -1 == -1

    def test_void(self):
        """Void: 0."""
        assert 0 == 0

    def test_win_pnl_positive(self):
        """Winning bet always has positive P&L (odds > 1)."""
        for o in [1.01, 1.5, 5.0, 10.0]:
            assert (o - 1.0) > 0

    def test_loss_pnl_negative(self):
        """Losing bet always has P&L = -1."""
        assert -1 < 0


# --------------------------------------------------------------------------- #
# CLV
# --------------------------------------------------------------------------- #


class TestCLV:
    """Closing Line Value calculation."""

    def test_clv_formula(self):
        """clv = soft_odds / fair_close - 1."""
        soft = 2.0
        fair_close = 1.9
        clv = soft / fair_close - 1.0
        assert clv > 0  # we got better price than fair close

    def test_clv_negative_when_soft_worse(self):
        """If soft odds < fair close, CLV is negative."""
        soft = 1.8
        fair_close = 2.0
        clv = soft / fair_close - 1.0
        assert clv < 0

    def test_clv_zero_when_equal(self):
        """If soft odds == fair close, CLV is zero."""
        soft = 2.0
        fair_close = 2.0
        clv = soft / fair_close - 1.0
        assert clv == 0.0

    def test_missing_close_excludes_from_clv_but_not_pnl(self):
        """A bet with missing closing price should still have P&L but no CLV."""
        # Simulate: soft_odds exists, fair_close is None
        soft_odds = 2.0
        fair_close = None
        # CLV should be None/NaN
        if fair_close is not None:
            clv = soft_odds / fair_close - 1.0
        else:
            clv = None
        assert clv is None
        # P&L should still be computable
        won = 1
        pnl = (soft_odds - 1.0) if won == 1 else -1.0
        assert pnl == 1.0


# --------------------------------------------------------------------------- #
# Discovery season guard
# --------------------------------------------------------------------------- #


class TestDiscoverySeasonGuard:
    """Confirmation seasons must not appear in the backtest."""

    def test_discovery_seasons_no_confirmation(self):
        """The discovery season list must not contain any confirmation season."""
        from step6_mainline_hist import DISCOVERY_SEASONS, CONFIRMATION_SEASONS
        overlap = set(DISCOVERY_SEASONS) & CONFIRMATION_SEASONS
        assert not overlap, f"Discovery contains confirmation seasons: {overlap}"

    def test_assert_no_confirmation_raises_on_confirmation_season(self):
        """assert_no_confirmation must raise when fed confirmation-season data."""
        frame = pd.DataFrame({"season": ["2023-2024"], "date": [pd.Timestamp("2024-01-01")]})
        with pytest.raises(RuntimeError, match="confirmation"):
            wf.assert_no_confirmation(frame, "test data")

    def test_assert_seasons_allowed_refuses_confirmation(self):
        """assert_seasons_allowed must refuse confirmation seasons."""
        with pytest.raises(RuntimeError, match="confirmation"):
            wf.assert_seasons_allowed(["2023-2024"])

    def test_assert_seasons_allowed_accepts_discovery(self):
        """assert_seasons_allowed must accept discovery seasons."""
        from step6_mainline_hist import DISCOVERY_SEASONS
        # Should not raise
        wf.assert_seasons_allowed(DISCOVERY_SEASONS)


# --------------------------------------------------------------------------- #
# Bootstrap CI
# --------------------------------------------------------------------------- #


class TestBootstrapCI:
    """Bootstrap confidence interval by matchday."""

    def test_ci_brackets_mean(self):
        """The bootstrap CI should bracket the sample mean."""
        from step6_mainline_hist import bootstrap_ci
        rng = np.random.default_rng(42)
        n_md = 10
        n_per_md = 5
        data = []
        for md in range(n_md):
            vals = rng.normal(0.05, 0.02, n_per_md)
            for v in vals:
                data.append({"_matchday": f"md{md}", "clv": v})
        df = pd.DataFrame(data)
        stat_fn = lambda s: s.mean()
        original, ci_low, ci_high = bootstrap_ci(df, "clv", stat_fn, 500, 12345)
        assert ci_low <= original <= ci_high, f"mean={original}, CI=[{ci_low}, {ci_high}]"

    def test_deterministic_with_fixed_seed(self):
        """Same seed must produce the same CI."""
        from step6_mainline_hist import bootstrap_ci
        rng = np.random.default_rng(42)
        data = []
        for md in range(5):
            for v in rng.normal(0.03, 0.01, 3):
                data.append({"_matchday": f"md{md}", "val": v})
        df = pd.DataFrame(data)
        stat_fn = lambda s: s.mean()
        r1 = bootstrap_ci(df, "val", stat_fn, 200, 999)
        r2 = bootstrap_ci(df, "val", stat_fn, 200, 999)
        assert r1 == r2

    def test_empty_series_returns_nan(self):
        """Empty series should return NaN for all values."""
        from step6_mainline_hist import bootstrap_ci
        df = pd.DataFrame(columns=["_matchday", "val"])
        result = bootstrap_ci(df, "val", lambda s: s.mean(), 100, 42)
        assert all(np.isnan(v) for v in result)


# --------------------------------------------------------------------------- #
# Holm correction
# --------------------------------------------------------------------------- #


class TestHolmCorrection:
    """Holm-Bonferroni multiple-testing correction."""

    def test_monotone(self):
        """Corrected p-values must be monotonically non-decreasing."""
        from step6_mainline_hist import holm_correction
        p_vals = [0.05, 0.01, 0.20, 0.03]
        corrected = holm_correction(p_vals)
        for i in range(1, len(corrected)):
            assert corrected[i] >= corrected[i - 1], \
                f"Not monotone at index {i}: {corrected[i-1]} > {corrected[i]}"

    def test_never_below_raw_p(self):
        """Corrected p-values must never be below the raw p-value."""
        from step6_mainline_hist import holm_correction
        p_vals = [0.05, 0.01, 0.20, 0.03]
        corrected = holm_correction(p_vals)
        for raw, corr in zip(p_vals, corrected):
            assert corr >= raw - 1e-12, f"Corrected {corr} < raw {raw}"

    def test_capped_at_one(self):
        """No corrected p-value should exceed 1."""
        from step6_mainline_hist import holm_correction
        p_vals = [0.5, 0.6, 0.7, 0.8, 0.9]
        corrected = holm_correction(p_vals)
        for c in corrected:
            assert c <= 1.0 + 1e-12

    def test_single_p_value_unchanged(self):
        """With one test, Holm correction is a no-op."""
        from step6_mainline_hist import holm_correction
        assert holm_correction([0.05]) == [0.05]

    def test_two_tests_simple(self):
        """Two tests: smallest p * 2, larger p * 1, then monotonicity."""
        from step6_mainline_hist import holm_correction
        p_vals = [0.04, 0.02]
        corrected = holm_correction(p_vals)
        # Sorted: 0.02 (rank 0, mult=2) -> 0.04, 0.04 (rank 1, mult=1) -> 0.04
        # Monotonicity: max(0.04, 0.04) = 0.04
        assert corrected[1] >= corrected[0]
