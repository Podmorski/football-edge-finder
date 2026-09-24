# Market matrix — derived goal markets

Rows are **families**. `calibrated?` is the pooled discovery verdict
(slope in [0.85, 1.15] AND log loss better than B0 with the paired
bootstrap CI excluding 0, Holm-corrected across families).

**No ROI is claimed without Soccer Bet prices.**

| family | calibrated? | gain vs B0 (pooled) | 95% CI | testable? | status |
|---|---|---|---|---|---|
| DOUBLE_CHANCE | no | +0.0001 | [-0.0002, +0.0000] | yes | FAIL |
| GOAL_RANGE_1H | yes | +0.0024 | [-0.0038, -0.0010] | yes | MODEL-READY-AWAITING-PRICES |
| GOAL_RANGE_2H | yes | +0.0043 | [-0.0056, -0.0031] | yes | MODEL-READY-AWAITING-PRICES |
| GOAL_RANGE_FT | no | +0.0000 | [-0.0001, +0.0001] | yes | FAIL |
| HALF_DC | yes | +0.0010 | [-0.0016, -0.0004] | yes | MODEL-READY-AWAITING-PRICES |
| HALF_GOAL_COMBOS | no | +0.0006 | [-0.0011, -0.0001] | yes | FAIL |
| HALF_RESULT | yes | +0.0010 | [-0.0016, -0.0004] | yes | MODEL-READY-AWAITING-PRICES |
| HTFT | yes | +0.0005 | [-0.0008, -0.0002] | yes | MODEL-READY-AWAITING-PRICES |
| HTFT_AND_GOALS | no | +0.0003 | [-0.0008, +0.0002] | yes | FAIL |
| HTFT_DC | no | +0.0006 | [-0.0011, -0.0001] | yes | FAIL |
| HTFT_NE | yes | +0.0008 | [-0.0014, -0.0002] | yes | MODEL-READY-AWAITING-PRICES |
| MARGIN | no | +0.0001 | [-0.0002, -0.0000] | yes | FAIL |
| MORE_GOALS_HALF | yes | +0.0087 | [-0.0112, -0.0062] | yes | MODEL-READY-AWAITING-PRICES |
| NO_BET | no | -0.0017 | [+0.0014, +0.0019] | yes | FAIL |
| RESULT | no | +0.0001 | [-0.0002, +0.0000] | yes | FAIL |
| RESULT_AND_GOALS | no | +0.0000 | [-0.0001, +0.0000] | yes | FAIL |
| WIN_BOTH_HALVES | no | -0.0001 | [-0.0001, +0.0003] | yes | FAIL |
| WIN_TO_NIL | no | +0.0000 | [-0.0002, +0.0002] | yes | FAIL |

## Per league (gain vs B0, pooled over discovery seasons)

| family | league_one_t3 | ligue_2_t2 | bundesliga_2 | bundesliga_1 |
|---|---|---|---|---|
| DOUBLE_CHANCE | +0.0001 | +0.0001 | +0.0000 | +0.0001 |
| GOAL_RANGE_1H | +0.0010 | +0.0050 | +0.0017 | +0.0022 |
| GOAL_RANGE_2H | +0.0024 | +0.0021 | +0.0084 | +0.0060 |
| GOAL_RANGE_FT | +0.0000 | -0.0000 | +0.0001 | +0.0000 |
| HALF_DC | +0.0006 | +0.0014 | +0.0014 | +0.0009 |
| HALF_GOAL_COMBOS | +0.0002 | +0.0011 | +0.0002 | +0.0010 |
| HALF_RESULT | +0.0006 | +0.0014 | +0.0014 | +0.0009 |
| HTFT | +0.0002 | +0.0010 | +0.0005 | +0.0003 |
| HTFT_AND_GOALS | +0.0000 | +0.0013 | +0.0000 | -0.0003 |
| HTFT_DC | +0.0001 | +0.0012 | +0.0008 | +0.0005 |
| HTFT_NE | +0.0003 | +0.0014 | +0.0010 | +0.0005 |
| MARGIN | +0.0001 | +0.0002 | -0.0001 | +0.0001 |
| MORE_GOALS_HALF | +0.0053 | +0.0082 | +0.0124 | +0.0113 |
| NO_BET | -0.0016 | -0.0019 | -0.0024 | -0.0008 |
| RESULT | +0.0001 | +0.0001 | +0.0000 | +0.0001 |
| RESULT_AND_GOALS | -0.0000 | +0.0000 | -0.0000 | +0.0002 |
| WIN_BOTH_HALVES | -0.0001 | +0.0001 | -0.0003 | +0.0001 |
| WIN_TO_NIL | -0.0001 | -0.0001 | +0.0001 | +0.0002 |

## Notes

* `FIRST_GOAL` is **not settleable** from HT/FT data — it needs the goal
  timeline, which football-data.co.uk does not provide. Marked UNTESTED.
* `TO_QUALIFY` is out of scope (needs tie context).
* `NO_BET` is significantly **worse** than B0 (slope 1.28), so it is FAIL.
* `HTFT` beats B0 significantly but its slope is 0.44, so it fails the
  calibration criterion and is FAIL.
* Families not listed in the catalogue are accepted at runtime with
  family `UNLISTED` until calibration-tested.
