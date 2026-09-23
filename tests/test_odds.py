"""Tests for the canonical odds accessors."""

from __future__ import annotations

import numpy as np
import pandas as pd

from core import odds


def test_proportional_demargin_sums_to_one():
    frame = pd.DataFrame({"home": [2.0, 1.5], "draw": [3.4, 4.0], "away": [4.2, 6.0]})
    probs = odds.demargin(frame, "proportional")
    assert np.allclose(probs.sum(axis=1), 1.0)


def test_power_demargin_sums_to_one():
    frame = pd.DataFrame({"home": [2.0, 1.5], "draw": [3.4, 4.0], "away": [4.2, 6.0]})
    probs = odds.demargin(frame, "power")
    assert np.allclose(probs.sum(axis=1), 1.0, atol=1e-9)


def test_power_demargin_favours_favourites_more_than_proportional():
    frame = pd.DataFrame({"home": [1.2], "draw": [6.0], "away": [12.0]})
    prop = odds.demargin(frame, "proportional").to_numpy()[0]
    power = odds.demargin(frame, "power").to_numpy()[0]
    assert power[0] >= prop[0]


def test_prematch_prefers_avg_then_bbav_then_b365():
    frame = pd.DataFrame(
        {
            "avg_h": [2.0, np.nan],
            "avg_d": [3.4, np.nan],
            "avg_a": [4.2, np.nan],
            "bb_av_h": [2.1, 2.1],
            "bb_av_d": [3.3, 3.3],
            "bb_av_a": [4.1, 4.1],
            "b365_h": [2.2, 2.2],
            "b365_d": [3.2, 3.2],
            "b365_a": [4.0, 4.0],
        }
    )
    market = odds.prematch_1x2(frame)
    assert market.source.tolist() == ["Avg", "BbAv"]
    assert market.odds.loc[0, "home"] == 2.0
    assert market.odds.loc[1, "home"] == 2.1


def test_closing_prefers_avgc_then_psc():
    frame = pd.DataFrame(
        {
            "avg_ch": [np.nan, 2.0],
            "avg_cd": [np.nan, 3.4],
            "avg_ca": [np.nan, 4.2],
            "psch": [1.9, 2.05],
            "pscd": [3.5, 3.45],
            "psca": [4.3, 4.15],
        }
    )
    market = odds.closing_1x2(frame)
    assert market.source.tolist() == ["PSC", "AvgC"]


def test_closing_reports_unavailable_when_no_source():
    frame = pd.DataFrame({"home": [1.0], "draw": [1.0], "away": [1.0]})
    market = odds.closing_1x2(frame)
    assert not market.available.any()
    assert market.source.tolist() == [None]


def test_ou_and_ah_carry_source_labels_and_line():
    frame = pd.DataFrame(
        {
            "bb_av>2.5": [1.9],
            "bb_av<2.5": [1.9],
            "bb_a_hh": [-0.5],
            "bb_av_ahh": [1.95],
            "bb_av_aha": [1.95],
        }
    )
    ou = odds.prematch_ou25(frame)
    ah = odds.prematch_ah(frame)
    assert ou.source.tolist() == ["BbAv>2.5"]
    assert ah.source.tolist() == ["BbAH"]
    assert ah.odds.loc[0, "line"] == -0.5


def test_booksum_margin_matches_manual_overround():
    frame = pd.DataFrame({"home": [2.0], "draw": [4.0], "away": [4.0]})
    assert abs(odds.booksum_margin(frame).iloc[0] - (0.5 + 0.25 + 0.25 - 1.0)) < 1e-12