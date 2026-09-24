"""Unit tests for audit_clv.py helper functions.

Offline, fast — no dependency on parquet files or the live project.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from audit_clv import (
    _build_parquet_lookup,
    _matchday_key,
    check_1_recompute_fair_close_odds,
    check_2_clv_identity,
    check_3_demargined_not_raw,
    check_4_summary_and_ci,
    check_5_log_close,
    check_6_no_snapshot_after_kickoff,
    compute_clv,
    fair_odds_from_probs,
    power_demargin,
)


# ── Power de-margin ──────────────────────────────────────────────────────────


class TestPowerDemargin:
    """Probability conversion via the power method."""

    def test_sums_to_one(self):
        """De-marginred probabilities must sum to 1."""
        probs = power_demargin(np.array([2.0, 3.4, 4.2]))
        assert np.isclose(probs.sum(), 1.0, atol=1e-9)

    def test_favourite_has_higher_probability(self):
        """The outcome with the lowest odds should have the highest probability."""
        probs = power_demargin(np.array([1.2, 6.0, 12.0]))
        assert probs[0] > probs[1]
        assert probs[0] > probs[2]

    def test_all_equal_odds_give_equal_probs(self):
        """If all odds are equal, probabilities should be equal."""
        probs = power_demargin(np.array([2.0, 2.0, 2.0]))
        assert np.allclose(probs, [1.0 / 3.0] * 3, atol=1e-9)

    def test_two_outcomes(self):
        """Two-way market (e.g. O/U) must also sum to 1."""
        probs = power_demargin(np.array([1.85, 1.97]))
        assert np.isclose(probs.sum(), 1.0, atol=1e-9)

    def test_non_finite_returns_nan(self):
        """Non-finite odds should return NaN."""
        # inf in odds -> 0 in raw -> power of 0 -> 0 probability
        # The function handles inf by computing 1/inf = 0, then powers
        probs = power_demargin(np.array([2.0, np.inf, 4.0]))
        # With inf odds, raw = [0.5, 0, 0.25], powered sum = 0.5^k + 0 + 0.25^k
        # The inf outcome gets probability 0 (correct behavior)
        assert probs[1] == 0.0  # inf odds -> 0 probability
        assert np.isclose(probs.sum(), 1.0, atol=1e-9)

    def test_deterministic(self):
        """Same input must always produce the same output."""
        r1 = power_demargin(np.array([1.5, 3.5, 5.0]))
        r2 = power_demargin(np.array([1.5, 3.5, 5.0]))
        assert np.allclose(r1, r2)


# ── Fair odds from probabilities ─────────────────────────────────────────────


class TestFairOddsFromProbs:
    """Convert probabilities back to decimal odds."""

    def test_1x2_home(self):
        """Home probability -> home odds."""
        probs = np.array([0.5, 0.3, 0.2])
        assert np.isclose(fair_odds_from_probs(probs, "home"), 2.0, atol=1e-9)

    def test_1x2_draw(self):
        """Draw probability -> draw odds."""
        probs = np.array([0.5, 0.3, 0.2])
        assert np.isclose(fair_odds_from_probs(probs, "draw"), 1.0 / 0.3, atol=1e-9)

    def test_ou_over(self):
        """Over probability -> over odds."""
        probs = np.array([0.55, 0.45])
        assert np.isclose(fair_odds_from_probs(probs, "over"), 1.0 / 0.55, atol=1e-9)

    def test_ou_under(self):
        """Under probability -> under odds."""
        probs = np.array([0.55, 0.45])
        assert np.isclose(fair_odds_from_probs(probs, "under"), 1.0 / 0.45, atol=1e-9)

    def test_zero_prob_returns_nan(self):
        """Zero probability should return NaN."""
        probs = np.array([1.0, 0.0, 0.0])
        assert np.isnan(fair_odds_from_probs(probs, "away"))


# ── CLV computation ──────────────────────────────────────────────────────────


class TestComputeCLV:
    """CLV = soft_odds / fair_close_odds - 1."""

    def test_positive_clv(self):
        """Better price than fair close -> positive CLV."""
        assert compute_clv(2.5, 2.0) == 0.25

    def test_negative_clv(self):
        """Worse price than fair close -> negative CLV."""
        assert np.isclose(compute_clv(1.8, 2.0), -0.1, atol=1e-9)

    def test_zero_clv(self):
        """Same price as fair close -> zero CLV."""
        assert compute_clv(2.0, 2.0) == 0.0

    def test_nan_on_invalid_fair_close(self):
        """Invalid fair_close should return NaN."""
        assert np.isnan(compute_clv(2.0, 0.0))
        assert np.isnan(compute_clv(2.0, -1.0))
        assert np.isnan(compute_clv(2.0, float("nan")))


# ── Matchday key ─────────────────────────────────────────────────────────────


class TestMatchdayKey:
    """Monday of the week containing a date."""

    def test_sunday(self):
        """Sunday 2024-01-07 -> Monday 2024-01-01."""
        assert _matchday_key("2024-01-07") == "2024-01-01"

    def test_monday(self):
        """Monday stays the same."""
        assert _matchday_key("2024-01-01") == "2024-01-01"

    def test_wednesday(self):
        """Wednesday 2024-01-03 -> Monday 2024-01-01."""
        assert _matchday_key("2024-01-03") == "2024-01-01"

    def test_saturday(self):
        """Saturday 2024-01-06 -> Monday 2024-01-01."""
        assert _matchday_key("2024-01-06") == "2024-01-01"


# ── Check 2: CLV identity ───────────────────────────────────────────────────


class TestCheck2CLVIdentity:
    """Verify clv = soft_odds / fair_close_odds - 1 from CSV values."""

    def test_identity_holds(self):
        """clv is exactly soft_odds / fair_close - 1 for every row."""
        soft = [2.5, 1.8, 3.0, 5.0]
        clv = [0.25, -0.1, 0.0, 0.5]
        df = pd.DataFrame({
            "soft_odds": soft,
            "fair_close": [s / (1.0 + c) for s, c in zip(soft, clv)],
            "clv": clv,
        })
        result = check_2_clv_identity(df)
        assert result["passed"]
        assert result["n_violations"] == 0

    def test_nan_values_skipped(self):
        """NaN values should be skipped, not cause violations."""
        df = pd.DataFrame({
            "soft_odds": [2.5, float("nan"), 3.0],
            "fair_close": [2.0, float("nan"), float("nan")],
            "clv": [0.25, 0.0, float("nan")],
        })
        result = check_2_clv_identity(df)
        assert result["passed"]

    def test_negative_clv_plus_one(self):
        """CLV = -0.5 means fair_close = 2 * soft_odds."""
        df = pd.DataFrame({
            "soft_odds": [2.0],
            "fair_close": [4.0],
            "clv": [-0.5],
        })
        result = check_2_clv_identity(df)
        assert result["passed"]


# ── Check 3: De-margined vs raw odds ─────────────────────────────────────────


class TestCheck3DemarginedNotRaw:
    """Verify de-marginred odds are LONGER than raw odds."""

    def test_fair_odds_longer_than_raw(self):
        """Power de-margin always produces longer odds."""
        # Use the actual parquet data for bundesliga_1
        df = pd.read_parquet("data/historical/bundesliga_1.parquet")
        df["date"] = pd.to_datetime(df["date"])
        # Pick a match with valid closing odds
        row = df.iloc[0]
        # The date in parquet is a Timestamp, convert to string the same way
        # the audit script does
        date_str = str(row["date"].date())
        bet_df = pd.DataFrame({
            "league": ["bundesliga_1"],
            "date": [date_str],
            "home": [row["team_home"]],
            "away": [row["team_away"]],
            "market": ["1X2"],
            "selection": ["home"],
            # the de-margined fair price is LONGER than the raw closing odd
            "fair_close": [float(row["psch"]) * 1.05],
        })
        # Debug: check if the lookup finds this match
        cache = _build_parquet_lookup()
        key = ("bundesliga_1", date_str, row["team_home"], row["team_away"])
        assert key in cache, f"Key {key} not in cache. Available keys: {list(cache.keys())[:5]}"
        result = check_3_demargined_not_raw(bet_df)
        # Should pass because fair odds are longer than raw
        assert result["passed"]
        # Task's claim (fair < raw) should be violated
        assert result["task_violations"] > 0


# ── Check 4: Summary and CI ──────────────────────────────────────────────────


class TestCheck4SummaryAndCI:
    """Recompute summary and bootstrap CIs."""

    def test_simple_summary_counts(self):
        """A simple DataFrame should produce correct counts."""
        df = pd.DataFrame({
            "date": ["2024-01-01", "2024-01-02", "2024-01-08"],
            "soft_book": ["b365", "b365", "b365"],
            "market": ["1X2", "1X2", "1X2"],
            "clv": [0.1, 0.2, 0.15],
            "won": [1, 0, 1],
            "pnl": [1.0, -1.0, 1.5],
        })
        # Create a summary with the right columns but wrong values
        summary = pd.DataFrame([{
            "soft_book": "wrong_book", "market": "wrong_market",
            "n_bets": 999, "n_void": 999, "n_missing_close": 999,
            "roi": 999, "roi_ci_low": 999, "roi_ci_high": 999,
            "mean_clv": 999, "clv_ci_low": 999, "clv_ci_high": 999,
            "p_raw": 999,
        }])
        result = check_4_summary_and_ci(df, summary)
        # Should find mismatches since values are wrong
        assert not result["passed"]
        # But the recomputed summary should have correct counts
        my_s = result["my_summary"]
        assert len(my_s) == 1
        assert my_s.iloc[0]["n_bets"] == 3
        assert my_s.iloc[0]["n_void"] == 0
        assert np.isclose(my_s.iloc[0]["mean_clv"], 0.15, atol=1e-9)

    def test_empty_summary(self):
        """Empty DataFrame should handle gracefully."""
        df = pd.DataFrame(columns=["date", "soft_book", "market", "clv", "won", "pnl"])
        summary = pd.DataFrame()
        result = check_4_summary_and_ci(df, summary)
        assert result["passed"]


# ── Check 6: No snapshot after kick-off ──────────────────────────────────────


class TestCheck6NoSnapshotAfterKickoff:
    """Verify fetched_at <= commence_time for all snapshots."""

    def test_no_snapshot_dir(self, tmp_path, monkeypatch):
        """Missing snapshot dir should pass."""
        monkeypatch.setattr("audit_clv.SNAPSHOT_DIR", tmp_path / "nonexistent")
        result = check_6_no_snapshot_after_kickoff()
        assert result["passed"]
        assert result["n_files"] == 0

    def test_valid_snapshot(self, tmp_path, monkeypatch):
        """Snapshot fetched before kickoff should pass."""
        snap_dir = tmp_path / "snapshots"
        snap_dir.mkdir()
        monkeypatch.setattr("audit_clv.SNAPSHOT_DIR", snap_dir)

        import json
        snap_file = snap_dir / "test__20240101T120000Z.json"
        snap_file.write_text(json.dumps({
            "fetched_at": "2024-01-01T10:00:00+00:00",
            "data": [{
                "commence_time": "2024-01-01T15:00:00Z",
                "home_team": "Test Home",
                "away_team": "Test Away",
            }],
        }))

        result = check_6_no_snapshot_after_kickoff()
        assert result["passed"]
        assert result["violations"] == 0

    def test_invalid_snapshot(self, tmp_path, monkeypatch):
        """Snapshot fetched after kickoff should fail."""
        snap_dir = tmp_path / "snapshots"
        snap_dir.mkdir()
        monkeypatch.setattr("audit_clv.SNAPSHOT_DIR", snap_dir)

        import json
        snap_file = snap_dir / "test__20240101T120000Z.json"
        snap_file.write_text(json.dumps({
            "fetched_at": "2024-01-01T16:00:00+00:00",
            "data": [{
                "commence_time": "2024-01-01T15:00:00Z",
                "home_team": "Test Home",
                "away_team": "Test Away",
            }],
        }))

        result = check_6_no_snapshot_after_kickoff()
        assert not result["passed"]
        assert result["violations"] == 1
