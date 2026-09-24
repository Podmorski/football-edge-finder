"""Step 1c — generate config/markets_catalogue.yaml from the parser + official labels.

The catalogue is the single source of truth for which markets exist, their
Serbian labels, English definitions, family, period and status. It must accept
NEW codes at runtime (the user reports Soccer Bet offers more combinations than
listed): any parseable code is priceable, with family ``UNLISTED`` until it has
been calibration-tested.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from core.market_code import (
    DO_NOT_BET_UNTIL_CLARIFIED,
    Market,
    direct_markets,
    parse,
)

OUT = Path("config/markets_catalogue.yaml")

# (code, family, serbian label, english definition)
CODE_ENTRIES: list[tuple[str, str, str, str]] = []


def add(codes: list[str], family: str, labels: dict[str, str], definitions: dict[str, str]) -> None:
    for code in codes:
        CODE_ENTRIES.append((code, family, labels.get(code, code), definitions.get(code, "")))


# --- RESULT / DOUBLE_CHANCE -------------------------------------------------
add(["1", "X", "2"], "RESULT",
    {"1": "1", "X": "X", "2": "2"},
    {"1": "Home wins the match", "X": "Draw", "2": "Away wins the match"})
add(["1X", "12", "X2"], "DOUBLE_CHANCE",
    {"1X": "1X", "12": "12", "X2": "X2"},
    {"1X": "Home or draw", "12": "Home or away", "X2": "Away or draw"})

# --- HALF_RESULT / HALF_DC --------------------------------------------------
add(["I1", "IX", "I2"], "HALF_RESULT",
    {"I1": "I Pol. 1", "IX": "I Pol. X", "I2": "I Pol. 2"},
    {"I1": "Home leads at half time", "IX": "Half-time draw", "I2": "Away leads at half time"})
add(["II1", "IIX", "II2"], "HALF_RESULT",
    {"II1": "II Pol. 1", "IIX": "II Pol. X", "II2": "II Pol. 2"},
    {"II1": "Home wins the second half", "IIX": "Second half drawn", "II2": "Away wins the second half"})
add(["I1X", "IX2", "I12"], "HALF_DC",
    {"I1X": "I Pol. 1X", "IX2": "I Pol. X2", "I12": "I Pol. 12"},
    {"I1X": "Home or draw at half time", "IX2": "Away or draw at half time", "I12": "Not a half-time draw"})
add(["II1X", "IIX2", "II12"], "HALF_DC",
    {"II1X": "II Pol. 1X", "IIX2": "II Pol. X2", "II12": "II Pol. 12"},
    {"II1X": "Home or draw in the second half", "IIX2": "Away or draw in the second half",
     "II12": "Second half not drawn"})

# --- HTFT (9 basic + the double-chance variants) ----------------------------
HTFT_BASIC = ["1-1", "1-X", "1-2", "X-1", "X-X", "X-2", "2-1", "2-X", "2-2"]
add(HTFT_BASIC, "HTFT", {c: c for c in HTFT_BASIC},
    {c: f"Half time {c.split('-')[0]}, full time {c.split('-')[1]}" for c in HTFT_BASIC})
HTFT_DC = [
    "1X-1X", "1X-12", "1X-X2", "12-1X", "12-12", "12-X2", "X2-1X", "X2-12", "X2-X2",
    "1X-1", "1X-X", "1X-2", "12-1", "12-X", "12-2", "X2-1", "X2-X", "X2-2",
    "1-1X", "1-12", "1-X2", "X-1X", "X-12", "X-X2", "2-1X", "2-12", "2-X2",
]
add(HTFT_DC, "HTFT_DC", {c: c for c in HTFT_DC},
    {c: f"Half time {c.split('-')[0]}, full time {c.split('-')[1]}" for c in HTFT_DC})
HTFT_NE = ["NE 1-1", "NE X-1", "NE X-X", "NE X-2", "NE 2-2"]
add(HTFT_NE, "HTFT_NE", {c: c for c in HTFT_NE},
    {c: f"Not (half time {c[3:].split('-')[0]}, full time {c[3:].split('-')[1]})" for c in HTFT_NE})

# --- GOAL_RANGE_FT ----------------------------------------------------------
FT_GOALS = ["0-1", "0-2", "0-3", "0-4", "1", "1+", "1-2", "1-3", "1-4", "1-5", "1-6",
            "2", "2+", "2-3", "2-4", "2-5", "2-6", "3", "3+", "3-4", "3-5", "3-6",
            "4", "4+", "4-5", "4-6", "5", "5+", "6+", "7+"]
FT_NE = ["NE 1", "NE 1-2", "NE 1-3", "NE 1-4", "NE 2", "NE 4-6", "NE 3-4", "NE 3-5",
         "NE 3-6", "NE 4-5", "NE 3"]
add(FT_GOALS + FT_NE, "GOAL_RANGE_FT", {c: c for c in FT_GOALS + FT_NE},
    {c: f"Full-time total goals {c}" for c in FT_GOALS + FT_NE})

# --- GOAL_RANGE_1H / 2H -----------------------------------------------------
H1 = ["I0", "I0-1", "I0-2", "I1", "NE 1", "I1+", "I1-2", "NE 2", "I2", "I2+",
      "I2-3", "I2-4", "I3", "I3+", "I4+"]
H2 = ["II0", "II0-1", "II0-2", "II1", "NE 1", "II1+", "II1-2", "II1-3", "NE 2",
      "II2", "II2+", "II2-3", "II2-4", "II3", "II3+", "II4+"]
add(H1, "GOAL_RANGE_1H", {c: c for c in H1}, {c: f"First-half total goals {c}" for c in H1})
add(H2, "GOAL_RANGE_2H", {c: c for c in H2}, {c: f"Second-half total goals {c}" for c in H2})

# --- HALF_GOAL_COMBOS -------------------------------------------------------
COMBOS = [
    "I0-1&II0-1", "I0-1&II0-2", "I0-1&II0-3", "I0-2&II0-1", "I0-2&II0-2", "I0-2&II0-3",
    "I1+&II1+", "I1+&II2+", "I1+&II3+", "I1-2&II1-2", "I1-3&II1-3", "I2+&II1+",
    "I2+&II2+", "I2+&II3+", "I1+&2+", "I1+&3+", "I1-2&3+", "I1-2&4+", "I2+&3+",
    "I2+&4+", "NE I1-3&II1-3", "I2-3&4+", "NE I1+&II2+", "NE I1+&II1+",
    "I2-3&II2-3", "I2-3&II2+", "I2-3&II1-3", "I2-3&II1-2", "I2-3&II1+",
]
add(COMBOS, "HALF_GOAL_COMBOS", {c: c for c in COMBOS},
    {c: f"Half-goal combination {c}" for c in COMBOS})

# --- RESULT_AND_GOALS / HTFT_AND_GOALS --------------------------------------
RAG = ["1 & 2+", "1 & 3+", "1 & 4+", "2 & 2+", "2 & 3+", "2 & 4+",
       "1 & 0-2", "1 & 2-3", "2 & 0-2", "2 & 2-3"]
add(RAG, "RESULT_AND_GOALS", {c: c for c in RAG}, {c: f"Result and goals: {c}" for c in RAG})
HAG = ["1-1 & 2+", "1-1 & 3+", "2-2 & 2+", "2-2 & 3+"]
add(HAG, "HTFT_AND_GOALS", {c: c for c in HAG}, {c: f"HT/FT and goals: {c}" for c in HAG})

# --- MORE_GOALS_HALF is implemented directly (see core.market_code.direct_markets) ---


def main() -> int:
    entries: list[dict] = []
    errors: list[str] = []

    for code, family, label_sr, definition_en in CODE_ENTRIES:
        try:
            market: Market = parse(code, family, label_sr, definition_en)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{family} {code!r}: {exc}")
            continue
        entries.append({
            "code": code,
            "label_sr": label_sr,
            "definition_en": market.definition_en,
            "family": family,
            "period": market.period,
            "source": "soccerbet_rules",
            "testable": market.testable,
            "do_not_bet": code in DO_NOT_BET_UNTIL_CLARIFIED,
            "note": DO_NOT_BET_UNTIL_CLARIFIED.get(code, ""),
        })

    for market in direct_markets():
        entries.append({
            "code": market.code,
            "label_sr": market.label_sr,
            "definition_en": market.definition_en,
            "family": market.family,
            "period": market.period,
            "source": "soccerbet_rules",
            "testable": market.testable,
            "do_not_bet": market.code in DO_NOT_BET_UNTIL_CLARIFIED,
            "note": market.note or DO_NOT_BET_UNTIL_CLARIFIED.get(market.code, ""),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "generated_by": "step1_catalogue.py",
        "source": "docs/soccerbet_rules_sr.txt",
        "note": (
            "Any parseable code is priceable. Codes not listed here are accepted at "
            "runtime with family UNLISTED until calibration-tested."
        ),
        "markets": entries,
    }
    OUT.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")

    print(f"wrote {OUT}")
    print(f"markets: {len(entries)}")
    fams: dict[str, int] = {}
    for e in entries:
        fams[e["family"]] = fams.get(e["family"], 0) + 1
    print("\ncounts per family:")
    for fam, n in sorted(fams.items()):
        print(f"  {fam:<22} {n}")
    print(f"\nDO_NOT_BET flagged: {sum(1 for e in entries if e['do_not_bet'])}")
    for e in entries:
        if e["do_not_bet"]:
            print(f"  {e['family']:<20} {e['code']:<12} {e['note'][:70]}")
    if errors:
        print(f"\nPARSE ERRORS ({len(errors)}):")
        for err in errors:
            print(f"  {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())