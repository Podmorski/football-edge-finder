"""Audit historical odds / half-time column coverage in data/historical/*.parquet.

Local only — no network calls. Writes reports/odds_audit.md.

reports:
  * per league x season % non-null for the football-data.co.uk odds aliases
  * Pinnacle staleness check for recent seasons
  * a listing of unexpected / artefact columns
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from leagues import LEAGUES, label_of

DATA_DIR = Path("data/historical")
REPORT_PATH = Path("reports/odds_audit.md")

# Alias groups asked for. Values are candidate (already-sanitised) column names;
# the first present one is reported.
ALIASES: dict[str, list[str]] = {
    "HTHG/HTAG": ["hthg"],
    "HTR": ["htr"],
    "B365H/D/A": ["b365_h"],
    "AvgH/D/A": ["avg_h"],
    "PSH/D/A": ["psh"],
    "B365CH/D/A": ["b365_ch"],
    "AvgCH/D/A": ["avg_ch"],
    "PSCH/D/A": ["psch"],
    "Avg>2.5/<2.5": ["avg>2.5"],
    "AvgC>2.5/<2.5": ["avg_c>2.5"],
    "AHh": ["a_hh"],
    "AvgAHH/A": ["avg_ahh"],
    "AvgCAHH/A": ["avg_cahh"],
}

STALENESS_SEASONS = ["2025-2026", "2026-2027"]


def pct(series: pd.Series) -> str:
    if len(series) == 0:
        return "n/a"
    return f"{100 * series.notna().mean():.0f}%"


def season_order(season: str) -> str:
    return season


def main() -> int:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out: list[str] = ["# Historical odds / half-time coverage audit", ""]

    found_any_missing = False

    for league in LEAGUES:
        path = DATA_DIR / f"{league['slug']}.parquet"
        if not path.exists():
            out.append(f"## {label_of(league)} — MISSING FILE")
            out.append("")
            continue

        df = pd.read_parquet(path)
        seasons = sorted(df["season"].dropna().unique().tolist())

        out.append(f"## {label_of(league)}")
        out.append("")
        out.append(f"`{path}` — {len(df)} rows, seasons {seasons[0]}..{seasons[-1]}")
        out.append("")

        # which aliases resolve to a real column?
        resolved = {}
        for label, candidates in ALIASES.items():
            col = next((c for c in candidates if c in df.columns), None)
            resolved[label] = col
            if col is None:
                found_any_missing = True

        header = "| Season | " + " | ".join(ALIASES) + " |"
        sep = "|" + "---|" * (len(ALIASES) + 1)
        out.append(header)
        out.append(sep)
        for season in seasons:
            sub = df[df["season"] == season]
            cells = []
            for label, col in resolved.items():
                cells.append("MISSING" if col is None else pct(sub[col]))
            out.append(f"| {season} | " + " | ".join(cells) + " |")
        out.append("")

        missing_labels = [l for l, c in resolved.items() if c is None]
        out.append(
            "Alias resolution: "
            + ("all found" if not missing_labels else f"MISSING -> {missing_labels}")
        )
        out.append("")

    # --- Pinnacle staleness -------------------------------------------------
    out.append("## Pinnacle staleness check")
    out.append("")
    out.append(
        "Pinnacle odds on football-data.co.uk are unreliable from 2025-07-23. "
        "Check: % non-null Pinnacle closing, and % of rows where closing equals "
        "pre-closing (a stale-signal proxy)."
    )
    out.append("")
    out.append("| League | Season | PSH non-null | PSCH non-null | PSCH == PSH |")
    out.append("|---|---|---|---|---|")
    for league in LEAGUES:
        path = DATA_DIR / f"{league['slug']}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        for season in STALENESS_SEASONS:
            sub = df[df["season"] == season]
            if sub.empty:
                continue
            psh = sub["psh"] if "psh" in sub.columns else pd.Series(dtype=float)
            psch = sub["psch"] if "psch" in sub.columns else pd.Series(dtype=float)
            same = (
                (psh.notna() & psch.notna() & (psh == psch)).mean() if len(sub) else float("nan")
            )
            out.append(
                f"| {league['name']} | {season} | {pct(psh)} | {pct(psch)} | "
                f"{'n/a' if pd.isna(same) else f'{100*same:.0f}%'} |"
            )
    out.append("")

    # --- artefact columns ---------------------------------------------------
    out.append("## Artefact / unexpected columns")
    out.append("")
    for league in LEAGUES:
        path = DATA_DIR / f"{league['slug']}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        odd = [c for c in df.columns if not c.isascii() or c.startswith("_") or c.strip() == ""]
        out.append(f"- {label_of(league)}: {odd if odd else 'none'}")
    out.append("")

    REPORT_PATH.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {REPORT_PATH}")
    print(f"any alias missing: {found_any_missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())