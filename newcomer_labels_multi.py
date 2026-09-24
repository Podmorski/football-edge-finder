"""Newcomer labels for the other leagues, from auxiliary divisions.

Rules (per the brief):
  ligue_2_t2   relegated_in = last season in F1; otherwise promoted_or_other
  bundesliga_2 relegated_in = last season in D1 (bundesliga_1 on disk);
               otherwise promoted_or_other
  bundesliga_1 promoted_in  = last season in D2 (bundesliga_2 on disk);
               otherwise relegated_or_other

There is no third-tier data for France or Germany on football-data.co.uk, so
remaining newcomers cannot be split further and are labelled
``promoted_or_other``. Doubts are flagged, never guessed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from core import walkforward as wf

AUX = Path("data/auxiliary")
OUT = AUX / "newcomer_labels_multi.parquet"
HORIZON = 365

TARGET_SEASONS = ["2017-2018", "2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]

# league slug -> (above division file, above label, below division file, below label)
RULES = {
    "ligue_2_t2": ("f1", "relegated_in", None, "promoted_or_other"),
    "bundesliga_2": ("bundesliga_1", "relegated_in", None, "promoted_or_other"),
    "bundesliga_1": (None, "relegated_or_other", "bundesliga_2", "promoted_in"),
}


def load_division(name: str) -> pd.DataFrame:
    if name in ("e1", "e3", "f1"):
        return pd.read_parquet(AUX / f"{name}.parquet")
    return pd.read_parquet(Path("data/historical") / f"{name}.parquet")


def previous_season(season: str) -> str:
    a, b = season.split("-")
    return f"{int(a) - 1}-{int(b) - 1}"


def last_season_in(division: pd.DataFrame, team: str, season: str) -> str | None:
    sub = division[
        ((division["team_home"] == team) | (division["team_away"] == team))
        & (division["season"] < season)
    ]
    return sub["season"].max() if len(sub) else None


def was_in_previous_season(division: pd.DataFrame, team: str, season: str) -> bool:
    """True only if the team played in ``division`` in the IMMEDIATELY prior season.

    Requiring the immediately preceding season is what makes this a genuine
    relegation/promotion. Using "any earlier season" mislabels teams that were
    in the division above years ago and returned via a lower tier (e.g. Bastia
    and Ingolstadt in 2021-22, both promoted from the third tier).
    """
    prev = previous_season(season)
    sub = division[
        ((division["team_home"] == team) | (division["team_away"] == team))
        & (division["season"] == prev)
    ]
    return len(sub) > 0


def main() -> int:
    rows = []
    print("=" * 96)
    print("Newcomer labels for ligue_2_t2, bundesliga_2, bundesliga_1")
    print("=" * 96)

    for slug, (above_file, above_label, below_file, below_label) in RULES.items():
        pool = wf.load_pool(slug)
        above = load_division(above_file) if above_file else None
        below = load_division(below_file) if below_file else None

        print(f"\n=== {slug} ===")
        for season in TARGET_SEASONS:
            sub = pool[pool["season"] == season]
            if sub.empty:
                continue
            start = sub["date"].min()
            window = pool[
                (pool["date"] >= start - pd.Timedelta(days=HORIZON)) & (pool["date"] < start)
            ]
            recent = set(window["team_home"]) | set(window["team_away"])
            teams = sorted(set(sub["team_home"]) | set(sub["team_away"]))

            buckets: dict[str, list[str]] = {}
            for team in teams:
                if team in recent:
                    continue
                label = None
                if above is not None and was_in_previous_season(above, team, season):
                    label = above_label
                if label is None and below is not None and was_in_previous_season(below, team, season):
                    label = below_label
                if label is None:
                    label = "promoted_or_other" if above is not None else "relegated_or_other"
                buckets.setdefault(label, []).append(team)
                rows.append({"league": slug, "season": season, "team": team, "label": label})

            parts = " | ".join(
                f"{k}={sorted(v)}" for k, v in sorted(buckets.items())
            )
            print(f"  {season} ({sum(len(v) for v in buckets.values())}): {parts or '-'}")

    labels = pd.DataFrame(rows)
    labels.to_parquet(OUT, index=False)
    print(f"\nwrote {OUT} ({len(labels)} rows)")
    print("\nlabel counts per league:")
    print(labels.groupby(["league", "label"]).size().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())