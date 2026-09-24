"""PS3838 (Pinnacle) feed: sharp prices, de-margin and the event shape."""

from __future__ import annotations

import pytest

import ps3838_odds


def _market(canonical, outcomes, line=None, period="FULL_TIME", main=True):
    return {
        "canonicalMarket": canonical, "rawName": canonical, "period": period,
        "line": line, "isActive": True, "moreInfo": {"isMainLine": main},
        "selections": [
            {"canonicalOutcome": name, "rawName": name, "odds": odds, "isActive": True}
            for name, odds in outcomes
        ],
    }


def event(home=2.10, draw=3.40, away=3.60, over=1.90, under=1.95, line=2.5,
          extra_ou=None):
    markets = [_market("MATCH_RESULT", [("HOME", home), ("DRAW", draw), ("AWAY", away)])]
    markets.append(_market("OVER_UNDER", [("OVER", over), ("UNDER", under)], line=line))
    for pt, (o, u) in (extra_ou or {}).items():
        markets.append(_market("OVER_UNDER", [("OVER", o), ("UNDER", u)], line=pt, main=False))
    return {"eventId": "E1", "home": "Home FC", "away": "Away FC", "league": "X",
            "startTime": "2099-01-01T12:00:00.000Z", "updatedAt": "2099-01-01T10:00:00.000Z",
            "markets": markets}


def test_sharp_prices_demargin_and_sum_to_one():
    prices = ps3838_odds.sharp_prices(event())
    assert prices is not None
    assert prices["p_home"] + prices["p_draw"] + prices["p_away"] == pytest.approx(1.0)
    assert 0 < prices["p_over"] < 1
    assert prices["line"] == 2.5
    assert prices["snapshot"] == "2099-01-01T10:00:00.000Z"
    assert prices["margin_1x2"] > 0


def test_uses_the_totals_line_nearest_two_and_a_half():
    near = ps3838_odds.sharp_prices(event(extra_ou={1.5: (1.4, 2.9), 3.5: (3.1, 1.35)}))
    assert near["line"] == 2.5
    only = ps3838_odds.sharp_prices(event(line=3.5))
    assert only["line"] == 3.5


def test_returns_none_without_a_usable_1x2_or_totals():
    no_totals = {"eventId": "E", "home": "a", "away": "b", "markets": [
        _market("MATCH_RESULT", [("HOME", 2.0), ("DRAW", 3.0), ("AWAY", 4.0)])]}
    assert ps3838_odds.sharp_prices(no_totals) is None
    incomplete = {"eventId": "E", "home": "a", "away": "b", "markets": [
        _market("MATCH_RESULT", [("HOME", 2.0), ("DRAW", 3.0)])]}
    assert ps3838_odds.sharp_prices(incomplete) is None


def test_normalize_and_kickoff():
    norm = ps3838_odds.normalize(event(), "eng_premier")
    assert norm["league"] == "eng_premier"
    assert norm["home"] == "Home FC" and norm["away"] == "Away FC"
    assert norm["kickoff"].startswith("2099-01-01T12:00:00")
    assert norm["source"] == "ps3838" and norm["prices"] is not None
    assert ps3838_odds.normalize({"home": "a"}, "x") is None


def test_event_kickoff_is_utc_aware():
    kickoff = ps3838_odds.event_kickoff(event())
    assert kickoff is not None and kickoff.tzinfo is not None
    assert ps3838_odds.event_kickoff({}) is None