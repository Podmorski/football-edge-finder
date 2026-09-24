"""Soccer Bet market-code parser and settlement functions.

Every market settles on ``(hth, hta, fth, fta)`` — half-time and full-time goals
for home and away — and returns ``win`` / ``lose`` / ``void`` (void = stake back,
odds 1.00).

Grammar
-------
::

    code := ["NE "] leg ("&" leg)*
    leg  := [period] body
    period := "I" (1st half) | "II" (2nd half) | none (full time)
    body := result | htft | goals
      result : 1 | X | 2 | 1X | 12 | X2
      htft   : R-R, R in {1,X,2,1X,12,X2}   (half-time, then full time)
      goals  : "a+" (>= a) | "a-b" (a..b inclusive) | "a" (exactly a)

``NE`` is the complement of the WHOLE code (the conjunction of all legs). For a
single-leg code that is the same as complementing that leg, which is exactly what
``NE 1-1`` means in the Poluvreme/Kraj family.

Disambiguation
--------------
``a-b`` is a **goal range** in goal families and a **HT/FT pair** in the
Poluvreme/Kraj family. The family must be supplied for such codes; if a code is
ambiguous and no family is given, :func:`parse` **raises** rather than guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

WIN, LOSE, VOID = "win", "lose", "void"

Settle = Callable[[int, int, int, int], str]

# --------------------------------------------------------------------------- #
# atoms
# --------------------------------------------------------------------------- #
RESULT_TOKENS = ("1X", "12", "X2", "1", "X", "2")  # longest first

RESULT_SETS: dict[str, Callable[[int, int], bool]] = {
    "1": lambda h, a: h > a,
    "X": lambda h, a: h == a,
    "2": lambda h, a: h < a,
    "1X": lambda h, a: h >= a,
    "12": lambda h, a: h != a,
    "X2": lambda h, a: h <= a,
}

PERIODS = {"I": "1H", "II": "2H", "": "FT"}

# Families whose codes carry no explicit period prefix; the family supplies it.
FAMILY_PERIOD = {
    "GOAL_RANGE_1H": "1H",
    "GOAL_RANGE_2H": "2H",
    "GOAL_RANGE_FT": "FT",
}


def period_scores(period: str, hth: int, hta: int, fth: int, fta: int) -> tuple[int, int]:
    if period == "1H":
        return hth, hta
    if period == "2H":
        return fth - hth, fta - hta
    return fth, fta


def goals_predicate(text: str) -> Callable[[int], bool]:
    """``a+`` -> >= a; ``a-b`` -> a..b inclusive; ``a`` -> exactly a."""
    text = text.strip()
    if text.endswith("+"):
        low = int(text[:-1])
        return lambda g: g >= low
    if "-" in text:
        low, high = (int(x) for x in text.split("-", 1))
        return lambda g: low <= g <= high
    exact = int(text)
    return lambda g: g == exact


def _is_result_token(text: str) -> bool:
    return text in RESULT_SETS


def _is_goal_token(text: str) -> bool:
    body = text.strip()
    if body.endswith("+"):
        body = body[:-1]
    if "-" in body:
        left, right = body.split("-", 1)
        return left.isdigit() and right.isdigit()
    return body.isdigit()


def _is_htft_token(text: str) -> bool:
    if "-" not in text:
        return False
    left, right = text.split("-", 1)
    return _is_result_token(left) and _is_result_token(right)


def is_ambiguous(text: str) -> bool:
    """True when ``a-b`` could be a goal range or a HT/FT pair."""
    return _is_goal_token(text) and _is_htft_token(text)


# --------------------------------------------------------------------------- #
# legs
# --------------------------------------------------------------------------- #
def parse_leg(leg: str, family: str | None, default_period: str = "FT") -> tuple[str, Settle, str]:
    """Return (period, settle, english) for one leg."""
    text = leg.strip()
    period = default_period
    if text.startswith("II"):
        period, text = "2H", text[2:].strip()
    elif text.startswith("I"):
        period, text = "1H", text[1:].strip()

    # HT/FT pair (period-independent)
    if _is_htft_token(text):
        if _is_goal_token(text) and family is None:
            raise ValueError(
                f"ambiguous leg {leg!r}: could be a goal range or a HT/FT pair; "
                "pass family= to disambiguate"
            )
        if family == "HTFT" or family in HTFT_FAMILIES or not _is_goal_token(text):
            ht, ft = text.split("-", 1)
            ht_pred, ft_pred = RESULT_SETS[ht], RESULT_SETS[ft]
            settle: Settle = (
                lambda hth, hta, fth, fta, hp=ht_pred, fp=ft_pred: (
                    WIN if hp(hth, hta) and fp(fth, fta) else LOSE
                )
            )
            return period, settle, f"HT {ht} and FT {ft}"

    if _is_result_token(text):
        pred = RESULT_SETS[text]
        settle = (
            lambda hth, hta, fth, fta, p=pred, per=period: (
                WIN if p(*period_scores(per, hth, hta, fth, fta)) else LOSE
            )
        )
        return period, settle, f"{period} result {text}"

    if _is_goal_token(text):
        pred = goals_predicate(text)
        settle = (
            lambda hth, hta, fth, fta, p=pred, per=period: (
                WIN
                if p(sum(period_scores(per, hth, hta, fth, fta)))
                else LOSE
            )
        )
        return period, settle, f"{period} total goals {text}"

    raise ValueError(f"cannot parse leg {leg!r}")


HTFT_FAMILIES = {"HTFT", "HTFT_NE", "HTFT_DC", "HTFT_AND_GOALS"}


# --------------------------------------------------------------------------- #
# market
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Market:
    code: str
    family: str
    period: str
    label_sr: str
    definition_en: str
    settle: Settle
    testable: bool = True
    do_not_bet: bool = False
    note: str = ""

    def outcome(self, hth: int, hta: int, fth: int, fta: int) -> str:
        return self.settle(hth, hta, fth, fta)


def parse(code: str, family: str | None = None, label_sr: str = "", definition_en: str = "") -> Market:
    """Parse a Soccer Bet code into a :class:`Market`."""
    raw = code.strip()
    negate = False
    if raw.upper().startswith("NE "):
        negate, raw = True, raw[3:].strip()
    elif raw.upper() == "NE":
        raise ValueError("'NE' with no body")

    legs = [leg.strip() for leg in raw.split("&")]
    if not legs or any(not leg for leg in legs):
        raise ValueError(f"malformed code {code!r}")

    parsed = [parse_leg(leg, family, FAMILY_PERIOD.get(family or "", "FT")) for leg in legs]
    periods = {p for p, _, _ in parsed}
    period = periods.pop() if len(periods) == 1 else "MIXED"
    english = " and ".join(e for _, _, e in parsed)

    def settle(hth: int, hta: int, fth: int, fta: int) -> str:
        hit = all(fn(hth, hta, fth, fta) == WIN for _, fn, _ in parsed)
        if negate:
            return LOSE if hit else WIN
        return WIN if hit else LOSE

    if negate:
        english = f"NOT ({english})"

    return Market(
        code=code,
        family=family or "UNLISTED",
        period=period,
        label_sr=label_sr,
        definition_en=definition_en or english,
        settle=settle,
    )


# --------------------------------------------------------------------------- #
# families that are not code-parsed
# --------------------------------------------------------------------------- #
def _direct(code, family, period, label_sr, definition_en, fn, **kw) -> Market:
    return Market(code, family, period, label_sr, definition_en, fn, **kw)


def direct_markets() -> list[Market]:
    """Families implemented directly rather than through the code grammar."""
    out: list[Market] = []

    # Dupla Pobeda — win both halves
    for side, name in ((1, "home"), (2, "away")):
        out.append(_direct(
            f"DP {side}", "WIN_BOTH_HALVES", "MIXED", f"Dupla Pobeda {side}",
            f"{name} wins both halves",
            (lambda hth, hta, fth, fta, s=side: WIN if (
                (hth > hta and fth - hth > fta - hta) if s == 1
                else (hta > hth and fta - hta > fth - hth)
            ) else LOSE),
        ))
        out.append(_direct(
            f"DP {side}&4+", "WIN_BOTH_HALVES", "MIXED", f"Dupla Pobeda {side}&4+",
            f"{name} wins both halves and total goals >= 4",
            (lambda hth, hta, fth, fta, s=side: WIN if (
                ((hth > hta and fth - hth > fta - hta) if s == 1
                 else (hta > hth and fta - hta > fth - hth)) and fth + fta >= 4
            ) else LOSE),
        ))

    # Dupla Super Pobeda — win both halves and opponent scores 0
    for side, name, opp in ((1, "home", "away"), (2, "away", "home")):
        out.append(_direct(
            f"DSP {side}", "WIN_BOTH_HALVES", "MIXED", f"Dupla Super Pobeda {side}",
            f"{name} wins both halves and {opp} scores 0",
            (lambda hth, hta, fth, fta, s=side: WIN if (
                ((hth > hta and fth - hth > fta - hta) if s == 1
                 else (hta > hth and fta - hta > fth - hth))
                and (hta + (fta - hta) == 0 if s == 1 else hth + (fth - hth) == 0)
            ) else LOSE),
        ))

    # Super Pobeda — win to nil
    for side, name in ((1, "home"), (2, "away")):
        out.append(_direct(
            f"SP {side}", "WIN_TO_NIL", "FT", f"Super Pobeda {side}",
            f"{name} wins and opponent scores 0",
            (lambda hth, hta, fth, fta, s=side: WIN if (
                (fth > fta and fta == 0) if s == 1 else (fta > fth and fth == 0)
            ) else LOSE),
        ))

    # Margin families
    for side, name in ((1, "home"), (2, "away")):
        out.append(_direct(f"HP {side}", "MARGIN", "FT", f"Hendikep Pobeda {side}",
                           f"{name} wins by >= 2",
                           (lambda hth, hta, fth, fta, s=side: WIN if (
                               (fth - fta >= 2) if s == 1 else (fta - fth >= 2)
                           ) else LOSE)))
        out.append(_direct(f"HH {side} 3+", "MARGIN", "FT", f"HH {side} 3+",
                           f"{name} wins by >= 3",
                           (lambda hth, hta, fth, fta, s=side: WIN if (
                               (fth - fta >= 3) if s == 1 else (fta - fth >= 3)
                           ) else LOSE)))
        out.append(_direct(f"W1 {side}", "MARGIN", "FT", f"Pobeda tacno 1 razlike {side}",
                           f"{name} wins by exactly 1",
                           (lambda hth, hta, fth, fta, s=side: WIN if (
                               (fth - fta == 1) if s == 1 else (fta - fth == 1)
                           ) else LOSE)))
        out.append(_direct(f"W2 {side}", "MARGIN", "FT", f"Pobeda tacno 2 razlike {side}",
                           f"{name} wins by exactly 2",
                           (lambda hth, hta, fth, fta, s=side: WIN if (
                               (fth - fta == 2) if s == 1 else (fta - fth == 2)
                           ) else LOSE)))

    # X No Bet — draw voids
    for period, pname in (("FT", "FT"), ("1H", "1. Pol."), ("2H", "2. Pol.")):
        for side, name in ((1, "home"), (2, "away")):
            def settle(hth, hta, fth, fta, s=side, per=period):
                h, a = period_scores(per, hth, hta, fth, fta)
                if h == a:
                    return VOID
                return WIN if ((h > a) if s == 1 else (h < a)) else LOSE

            out.append(_direct(f"XNB {pname} {side}", "NO_BET", period,
                               f"X No Bet {pname} {side}",
                               f"{name} wins, draw voids ({pname})", settle))

    # Pada Vise Golova — which half has more goals
    out.append(_direct("I>II", "MORE_GOALS_HALF", "MIXED", "I>II",
                       "1H goals > 2H goals",
                       lambda hth, hta, fth, fta: WIN if (hth + hta) > ((fth - hth) + (fta - hta)) else LOSE))
    out.append(_direct("I=II", "MORE_GOALS_HALF", "MIXED", "I = II",
                       "1H goals == 2H goals",
                       lambda hth, hta, fth, fta: WIN if (hth + hta) == ((fth - hth) + (fta - hta)) else LOSE))
    out.append(_direct("I<II", "MORE_GOALS_HALF", "MIXED", "I<II",
                       "1H goals < 2H goals",
                       lambda hth, hta, fth, fta: WIN if (hth + hta) < ((fth - hth) + (fta - hta)) else LOSE))

    # First goal — NOT settleable from HT/FT data
    for period, pname in (("FT", "FT"), ("1H", "1. Pol."), ("2H", "2. Pol.")):
        for side, name in ((1, "home"), (2, "away")):
            out.append(_direct(f"FDG {pname} {side}", "FIRST_GOAL", period,
                               f"Prvi Daje Gol {pname} {side}",
                               f"{name} scores the first goal ({pname})",
                               lambda hth, hta, fth, fta: VOID,
                               testable=False,
                               note="not settleable from HT/FT data"))

    # Prolazi Dalje — out of scope
    for side, name in ((1, "home"), (2, "away")):
        out.append(_direct(f"PD {side}", "TO_QUALIFY", "FT", f"Prolazi Dalje {side}",
                           f"{name} progresses to the next round",
                           lambda hth, hta, fth, fta: VOID,
                           testable=False, note="out of scope (needs tie context)"))

    return out


# --------------------------------------------------------------------------- #
# DO_NOT_BET flags from rules-text inconsistencies
# --------------------------------------------------------------------------- #
DO_NOT_BET_UNTIL_CLARIFIED: dict[str, str] = {
    "3-4": "rules text says 'najmanje 3' (at least 3) but the code is a range; "
           "implemented as 3 or 4",
    "XNB 1. Pol. 1": "rules text defines 1 = away wins and 2 = home wins, the opposite "
                     "of every other market; implemented as 1 = home, 2 = away",
    "XNB 1. Pol. 2": "same 1/2 inversion as XNB 1. Pol. 1; implemented as 1 = home, 2 = away",
    "I<II": "definition text is scrambled in the source; implemented as 1H goals < 2H goals",
}

OTHER_INCONSISTENCIES = [
    "Ukupno Golova '0-1' is described as 'najviše 1' (at most 1), consistent with a "
    "0..1 range, but '3-4' is described as 'najmanje 3' (at least 3), which is NOT a "
    "range. The two cannot both be ranges; we implement ranges throughout and flag 3-4.",
    "Poluvreme/Kraj 'NE' entries are listed only for 1-1, X-1, X-X, X-2 and 2-2, so the "
    "NE set is incomplete relative to the 9 HTFT outcomes.",
    "Dupla Pobeda codes '1' and '2' collide textually with Konačni Ishod '1' and '2'; "
    "the family must always be supplied.",
    "Hendikep Pobeda appears three times with different meanings (HP >= 2, HH >= 3, "
    "exactly 1, exactly 2); the family label alone is not sufficient to identify a market.",
]
