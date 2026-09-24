"""The SECTION decides what a code means.

A bare code is ambiguous and is never used to guess a market's meaning:
``1`` is a home win under ``Konačni Ishod`` and exactly one goal under
``Ukupno Golova``; ``I1`` is a home win in the first half under ``Poluvreme`` and
exactly one first-half goal under ``I Pol. Uk. Golova``.

The cases below are pinned to the user's clarification (2026-09-24), which is
authoritative, plus the guard that the goal families can only ever settle on goal
totals — the bug that made 12 catalogue codes mean something else entirely.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest
import yaml

from core.market_code import (
    GOAL_FAMILIES,
    SECTIONS,
    LOSE,
    VOID,
    WIN,
    parse,
    section_family,
)

CATALOGUE = Path("config/markets_catalogue.yaml")


def load_catalogue() -> list[dict]:
    return yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))["markets"]


PERIOD_OF = {"GOAL_RANGE_FT": "FT", "GOAL_RANGE_1H": "1H", "GOAL_RANGE_2H": "2H"}


def period_total(period: str, hth: int, hta: int, fth: int, fta: int) -> int:
    if period == "1H":
        return hth + hta
    if period == "2H":
        return (fth - hth) + (fta - hta)
    return fth + fta


# --------------------------------------------------------------------------- #
# the user's pinned examples
# --------------------------------------------------------------------------- #
# (section, code, family, one-line meaning, [(score, expected), ...]) where
# `score` is (hth, hta, fth, fta). Every case has scores that discriminate it
# from the other section that shares the same code.
SECTION_CASES = [
    ("Konačni Ishod", "1", "RESULT", "home win",
     [((0, 0, 1, 0), WIN), ((0, 0, 2, 1), WIN), ((0, 0, 0, 0), LOSE), ((0, 0, 0, 1), LOSE)]),
    ("Ukupno Golova", "1", "GOAL_RANGE_FT", "exactly 1 goal",
     [((0, 0, 1, 0), WIN), ((0, 0, 0, 1), WIN), ((0, 0, 0, 0), LOSE), ((0, 0, 2, 0), LOSE)]),
    ("Ukupno Golova", "2", "GOAL_RANGE_FT", "exactly 2 goals",
     [((0, 0, 2, 0), WIN), ((0, 0, 1, 1), WIN), ((0, 0, 1, 0), LOSE), ((0, 0, 3, 0), LOSE)]),
    ("I Pol. Uk. Golova", "I1", "GOAL_RANGE_1H", "exactly 1 goal in the 1st half",
     [((1, 0, 3, 1), WIN), ((0, 1, 0, 1), WIN), ((2, 1, 2, 1), LOSE), ((0, 0, 3, 0), LOSE)]),
    ("Poluvreme", "I1", "HALF_RESULT", "home wins the 1st half",
     [((1, 0, 3, 1), WIN), ((0, 1, 0, 1), LOSE), ((2, 1, 2, 1), WIN), ((1, 1, 1, 1), LOSE)]),
    ("II Pol. Uk. Golova", "II2", "GOAL_RANGE_2H", "exactly 2 goals in the 2nd half",
     [((0, 0, 2, 0), WIN), ((1, 1, 2, 2), WIN), ((0, 0, 1, 0), LOSE), ((0, 0, 3, 0), LOSE)]),
    ("II Poluvreme", "II2", "HALF_RESULT", "away wins the 2nd half",
     [((0, 0, 0, 1), WIN), ((1, 1, 2, 2), LOSE), ((0, 0, 2, 0), LOSE)]),
]


@pytest.mark.parametrize("section,code,family,meaning,scores", SECTION_CASES,
                         ids=[f"{s[:12]}|{c}" for s, c, _, _, _ in SECTION_CASES])
def test_the_section_decides_the_market(section, code, family, meaning, scores):
    market = parse(code, section=section)
    assert market.family == family, f"{section} {code}: {market.family} != {family}"
    assert market.section == section
    for score, expected in scores:
        got = market.outcome(*score)
        assert got == expected, f"{section} {code} ({meaning}) on {score}: {got} != {expected}"


def test_the_same_bare_code_means_two_different_markets():
    """The headline ambiguity: `1`, and `I1`, under two different sections."""
    one = {section: parse("1", section=section).family
           for section in ("Konačni Ishod", "Ukupno Golova")}
    assert one == {"Konačni Ishod": "RESULT", "Ukupno Golova": "GOAL_RANGE_FT"}

    half = {section: parse("I1", section=section).family
            for section in ("Poluvreme", "I Pol. Uk. Golova")}
    assert half == {"Poluvreme": "HALF_RESULT", "I Pol. Uk. Golova": "GOAL_RANGE_1H"}

    # and they disagree on a score where the 1st half had two goals
    score = (2, 1, 2, 1)
    assert parse("I1", section="Poluvreme").outcome(*score) == WIN
    assert parse("I1", section="I Pol. Uk. Golova").outcome(*score) == LOSE


def test_an_unknown_section_is_refused_rather_than_guessed():
    with pytest.raises(ValueError, match="unknown section"):
        parse("1", section="Neka Sekcija")


def test_a_section_that_contradicts_the_family_is_refused():
    with pytest.raises(ValueError, match="says GOAL_RANGE_FT"):
        parse("1", "RESULT", section="Ukupno Golova")


def test_every_section_maps_to_a_known_family():
    from core.market_code import FAMILY_SECTION

    assert set(SECTIONS.values()) <= set(FAMILY_SECTION)
    assert len(SECTIONS) >= 29


# --------------------------------------------------------------------------- #
# the 12 codes the goal families used to misparse
# --------------------------------------------------------------------------- #
# (section, code, the goal count it means) — all 12 were read as results.
MISPARSED = [
    ("Ukupno Golova", "1", lambda t: t == 1),
    ("Ukupno Golova", "2", lambda t: t == 2),
    ("Ukupno Golova", "NE 1", lambda t: t != 1),
    ("Ukupno Golova", "NE 2", lambda t: t != 2),
    ("I Pol. Uk. Golova", "I1", lambda t: t == 1),
    ("I Pol. Uk. Golova", "I2", lambda t: t == 2),
    ("I Pol. Uk. Golova", "NE 1", lambda t: t != 1),
    ("I Pol. Uk. Golova", "NE 2", lambda t: t != 2),
    ("II Pol. Uk. Golova", "II1", lambda t: t == 1),
    ("II Pol. Uk. Golova", "II2", lambda t: t == 2),
    ("II Pol. Uk. Golova", "NE 1", lambda t: t != 1),
    ("II Pol. Uk. Golova", "NE 2", lambda t: t != 2),
]


@pytest.mark.parametrize("section,code,predicate", MISPARSED,
                         ids=[f"{s.split()[0]}-{c}" for s, c, _ in MISPARSED])
def test_the_12_misparsed_codes_settle_on_goal_counts(section, code, predicate):
    market = parse(code, section=section)
    period = PERIOD_OF[market.family]
    assert market.family.startswith("GOAL_RANGE")
    for hth, hta, h2, a2 in itertools.product(range(4), repeat=4):
        fth, fta = hth + h2, hta + a2
        total = period_total(period, hth, hta, fth, fta)
        expected = WIN if predicate(total) else LOSE
        got = market.outcome(hth, hta, fth, fta)
        assert got == expected, f"{section} {code} on {(hth, hta, fth, fta)}: {got} != {expected}"


def test_the_misparsed_codes_now_disagree_with_the_result_reading():
    """`GOAL_RANGE_FT 1` must no longer be `RESULT 1` (it was, before the fix)."""
    result = parse("1", "RESULT")
    goals = parse("1", "GOAL_RANGE_FT")
    disagreements = 0
    for hth, hta, h2, a2 in itertools.product(range(3), repeat=4):
        fth, fta = hth + h2, hta + a2
        disagreements += result.outcome(hth, hta, fth, fta) != goals.outcome(hth, hta, fth, fta)
    assert disagreements > 0


# --------------------------------------------------------------------------- #
# guard: a goal family can ONLY settle on goal totals
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("family", sorted(GOAL_FAMILIES))
def test_every_code_in_a_goal_family_settles_on_the_goal_total(family):
    """The outcome must be a function of the period's goal total, nothing else.

    This is the invariant the 12 misparsed codes violated: as a result market,
    `GOAL_RANGE_1H I1` depended on which team was ahead, not on the goal count.
    """
    from core.market_code import FAMILY_SECTION

    codes = [entry["code"] for entry in load_catalogue() if entry["family"] == family]
    assert len(codes) >= 15
    period = PERIOD_OF[family]
    for code in codes:
        market = parse(code, family, section=FAMILY_SECTION[family])
        by_total: dict[int, set[str]] = {}
        for hth, hta, h2, a2 in itertools.product(range(4), repeat=4):
            fth, fta = hth + h2, hta + a2
            total = period_total(period, hth, hta, fth, fta)
            by_total.setdefault(total, set()).add(market.outcome(hth, hta, fth, fta))
        for total, outcomes in by_total.items():
            assert len(outcomes) == 1, (
                f"{family} {code}: {total} goals can be both {sorted(outcomes)}")


def test_a_section_loads_every_code_the_catalogue_puts_in_it():
    """Round-trip: for each section, every catalogue code in it parses back."""
    checked = 0
    for entry in load_catalogue():
        section = entry["section"]
        if entry["family"] in {"WIN_BOTH_HALVES", "WIN_BOTH_HALVES_TO_NIL", "WIN_TO_NIL",
                              "MARGIN", "NO_BET", "MORE_GOALS_HALF", "FIRST_GOAL",
                              "TO_QUALIFY"}:
            continue                      # implemented directly, not through the grammar
        market = parse(entry["code"], section=section)
        assert (market.family, market.section) == (entry["family"], section)
        checked += 1
    assert checked >= 120


# --------------------------------------------------------------------------- #
# Poluvreme-GG: the 12 printed codes of one section
# --------------------------------------------------------------------------- #
HRG_SECTION = "Soccer Kombinacije Poluvreme-GG"

HRG_MEANINGS = {
    "I1&IGG": ("1H", "1", "GG"), "IX&IGG": ("1H", "X", "GG"), "I2&IGG": ("1H", "2", "GG"),
    "I1&ING": ("1H", "1", "NG"), "IX&ING": ("1H", "X", "NG"), "I2&ING": ("1H", "2", "NG"),
    "II1&IIGG": ("2H", "1", "GG"), "IIX&IIGG": ("2H", "X", "GG"), "II2&IIGG": ("2H", "2", "GG"),
    "II1&IING": ("2H", "1", "NG"), "IIX&IING": ("2H", "X", "NG"), "II2&IING": ("2H", "2", "NG"),
}


def half_result(period_scores: tuple[int, int], token: str) -> bool:
    home, away = period_scores
    return {"1": home > away, "X": home == away, "2": home < away}[token]


def both_scored(period_scores: tuple[int, int], token: str) -> bool:
    home, away = period_scores
    hit = home > 0 and away > 0
    return hit if token == "GG" else not hit


def test_poluvreme_gg_has_the_12_printed_codes_with_the_stated_meanings():
    from core.soccerbet_ext import resolve

    assert len(HRG_MEANINGS) == 12
    for code, (half, result_token, btts_token) in HRG_MEANINGS.items():
        assert section_family(HRG_SECTION, code) == "HALF_RESULT_AND_BTTS"
        market = resolve("HRG", code)
        assert market.section == HRG_SECTION
        for hth, hta, h2, a2 in itertools.product(range(3), repeat=4):
            fth, fta = hth + h2, hta + a2
            scores = (hth, hta) if half == "1H" else (fth - hth, fta - hta)
            expected = WIN if (half_result(scores, result_token)
                              and both_scored(scores, btts_token)) else LOSE
            got = market.outcome(hth, hta, fth, fta)
            assert got == expected, f"HRG:{code} on {(hth, hta, fth, fta)}: {got} != {expected}"


def test_poluvreme_gg_is_registered_with_all_12_codes():
    doc = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
    groups = [group for family in doc["ext_markets"]["families"]
              for group in family["prefixes"]
              if family["family"] == "HALF_RESULT_AND_BTTS"]
    assert len(groups) == 1
    assert groups[0]["section"] == HRG_SECTION
    assert set(groups[0]["codes"]) == set(HRG_MEANINGS)
    # two of the twelve are the same bet as a bare goal-range price; recorded, not hidden
    assert groups[0]["settles_like_a_base_market"] == {
        "HRG:IX&ING": "GOAL_RANGE_1H I0",
        "HRG:IIX&IING": "GOAL_RANGE_2H II0",
    }


def test_untestable_sections_are_named_or_flagged_never_invented():
    from core.soccerbet_ext import SECTION_UNCONFIRMED, resolve

    for prefix in ("PDG", "PDG1", "PDG2", "HF", "T", "T1", "T2", "HRG", "FT",
                   "HT", "HT1", "HT2", "AT", "AT1", "AT2", "C", "CH", "CA",
                   "CS", "CS1", "PN", "GG", "R", "DCG", "HFG", "GGC", "PGC",
                   "SANSA", "M15", "M30"):
        assert resolve(prefix, "1").section != SECTION_UNCONFIRMED
    # a prefix with no confirmed display name says so instead of guessing
    assert resolve("ZZZ", "1").section == SECTION_UNCONFIRMED


def test_gg_and_hf_sections_depend_on_the_code():
    """GG and HF carry several displayed sections under one prefix."""
    from core.soccerbet_ext import resolve

    assert resolve("GG", "GG").section == "Oba Tima Daju Gol"
    assert resolve("GG", "NG").section == "Oba Tima Daju Gol"
    assert resolve("GG", "2GG").section == "Oba Tima Daju Gol"
    assert resolve("GG", "IGG").section == "1. Pol. Oba Tima Daju Gol"
    assert resolve("GG", "ING").section == "1. Pol. Oba Tima Daju Gol"
    assert resolve("GG", "IIGG").section == "2. Pol. Oba Tima Daju Gol"
    assert resolve("GG", "IING").section == "2. Pol. Oba Tima Daju Gol"
    assert resolve("GG", "IGG&IIGG").section == "Oba Tima Daju Gol"
    assert resolve("HF", "1-1").section == "Poluvreme/Kraj"
    assert resolve("HF", "NEX-1").section == "Poluvreme/Kraj"
    assert resolve("HF", "1X-1X").section == "Poluvreme/Kraj DS"
