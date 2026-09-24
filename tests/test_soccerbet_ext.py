"""Tests for the extended Soccer Bet families (:mod:`core.soccerbet_ext`).

Covers, per family, the official definition on hand-made scores; the
exhaustiveness of the partitions used to measure margin; the regressions found
while ingesting the Hoffenheim vs Hamburger SV sample (inverted ``2GG``/``IGG``,
``NE1-2`` misread as a HT/FT pair, ``II`` period ordering, per-component ``NE``);
and the sample file itself when it is present (``data/`` is gitignored, so the
sample test skips on a clean checkout).
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from core.soccerbet_ext import (
    LOSE,
    UNCONFIRMED,
    VOID,
    WIN,
    parse_component,
    resolve,
)
from step1b_ingest_soccerbet import PARTITIONS, RAW

# --------------------------------------------------------------------------- #
# official definitions on hand-made scores
# --------------------------------------------------------------------------- #
# (prefix, code, family, [(hth, hta, fth, fta, expected), ...])
CASES: list[tuple[str, str, str, list[tuple[int, int, int, int, str]]]] = [
    # --- RESULT / DOUBLE_CHANCE --------------------------------------------
    ("FT", "1", "RESULT", [(0, 0, 1, 0, WIN), (0, 0, 2, 1, WIN), (0, 0, 0, 0, LOSE),
                           (0, 0, 1, 1, LOSE), (0, 0, 0, 1, LOSE)]),
    ("FT", "X", "RESULT", [(0, 0, 0, 0, WIN), (1, 1, 2, 2, WIN), (0, 0, 1, 0, LOSE)]),
    ("FT", "2", "RESULT", [(0, 0, 0, 1, WIN), (0, 0, 1, 2, WIN), (0, 0, 1, 0, LOSE)]),
    ("DC", "1X", "DOUBLE_CHANCE", [(0, 0, 1, 0, WIN), (0, 0, 0, 0, WIN), (0, 0, 0, 1, LOSE)]),
    ("DC", "12", "DOUBLE_CHANCE", [(0, 0, 1, 0, WIN), (0, 0, 1, 1, LOSE)]),
    ("DC", "X2", "DOUBLE_CHANCE", [(0, 0, 1, 1, WIN), (0, 0, 1, 0, LOSE)]),

    # --- halves: result and double chance ---------------------------------
    ("H1", "1", "HALF_RESULT", [(1, 0, 3, 1, WIN), (0, 0, 1, 0, LOSE)]),
    ("H1", "X", "HALF_RESULT", [(0, 0, 1, 0, WIN), (1, 0, 1, 0, LOSE)]),
    ("H2", "2", "HALF_RESULT", [(0, 0, 0, 1, WIN), (0, 0, 1, 0, LOSE)]),
    ("H2", "1", "HALF_RESULT", [(1, 0, 2, 0, WIN), (0, 0, 0, 0, LOSE)]),
    ("H1DC", "1X", "HALF_DC", [(0, 0, 1, 0, WIN), (0, 1, 1, 1, LOSE)]),
    ("H1DC", "12", "HALF_DC", [(0, 0, 2, 0, LOSE), (1, 0, 2, 0, WIN)]),
    ("H2DC", "X2", "HALF_DC", [(0, 0, 0, 1, WIN), (0, 0, 1, 0, LOSE)]),

    # --- win both halves / to nil -----------------------------------------
    ("DP", "1", "WIN_BOTH_HALVES", [(1, 0, 2, 0, WIN), (1, 0, 1, 1, LOSE), (0, 1, 1, 0, LOSE)]),
    ("DP", "2", "WIN_BOTH_HALVES", [(0, 1, 0, 2, WIN), (0, 1, 0, 1, LOSE)]),
    ("SP", "1", "WIN_TO_NIL", [(0, 0, 2, 0, WIN), (1, 0, 2, 1, LOSE), (0, 0, 0, 1, LOSE)]),
    ("SP", "2", "WIN_TO_NIL", [(0, 0, 0, 1, WIN), (0, 0, 1, 0, LOSE)]),
    ("DSP", "1", "WIN_BOTH_HALVES_TO_NIL", [(1, 0, 2, 0, WIN), (1, 0, 2, 1, LOSE)]),
    ("DSP", "2", "WIN_BOTH_HALVES_TO_NIL", [(0, 1, 0, 2, WIN), (0, 1, 1, 2, LOSE)]),

    # --- margin ------------------------------------------------------------
    ("HP", "1", "MARGIN", [(0, 0, 2, 0, WIN), (0, 0, 3, 1, WIN), (0, 0, 1, 0, LOSE)]),
    ("HP", "2", "MARGIN", [(0, 0, 0, 2, WIN), (0, 0, 1, 0, LOSE)]),
    ("HH", "D3", "MARGIN", [(0, 0, 3, 0, WIN), (0, 0, 2, 0, LOSE)]),
    ("HH", "G3", "MARGIN", [(0, 0, 0, 3, WIN), (0, 0, 0, 2, LOSE)]),
    ("E1", "1", "MARGIN", [(0, 0, 1, 0, WIN), (0, 0, 2, 0, LOSE)]),
    ("E2", "1", "MARGIN", [(0, 0, 2, 0, WIN), (0, 0, 1, 0, LOSE)]),
    ("E1", "2", "MARGIN", [(0, 0, 0, 1, WIN), (0, 0, 0, 2, LOSE)]),
    ("E2", "2", "MARGIN", [(0, 0, 0, 2, WIN), (0, 0, 0, 1, LOSE)]),

    # --- no bet (draw voids) ----------------------------------------------
    ("XNB", "1", "NO_BET", [(0, 0, 1, 0, WIN), (0, 0, 1, 1, VOID), (0, 0, 0, 1, LOSE)]),
    ("XNB", "2", "NO_BET", [(0, 0, 0, 1, WIN), (0, 0, 1, 0, LOSE)]),
    ("H1XNB", "1", "NO_BET", [(1, 0, 1, 1, WIN), (1, 1, 1, 2, VOID)]),
    ("H2XNB", "2", "NO_BET", [(0, 0, 0, 1, WIN), (0, 0, 1, 1, VOID)]),

    # --- team goals --------------------------------------------------------
    ("HT", "2-3", "TEAM_GOALS_HOME_FT", [(0, 0, 2, 0, WIN), (0, 0, 1, 0, LOSE), (0, 0, 4, 0, LOSE)]),
    ("HT", "I>II", "TEAM_GOALS_HOME_FT", [(2, 0, 2, 0, WIN), (0, 0, 2, 0, LOSE)]),
    ("HT", "I=II", "TEAM_GOALS_HOME_FT", [(1, 0, 2, 0, WIN), (2, 0, 2, 0, LOSE)]),
    ("AT", "0-1", "TEAM_GOALS_AWAY_FT", [(0, 0, 1, 1, WIN), (0, 0, 1, 2, LOSE)]),
    ("AT", "I<II", "TEAM_GOALS_AWAY_FT", [(0, 0, 1, 2, WIN), (0, 1, 0, 1, LOSE)]),
    # regression: the 1H/2H families must settle, not fall through to UNCONFIRMED
    ("HT1", "1+", "TEAM_GOALS_HOME_1H", [(1, 0, 1, 1, WIN), (0, 0, 1, 1, LOSE)]),
    ("HT2", "0", "TEAM_GOALS_HOME_2H", [(0, 0, 0, 0, WIN), (0, 0, 1, 0, LOSE)]),
    ("AT1", "1+", "TEAM_GOALS_AWAY_1H", [(0, 1, 1, 1, WIN), (0, 0, 1, 1, LOSE)]),
    ("AT2", "2+", "TEAM_GOALS_AWAY_2H", [(0, 0, 0, 3, WIN), (0, 0, 0, 1, LOSE)]),

    # --- goal ranges -------------------------------------------------------
    ("T", "0-1", "GOAL_RANGE_FT", [(0, 0, 0, 0, WIN), (0, 0, 2, 0, LOSE)]),
    ("T", "3+", "GOAL_RANGE_FT", [(0, 0, 2, 1, WIN), (0, 0, 2, 0, LOSE)]),
    # regression: 'NE1-2' (no space) is a goal range, not a HT/FT pair
    ("T", "NE1-2", "GOAL_RANGE_FT", [(0, 0, 0, 0, WIN), (0, 0, 1, 0, LOSE),
                                     (0, 0, 2, 1, WIN), (2, 0, 2, 0, LOSE)]),
    ("T1", "0", "GOAL_RANGE_1H", [(0, 0, 0, 0, WIN), (1, 0, 1, 0, LOSE)]),
    ("T1", "4+", "GOAL_RANGE_1H", [(2, 0, 2, 0, LOSE), (2, 2, 2, 2, WIN)]),
    ("T2", "2+", "GOAL_RANGE_2H", [(0, 0, 2, 0, WIN), (0, 0, 1, 0, LOSE)]),

    # --- half-goal combos (total) -----------------------------------------
    ("C", "I1+&II1+", "HALF_GOAL_COMBOS", [(1, 0, 2, 1, WIN), (1, 0, 1, 0, LOSE)]),
    ("C", "I1+&3+", "HALF_GOAL_COMBOS", [(1, 0, 2, 1, WIN), (1, 0, 1, 0, LOSE)]),
    ("C", "NE I1+&II1+", "HALF_GOAL_COMBOS", [(0, 0, 0, 0, WIN), (1, 0, 2, 1, LOSE)]),
    # regression: I1-2 is a 1..2 goal range, not a HT/FT pair
    ("C", "I1-2&II1-2", "HALF_GOAL_COMBOS", [(1, 0, 2, 1, WIN), (1, 0, 1, 0, LOSE)]),
    ("CH", "I1+&II2+", "TEAM_HALF_COMBOS_HOME", [(1, 0, 3, 1, WIN), (1, 0, 2, 2, LOSE)]),
    ("CA", "I2+&II1+", "TEAM_HALF_COMBOS_AWAY", [(0, 2, 2, 3, WIN), (0, 1, 2, 2, LOSE)]),

    # --- which half more goals --------------------------------------------
    ("PV", "I>II", "MORE_GOALS_HALF", [(2, 0, 2, 0, WIN), (1, 0, 2, 1, LOSE)]),
    ("PV", "I=II", "MORE_GOALS_HALF", [(0, 0, 0, 0, WIN), (1, 0, 1, 0, LOSE)]),
    ("PV", "I<II", "MORE_GOALS_HALF", [(0, 0, 1, 0, WIN), (2, 0, 2, 0, LOSE)]),

    # --- odd / even --------------------------------------------------------
    ("PN", "Par", "ODD_EVEN", [(0, 0, 2, 0, WIN), (0, 0, 1, 0, LOSE)]),
    ("PN", "Nepar", "ODD_EVEN", [(0, 0, 1, 0, WIN), (0, 0, 2, 0, LOSE)]),

    # --- both teams to score ----------------------------------------------
    ("GG", "GG", "BTTS", [(0, 0, 1, 1, WIN), (0, 0, 2, 0, LOSE)]),
    ("GG", "NG", "BTTS", [(0, 0, 2, 0, WIN), (1, 1, 1, 1, LOSE)]),
    # regression: 2GG is "both score 2+", NOT its complement
    ("GG", "2GG", "BTTS", [(0, 0, 2, 2, WIN), (1, 1, 1, 1, LOSE), (0, 0, 3, 1, LOSE)]),
    ("GG", "2NG", "BTTS", [(0, 0, 3, 1, WIN), (0, 0, 2, 2, LOSE)]),
    # regression: IGG/IIGG must use their own half, in the right order
    ("GG", "IGG", "BTTS", [(1, 1, 1, 1, WIN), (0, 0, 1, 1, LOSE)]),
    ("GG", "ING", "BTTS", [(0, 0, 1, 1, WIN), (1, 1, 1, 1, LOSE)]),
    ("GG", "IIGG", "BTTS", [(0, 0, 1, 1, WIN), (1, 1, 1, 1, LOSE)]),
    ("GG", "IING", "BTTS", [(1, 1, 1, 1, WIN), (0, 0, 1, 1, LOSE)]),

    # --- BTTS combos -------------------------------------------------------
    ("GGC", "IGG&IIGG", "BTTS_COMBOS", [(1, 1, 2, 2, WIN), (1, 1, 1, 1, LOSE)]),
    ("GGC", "GG&3+", "BTTS_COMBOS", [(0, 0, 2, 1, WIN), (0, 0, 2, 0, LOSE)]),
    # regression: a leading NE negates the WHOLE conjunction, not one leg
    ("GGC", "NE GG&3+", "BTTS_COMBOS", [(0, 0, 2, 0, WIN), (0, 0, 2, 1, LOSE),
                                        (0, 0, 1, 1, WIN)]),

    # --- result / double chance and goals ---------------------------------
    ("R", "1&2+", "RESULT_AND_GOALS", [(0, 0, 2, 1, WIN), (0, 0, 1, 0, LOSE)]),
    ("R", "1&D2-3", "RESULT_AND_GOALS", [(0, 0, 2, 1, WIN), (0, 0, 4, 1, LOSE)]),
    ("R", "1&I>II", "RESULT_AND_GOALS", [(2, 0, 2, 0, WIN), (1, 0, 2, 0, LOSE)]),
    ("R", "DP1&4+", "RESULT_AND_GOALS", [(1, 0, 3, 1, WIN), (1, 0, 2, 1, LOSE)]),
    ("DCG", "1X&2+", "DOUBLE_CHANCE_AND_GOALS", [(0, 0, 1, 1, WIN), (0, 0, 0, 0, LOSE)]),
    # regression: '1-2' is a goal range here, not a HT/FT pair
    ("DCG", "1X&1-2", "DOUBLE_CHANCE_AND_GOALS", [(0, 0, 1, 1, WIN), (0, 0, 3, 1, LOSE)]),
    ("DCG", "1X&D2+", "DOUBLE_CHANCE_AND_GOALS", [(0, 0, 2, 1, WIN), (0, 0, 1, 1, LOSE)]),
    ("DCG", "12&G2+", "DOUBLE_CHANCE_AND_GOALS", [(0, 0, 0, 2, WIN), (0, 0, 0, 1, LOSE)]),
    ("HFG", "1-1&2+", "HTFT_AND_GOALS", [(1, 0, 2, 0, WIN), (1, 0, 1, 0, LOSE)]),
    ("HFG", "X-2&3+", "HTFT_AND_GOALS", [(0, 0, 1, 2, WIN), (0, 0, 1, 1, LOSE)]),
    ("HFG", "1-1&HP1", "HTFT_AND_GOALS", [(1, 0, 3, 0, WIN), (1, 0, 2, 1, LOSE)]),
    ("HFG", "2-2&GG", "HTFT_AND_GOALS", [(1, 2, 2, 3, WIN), (1, 2, 2, 2, LOSE)]),
    ("HRG", "I1&IGG", "HALF_RESULT_AND_BTTS", [(2, 1, 2, 1, WIN), (2, 0, 2, 0, LOSE)]),
    ("HRG", "II2&IIGG", "HALF_RESULT_AND_BTTS", [(1, 1, 2, 3, WIN), (1, 1, 2, 2, LOSE)]),
    ("HRG", "I2&ING", "HALF_RESULT_AND_BTTS", [(0, 1, 0, 2, WIN), (1, 1, 1, 1, LOSE)]),

    # --- OR markets --------------------------------------------------------
    ("SANSA", "1v3+", "OR_MARKETS", [(0, 0, 1, 0, WIN), (0, 0, 1, 2, WIN), (0, 0, 0, 0, LOSE)]),
    ("SANSA", "GGv3+", "OR_MARKETS", [(0, 0, 1, 1, WIN), (0, 0, 1, 0, LOSE)]),
    ("SANSA", "1:0v2:0v3:0", "OR_MARKETS", [(0, 0, 1, 0, WIN), (0, 0, 0, 0, LOSE)]),
    ("SANSA", "X-1vX-X", "OR_MARKETS", [(0, 0, 1, 0, WIN), (0, 0, 0, 0, WIN), (1, 0, 1, 1, LOSE)]),
    ("SANSA", "DI0vII0", "OR_MARKETS", [(0, 0, 1, 0, WIN), (0, 0, 0, 0, WIN), (1, 0, 2, 0, LOSE)]),
    ("SANSA", "I2vII2", "OR_MARKETS", [(0, 1, 0, 2, WIN), (0, 0, 1, 0, LOSE)]),
    ("SANSA", "I2-3vII3+", "OR_MARKETS", [(0, 0, 1, 3, WIN), (0, 0, 1, 1, LOSE)]),
    # regression: the II-before-I ordering made this a tautology (always WIN)
    ("SANSA", "GGIvNGII", "OR_MARKETS", [(1, 1, 1, 1, WIN), (0, 0, 1, 1, LOSE)]),
    ("SANSA", "NGIvGGII", "OR_MARKETS", [(0, 0, 1, 1, WIN), (1, 1, 1, 1, LOSE)]),

    # --- correct score -----------------------------------------------------
    ("CS", "2:1", "CORRECT_SCORE", [(0, 0, 2, 1, WIN), (0, 0, 2, 2, LOSE)]),
    ("CS1", "1:0", "CORRECT_SCORE_1H", [(1, 0, 3, 1, WIN), (0, 0, 1, 0, LOSE)]),
]


@pytest.mark.parametrize("prefix,code,family,scores", CASES,
                         ids=[f"{p}-{c}" for p, c, _, _ in CASES])
def test_official_definition(prefix, code, family, scores):
    market = resolve(prefix, code)
    assert market.status == "OK"
    assert market.family == family
    for hth, hta, fth, fta, expected in scores:
        assert market.outcome(hth, hta, fth, fta) == expected, (
            f"{prefix}:{code} on {hth}-{hta}/{fth}-{fta}")


# --------------------------------------------------------------------------- #
# untestable and unconfirmed
# --------------------------------------------------------------------------- #
def test_first_goal_and_minute_markets_are_untestable():
    for prefix, code, family in [("PDG", "1", "FIRST_GOAL"), ("PDG1", "2", "FIRST_GOAL"),
                                 ("PDG2", "1", "FIRST_GOAL"), ("PGC", "PG1&2+", "FIRST_GOAL"),
                                 ("M15", "1", "MINUTE_MARKETS"), ("M30", "G2+", "MINUTE_MARKETS")]:
        market = resolve(prefix, code)
        assert (market.family, market.status) == (family, "UNTESTABLE")
        assert market.outcome(1, 1, 2, 2) == VOID


def test_unknown_prefix_is_unconfirmed():
    market = resolve("ZZ", "whatever")
    assert market.status == "UNCONFIRMED"
    assert market.outcome(0, 0, 1, 0) == UNCONFIRMED


def test_unsettleable_codes_are_refused_not_guessed():
    # 'GG3+' (both score AND 3+?) and the malformed 'I2-3+' have no unambiguous
    # reading from the printed code alone.
    for prefix, code in [("SANSA", "1vGG3+"), ("SANSA", "2vGG3+"), ("SANSA", "I2-3+vII3+")]:
        assert resolve(prefix, code).status == "UNCONFIRMED"


def test_every_market_returns_a_known_outcome():
    for prefix, code, _family, _scores in CASES:
        market = resolve(prefix, code)
        for hth, hta, fth, fta in itertools.product(range(3), repeat=4):
            assert market.outcome(hth, hta, fth, fta) in (WIN, LOSE, VOID, UNCONFIRMED)


# --------------------------------------------------------------------------- #
# partitions: exactly `reference` markets win on every scoreline
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", sorted(PARTITIONS))
def test_partition_is_exhaustive(name):
    reference, keys = PARTITIONS[name]
    markets = []
    for key in keys:
        prefix, code = key.split(":", 1)
        market = resolve(prefix, code)
        assert market.status == "OK", f"{key} does not resolve"
        markets.append(market)
    for hth, hta, fth, fta in itertools.product(range(4), repeat=4):
        wins = sum(m.outcome(hth, hta, fth, fta) == WIN for m in markets)
        assert wins == reference, (
            f"{name} on {hth}-{hta}/{fth}-{fta}: {wins} winners, expected {reference}")


# --------------------------------------------------------------------------- #
# parser unit checks
# --------------------------------------------------------------------------- #
def test_parse_component_refuses_ambiguous_gg_variants():
    assert parse_component("GG") is not None
    assert parse_component("GG2") is not None
    assert parse_component("GG3+") is None
    assert parse_component("IGG") is not None
    assert parse_component("GGI") is not None


# --------------------------------------------------------------------------- #
# the sample file (skipped when data/ is absent)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not RAW.exists(), reason="sample capture not present (data/ is gitignored)")
def test_sample_resolves_with_only_the_known_unconfirmed_codes():
    from step1b_ingest_soccerbet import parse_blocks

    rows = parse_blocks()
    assert len(rows) == 777
    statuses = {}
    unconfirmed = set()
    for prefix, code, _odds in rows:
        market = resolve(prefix, code)
        statuses[market.status] = statuses.get(market.status, 0) + 1
        if market.status == "UNCONFIRMED":
            unconfirmed.add(f"{prefix}:{code}")
    assert statuses == {"OK": 720, "UNTESTABLE": 54, "UNCONFIRMED": 3}
    assert unconfirmed == {"SANSA:1vGG3+", "SANSA:2vGG3+", "SANSA:I2-3+vII3+"}