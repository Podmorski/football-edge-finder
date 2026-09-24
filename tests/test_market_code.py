"""Tests for the Soccer Bet market-code parser.

Covers: official definitions on hand-made scores, the NE complement property,
the HTFT partition, the "1-2" disambiguation, and a catalogue round-trip.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest
import yaml

from core.market_code import WIN, LOSE, VOID, is_ambiguous, parse

CATALOGUE = Path("config/markets_catalogue.yaml")


def load_catalogue() -> list[dict]:
    return yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))["markets"]


# --------------------------------------------------------------------------- #
# official definitions on hand-made scores
# --------------------------------------------------------------------------- #
# (code, family, [(hth, hta, fth, fta, expected), ...])  -- at least 5 scores each
CASES: list[tuple[str, str, list[tuple[int, int, int, int, str]]]] = [
    ("1", "RESULT", [
        (0, 0, 1, 0, WIN), (0, 0, 2, 1, WIN), (0, 0, 0, 0, LOSE),
        (0, 0, 1, 1, LOSE), (0, 0, 0, 1, LOSE),
    ]),
    ("X", "RESULT", [
        (0, 0, 0, 0, WIN), (1, 1, 1, 1, WIN), (0, 0, 2, 2, WIN),
        (0, 0, 1, 0, LOSE), (0, 0, 0, 1, LOSE),
    ]),
    ("2", "RESULT", [
        (0, 0, 0, 1, WIN), (0, 0, 1, 2, WIN), (0, 0, 0, 0, LOSE),
        (0, 0, 1, 1, LOSE), (0, 0, 1, 0, LOSE),
    ]),
    ("1X", "DOUBLE_CHANCE", [
        (0, 0, 1, 0, WIN), (0, 0, 0, 0, WIN), (0, 0, 1, 1, WIN),
        (0, 0, 0, 1, LOSE), (0, 0, 1, 2, LOSE),
    ]),
    ("12", "DOUBLE_CHANCE", [
        (0, 0, 1, 0, WIN), (0, 0, 0, 1, WIN), (0, 0, 0, 0, LOSE),
        (0, 0, 1, 1, LOSE), (0, 0, 2, 2, LOSE),
    ]),
    ("X2", "DOUBLE_CHANCE", [
        (0, 0, 0, 0, WIN), (0, 0, 0, 1, WIN), (0, 0, 1, 1, WIN),
        (0, 0, 1, 0, LOSE), (0, 0, 2, 1, LOSE),
    ]),
    ("I1", "HALF_RESULT", [
        (1, 0, 0, 0, WIN), (2, 1, 3, 1, WIN), (0, 0, 1, 0, LOSE),
        (1, 1, 2, 2, LOSE), (0, 1, 0, 1, LOSE),
    ]),
    ("II2", "HALF_RESULT", [
        (0, 0, 0, 1, WIN), (1, 1, 1, 2, WIN), (0, 0, 1, 0, LOSE),
        (0, 0, 1, 1, LOSE), (0, 0, 0, 0, LOSE),
    ]),
    ("I1X", "HALF_DC", [
        (1, 0, 0, 0, WIN), (0, 0, 0, 0, WIN), (1, 1, 1, 1, WIN),
        (0, 1, 0, 1, LOSE), (0, 2, 0, 2, LOSE),
    ]),
    ("3+", "GOAL_RANGE_FT", [
        (1, 1, 2, 1, WIN), (0, 0, 3, 0, WIN), (0, 0, 2, 2, WIN),
        (0, 0, 1, 1, LOSE), (0, 0, 0, 0, LOSE),
    ]),
    ("1-2", "GOAL_RANGE_FT", [
        (0, 0, 1, 0, WIN), (0, 0, 2, 0, WIN), (0, 0, 1, 1, WIN),
        (0, 0, 0, 0, LOSE), (0, 0, 3, 0, LOSE),
    ]),
    ("0-2", "GOAL_RANGE_FT", [
        (0, 0, 0, 0, WIN), (0, 0, 1, 0, WIN), (0, 0, 2, 0, WIN),
        (0, 0, 3, 0, LOSE), (0, 0, 2, 2, LOSE),
    ]),
    ("I1+", "GOAL_RANGE_1H", [
        (1, 0, 1, 0, WIN), (2, 1, 2, 1, WIN), (0, 0, 3, 0, LOSE),
        (0, 0, 1, 0, LOSE), (0, 0, 0, 0, LOSE),
    ]),
    ("II2+", "GOAL_RANGE_2H", [
        (0, 0, 1, 1, WIN), (1, 1, 2, 2, WIN), (0, 0, 2, 0, WIN),
        (0, 0, 1, 0, LOSE), (0, 0, 0, 0, LOSE),
    ]),
    ("1-1", "HTFT", [
        (1, 0, 2, 0, WIN), (1, 0, 3, 1, WIN), (1, 0, 1, 1, LOSE),
        (0, 0, 1, 0, LOSE), (0, 1, 1, 0, LOSE),
    ]),
    ("X-X", "HTFT", [
        (0, 0, 0, 0, WIN), (1, 1, 1, 1, WIN), (0, 0, 1, 0, LOSE),
        (0, 0, 0, 1, LOSE), (1, 0, 1, 0, LOSE),
    ]),
    ("1X-12", "HTFT_DC", [
        (1, 0, 2, 1, WIN), (0, 0, 1, 0, WIN), (1, 1, 2, 1, WIN),
        (0, 1, 0, 1, LOSE), (1, 0, 1, 1, LOSE),
    ]),
]


@pytest.mark.parametrize("code,family,scores", CASES, ids=[c[0] for c in CASES])
def test_official_definitions(code, family, scores):
    market = parse(code, family)
    assert len(scores) >= 5
    for hth, hta, fth, fta, expected in scores:
        got = market.outcome(hth, hta, fth, fta)
        assert got == expected, f"{code} on {(hth, hta, fth, fta)}: {got} != {expected}"


def test_direct_family_definitions():
    from core.market_code import direct_markets

    by_code = {m.code: m for m in direct_markets()}
    # Pada Vise Golova
    assert by_code["I>II"].outcome(2, 0, 2, 0) == WIN
    assert by_code["I>II"].outcome(0, 0, 1, 0) == LOSE
    assert by_code["I=II"].outcome(1, 0, 1, 1) == WIN
    assert by_code["I=II"].outcome(1, 0, 1, 0) == LOSE
    assert by_code["I<II"].outcome(0, 0, 1, 0) == WIN
    assert by_code["I<II"].outcome(2, 0, 2, 0) == LOSE
    # Dupla Pobeda: home wins both halves
    dp = by_code["DP 1"]
    assert dp.outcome(1, 0, 2, 0) == WIN
    assert dp.outcome(1, 0, 1, 1) == LOSE
    assert dp.outcome(0, 1, 1, 2) == LOSE
    # Dupla Super Pobeda: home wins both halves and away scores 0
    dsp = by_code["DSP 1"]
    assert dsp.outcome(1, 0, 2, 0) == WIN
    assert dsp.outcome(1, 1, 2, 1) == LOSE
    # Super Pobeda: win to nil
    sp = by_code["SP 1"]
    assert sp.outcome(1, 0, 2, 0) == WIN
    assert sp.outcome(1, 1, 2, 1) == LOSE
    # HP / HH / exact margins
    assert by_code["HP 1"].outcome(0, 0, 2, 0) == WIN
    assert by_code["HP 1"].outcome(0, 0, 2, 1) == LOSE
    assert by_code["HH 1 3+"].outcome(0, 0, 3, 0) == WIN
    assert by_code["HH 1 3+"].outcome(0, 0, 2, 0) == LOSE
    assert by_code["W1 1"].outcome(0, 0, 1, 0) == WIN
    assert by_code["W1 1"].outcome(0, 0, 2, 0) == LOSE
    assert by_code["W2 1"].outcome(0, 0, 2, 0) == WIN
    assert by_code["W2 1"].outcome(0, 0, 3, 0) == LOSE
    # X No Bet voids on a draw
    assert by_code["XNB FT 1"].outcome(0, 0, 0, 0) == VOID
    assert by_code["XNB FT 1"].outcome(0, 0, 1, 0) == WIN
    assert by_code["XNB FT 1"].outcome(0, 0, 0, 1) == LOSE
    assert by_code["XNB 1. Pol. 1"].outcome(0, 0, 0, 0) == VOID
    assert by_code["XNB 1. Pol. 1"].outcome(1, 0, 1, 0) == WIN
    # first goal is untestable
    assert by_code["FDG FT 1"].testable is False
    assert by_code["FDG FT 1"].outcome(1, 0, 2, 0) == VOID


# --------------------------------------------------------------------------- #
# NE combos (the three cases named in the brief)
# --------------------------------------------------------------------------- #
def test_ne_i1_and_ii1_wins_iff_a_half_has_zero_goals():
    m = parse("NE I1+&II1+", "HALF_GOAL_COMBOS")
    for hth, hta, h2, a2 in itertools.product(range(4), repeat=4):
        fth, fta = hth + h2, hta + a2
        first, second = hth + hta, h2 + a2
        expected = WIN if (first == 0 or second == 0) else LOSE
        assert m.outcome(hth, hta, fth, fta) == expected


def test_ne_i1_3_and_ii1_3_wins_iff_a_half_is_outside_1_2_3():
    m = parse("NE I1-3&II1-3", "HALF_GOAL_COMBOS")
    for hth, hta, h2, a2 in itertools.product(range(4), repeat=4):
        fth, fta = hth + h2, hta + a2
        first, second = hth + hta, h2 + a2
        expected = WIN if not (1 <= first <= 3 and 1 <= second <= 3) else LOSE
        assert m.outcome(hth, hta, fth, fta) == expected


def test_ne_i1_and_ii2_wins_iff_first_is_zero_or_second_at_most_one():
    m = parse("NE I1+&II2+", "HALF_GOAL_COMBOS")
    for hth, hta, h2, a2 in itertools.product(range(4), repeat=4):
        fth, fta = hth + h2, hta + a2
        first, second = hth + hta, h2 + a2
        expected = WIN if (first == 0 or second <= 1) else LOSE
        assert m.outcome(hth, hta, fth, fta) == expected


# --------------------------------------------------------------------------- #
# every NE code is the exact complement of its base
# --------------------------------------------------------------------------- #
def test_every_ne_code_is_the_exact_complement_of_its_base():
    checked = 0
    for entry in load_catalogue():
        code = entry["code"]
        if not code.startswith("NE "):
            continue
        base = parse(code[3:], entry["family"])
        negated = parse(code, entry["family"])
        for hth, hta, h2, a2 in itertools.product(range(4), repeat=4):
            fth, fta = hth + h2, hta + a2
            b = base.outcome(hth, hta, fth, fta)
            n = negated.outcome(hth, hta, fth, fta)
            assert n == (LOSE if b == WIN else WIN), f"{code} vs {code[3:]} on {(hth, hta, fth, fta)}"
        checked += 1
    assert checked >= 16, f"only checked {checked} NE codes"


# --------------------------------------------------------------------------- #
# HTFT 9 outcomes partition
# --------------------------------------------------------------------------- #
def test_htft_nine_outcomes_partition():
    nine = ["1-1", "1-X", "1-2", "X-1", "X-X", "X-2", "2-1", "2-X", "2-2"]
    markets = [parse(c, "HTFT") for c in nine]
    for hth, hta, h2, a2 in itertools.product(range(4), repeat=4):
        fth, fta = hth + h2, hta + a2
        wins = sum(1 for m in markets if m.outcome(hth, hta, fth, fta) == WIN)
        assert wins == 1, f"{(hth, hta, fth, fta)} matched {wins} HTFT outcomes"


# --------------------------------------------------------------------------- #
# disambiguation
# --------------------------------------------------------------------------- #
def test_1_2_disambiguation():
    assert is_ambiguous("1-2")
    htft = parse("1-2", "HTFT")
    assert htft.outcome(1, 0, 1, 2) == WIN
    assert htft.outcome(0, 0, 1, 1) == LOSE
    goals = parse("1-2", "GOAL_RANGE_FT")
    assert goals.outcome(0, 0, 1, 0) == WIN
    assert goals.outcome(1, 0, 1, 2) == LOSE
    with pytest.raises(ValueError):
        parse("1-2")


def test_unambiguous_codes_need_no_family():
    assert parse("3+").outcome(0, 0, 3, 0) == WIN
    assert parse("1X").outcome(0, 0, 0, 0) == WIN
    assert parse("X-X").outcome(0, 0, 0, 0) == WIN


def test_spaces_around_ampersand_are_optional():
    a = parse("I1+&II1+", "HALF_GOAL_COMBOS")
    b = parse("I1+ & II1+", "HALF_GOAL_COMBOS")
    for hth, hta, h2, a2 in itertools.product(range(3), repeat=4):
        fth, fta = hth + h2, hta + a2
        assert a.outcome(hth, hta, fth, fta) == b.outcome(hth, hta, fth, fta)


# --------------------------------------------------------------------------- #
# catalogue round-trip
# --------------------------------------------------------------------------- #
DIRECT_FAMILIES = {
    "WIN_BOTH_HALVES", "WIN_BOTH_HALVES_TO_NIL", "WIN_TO_NIL", "MARGIN", "NO_BET",
    "MORE_GOALS_HALF", "FIRST_GOAL", "TO_QUALIFY",
}


def test_parser_round_trips_every_catalogue_code():
    from core.market_code import direct_markets

    entries = load_catalogue()
    assert len(entries) >= 200
    direct = {m.code: m for m in direct_markets()}
    for entry in entries:
        if entry["family"] in DIRECT_FAMILIES:
            market = direct[entry["code"]]
        else:
            market = parse(entry["code"], entry["family"], entry["label_sr"],
                           entry["definition_en"], section=entry["section"])
        assert market.code == entry["code"]
        assert market.family == entry["family"]
        assert market.section == entry["section"]
        assert market.definition_en == entry["definition_en"]
        assert market.testable == entry["testable"]


def test_catalogue_accepts_new_codes_at_runtime():
    """Any parseable code is priceable, family UNLISTED until tested."""
    market = parse("I3-4&II3-4", None)
    assert market.family == "UNLISTED"
    assert market.outcome(2, 1, 4, 2) == WIN
    assert market.outcome(0, 0, 1, 1) == LOSE
