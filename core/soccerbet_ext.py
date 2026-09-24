"""Extended Soccer Bet families beyond the code grammar.

Covers the families the sample price list uses that are **not** part of the base
grammar in :mod:`core.market_code`:

  TEAM_GOALS_{HOME,AWAY}_{FT,1H,2H}, BTTS, BTTS_COMBOS, ODD_EVEN, OR_MARKETS,
  CORRECT_SCORE, CORRECT_SCORE_1H, TEAM_HALF_COMBOS_{HOME,AWAY},
  DOUBLE_CHANCE_AND_GOALS, HALF_RESULT_AND_BTTS, MINUTE_MARKETS,
  WIN_BOTH_HALVES_TO_NIL

Markets are keyed by the **raw Soccer Bet prefix and code** (``PREFIX_MAP``),
because the same printed code means different things under different prefixes:
``II0`` is "no goals in the 2nd half" under ``T2``/``SANSA`` but "away leads"
under ``H2``, and ``1-2`` is a HT/FT pair under ``HF``/``HFG``/``SANSA`` but a
1..2 goal range under ``T``/``R``/``DCG``/``C``. The family therefore cannot be
inferred from the code alone; it comes from the prefix, exactly as printed.

Every settlement returns ``win`` / ``lose`` / ``void`` / ``unconfirmed``.
Anything that cannot be settled unambiguously is ``unconfirmed`` — never
guessed. ``UNTESTABLE`` markets (first goal, minute markets) can be ingested and
priced but not settled from ``(HT, FT)`` scores alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

WIN, LOSE, VOID, UNCONFIRMED = "win", "lose", "void", "unconfirmed"

# SB prefix -> catalogue family. HF and GG resolve per code.
PREFIX_MAP: dict[str, str] = {
    "FT": "RESULT",
    "DC": "DOUBLE_CHANCE",
    "DP": "WIN_BOTH_HALVES",
    "SP": "WIN_TO_NIL",
    "DSP": "WIN_BOTH_HALVES_TO_NIL",
    "HP": "MARGIN",
    "HH": "MARGIN",
    "E1": "MARGIN",
    "E2": "MARGIN",
    "H1": "HALF_RESULT",
    "H2": "HALF_RESULT",
    "H1DC": "HALF_DC",
    "H2DC": "HALF_DC",
    "XNB": "NO_BET",
    "H1XNB": "NO_BET",
    "H2XNB": "NO_BET",
    "T": "GOAL_RANGE_FT",
    "T1": "GOAL_RANGE_1H",
    "T2": "GOAL_RANGE_2H",
    "HT": "TEAM_GOALS_HOME_FT",
    "HT1": "TEAM_GOALS_HOME_1H",
    "HT2": "TEAM_GOALS_HOME_2H",
    "AT": "TEAM_GOALS_AWAY_FT",
    "AT1": "TEAM_GOALS_AWAY_1H",
    "AT2": "TEAM_GOALS_AWAY_2H",
    "PV": "MORE_GOALS_HALF",
    "PN": "ODD_EVEN",
    "C": "HALF_GOAL_COMBOS",
    "CH": "TEAM_HALF_COMBOS_HOME",
    "CA": "TEAM_HALF_COMBOS_AWAY",
    "R": "RESULT_AND_GOALS",
    "DCG": "DOUBLE_CHANCE_AND_GOALS",
    "HFG": "HTFT_AND_GOALS",
    "GGC": "BTTS_COMBOS",
    "HRG": "HALF_RESULT_AND_BTTS",
    "PDG": "FIRST_GOAL",
    "PDG1": "FIRST_GOAL",
    "PDG2": "FIRST_GOAL",
    "PGC": "FIRST_GOAL",
    "SANSA": "OR_MARKETS",
    "CS": "CORRECT_SCORE",
    "CS1": "CORRECT_SCORE_1H",
    "M15": "MINUTE_MARKETS",
    "M30": "MINUTE_MARKETS",
}

TEAM_GOALS_FAMILIES = {
    "TEAM_GOALS_HOME_FT", "TEAM_GOALS_AWAY_FT",
    "TEAM_GOALS_HOME_1H", "TEAM_GOALS_AWAY_1H",
    "TEAM_GOALS_HOME_2H", "TEAM_GOALS_AWAY_2H",
}

HALF_COMBO_FAMILIES = {"HALF_GOAL_COMBOS", "TEAM_HALF_COMBOS_HOME", "TEAM_HALF_COMBOS_AWAY"}

COMPOSITE_FAMILIES = {
    "RESULT_AND_GOALS", "DOUBLE_CHANCE_AND_GOALS", "HTFT_AND_GOALS",
    "BTTS_COMBOS", "HALF_RESULT_AND_BTTS",
}

# Families whose markets are untestable from (HT, FT) scores alone.
UNTESTABLE_FAMILIES = {"FIRST_GOAL", "MINUTE_MARKETS", "TO_QUALIFY"}

DC_TOKENS = {"1X", "12", "X2"}
RESULT_TOKENS = {"1", "X", "2"}
# first characters that may follow an explicit 'I'/'II' period marker
_BODY_STARTS = "XNGHDPAI"


def _scores(period: str, hth: int, hta: int, fth: int, fta: int) -> tuple[int, int]:
    if period == "1H":
        return hth, hta
    if period == "2H":
        return fth - hth, fta - hta
    return fth, fta


def _result(tok: str, h: int, a: int) -> bool:
    return {
        "1": h > a, "X": h == a, "2": h < a,
        "1X": h >= a, "12": h != a, "X2": h <= a,
    }[tok]


def _spec(text: str) -> tuple[int, int] | None:
    """'a+' -> (a, inf); 'a-b' -> (a,b); 'a' -> (a,a); else None."""
    t = text.strip()
    try:
        if t.endswith("+"):
            body = t[:-1]
            if not body.isdigit():
                return None
            return (int(body), 10 ** 6)
        if "-" in t:
            lo, hi = t.split("-", 1)
            if lo.isdigit() and hi.isdigit():
                return (int(lo), int(hi))
            return None
        if t.isdigit():
            return (int(t), int(t))
    except (TypeError, ValueError):
        return None
    return None


def _in_range(g: int, spec: tuple[int, int]) -> bool:
    return spec[0] <= g <= spec[1]


def _margin(side: str, hth: int, hta: int, fth: int, fta: int) -> int:
    return (fth - fta) if side == "1" else (fta - fth)


def _split_period(raw: str, period: str) -> tuple[str, str]:
    """Strip a leading explicit period marker; 'II' must be tested before 'I'."""
    for marker, per in (("II", "2H"), ("I", "1H")):
        if raw.startswith(marker):
            rest = raw[len(marker):]
            if rest and (rest[0].isdigit() or rest[0].upper() in _BODY_STARTS):
                return per, rest
    return period, raw


# --------------------------------------------------------------------------- #
# component parser
# --------------------------------------------------------------------------- #
def parse_component(
    text: str,
    period: str = "FT",
    subject: str = "total",
    mode: str = "result",
    allow_htft: bool = True,
) -> Callable[[int, int, int, int], bool] | None:
    """Parse one '&'-component (or a whole 'v'-part of an OR market).

    ``subject`` is 'total', 'home' or 'away'. ``mode`` is 'result' for families
    where a bare ``1``/``2``/``X`` means the match result (RESULT, DOUBLE_CHANCE,
    HTFT, composites), or 'goals' for goal families where a bare digit is a goal
    count (GOAL_RANGE_*, TEAM_GOALS_*). Getting this wrong silently settles
    'exactly 1 goal' as 'home wins'.

    ``allow_htft`` controls whether ``a-b`` may be read as a HT/FT pair. It is
    True only where the book clearly means that (``HF``, ``HFG``, ``SANSA``) and
    False in the goal families, where ``I1-2``/``1-2`` is a 1..2 goal range.
    """
    raw = text.strip()
    negate = False
    if raw.upper().startswith("NE "):
        negate, raw = True, raw[3:].strip()
    elif raw.upper().startswith("NE"):
        negate, raw = True, raw[2:].strip()

    period, raw = _split_period(raw, period)
    upper = raw.upper()

    # which-half comparison for the subject (HT/AT/PV/C contexts)
    for marker, cmp_fn in (("I>II", lambda a, b: a > b), ("I=II", lambda a, b: a == b),
                           ("I<II", lambda a, b: a < b)):
        if upper == marker:
            fn = cmp_fn
            subj = subject

            def pred(hth, hta, fth, fta, s=subj, f=fn):
                if s == "home":
                    return f(hth, fth - hth)
                if s == "away":
                    return f(hta, fta - hta)
                return f(hth + hta, (fth - hth) + (fta - hta))

            return (lambda *a, p=pred: not p(*a)) if negate else pred

    # both teams to score, optionally in a period ('IGG' prefix or 'GGI'
    # suffix) or with 2+ each. 'II' must be tested before 'I'.
    if upper.startswith("GG") or upper.startswith("NG"):
        want = upper.startswith("GG")
        per, rest = period, raw[2:]
        for marker, name in (("II", "2H"), ("I", "1H")):
            if rest.startswith(marker):
                per, rest = name, rest[len(marker):]
                break
        two_plus = False
        rest = rest.strip()
        if rest in ("2", "2+"):
            two_plus = True
        elif rest:
            # e.g. 'GG3+' — a conjunction (both score AND 3+ goals) that the
            # printed code does not settle unambiguously; refuse rather than guess
            return None

        def pred(hth, hta, fth, fta, p=per, w=want, t=two_plus):
            h, a = _scores(p, hth, hta, fth, fta)
            hit = (h >= (2 if t else 1)) and (a >= (2 if t else 1))
            return hit if w else not hit

        return (lambda *a, p=pred: not p(*a)) if negate else pred

    # margin conditions
    if upper in ("HP1", "HP2"):
        side = upper[-1]

        def pred(hth, hta, fth, fta, s=side):
            return _margin(s, hth, hta, fth, fta) >= 2

        return pred
    if upper in ("HH1", "HH2", "D3", "G3"):
        side = "1" if upper in ("HH1", "D3") else "2"

        def pred(hth, hta, fth, fta, s=side):
            return _margin(s, hth, hta, fth, fta) >= 3

        return pred

    # win both halves as a component (used inside RESULT_AND_GOALS)
    if upper in ("DP1", "DP2"):
        side = upper[-1]

        def pred(hth, hta, fth, fta, s=side):
            if s == "1":
                return hth > hta and (fth - hth) > (fta - hta)
            return hta > hth and (fta - hta) > (fth - hth)

        return pred

    # D/G with an embedded period, e.g. 'DI0' (home 1H goals 0), 'GII2-3'
    if upper and upper[0] in ("D", "G") and len(upper) > 1:
        subject_letter, rest = upper[0], raw[1:]
        per2, rest = _split_period(rest, period)
        spec2 = _spec(rest)
        if spec2 is not None:
            subj2 = "home" if subject_letter == "D" else "away"

            def pred(hth, hta, fth, fta, s=spec2, p=per2, sub=subj2):
                h, a = _scores(p, hth, hta, fth, fta)
                value = h if sub == "home" else a
                return _in_range(value, s)

            return (lambda *a, p=pred: not p(*a)) if negate else pred

    # D<spec> / G<spec> -> that team's goals in the period
    if upper.startswith("D") and _spec(raw[1:]) is not None:
        spec = _spec(raw[1:])

        def pred(hth, hta, fth, fta, s=spec, p=period):
            return _in_range(_scores(p, hth, hta, fth, fta)[0], s)

        return (lambda *a, p=pred: not p(*a)) if negate else pred
    if upper.startswith("G") and _spec(raw[1:]) is not None:
        spec = _spec(raw[1:])

        def pred(hth, hta, fth, fta, s=spec, p=period):
            return _in_range(_scores(p, hth, hta, fth, fta)[1], s)

        return (lambda *a, p=pred: not p(*a)) if negate else pred

    # HT/FT pair (period-independent) — only where the family means a pair
    if allow_htft and mode != "goals" and "-" in raw:
        left, right = raw.split("-", 1)
        if left in RESULT_TOKENS | DC_TOKENS and right in RESULT_TOKENS | DC_TOKENS:
            def pred(hth, hta, fth, fta, l=left, r=right):
                return _result(l, hth, hta) and _result(r, fth, fta)

            return (lambda *a, p=pred: not p(*a)) if negate else pred

    # correct score h:a
    if ":" in raw:
        parts = raw.split(":")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            hh, aa = int(parts[0]), int(parts[1])

            def pred(hth, hta, fth, fta, h=hh, a=aa, p=period):
                return _scores(p, hth, hta, fth, fta) == (h, a)

            return pred

    # result token in the period (only in 'result' mode)
    if mode != "goals" and raw in RESULT_TOKENS | DC_TOKENS:

        def pred(hth, hta, fth, fta, t=raw, p=period):
            return _result(t, *_scores(p, hth, hta, fth, fta))

        return (lambda *a, p=pred: not p(*a)) if negate else pred

    # goal range applied to the subject
    spec = _spec(raw)
    if spec is not None:

        def pred(hth, hta, fth, fta, s=spec, p=period, subj=subject):
            h, a = _scores(p, hth, hta, fth, fta)
            value = (h + a) if subj == "total" else (h if subj == "home" else a)
            return _in_range(value, s)

        return (lambda *a, p=pred: not p(*a)) if negate else pred

    return None


# --------------------------------------------------------------------------- #
# market wrapper
# --------------------------------------------------------------------------- #
@dataclass
class ExtMarket:
    prefix: str
    code: str
    family: str
    settle: Callable[[int, int, int, int], str]
    status: str = "OK"
    note: str = ""

    def outcome(self, hth: int, hta: int, fth: int, fta: int) -> str:
        return self.settle(hth, hta, fth, fta)


def _ok(prefix: str, code: str, family: str, pred) -> ExtMarket:
    return ExtMarket(prefix, code, family,
                     lambda hth, hta, fth, fta, p=pred: WIN if p(hth, hta, fth, fta) else LOSE)


def _bad(prefix: str, code: str, family: str, reason: str) -> ExtMarket:
    return ExtMarket(prefix, code, family, lambda *a: UNCONFIRMED, "UNCONFIRMED", reason)


def _composite(prefix: str, code: str, family: str, joiner: str, allow_htft: bool,
               mode: str = "result") -> ExtMarket:
    """All/any over '&'- or 'v'-joined components, with an optional leading 'NE '."""
    negate_all = code.strip().upper().startswith("NE ")
    body = code.strip()[3:] if negate_all else code
    preds = []
    for part in body.split(joiner):
        pred = parse_component(part, "FT", "total", mode=mode, allow_htft=allow_htft)
        if pred is None:
            return _bad(prefix, code, family, f"could not parse {part!r}")
        preds.append(pred)

    every = joiner == "&"

    def settle(hth, hta, fth, fta, ps=preds, neg=negate_all, all_=every):
        hits = [p(hth, hta, fth, fta) for p in ps]
        hit = all(hits) if all_ else any(hits)
        return WIN if (hit != neg) else LOSE

    return ExtMarket(prefix, code, family, settle)


def resolve(prefix: str, code: str) -> ExtMarket:
    """Map an SB prefix+code to a family and a settlement function."""
    family = PREFIX_MAP.get(prefix)

    # a first-goal component makes the whole market untestable from HT/FT data
    if "PG1" in code.upper() or "PG2" in code.upper():
        return ExtMarket(prefix, code, "FIRST_GOAL", lambda *a: VOID, "UNTESTABLE",
                         "contains a first-goal component (not settleable from HT/FT)")

    if prefix == "HF":
        if code.upper().startswith("NE"):
            family = "HTFT_NE"
        elif any(part in DC_TOKENS for part in code.split("-")):
            family = "HTFT_DC"
        else:
            family = "HTFT"
    elif prefix == "GG":
        family = "BTTS_COMBOS" if "&" in code else "BTTS"

    if family is None:
        return ExtMarket(prefix, code, "UNLISTED", lambda *a: UNCONFIRMED,
                         "UNCONFIRMED", f"unknown prefix {prefix!r}")

    if family in UNTESTABLE_FAMILIES:
        return ExtMarket(prefix, code, family, lambda *a: VOID, "UNTESTABLE",
                         "not settleable from HT/FT scores")

    # --- bespoke settlements ------------------------------------------------
    if family == "ODD_EVEN":
        want_even = code.strip().lower() in ("par", "even")

        def settle(hth, hta, fth, fta, w=want_even):
            odd = (fth + fta) % 2 == 1
            return WIN if (odd != w) else LOSE

        return ExtMarket(prefix, code, family, settle)

    if family == "BTTS":
        # 2GG / 2NG (both teams score 2+, and its complement) are FT-only and
        # sit outside the GG/NG/IGG/IIGG grammar, so they settle here.
        if code.strip().upper() in ("2GG", "2NG"):
            want = code.strip().upper() == "2GG"

            def settle(hth, hta, fth, fta, w=want):
                hit = fth >= 2 and fta >= 2
                return WIN if hit == w else LOSE

            return ExtMarket(prefix, code, family, settle)
        pred = parse_component(code, "FT", "total")
        if pred is None:
            return _bad(prefix, code, family, f"could not parse BTTS code {code!r}")
        return _ok(prefix, code, family, pred)

    if family in TEAM_GOALS_FAMILIES:
        per = "1H" if family.endswith("_1H") else ("2H" if family.endswith("_2H") else "FT")
        subj = "home" if "HOME" in family else "away"
        pred = parse_component(code, per, subj, mode="goals")
        if pred is None:
            return _bad(prefix, code, family, "could not parse team-goals code")
        return _ok(prefix, code, family, pred)

    if family in HALF_COMBO_FAMILIES:
        subj = "total" if family == "HALF_GOAL_COMBOS" else ("home" if "HOME" in family else "away")
        negate_all = code.strip().upper().startswith("NE ")
        body = code.strip()[3:] if negate_all else code
        preds = []
        for part in body.split("&"):
            pred = parse_component(part, "FT", subj, allow_htft=False)
            if pred is None:
                return _bad(prefix, code, family, f"could not parse {part!r}")
            preds.append(pred)

        def settle(hth, hta, fth, fta, ps=preds, neg=negate_all):
            hit = all(p(hth, hta, fth, fta) for p in ps)
            return WIN if (hit != neg) else LOSE

        return ExtMarket(prefix, code, family, settle)

    if family in COMPOSITE_FAMILIES:
        # 'a-b' is a HT/FT pair only in HTFT_AND_GOALS (e.g. '1-1 & 2+'); under
        # RESULT/DC_AND_GOALS it is a goal range ('1X & 1-2' = DC 1X and 1..2 goals).
        return _composite(prefix, code, family, "&", allow_htft=family == "HTFT_AND_GOALS")

    if family == "OR_MARKETS":
        return _composite(prefix, code, family, "v", allow_htft=True)

    if family in ("CORRECT_SCORE", "CORRECT_SCORE_1H"):
        per = "1H" if family == "CORRECT_SCORE_1H" else "FT"
        if ":" not in code:
            return _bad(prefix, code, family, "not a correct-score code")
        hh, aa = (int(x) for x in code.split(":"))

        def settle(hth, hta, fth, fta, h=hh, a=aa, p=per):
            return WIN if _scores(p, hth, hta, fth, fta) == (h, a) else LOSE

        return ExtMarket(prefix, code, family, settle)

    if family == "WIN_BOTH_HALVES_TO_NIL":
        side = "1" if code.strip() == "1" else "2"

        def settle(hth, hta, fth, fta, s=side):
            if s == "1":
                wins = hth > hta and (fth - hth) > (fta - hta)
                conceded = hta + (fta - hta)
            else:
                wins = hta > hth and (fta - hta) > (fth - hth)
                conceded = hth + (fth - hth)
            return WIN if (wins and conceded == 0) else LOSE

        return ExtMarket(prefix, code, family, settle)

    if family == "WIN_BOTH_HALVES":
        side = "1" if code.strip() == "1" else "2"

        def settle(hth, hta, fth, fta, s=side):
            if s == "1":
                return WIN if (hth > hta and (fth - hth) > (fta - hta)) else LOSE
            return WIN if (hta > hth and (fta - hta) > (fth - hth)) else LOSE

        return ExtMarket(prefix, code, family, settle)

    if family == "WIN_TO_NIL":
        side = "1" if code.strip() == "1" else "2"

        def settle(hth, hta, fth, fta, s=side):
            if s == "1":
                return WIN if (fth > fta and fta == 0) else LOSE
            return WIN if (fta > fth and fth == 0) else LOSE

        return ExtMarket(prefix, code, family, settle)

    if family == "MARGIN":
        # HP:1/2 -> win by >=2; HH:D3/G3 -> win by >=3;
        # E1:1/2 -> exactly 1; E2:1/2 -> exactly 2
        raw = code.strip()
        if prefix == "HP":
            lo, hi = 2, 10 ** 6
        elif prefix == "HH":
            lo, hi = 3, 10 ** 6
        elif prefix == "E1":
            lo, hi = 1, 1
        elif prefix == "E2":
            lo, hi = 2, 2
        else:
            return _bad(prefix, code, family, f"unknown margin prefix {prefix!r}")
        if prefix == "HH":
            side = "1" if raw.upper().endswith("D3") else "2"
        else:
            side = "1" if raw.endswith("1") else "2"

        def settle(hth, hta, fth, fta, s=side, l=lo, h=hi):
            return WIN if l <= _margin(s, hth, hta, fth, fta) <= h else LOSE

        return ExtMarket(prefix, code, family, settle)

    if family == "NO_BET":
        per = {"XNB": "FT", "H1XNB": "1H", "H2XNB": "2H"}[prefix]
        side = "1" if code.strip().endswith("1") else "2"

        def settle(hth, hta, fth, fta, s=side, p=per):
            h, a = _scores(p, hth, hta, fth, fta)
            if h == a:
                return VOID
            return WIN if ((h > a) if s == "1" else (h < a)) else LOSE

        return ExtMarket(prefix, code, family, settle)

    # --- generic families parsed through parse_component -------------------
    GENERIC = {
        "RESULT": "FT", "DOUBLE_CHANCE": "FT",
        "HALF_RESULT": "1H" if prefix == "H1" else "2H",
        "HALF_DC": "1H" if prefix == "H1DC" else "2H",
        "GOAL_RANGE_FT": "FT", "GOAL_RANGE_1H": "1H", "GOAL_RANGE_2H": "2H",
        "MORE_GOALS_HALF": "FT",
    }
    if family in GENERIC:
        pred = parse_component(code, GENERIC[family], "total",
                               mode="goals" if family.startswith("GOAL_RANGE") else "result")
        if pred is None:
            return _bad(prefix, code, family, f"could not parse {code!r}")
        return _ok(prefix, code, family, pred)

    if family in ("HTFT", "HTFT_NE", "HTFT_DC"):
        pred = parse_component(code, "FT", "total")
        if pred is None:
            return _bad(prefix, code, family, f"could not parse HTFT {code!r}")
        return _ok(prefix, code, family, pred)

    return _bad(prefix, code, family, f"no settlement rule for {prefix}:{code}")