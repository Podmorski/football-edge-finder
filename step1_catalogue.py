"""Step 1c — generate config/markets_catalogue.yaml from the parser + official labels.

The catalogue is the single source of truth for which markets exist, their
Serbian labels, English definitions, family, period and status. It must accept
NEW codes at runtime (the user reports Soccer Bet offers more combinations than
listed): any parseable code is priceable, with family ``UNLISTED`` until it has
been calibration-tested.

Two sections:

* ``markets`` — the **base** catalogue, generated from the rules text
  (``docs/soccerbet_rules_sr.txt``) and keyed by bare code.
* ``ext_markets`` — the families settled by :mod:`core.soccerbet_ext`, keyed by
  the printed ``PREFIX`` because the same bare code means different things under
  different prefixes. The base section is never modified by this section: a code
  whose settlement matches a base market exactly on every scoreline is omitted,
  so the two sections together list each distinct market once.
"""

from __future__ import annotations

import csv
import itertools
import sys
from pathlib import Path

import yaml

from core.market_code import (
    DO_NOT_BET_UNTIL_CLARIFIED,
    Market,
    direct_markets,
    parse,
)
from core.soccerbet_ext import PREFIX_SECTION, SECTION_UNCONFIRMED, resolve

OUT = Path("config/markets_catalogue.yaml")
# Codes observed in the one Soccer Bet capture we hold. ``data/`` is gitignored,
# so on a clean checkout the existing ext_markets section is carried over
# unchanged instead of being rebuilt.
EXT_SAMPLE = Path("data/soccerbet/2026-09-24_hoffenheim_hamburg.csv")
EXT_NOTE = (
    "Extended Soccer Bet families, settled by core.soccerbet_ext. Keyed by the "
    "printed PREFIX: the same code means different things under different "
    "prefixes (II0 is 'no goals in the 2nd half' under T2 but 'away leads' under "
    "H2), so the family cannot be inferred from the code alone. A code here whose "
    "settlement matches a market in the base `markets` section exactly on all "
    "0..3^4 scorelines is omitted, so the two sections together list every "
    "distinct market once. UNTESTABLE families cannot be settled from (HT, FT) "
    "scores and are ingest-only."
)
EXT_UNCONFIRMED_REASON = "the printed code has no unambiguous reading; refused rather than guessed"

# (code, family, section, serbian label, english definition)
CODE_ENTRIES: list[tuple[str, str, str, str, str]] = []


def add(codes: list[str], family: str, section: str, labels: dict[str, str],
        definitions: dict[str, str]) -> None:
    for code in codes:
        CODE_ENTRIES.append((code, family, section, labels.get(code, code),
                             definitions.get(code, "")))


# --- RESULT / DOUBLE_CHANCE -------------------------------------------------
add(["1", "X", "2"], "RESULT", "Konačni Ishod",
    {"1": "1", "X": "X", "2": "2"},
    {"1": "Home wins the match", "X": "Draw", "2": "Away wins the match"})
add(["1X", "12", "X2"], "DOUBLE_CHANCE", "Dupla Šansa",
    {"1X": "1X", "12": "12", "X2": "X2"},
    {"1X": "Home or draw", "12": "Home or away", "X2": "Away or draw"})

# --- HALF_RESULT / HALF_DC --------------------------------------------------
add(["I1", "IX", "I2"], "HALF_RESULT", "I Poluvreme",
    {"I1": "I Pol. 1", "IX": "I Pol. X", "I2": "I Pol. 2"},
    {"I1": "Home leads at half time", "IX": "Half-time draw", "I2": "Away leads at half time"})
add(["II1", "IIX", "II2"], "HALF_RESULT", "II Poluvreme",
    {"II1": "II Pol. 1", "IIX": "II Pol. X", "II2": "II Pol. 2"},
    {"II1": "Home wins the second half", "IIX": "Second half drawn", "II2": "Away wins the second half"})
add(["I1X", "IX2", "I12"], "HALF_DC", "I Pol. Dupla Šansa",
    {"I1X": "I Pol. 1X", "IX2": "I Pol. X2", "I12": "I Pol. 12"},
    {"I1X": "Home or draw at half time", "IX2": "Away or draw at half time", "I12": "Not a half-time draw"})
add(["II1X", "IIX2", "II12"], "HALF_DC", "II Pol. Dupla Šansa",
    {"II1X": "II Pol. 1X", "IIX2": "II Pol. X2", "II12": "II Pol. 12"},
    {"II1X": "Home or draw in the second half", "IIX2": "Away or draw in the second half",
     "II12": "Second half not drawn"})

# --- HTFT (9 basic + the double-chance variants) ----------------------------
HTFT_SECTION = "Poluvreme/Kraj"
HTFT_BASIC = ["1-1", "1-X", "1-2", "X-1", "X-X", "X-2", "2-1", "2-X", "2-2"]
add(HTFT_BASIC, "HTFT", HTFT_SECTION, {c: c for c in HTFT_BASIC},
    {c: f"Half time {c.split('-')[0]}, full time {c.split('-')[1]}" for c in HTFT_BASIC})
HTFT_DC = [
    "1X-1X", "1X-12", "1X-X2", "12-1X", "12-12", "12-X2", "X2-1X", "X2-12", "X2-X2",
    "1X-1", "1X-X", "1X-2", "12-1", "12-X", "12-2", "X2-1", "X2-X", "X2-2",
    "1-1X", "1-12", "1-X2", "X-1X", "X-12", "X-X2", "2-1X", "2-12", "2-X2",
]
add(HTFT_DC, "HTFT_DC", HTFT_SECTION, {c: c for c in HTFT_DC},
    {c: f"Half time {c.split('-')[0]}, full time {c.split('-')[1]}" for c in HTFT_DC})
HTFT_NE = ["NE 1-1", "NE X-1", "NE X-X", "NE X-2", "NE 2-2"]
add(HTFT_NE, "HTFT_NE", HTFT_SECTION, {c: c for c in HTFT_NE},
    {c: f"Not (half time {c[3:].split('-')[0]}, full time {c[3:].split('-')[1]})" for c in HTFT_NE})

# --- GOAL_RANGE_FT ----------------------------------------------------------
FT_GOALS = ["0-1", "0-2", "0-3", "0-4", "1", "1+", "1-2", "1-3", "1-4", "1-5", "1-6",
            "2", "2+", "2-3", "2-4", "2-5", "2-6", "3", "3+", "3-4", "3-5", "3-6",
            "4", "4+", "4-5", "4-6", "5", "5+", "6+", "7+"]
FT_NE = ["NE 1", "NE 1-2", "NE 1-3", "NE 1-4", "NE 2", "NE 4-6", "NE 3-4", "NE 3-5",
         "NE 3-6", "NE 4-5", "NE 3"]
add(FT_GOALS + FT_NE, "GOAL_RANGE_FT", "Ukupno Golova", {c: c for c in FT_GOALS + FT_NE},
    {c: f"Full-time total goals {c}" for c in FT_GOALS + FT_NE})

# --- GOAL_RANGE_1H / 2H -----------------------------------------------------
H1 = ["I0", "I0-1", "I0-2", "I1", "NE 1", "I1+", "I1-2", "NE 2", "I2", "I2+",
      "I2-3", "I2-4", "I3", "I3+", "I4+"]
H2 = ["II0", "II0-1", "II0-2", "II1", "NE 1", "II1+", "II1-2", "II1-3", "NE 2",
      "II2", "II2+", "II2-3", "II2-4", "II3", "II3+", "II4+"]
add(H1, "GOAL_RANGE_1H", "I Pol. Uk. Golova", {c: c for c in H1},
    {c: f"First-half total goals {c}" for c in H1})
add(H2, "GOAL_RANGE_2H", "II Pol. Uk. Golova", {c: c for c in H2},
    {c: f"Second-half total goals {c}" for c in H2})

# --- HALF_GOAL_COMBOS -------------------------------------------------------
COMBOS = [
    "I0-1&II0-1", "I0-1&II0-2", "I0-1&II0-3", "I0-2&II0-1", "I0-2&II0-2", "I0-2&II0-3",
    "I1+&II1+", "I1+&II2+", "I1+&II3+", "I1-2&II1-2", "I1-3&II1-3", "I2+&II1+",
    "I2+&II2+", "I2+&II3+", "I1+&2+", "I1+&3+", "I1-2&3+", "I1-2&4+", "I2+&3+",
    "I2+&4+", "NE I1-3&II1-3", "I2-3&4+", "NE I1+&II2+", "NE I1+&II1+",
    "I2-3&II2-3", "I2-3&II2+", "I2-3&II1-3", "I2-3&II1-2", "I2-3&II1+",
]
add(COMBOS, "HALF_GOAL_COMBOS", "Uk. Golova Kombinacije", {c: c for c in COMBOS},
    {c: f"Half-goal combination {c}" for c in COMBOS})

# --- RESULT_AND_GOALS / HTFT_AND_GOALS --------------------------------------
RAG = ["1 & 2+", "1 & 3+", "1 & 4+", "2 & 2+", "2 & 3+", "2 & 4+"]
RAG_RANGE = ["1 & 0-2", "1 & 2-3", "2 & 0-2", "2 & 2-3"]
add(RAG, "RESULT_AND_GOALS", "Match Outcome & Goals Combinations", {c: c for c in RAG},
    {c: f"Result and goals: {c}" for c in RAG})
add(RAG_RANGE, "RESULT_AND_GOALS", "Win & Under / Range Goals", {c: c for c in RAG_RANGE},
    {c: f"Result and goals: {c}" for c in RAG_RANGE})
HAG = ["1-1 & 2+", "1-1 & 3+", "2-2 & 2+", "2-2 & 3+"]
add(HAG, "HTFT_AND_GOALS", "Half + Match Outcome Combinations", {c: c for c in HAG},
    {c: f"HT/FT and goals: {c}" for c in HAG})

# --- MORE_GOALS_HALF is implemented directly (see core.market_code.direct_markets) ---


# --------------------------------------------------------------------------- #
# ext_markets section
# --------------------------------------------------------------------------- #
def settlement_signature(outcome) -> tuple:
    """Settlement over every half-by-half scoreline in 0..3, as an identity.

    Two markets are the same market exactly when their signatures match. The
    grid is the one :func:`core.half_model.market_prob` evaluates on, so the
    signature also captures void handling.
    """
    return tuple(
        outcome(h1, a1, h1 + h2, a1 + a2)
        for h1, a1, h2, a2 in itertools.product(range(4), repeat=4)
    )


def build_ext_markets(base_markets: list[Market]) -> dict:
    """Build the ``ext_markets`` section from the sample capture + the ext layer.

    A printed code is dropped only when **its own family already exists in the base
    catalogue and its settlement coincides with a base market** — that is the
    re-listing the crashed draft did wholesale, and the bare code is the canonical
    carrier there. Inside a family the base does not cover, every printed code is
    kept, and a code that happens to settle like a base market is recorded in
    ``settles_like_a_base_market`` rather than silently dropped (e.g. the
    Poluvreme-GG price ``IX&ING`` is a 0-0 first half, the same bet as
    ``GOAL_RANGE_1H I0``).
    """
    base_signatures: dict[tuple, tuple[str, str]] = {}
    for market in base_markets:
        base_signatures.setdefault(settlement_signature(market.outcome), (market.family, market.code))
    base_families = {m.family for m in base_markets}

    groups: dict[str, dict[str, list[str]]] = {}
    coincidences: dict[str, dict[str, str]] = {}
    untestable: dict[str, set[str]] = {}
    unconfirmed: list[dict] = []

    with EXT_SAMPLE.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            prefix, _, code = row["market_code"].partition(":")
            market = resolve(prefix, code)
            if market.status == "UNCONFIRMED":
                unconfirmed.append({
                    "prefix": prefix, "code": code, "family": market.family,
                    "section": market.section,
                    "status": "UNCONFIRMED", "note": market.note or EXT_UNCONFIRMED_REASON,
                })
            elif market.status == "UNTESTABLE":
                untestable.setdefault(market.family, set()).add(prefix)
            else:
                signature = settlement_signature(market.outcome)
                if market.family in base_families and signature in base_signatures:
                    continue
                groups.setdefault(market.family, {}).setdefault(prefix, []).append(code)
                if signature in base_signatures:
                    family, base_code = base_signatures[signature]
                    coincidences.setdefault(market.family, {})[f"{prefix}:{code}"] = f"{family} {base_code}"

    families = [
        {
            "family": family,
            "testable": True,
            "prefixes": [
                {
                    "prefix": prefix,
                    "section": PREFIX_SECTION.get(prefix, SECTION_UNCONFIRMED),
                    "codes": sorted(groups[family][prefix]),
                    **(({"settles_like_a_base_market": coincidences[family]})
                       if family in coincidences else {}),
                }
                for prefix in sorted(groups[family])
            ],
        }
        for family in sorted(groups)
    ]
    unconfirmed.sort(key=lambda e: (e["prefix"], e["code"]))
    return {
        "note": EXT_NOTE,
        "source": f"core/soccerbet_ext.py; codes observed in {EXT_SAMPLE.as_posix()}",
        "families": families,
        "untestable": [
            {
                "family": family,
                "prefixes": sorted(untestable[family]),
                "note": "not settleable from (HT, FT) scores; ingest only",
            }
            for family in sorted(untestable)
        ],
        "unconfirmed": unconfirmed,
    }


def load_existing_ext() -> dict | None:
    """The ext_markets section already in the catalogue, if any."""
    if not OUT.exists():
        return None
    return yaml.safe_load(OUT.read_text(encoding="utf-8")).get("ext_markets")


def main() -> int:
    entries: list[dict] = []
    errors: list[str] = []
    markets: list[Market] = []

    for code, family, section, label_sr, definition_en in CODE_ENTRIES:
        try:
            market: Market = parse(code, family, label_sr, definition_en, section=section)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{family} {code!r}: {exc}")
            continue
        markets.append(market)
        entries.append({
            "code": code,
            "label_sr": label_sr,
            "definition_en": market.definition_en,
            "family": family,
            "section": market.section,
            "period": market.period,
            "source": "soccerbet_rules",
            "testable": market.testable,
            "do_not_bet": code in DO_NOT_BET_UNTIL_CLARIFIED,
            "note": DO_NOT_BET_UNTIL_CLARIFIED.get(code, ""),
        })

    for market in direct_markets():
        markets.append(market)
        entries.append({
            "code": market.code,
            "label_sr": market.label_sr,
            "definition_en": market.definition_en,
            "family": market.family,
            "section": market.section,
            "period": market.period,
            "source": "soccerbet_rules",
            "testable": market.testable,
            "do_not_bet": market.code in DO_NOT_BET_UNTIL_CLARIFIED,
            "note": market.note or DO_NOT_BET_UNTIL_CLARIFIED.get(market.code, ""),
        })

    if EXT_SAMPLE.exists():
        ext_section = build_ext_markets(markets)
    else:
        ext_section = load_existing_ext()
        if ext_section is None:
            print(f"WARNING: neither {EXT_SAMPLE} nor an existing ext_markets section; "
                  "the catalogue will have no ext section")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "generated_by": "step1_catalogue.py",
        "source": "docs/soccerbet_rules_sr.txt",
        "note": (
            "Any parseable code is priceable. Codes not listed here are accepted at "
            "runtime with family UNLISTED until calibration-tested. `section` is the "
            "Serbian Soccer Bet section as displayed; the SECTION decides what a code "
            "means, because a bare code does not (1 is a home win under Konačni Ishod "
            "and exactly one goal under Ukupno Golova)."
        ),
        "markets": entries,
    }
    if ext_section is not None:
        doc["ext_markets"] = ext_section
    OUT.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")

    print(f"wrote {OUT}")
    print(f"markets: {len(entries)}")
    if ext_section is not None:
        n_codes = sum(len(p["codes"]) for f in ext_section["families"] for p in f["prefixes"])
        print(f"ext_markets: {len(ext_section['families'])} families, {n_codes} codes, "
              f"{len(ext_section['untestable'])} untestable families, "
              f"{len(ext_section['unconfirmed'])} unconfirmed")
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