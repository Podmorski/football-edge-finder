"""Classify League One newcomers using auxiliary E1 (Championship) and E3 (League Two).

A team is a **newcomer** in season S if it has no League One match in the 365
days before S's first match. It is then:

* ``relegated_in`` — its most recent season before S was in E1
* ``promoted_in``  — its most recent season before S was in E3
* ``other``        — neither (e.g. no visible history in either division)

E1/E3 are auxiliary only: they are never used to fit a model or to bet.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from core import walkforward as wf

AUX_DIR = Path("data/auxiliary")
LABELS_PATH = AUX_DIR / "newcomer_labels.parquet"

TARGET_SEASONS = ["2017-2018", "2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]
HORIZON_DAYS = 365

SPOT_CHECKS = {
    "2021-2022": {
        "relegated_in": ["Wycombe", "Rotherham", "Sheffield Weds"],
        "promoted_in": ["Cheltenham", "Cambridge", "Bolton", "Morecambe"],
    },
    "2022-2023": {
        "relegated_in": ["Peterborough", "Derby", "Barnsley"],
        "promoted_in": ["Forest Green", "Exeter", "Bristol Rvs", "Port Vale"],
    },
}


def last_division(team: str, season: str, e1: pd.DataFrame, e3: pd.DataFrame):
    """Most recent division (before ``season``) the team played in, and its season."""

    def latest(df: pd.DataFrame) -> str | None:
        sub = df[((df["team_home"] == team) | (df["team_away"] == team)) & (df["season"] < season)]
        return sub["season"].max() if len(sub) else None

    l1, l3 = latest(e1), latest(e3)
    if l1 is None and l3 is None:
        return (None, None)
    if l3 is None or (l1 is not None and l1 > l3):
        return ("E1", l1)
    return ("E3", l3)


def build_labels() -> pd.DataFrame:
    pool = wf.load_pool("league_one_t3")
    e1 = pd.read_parquet(AUX_DIR / "e1.parquet")
    e3 = pd.read_parquet(AUX_DIR / "e3.parquet")

    rows = []
    for season in TARGET_SEASONS:
        sub = pool[pool["season"] == season]
        if sub.empty:
            continue
        start = sub["date"].min()
        window = pool[(pool["date"] >= start - pd.Timedelta(days=HORIZON_DAYS)) & (pool["date"] < start)]
        recent = set(window["team_home"]) | set(window["team_away"])
        teams = sorted(set(sub["team_home"]) | set(sub["team_away"]))

        for team in teams:
            if team in recent:
                continue
            division, div_season = last_division(team, season, e1, e3)
            label = {"E1": "relegated_in", "E3": "promoted_in", None: "other"}[division]
            rows.append(
                {
                    "season": season,
                    "team": team,
                    "newcomer": True,
                    "label": label,
                    "last_division": division,
                    "last_division_season": div_season,
                }
            )
    return pd.DataFrame(rows)


def match_expected(expected: str, actual: list[str]) -> str:
    """Find the dataset's spelling nearest to ``expected`` (prefix heuristic)."""
    key = expected.lower()[:6]
    for name in actual:
        if name.lower().startswith(key) or key.startswith(name.lower()[:6]):
            return name
    return f"NOT FOUND ({expected})"


def main() -> int:
    labels = build_labels()
    LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    labels.to_parquet(LABELS_PATH, index=False)

    print("=" * 84)
    print("Step 3a — League One newcomers classified from E1/E3")
    print("=" * 84)
    for season in TARGET_SEASONS:
        sub = labels[labels["season"] == season]
        print(f"\n{season}  ({len(sub)} newcomers)")
        for label in ("relegated_in", "promoted_in", "other"):
            names = sorted(sub[sub["label"] == label]["team"].tolist())
            print(f"  {label:<14} ({len(names)}): {', '.join(names) if names else '-'}")

    print("\n--- spot checks ---")
    all_ok = True
    for season, expected_sets in SPOT_CHECKS.items():
        sub = labels[labels["season"] == season]
        for label, expected in expected_sets.items():
            actual = sorted(sub[sub["label"] == label]["team"].tolist())
            resolved = [match_expected(e, actual) for e in expected]
            missing = [r for r in resolved if r.startswith("NOT FOUND")]
            present = [r for r in resolved if not r.startswith("NOT FOUND")]
            status = "PASS" if not missing else "FAIL"
            if missing:
                all_ok = False
            print(f"  [{status}] {season} {label}: expected {expected}")
            print(f"         dataset spelling: {present}"
                  + (f"  missing: {missing}" if missing else ""))
            extras = [n for n in actual if n not in present]
            if extras:
                print(f"         extra in dataset: {extras}")
    print(f"\nall spot checks pass: {all_ok}")
    print(f"labels -> {LABELS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())