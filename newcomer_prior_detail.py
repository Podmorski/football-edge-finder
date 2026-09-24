"""Print the teams behind each newcomer prior's n, and explain the n growth.

Also checks the 2019-20 anomaly: League One had only 6 newcomers that season
because Bury were expelled from the league in August 2019.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from core import walkforward as wf

TARGETS = ["2019-2020", "2020-2021", "2021-2022", "2022-2023"]
OUT = Path("reports/figures/newcomer_prior_detail.csv")


def main() -> int:
    pool = wf.load_pool("league_one_t3")
    labels = wf.load_labels()
    config = wf.Config(xi=0.002, covid_mode="exclude_after", newcomer="newcomer_prior")

    print("=" * 92)
    print("Newcomer prior detail — teams behind each n")
    print("=" * 92)

    rows = []
    for target in TARGETS:
        sub = pool[pool["season"] == target]
        cutoff = wf.cutoff_mondays(sub).min()
        train = wf.training_frame_for(pool, cutoff, config, target)
        params = wf.fit_at(config, train, cutoff, target)
        members = wf.newcomer_prior_members(pool, cutoff, labels, target)

        print(f"\n{target}  (cutoff {cutoff.date()})")
        for label in ("promoted_in", "relegated_in", "other"):
            people = sorted(members[label])
            print(f"  {label:<14} n={len(people):<3} "
                  f"{', '.join(f'{t} ({s})' for t, s in people) if people else '-'}")
            for team, season in people:
                rows.append({"target_season": target, "label": label,
                             "team": team, "arrival_season": season})

    print("\n--- why n grows ---")
    print("  The rule requires the arrival season to be strictly before the target AND")
    print("  more than 365 days before the cutoff (past their first year).")
    for target in TARGETS:
        sub = pool[pool["season"] == target]
        cutoff = wf.cutoff_mondays(sub).min()
        starts = wf.season_start_dates(pool)
        eligible = [
            s for s in sorted(starts)
            if s < target and (cutoff - starts[s]).days > wf.NEWCOMER_HORIZON_DAYS
        ]
        print(f"  {target}: cutoff {cutoff.date()} -> arrival seasons old enough: {eligible}")

    print("\n--- 2019-20 anomaly ---")
    for season in ("2018-2019", "2019-2020", "2020-2021"):
        sub = pool[pool["season"] == season]
        teams = sorted(set(sub["team_home"]) | set(sub["team_away"]))
        print(f"  {season}: {len(teams)} distinct teams")
    print("  Bury were expelled from League One in August 2019, so 2019-20 ran with")
    print("  23 teams and produced only 6 newcomers (3 relegated + 3 promoted).")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT, index=False)
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())