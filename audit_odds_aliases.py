"""Odds-alias coverage audit for 2015-16 .. 2022-23, all four leagues.

Local only — no network. Writes reports/odds_alias_audit.md.

Reports, per league x season:
  * % non-null for the BetBrain (pre-2019-20) aliases
  * % non-null for Pinnacle closing / O-U / AH aliases
  * whether a pre-match 1X2 benchmark and a closing 1X2 price exist
  * mean book margin (overround) for pre-match and closing 1X2
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from core import odds
from leagues import LEAGUES, label_of

DATA_DIR = Path("data/historical")
REPORT_PATH = Path("reports/odds_alias_audit.md")

SEASONS = [
    "2015-2016",
    "2016-2017",
    "2017-2018",
    "2018-2019",
    "2019-2020",
    "2020-2021",
    "2021-2022",
    "2022-2023",
]

# The aliases asked for, in the order requested (lower-cased parquet names).
ALIASES = [
    ("BbAvH", "bb_av_h"),
    ("BbAvD", "bb_av_d"),
    ("BbAvA", "bb_av_a"),
    ("BbMxH", "bb_mx_h"),
    ("BbMxD", "bb_mx_d"),
    ("BbMxA", "bb_mx_a"),
    ("BbAv>2.5", "bb_av>2.5"),
    ("BbAv<2.5", "bb_av<2.5"),
    ("BbAHh", "bb_a_hh"),
    ("BbAvAHH", "bb_av_ahh"),
    ("BbAvAHA", "bb_av_aha"),
    ("PSCH", "psch"),
    ("PSCD", "pscd"),
    ("PSCA", "psca"),
    ("P>2.5", "p>2.5"),
    ("P<2.5", "p<2.5"),
    ("PC>2.5", "pc>2.5"),
    ("PC<2.5", "pc<2.5"),
    ("PAHH", "pahh"),
    ("PAHA", "paha"),
    ("PCAHH", "pcahh"),
    ("PCAHA", "pcaha"),
]


def pct(series: pd.Series) -> str:
    if len(series) == 0:
        return "-"
    return f"{100 * series.notna().mean():.0f}"


def main() -> int:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out: list[str] = ["# Odds alias coverage, 2015-16 .. 2022-23", ""]

    availability: list[str] = []
    margins: list[str] = []

    for league in LEAGUES:
        path = DATA_DIR / f"{league['slug']}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        df = df[df["season"].isin(SEASONS)]

        out.append(f"## {label_of(league)}")
        out.append("")
        out.append("| Season | n | " + " | ".join(a for a, _ in ALIASES) + " |")
        out.append("|" + "---|" * (len(ALIASES) + 2))

        for season in SEASONS:
            sub = df[df["season"] == season]
            if sub.empty:
                out.append(f"| {season} | 0 |" + " - |" * len(ALIASES))
                continue
            cells = [pct(sub[col]) if col in sub.columns else "MISS" for _, col in ALIASES]
            out.append(f"| {season} | {len(sub)} | " + " | ".join(cells) + " |")
        out.append("")

        # benchmark availability
        availability.append(f"### {label_of(league)}")
        availability.append("")
        availability.append("| Season | pre-match 1X2 | source(s) | closing 1X2 | source(s) |")
        availability.append("|---|---|---|---|---|")
        margins.append(f"### {label_of(league)}")
        margins.append("")
        margins.append("| Season | pre-match margin | closing margin |")
        margins.append("|---|---|---|")
        for season in SEASONS:
            sub = df[df["season"] == season]
            if sub.empty:
                continue
            pre = odds.prematch_1x2(sub)
            clo = odds.closing_1x2(sub)
            pre_src = sorted(set(pre.source.dropna()))
            clo_src = sorted(set(clo.source.dropna()))
            availability.append(
                f"| {season} | {'yes' if pre.available.any() else 'NO'} "
                f"({int(pre.available.sum())}/{len(sub)}) | {', '.join(pre_src) or '-'} | "
                f"{'yes' if clo.available.any() else 'NO'} "
                f"({int(clo.available.sum())}/{len(sub)}) | {', '.join(clo_src) or '-'} |"
            )
            pre_margin = odds.booksum_margin(pre.odds[pre.available]).mean()
            clo_margin = (
                odds.booksum_margin(clo.odds[clo.available]).mean()
                if clo.available.any()
                else float("nan")
            )
            margins.append(
                f"| {season} | {pre_margin:.4f} | "
                f"{'n/a' if pd.isna(clo_margin) else f'{clo_margin:.4f}'} |"
            )
        availability.append("")
        margins.append("")

    out.append("## Benchmark availability")
    out.append("")
    out.extend(availability)
    out.append("## Mean book margin (overround), 1X2")
    out.append("")
    out.append(
        "The margin removed is the raw overround `sum(1/o) - 1`; both the "
        "proportional and power de-margin methods consume exactly this input."
    )
    out.append("")
    out.extend(margins)

    REPORT_PATH.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())