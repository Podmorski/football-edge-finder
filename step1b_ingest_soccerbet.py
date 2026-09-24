"""Step 1b — ingest the Soccer Bet sample price list for one match.

Input: ``data/soccerbet/hoffenheim_hamburg_raw.txt`` — two blocks of
``FAMILY:code odds`` items separated by ``|``. Output: a price file in the
template schema, one row per market.

Reports:
  * resolution status counts (OK / UNCONFIRMED / UNTESTABLE)
  * the UNCONFIRMED list — never guessed, always listed
  * market count per family
  * margin per family, from the explicit exhaustive partitions only

The base catalogue (``config/markets_catalogue.yaml``) is deliberately **not**
modified. It is generated from the rules text by ``step1_catalogue.py`` and is
keyed by bare code; the new families here are keyed by the printed
``PREFIX:code`` (the same code means different things under different prefixes)
and live in :mod:`core.soccerbet_ext`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from core.soccerbet_ext import resolve

RAW = Path("data/soccerbet/hoffenheim_hamburg_raw.txt")
OUT = Path("data/soccerbet/2026-09-24_hoffenheim_hamburg.csv")

MATCH = {
    "date": "2026-10-10",
    "league": "bundesliga_1",
    "home": "Hoffenheim",
    "away": "Hamburger SV",
    "capture_time_local": "2026-09-24T17:25",
}

# Explicit exhaustive partitions: {name: (reference sum, [PREFIX:code keys])}.
# Most sum to 1; double-chance sets cover two of three outcomes so they sum to 2.
# Only true partitions belong here — a partial set's sum is NOT a margin.
PARTITIONS: dict[str, tuple[float, list[str]]] = {
    "RESULT": (1.0, ["FT:1", "FT:X", "FT:2"]),
    "DOUBLE_CHANCE": (2.0, ["DC:1X", "DC:12", "DC:X2"]),
    "HALF_RESULT_1H": (1.0, ["H1:1", "H1:X", "H1:2"]),
    "HALF_RESULT_2H": (1.0, ["H2:1", "H2:X", "H2:2"]),
    "HALF_DC_1H": (2.0, ["H1DC:1X", "H1DC:12", "H1DC:X2"]),
    "HALF_DC_2H": (2.0, ["H2DC:1X", "H2DC:12", "H2DC:X2"]),
    "HTFT": (1.0, [f"HF:{c}" for c in
                   ["1-1", "1-X", "1-2", "X-1", "X-X", "X-2", "2-1", "2-X", "2-2"]]),
    "BTTS": (1.0, ["GG:GG", "GG:NG"]),
    "BTTS_2PLUS": (1.0, ["GG:2GG", "GG:2NG"]),
    "BTTS_HALVES": (1.0, ["GG:IGG&IIGG", "GG:IGG&IING", "GG:ING&IIGG", "GG:ING&IING"]),
    "ODD_EVEN": (1.0, ["PN:Par", "PN:Nepar"]),
    "MORE_GOALS_HALF": (1.0, ["PV:I>II", "PV:I=II", "PV:I<II"]),
}

# which family each partition measures (for the per-family margin summary)
PARTITION_FAMILY = {
    "RESULT": "RESULT", "DOUBLE_CHANCE": "DOUBLE_CHANCE",
    "HALF_RESULT_1H": "HALF_RESULT", "HALF_RESULT_2H": "HALF_RESULT",
    "HALF_DC_1H": "HALF_DC", "HALF_DC_2H": "HALF_DC",
    "HTFT": "HTFT", "BTTS": "BTTS",
    "BTTS_2PLUS": "BTTS", "BTTS_HALVES": "BTTS_COMBOS",
    "ODD_EVEN": "ODD_EVEN", "MORE_GOALS_HALF": "MORE_GOALS_HALF",
}


def parse_blocks() -> list[tuple[str, str, float]]:
    """Return ``[(prefix, code, odds)]`` for both blocks, in file order."""
    rows: list[tuple[str, str, float]] = []
    for line in RAW.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("==="):
            continue
        for item in line.split("|"):
            item = item.strip()
            if not item:
                continue
            prefix, rest = item.split(":", 1)
            code, odds = rest.rsplit(" ", 1)
            rows.append((prefix.strip(), code.strip(), float(odds)))
    return rows


def margin_table(rows: list[tuple[str, str, float]]) -> list[dict]:
    """Margin per family, using exhaustive partitions where they exist."""
    price = {f"{p}:{c}": o for p, c, o in rows}
    by_family: dict[str, list[float]] = {}
    for p, c, o in rows:
        by_family.setdefault(resolve(p, c).family, []).append(o)

    margins: dict[str, list[tuple[str, float]]] = {}
    for name, (reference, keys) in PARTITIONS.items():
        prices = [price[k] for k in keys if k in price]
        if len(prices) != len(keys):
            continue  # incomplete set: not a margin
        family = PARTITION_FAMILY[name]
        m = float(sum(1.0 / p for p in prices) / reference - 1.0)
        margins.setdefault(family, []).append((name, m))

    table = []
    for family, prices in sorted(by_family.items(), key=lambda kv: -len(kv[1])):
        table.append({
            "family": family,
            "n": len(prices),
            "sum_inv": float(sum(1.0 / p for p in prices)),
            "margins": margins.get(family, []),
        })
    return table


def print_margin_table(table: list[dict]) -> None:
    print("\n--- margin per family (partitions only; 'n/a' = partial set, "
          "its sum is NOT a margin) ---")
    print(f"  {'family':<28}{'n':>4}{'sum(1/odds)':>13}   margin (partition)")
    for row in table:
        margin_txt = ", ".join(f"{name} {m:+.4f}" for name, m in row["margins"]) or "n/a"
        print(f"  {row['family']:<28}{row['n']:>4}{row['sum_inv']:>13.4f}   {margin_txt}")


def main() -> int:
    rows = parse_blocks()
    print("=" * 100)
    print(f"Soccer Bet sample ingest: {MATCH['home']} vs {MATCH['away']} "
          f"({MATCH['league']}, kickoff {MATCH['date']}, captured "
          f"{MATCH['capture_time_local']} local)")
    print("=" * 100)
    print(f"price rows: {len(rows)}")

    out_rows, by_status, unconfirmed = [], {}, []
    untestable: dict[str, int] = {}
    for prefix, code, odds in rows:
        market = resolve(prefix, code)
        by_status[market.status] = by_status.get(market.status, 0) + 1
        if market.status == "UNCONFIRMED":
            unconfirmed.append((prefix, code, market.note))
        if market.status == "UNTESTABLE":
            untestable[market.family] = untestable.get(market.family, 0) + 1
        out_rows.append({
            "date": MATCH["date"], "league": MATCH["league"],
            "home": MATCH["home"], "away": MATCH["away"],
            "capture_time_local": MATCH["capture_time_local"],
            "market_code": f"{prefix}:{code}", "family": market.family,
            "soccer_bet_odds": odds, "status": market.status, "note": market.note,
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(out_rows).to_csv(OUT, index=False)
    print(f"wrote {OUT}")

    print(f"\nresolution status: {by_status}")

    print(f"\n--- UNCONFIRMED ({len(unconfirmed)}) — never guessed, listed for the user ---")
    for prefix, code, note in unconfirmed:
        print(f"  {prefix}:{code}  ({note})")

    print(f"\n--- UNTESTABLE ({sum(untestable.values())}) — ingested, not settleable "
          "from HT/FT scores ---")
    for family, n in sorted(untestable.items(), key=lambda kv: -kv[1]):
        print(f"  {family:<22} {n}")

    table = margin_table(rows)
    print_margin_table(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())