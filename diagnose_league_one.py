"""League One season diagnostics + in-sample and home/away-swap checks.

No tuning. Uses warmup + discovery only (never confirmation).

Reports:
  * per season: matches, home/draw/away rates, mean home/away goals,
    with 2019-20 (curtailed) and 2020-21 (closed doors) flagged
  * in-sample log loss: model vs naive training base rates
  * home/away swap test on the 2021-22 holdout (log loss must get worse)
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from models import league_one_dixon_coles as m

FLAGS = {
    "2019-2020": "CURTAILED (COVID)",
    "2020-2021": "CLOSED DOORS (COVID)",
}


def season_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for season in sorted(df["season"].unique()):
        sub = df[df["season"] == season]
        fthg = sub["fthg"].to_numpy()
        ftag = sub["ftag"].to_numpy()
        rows.append(
            {
                "season": season,
                "matches": len(sub),
                "home_win": float(np.mean(fthg > ftag)),
                "draw": float(np.mean(fthg == ftag)),
                "away_win": float(np.mean(fthg < ftag)),
                "mean_home_goals": float(fthg.mean()),
                "mean_away_goals": float(ftag.mean()),
                "flag": FLAGS.get(season, ""),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    matches = m.load_matches()
    train = m.training_frame(matches)
    holdout = m.holdout_frame(matches)

    print("=" * 78)
    print("League One diagnostics (warmup + discovery only; no tuning)")
    print("=" * 78)

    table = season_table(matches)
    print(f"\n{'season':<10} {'n':>5} {'home%':>7} {'draw%':>7} {'away%':>7} "
          f"{'hm/goal':>8} {'aw/goal':>8}  flag")
    for row in table.itertuples(index=False):
        print(f"{row.season:<10} {row.matches:>5} {100*row.home_win:>6.1f}% "
              f"{100*row.draw:>6.1f}% {100*row.away_win:>6.1f}% "
              f"{row.mean_home_goals:>8.3f} {row.mean_away_goals:>8.3f}  {row.flag}")

    non_covid = table[~table["flag"].str.contains("COVID")]
    covid = table[table["flag"].str.contains("COVID")]
    print(f"\nhome-win rate, non-COVID seasons : {100*non_covid['home_win'].mean():.1f}%")
    print(f"home-win rate, COVID seasons     : {100*covid['home_win'].mean():.1f}%")

    # ---------------- in-sample ----------------
    print("\n" + "-" * 78)
    print("IN-SAMPLE (fit and scored on the same 2015-16..2020-21 rows)")
    model, fit_seconds = m.fit(train)
    probs_model = m.outcome_probs(model, train)
    actual = m.actual_outcome(train)
    naive = m.base_rates(train)
    probs_naive = np.tile(naive, (len(train), 1))

    ll_model = m.log_loss(probs_model, actual)
    ll_naive = m.log_loss(probs_naive, actual)
    print(f"model in-sample log loss : {ll_model:.4f}")
    print(f"naive in-sample log loss : {ll_naive:.4f}")
    print(f"model beats naive in-sample: {ll_model < ll_naive}")
    if not (ll_model < ll_naive):
        print("!! MODEL DOES NOT BEAT NAIVE IN-SAMPLE -> suspected bug, stopping")
        return 1

    # ---------------- swap test ----------------
    print("\n" + "-" * 78)
    print("HOME/AWAY SWAP TEST on the 2021-22 holdout")
    eligible = m.eligible_teams(train)
    ok = holdout["team_home"].isin(eligible) & holdout["team_away"].isin(eligible)
    remaining = holdout[ok].reset_index(drop=True)
    holdout_actual = m.actual_outcome(remaining)

    normal = m.outcome_probs(model, remaining)
    swapped_raw = m.outcome_probs(
        model,
        remaining.assign(
            team_home=remaining["team_away"], team_away=remaining["team_home"]
        ),
    )
    # swapped_raw is oriented from the reversed fixture; flip back so the
    # columns again mean (original home, draw, original away).
    swapped = swapped_raw[:, [2, 1, 0]]

    ll_normal = m.log_loss(normal, holdout_actual)
    ll_swapped = m.log_loss(swapped, holdout_actual)
    print(f"log loss, correct orientation : {ll_normal:.4f}")
    print(f"log loss, home/away swapped   : {ll_swapped:.4f}")
    print(f"swapping makes it worse       : {ll_swapped > ll_normal}")
    print(f"mean P(home), correct : {normal[:, 0].mean():.4f}")
    print(f"mean P(home), swapped : {swapped[:, 0].mean():.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())