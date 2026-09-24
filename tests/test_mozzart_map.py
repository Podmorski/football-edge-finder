"""Mozzart market mapping: the section decides the code, and unmapped is refused.

The cases are pinned to the raw PulseScore sample (Netherlands v Germany,
2026-09-24) and settle on hand-made ``(hth, hta, fth, fta)`` scorelines.
"""

from __future__ import annotations

import pytest

from core.market_code import LOSE, VOID, WIN
from core.mozzart_map import UNMAPPED, load_rules, resolve, unmapped_sections

# (section, period, code, family, [(score, expected), ...])
CASES = [
    ("Konačan ishod", "FULL_TIME", "1", "RESULT",
     [((0, 0, 1, 0), WIN), ((0, 0, 0, 0), LOSE)]),
    ("Konačan ishod", "FULL_TIME", "X", "RESULT",
     [((0, 0, 1, 1), WIN), ((0, 0, 1, 0), LOSE)]),
    ("Ukupno golova na meču", "FULL_TIME", "2+", "GOAL_RANGE_FT",
     [((0, 0, 1, 1), WIN), ((0, 0, 1, 0), LOSE)]),
    ("Tačan broj golova na meču", "FULL_TIME", "3", "GOAL_RANGE_FT",
     [((0, 0, 2, 1), WIN), ((0, 0, 2, 0), LOSE)]),
    ("Prvo poluvreme", "FIRST_HALF", "1", "HALF_RESULT",
     [((1, 0, 0, 0), WIN), ((0, 1, 0, 1), LOSE)]),
    ("Dupla šansa prvo poluvreme", "FIRST_HALF", "1X", "HALF_DC",
     [((0, 0, 0, 0), WIN), ((0, 1, 0, 1), LOSE)]),
    ("Ukupno golova prvo poluvreme", "FIRST_HALF", "2+", "GOAL_RANGE_1H",
     [((2, 0, 0, 0), WIN), ((1, 0, 0, 0), LOSE)]),
    ("Drugo poluvreme", "SECOND_HALF", "2", "HALF_RESULT",
     [((0, 0, 0, 1), WIN), ((0, 0, 1, 0), LOSE)]),
    ("Ukupno golova drugo poluvreme", "SECOND_HALF", "1+", "GOAL_RANGE_2H",
     [((0, 0, 1, 0), WIN), ((0, 0, 0, 0), LOSE)]),
    ("Poluvreme - Kraj", "FULL_TIME", "1-1", "HTFT",
     [((1, 0, 2, 1), WIN), ((0, 0, 1, 0), LOSE)]),
    ("Poluvreme - Kraj", "FULL_TIME", "NE 1-1", "HTFT_NE",
     [((0, 0, 1, 0), WIN), ((1, 0, 2, 1), LOSE)]),
    ("Poluvreme- Kraj / Dupla šansa", "FULL_TIME", "1X-1X", "HTFT_DC",
     [((0, 0, 1, 1), WIN), ((0, 0, 0, 1), LOSE)]),
    ("Poluvreme sa više golova", "FULL_TIME", "prvo", "MORE_GOALS_HALF",
     [((2, 0, 2, 0), WIN), ((0, 0, 1, 0), LOSE)]),
    ("Oba tima daju gol", "FULL_TIME", "GG", "BTTS",
     [((0, 0, 1, 1), WIN), ((0, 0, 1, 0), LOSE)]),
    ("Oba tima daju gol", "FIRST_HALF", "IGG", "BTTS",
     [((1, 1, 1, 1), WIN), ((1, 0, 2, 1), LOSE)]),
    ("Oba tima daju gol", "SECOND_HALF", "IIGG", "BTTS",
     [((0, 0, 1, 1), WIN), ((1, 1, 1, 1), LOSE)]),
    ("Ukupno golova - Par/Nepar", "FULL_TIME", "PAR", "ODD_EVEN",
     [((0, 0, 1, 1), WIN), ((0, 0, 1, 0), LOSE)]),
    ("Winner", "FULL_TIME", "W1", "NO_BET",
     [((0, 0, 1, 0), WIN), ((0, 0, 1, 1), VOID), ((0, 0, 0, 1), LOSE)]),
    ("Dupla pobeda", "FULL_TIME", "DP1", "WIN_BOTH_HALVES",
     [((1, 0, 2, 0), WIN), ((1, 0, 1, 1), LOSE)]),
    ("Sigurna pobeda", "FULL_TIME", "SP2", "WIN_TO_NIL",
     [((0, 0, 0, 1), WIN), ((0, 0, 1, 1), LOSE)]),
    ("Hendikep pobeda", "FULL_TIME", "1", "MARGIN",
     [((0, 0, 2, 0), WIN), ((0, 0, 1, 0), LOSE)]),
    ("Tim 1 daje gol", "FULL_TIME", "2+", "TEAM_GOALS_HOME_FT",
     [((0, 0, 2, 0), WIN), ((0, 0, 1, 0), LOSE)]),
    ("Tim 2 daje gol", "FULL_TIME", "0", "TEAM_GOALS_AWAY_FT",
     [((1, 0, 2, 0), WIN), ((0, 0, 1, 1), LOSE)]),
    ("Tačan rezultat", "FULL_TIME", "2:1", "CORRECT_SCORE",
     [((0, 0, 2, 1), WIN), ((0, 0, 1, 2), LOSE)]),
    ("Konačan ishod + Golovi", "FULL_TIME", "1&2+", "RESULT_AND_GOALS",
     [((0, 0, 2, 1), WIN), ((0, 0, 1, 0), LOSE)]),
    ("Dupla šansa + Golovi", "FULL_TIME", "1X&2+", "DOUBLE_CHANCE_AND_GOALS",
     [((0, 0, 1, 1), WIN), ((0, 0, 0, 1), LOSE)]),
    ("Poluvreme - Kraj + Golovi", "FULL_TIME", "1-1&2+", "HTFT_AND_GOALS",
     [((1, 0, 2, 1), WIN), ((0, 0, 1, 0), LOSE)]),
    ("Broj golova u prvom i drugom poluvremenu", "SECOND_HALF", "I1+&II1+",
     "HALF_GOAL_COMBOS", [((1, 0, 2, 1), WIN), ((0, 0, 1, 0), LOSE)]),
]


@pytest.mark.parametrize("section,period,code,family,scores", CASES,
                         ids=[f"{c}|{p[:4]}" for _, p, c, _, _ in CASES])
def test_mozzart_section_decides_the_code(section, period, code, family, scores):
    market = resolve(section, period, code)
    assert market is not None, f"{section} {code} is UNMAPPED"
    assert market.family == family, f"{section} {code}: {market.family} != {family}"
    for score, expected in scores:
        got = market.outcome(*score)
        assert got == expected, f"{section} {code} on {score}: {got} != {expected}"


def test_the_same_bare_code_means_two_markets():
    """`1` is a home win under Konačan ishod and a goal count under Tačan broj."""
    assert resolve("Konačan ishod", "FULL_TIME", "1").family == "RESULT"
    assert resolve("Tačan broj golova na meču", "FULL_TIME", "1").family == "GOAL_RANGE_FT"
    score = (0, 0, 1, 0)
    assert resolve("Konačan ishod", "FULL_TIME", "1").outcome(*score) == WIN
    assert resolve("Tačan broj golova na meču", "FULL_TIME", "1").outcome(*score) == WIN
    # and they disagree where the home side wins by two
    score = (0, 0, 2, 0)
    assert resolve("Konačan ishod", "FULL_TIME", "1").outcome(*score) == WIN
    assert resolve("Tačan broj golova na meču", "FULL_TIME", "1").outcome(*score) == LOSE


def test_unmapped_markets_are_refused_never_guessed():
    # out of scope: corners, cards, shots, player props, "da" specials
    assert resolve("Broj kornera na meču", "FULL_TIME", "više") is None
    assert resolve("Broj golova K.Havertz", "FULL_TIME", "više") is None
    assert resolve("Penal na meču", "FULL_TIME", "da") is None
    # a code the section does not carry
    assert resolve("Konačan ishod", "FULL_TIME", "3") is None
    # an unknown section
    assert resolve("Neka Sekcija", "FULL_TIME", "1") is None


def test_unmapped_sections_groups_the_leftovers():
    rows = [
        {"section": "Konačan ishod", "period": "FULL_TIME", "code": "1"},
        {"section": "Broj kornera na meču", "period": "FULL_TIME", "code": "više"},
        {"section": "Broj kornera na meču", "period": "FULL_TIME", "code": "manje"},
    ]
    out = unmapped_sections(rows)
    assert out == {("Broj kornera na meču", "FULL_TIME"): ["više", "manje"]}


def test_every_rule_names_a_known_family_or_prefix():
    from core.market_code import FAMILY_SECTION
    from core.soccerbet_ext import PREFIX_MAP

    for rule in load_rules():
        assert (rule.family is None) != (rule.prefix is None), rule
        if rule.family:
            assert rule.family in FAMILY_SECTION, rule.family
        if rule.prefix:
            assert rule.prefix in PREFIX_MAP or rule.prefix == "GG", rule.prefix
        assert rule.period in ("FULL_TIME", "FIRST_HALF", "SECOND_HALF")