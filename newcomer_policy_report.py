"""Step 3c/3d — blend-weight audit and newcomer-policy comparison.

3c: report, per season, how many matches involve a team with blend weight < 1.
3d: compare the three policies on ALL matches and on EARLY-SPELL matches
    (either team has blend weight < 1, i.e. fewer than k=10 recent matches).
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from core import odds, walkforward as wf
from models import league_one_dixon_coles as m

SEASONS = ["2017-2018", "2018-2019", "2019-2020", "2020-2021", "2021-2022", "2022-2023"]
POLICIES = ["exclude", "league_avg", "newcomer_prior"]


def outcome(frame: pd.DataFrame) -> np.ndarray:
    fthg, ftag = frame["fthg"].to_numpy(), frame["ftag"].to_numpy()
    out = np.full(len(frame), 1, dtype=int)
    out[fthg > ftag] = 0
    out[fthg < ftag] = 2
    return out


def metrics(frame: pd.DataFrame) -> dict[str, float]:
    probs = frame[["p_home", "p_draw", "p_away"]].to_numpy()
    actual = outcome(frame)
    over = (frame["fthg"] + frame["ftag"] > 2.5).to_numpy().astype(int)
    p_over = frame["p_over25"].to_numpy()
    return {
        "n": len(frame),
        "log_loss": m.log_loss(probs, actual) if len(frame) else float("nan"),
        "log_loss_ou25": m.log_loss(np.column_stack([1 - p_over, p_over]), over) if len(frame) else float("nan"),
    }


def main() -> int:
    pool = wf.load_pool("league_one_t3")
    frames = {
        policy: wf.run(
            wf.Config(xi=0.002, covid_mode="include", newcomer=policy), SEASONS, pool=pool
        )
        for policy in POLICIES
    }

    print("=" * 86)
    print("Step 3c — blend-weight audit")
    print("=" * 86)
    reference = frames["league_avg"]
    reference = reference.assign(
        early=(reference["home_blend_weight"] < 1) | (reference["away_blend_weight"] < 1)
    )
    print(f"{'season':<10}{'matches':>8}{'n<10 matches':>14}{'n=0 legs':>10}"
          f"{'home w<1':>10}{'away w<1':>10}")
    total_early = 0
    for season in SEASONS:
        sub = reference[reference["season"] == season]
        early = int(sub["early"].sum())
        total_early += early
        zero_legs = int(
            ((sub["home_blend_weight"] == 0) | (sub["away_blend_weight"] == 0)).sum()
        )
        print(f"{season:<10}{len(sub):>8}{early:>14}{zero_legs:>10}"
              f"{int((sub['home_blend_weight'] < 1).sum()):>10}"
              f"{int((sub['away_blend_weight'] < 1).sum()):>10}")
    print(f"{'TOTAL':<10}{len(reference):>8}{total_early:>14}")
    print(f"\n(blend weight < 1 means fewer than {wf.NEWCOMER_K} recent matches;"
          " weight == 0 means no fitted rating)")

    print("\n" + "=" * 86)
    print("Step 3d — newcomer policy comparison")
    print("=" * 86)

    for scope, selector in (
        ("ALL matches", None),
        ("EARLY-SPELL matches (either team weight < 1)", "early"),
    ):
        print(f"\n--- {scope} ---")
        common_keys = None
        for policy in POLICIES:
            frame = frames[policy]
            if selector == "early":
                frame = frame.assign(
                    early=(frame["home_blend_weight"] < 1) | (frame["away_blend_weight"] < 1)
                )
                frame = frame[frame["early"]]
            keys = set(frame["match_key"])
            common_keys = keys if common_keys is None else (common_keys & keys)
        print(f"  (same {len(common_keys)} matches for every policy)")
        print(f"  {'policy':<16}{'n':>5}{'pooled 1X2':>12}{'pooled O/U':>12}")
        for policy in POLICIES:
            frame = frames[policy]
            if selector == "early":
                frame = frame.assign(
                    early=(frame["home_blend_weight"] < 1) | (frame["away_blend_weight"] < 1)
                )
                frame = frame[frame["early"]]
            sub = frame[frame["match_key"].isin(common_keys)]
            mm = metrics(sub)
            print(f"  {policy:<16}{mm['n']:>5}{mm['log_loss']:>12.4f}{mm['log_loss_ou25']:>12.4f}")

    print("\n--- per-season pooled 1X2 on the early-spell subset ---")
    early_keys = set(reference[reference["early"]]["match_key"])
    print(f"  {'season':<10}" + "".join(f"{p:>16}" for p in POLICIES))
    for season in SEASONS:
        cells = []
        for policy in POLICIES:
            frame = frames[policy]
            sub = frame[(frame["season"] == season) & (frame["match_key"].isin(early_keys))]
            cells.append(f"{metrics(sub)['log_loss']:>16.4f}" if len(sub) else f"{'-':>16}")
        print(f"  {season:<10}" + "".join(cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())