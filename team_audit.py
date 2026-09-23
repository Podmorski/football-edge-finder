"""Team-name audit across each league's historical data (local only).

Reads ``data/historical/<slug>.parquet`` and writes one report per league to
``reports/team_audit_<slug>.md``. Purely investigative — nothing is renamed.

Flags per league:
  1. near-duplicate team-name candidates (case/spacing/abbreviation variants)
  2. teams present in only one season
  3. per season, which teams are new versus the previous season
"""

from __future__ import annotations

import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from leagues import LEAGUES, label_of

DATA_DIR = Path("data/historical")
REPORT_DIR = Path("reports")

# Fuzzy threshold for "near-duplicate name" candidates.
SIMILARITY_THRESHOLD = 0.82
MIN_SUBSTRING_LEN = 5


def normalise(name: str) -> str:
    """Lowercase, strip everything but letters/digits."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def near_duplicate_pairs(names: list[str]) -> list[tuple[str, str, str]]:
    """Return (a, b, reason) for candidate near-duplicate name pairs."""
    pairs: list[tuple[str, str, str]] = []
    ordered = sorted(set(names))
    for i, a in enumerate(ordered):
        for b in ordered[i + 1 :]:
            na, nb = normalise(a), normalise(b)
            if not na or not nb or na == nb and a == b:
                continue
            if na == nb:
                pairs.append((a, b, "same normalised form"))
                continue
            shorter, longer = sorted((na, nb), key=len)
            if len(shorter) >= MIN_SUBSTRING_LEN and shorter in longer:
                pairs.append((a, b, "one name contains the other"))
                continue
            ratio = SequenceMatcher(None, na, nb).ratio()
            if ratio >= SIMILARITY_THRESHOLD:
                pairs.append((a, b, f"similarity {ratio:.2f}"))
    return pairs


def audit_league(league: dict) -> str | None:
    path = DATA_DIR / f"{league['slug']}.parquet"
    if not path.exists():
        return None

    df = pd.read_parquet(path)
    seasons = sorted(df["season"].dropna().unique().tolist())

    team_seasons: dict[str, set[str]] = {}
    for team, season in pd.concat(
        [
            df[["team_home", "season"]].rename(columns={"team_home": "team"}),
            df[["team_away", "season"]].rename(columns={"team_away": "team"}),
        ]
    ).itertuples(index=False):
        team_seasons.setdefault(team, set()).add(season)

    seasons_by_team = {t: sorted(s) for t, s in team_seasons.items()}
    all_names = sorted(seasons_by_team)

    lines: list[str] = []
    lines.append(f"# Team audit — {label_of(league)}")
    lines.append("")
    lines.append(
        f"Multiple names flagged but **nothing has been renamed**. "
        f"Source: `data/historical/{league['slug']}.parquet`"
    )
    lines.append("")
    lines.append(f"- Matches: {len(df)}")
    lines.append(f"- Seasons: {len(seasons)} ({seasons[0]} .. {seasons[-1]})")
    lines.append(f"- Distinct team names: {len(all_names)}")
    lines.append("")

    # --- 1. near-duplicates -------------------------------------------------
    dupes = near_duplicate_pairs(all_names)
    lines.append("## 1. Near-duplicate name candidates")
    lines.append("")
    if dupes:
        lines.append("| A | B | Reason |")
        lines.append("|---|---|---|")
        for a, b, reason in dupes:
            lines.append(f"| {a} | {b} | {reason} |")
    else:
        lines.append("None found.")
    lines.append("")

    # --- 2. single-season teams --------------------------------------------
    single = [t for t, s in seasons_by_team.items() if len(s) == 1]
    lines.append("## 2. Teams present in only one season")
    lines.append("")
    if single:
        for team in sorted(single):
            lines.append(f"- {team} ({seasons_by_team[team][0]})")
    else:
        lines.append("None.")
    lines.append("")

    # --- 3. per-season new teams -------------------------------------------
    lines.append("## 3. New teams per season (promoted / relegated in)")
    lines.append("")
    previous: set[str] = set()
    for season in seasons:
        current = {t for t, s in seasons_by_team.items() if season in s}
        new = sorted(current - previous)
        lines.append(f"### {season}")
        lines.append("")
        lines.append(f"- teams: {len(current)}")
        lines.append(f"- new vs previous season: {', '.join(new) if new else '(none)'}")
        lines.append("")
        previous = current

    # --- full listing -------------------------------------------------------
    lines.append("## Teams and the seasons they appear in")
    lines.append("")
    lines.append("| Team | # seasons | Seasons |")
    lines.append("|---|---|---|")
    for team in all_names:
        s = seasons_by_team[team]
        lines.append(f"| {team} | {len(s)} | {', '.join(s)} |")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for league in LEAGUES:
        report = audit_league(league)
        if report is None:
            print(f"{label_of(league)}: no parquet — skipped")
            continue
        out = REPORT_DIR / f"team_audit_{league['slug']}.md"
        out.write_text(report, encoding="utf-8")
        print(f"{label_of(league)}: wrote {out}")
        written += 1
    print(f"\nReports written: {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())