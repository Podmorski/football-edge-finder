# Pre-registration — derived goal markets (Phase 3)

Written **before** any calibration number was computed (2026-09-24).

## Hypothesis
Soccer Bet prices hundreds of derived goal markets by formula. A joint
half-by-half model anchored on the sharp **pre-match** 1X2 + O/U 2.5 should
price some families more accurately than a plausible book formula (B0: 50/50
half split, independent halves).

## Success criterion (per family)
Pooled over discovery seasons 2017-18..2022-23 (per league and pooled across the
four leagues):

1. calibration slope in **[0.85, 1.15]**, AND
2. log loss better than **B0** with a paired bootstrap 95% CI
   (2000 resamples, by matchday) **excluding 0**.

Holm correction across families; raw and corrected p-values both reported.

## What this does NOT claim
No ROI, no staking, no edge. A family that passes is a **CONFIRMATION
CANDIDATE** only. Confirmation seasons (2023-24+) are untouched.

---

# MAINLINE-1 (written 2026-09-24, BEFORE any user price data arrives)

## Hypothesis
Soccer Bet's **MAIN LINE** (1X2 + goal totals) sometimes deviates from the sharp
market by **more than its own margin**.

Sharp prices (Pinnacle, via The Odds API, region `eu`) are used **ONLY** as the
reference for true probability. Bets would be placed **ONLY at Soccer Bet**, and
only in the **lowest-margin market that captures the deviation**. **Never
combos.**

## Why this is the only remaining hypothesis
The derived-market structure hypothesis is **CLOSED**: Soccer Bet's implied
first-half goal share (~0.42) already matches our historical estimate
(0.41–0.44), their game-state effects are small, and an external analysis of one
full match found **0 markets with positive EV** anchored on their own main line
(margins ~8% on 1X2, 10–15% on singles, 15–45% on combos). Beating the naive B0
formula is **not** evidence of edge against the book.

## Data requirement
**≥ 30 matches** captured within **60 minutes** of a sharp snapshot. Anything
else is flagged `STALE` and excluded from the verdict.

## Success criterion
Report the distribution of `EV_max` across matches. The hypothesis is
**SUPPORTED** only if **both**:

1. **≥ 10% of matches** have a flagged market (EV > +3% after the safety
   haircut: `p_sharp` shrunk 20% toward Soccer Bet's de-margined probability), AND
2. the **mean EV of flagged markets is > 0** with a bootstrap 95% CI
   (2000 resamples, by match) **above 0**.

## Otherwise
**CLOSE the betting hypothesis for Soccer Bet.** No further tweaking.

## What this does NOT claim
No ROI, no staking, no bet simulation. A supported hypothesis is a
**CONFIRMATION CANDIDATE** only.
