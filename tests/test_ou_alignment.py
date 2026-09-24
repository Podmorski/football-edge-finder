"""Regression tests for the O/U market alignment bug.

The bug: ``ou.odds`` columns are ``("over", "under")``, but three consumers
indexed ``.to_numpy()[:, 1]`` — which is **under** — and used it as P(over).
That inverted the market probability, making the de-margined market look worse
than a constant and flipping the sign of corr(prob, outcome).

These tests fail loudly if the alignment ever breaks again.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core import odds, walkforward as wf

FINAL = wf.Config(xi=0.002, covid_mode="exclude_after", newcomer="newcomer_prior")
PRED = wf.PRED_DIR / f"{FINAL.config_id}.parquet"
ODDS_COLUMNS = ["avg>2.5", "avg<2.5", "bb_av>2.5", "bb_av<2.5", "b365>2.5", "b365<2.5"]


def test_ou_cascade_maps_over_and_under_by_name():
    frame = pd.DataFrame({"avg>2.5": [1.50], "avg<2.5": [2.60]})
    market = odds.prematch_ou25(frame)
    assert list(market.odds.columns) == ["over", "under"]
    assert market.odds.loc[0, "over"] == 1.50
    assert market.odds.loc[0, "under"] == 2.60


def test_demargined_over_exceeds_under_when_over_price_is_shorter():
    frame = pd.DataFrame({"avg>2.5": [1.50], "avg<2.5": [2.60]})
    market = odds.prematch_ou25(frame)
    probs = odds.demargin(market.odds, "proportional")
    assert probs.loc[0, "over"] > probs.loc[0, "under"]
    assert probs.loc[0, "over"] > 0.5


def test_positional_index_one_is_under_not_over():
    """Documents the trap explicitly."""
    frame = pd.DataFrame({"avg>2.5": [1.50], "avg<2.5": [2.60]})
    market = odds.prematch_ou25(frame)
    probs = odds.demargin(market.odds, "proportional")
    assert probs.to_numpy()[0, 1] == pytest.approx(probs.loc[0, "under"])
    assert probs.to_numpy()[0, 0] == pytest.approx(probs.loc[0, "over"])


@pytest.mark.skipif(not PRED.exists(), reason="predictions artifact not built")
def test_real_artifact_over_probability_correlates_positively_with_outcome():
    preds = pd.read_parquet(PRED)
    pool = wf.load_pool(FINAL.league)
    raw = pool.reset_index().rename(columns={"index": "row", "id": "match_key"})
    frame = preds.merge(raw[["match_key"] + ODDS_COLUMNS], on="match_key", how="left")

    market = odds.prematch_ou25(frame)
    probs = odds.demargin(market.odds.where(market.available), "proportional")
    total = (frame["fthg"] + frame["ftag"]).to_numpy()
    over = (total > 2.5).astype(int)
    ok = np.isfinite(probs["over"].to_numpy())

    p_over = probs["over"].to_numpy()[ok]
    p_under = probs["under"].to_numpy()[ok]
    y = over[ok]

    # The whole point: the market's OVER probability must be POSITIVELY
    # correlated with the over outcome. The bug made this negative.
    assert np.corrcoef(p_over, y)[0, 1] > 0.0
    assert np.corrcoef(p_under, y)[0, 1] < 0.0

    # And the de-margined market must not be worse than a constant.
    from models import league_one_dixon_coles as m

    ll_market = m.log_loss(np.column_stack([1 - p_over, p_over]), y)
    ll_const = m.log_loss(np.column_stack([np.full(len(y), 0.5)] * 2), y)
    assert ll_market < ll_const, f"market {ll_market:.4f} vs constant {ll_const:.4f}"

    # Mean probability should track the observed rate closely.
    assert abs(p_over.mean() - y.mean()) < 0.02


@pytest.mark.skipif(not PRED.exists(), reason="predictions artifact not built")
def test_known_match_alignment():
    """A concrete row: shortest over price must carry the higher over probability."""
    preds = pd.read_parquet(PRED)
    pool = wf.load_pool(FINAL.league)
    raw = pool.reset_index().rename(columns={"index": "row", "id": "match_key"})
    frame = preds.merge(raw[["match_key"] + ODDS_COLUMNS], on="match_key", how="left")

    market = odds.prematch_ou25(frame)
    probs = odds.demargin(market.odds.where(market.available), "proportional")
    odds_over = market.odds["over"].to_numpy(dtype=float)
    valid = np.isfinite(odds_over) & np.isfinite(probs["over"].to_numpy())

    # the match with the shortest over price must have P(over) > 0.5
    idx = np.where(valid)[0][np.argmin(odds_over[valid])]
    assert probs["over"].to_numpy()[idx] > 0.5
    assert probs["under"].to_numpy()[idx] < 0.5