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

---

# MAINLINE-HIST-1 (written 2026-09-24, BEFORE any number in this run)

Same hypothesis as MAINLINE-1, tested on history instead of on captures we could
not collect. Frozen before any figure below was computed.

## Hypothesis
At bet time, a **soft** book's **pre-match** price for a main-line market is
sometimes above the de-margined **sharp pre-match** price by more than the cushion.

## Fair probability (the only inputs)
```
fair_prob = Pinnacle PRE-MATCH odds de-margined with the POWER method
fair_odds = 1 / fair_prob
```
No model is involved: this is a pure market-relative test.

## Bet rule
Bet **1 unit** at the SOFT book's **pre-match** odds whenever

```
soft_odds >= fair_odds x 1.035
```

Nothing else. **Never** `Max` / best-of-market: one book at a time, the price it
actually showed.

## Soft books — tested SEPARATELY
| Book | Columns |
|---|---|
| **B365** | `b365_h/d/a`, `b365>2.5/<2.5`, `b365_ahh/aha` |
| **market average** | `avg_*` where present, else `bb_av_*` (the `Avg` block does not exist before 2019-20) |

The average series always names the source actually used on each row.

## Markets
**1X2** (each outcome), **O/U 2.5** (each side), **AH main line** (home, away).
Only rows where BOTH the Pinnacle pre-match price AND the soft price exist.

## Evaluation (per soft book x market)
1. **P&L and ROI** with a bootstrap 95% CI, resampling **by matchday**
   (2000 draws, fixed seed). Standard stakes of 1 unit.
2. **CLV** `= soft_odds / fair_close - 1`, where `fair_close` is the de-margined
   Pinnacle **CLOSING** price (`psch/pscd/psca`, `pc>2.5/<2.5`, `pcahh/pcaha`),
   power method, with a bootstrap 95% CI by matchday.

The closing price is used **ONLY** for evaluation, never as an input to a decision.

## Discovery window
**2017-18 .. 2022-23**, all four leagues. **Confirmation seasons are not opened.**

## Data availability disclosed before computing
Pinnacle **pre-match O/U and AH do not exist before 2019-20** (see the data
check). Those two markets therefore cover **four** discovery seasons, not six, and
the `n >= 300` gate is applied to what exists.

## Success criterion (per soft book x market)
**mean CLV > 0 with the 95% CI above 0 AND n >= 300 bets.**
Holm correction across the tests; raw and corrected p-values both reported.

## Reported but NEVER used to select
* edge bucket (3.5-5%, 5-8%, 8%+),
* odds band (<2, 2-4, 4+),
* threshold sensitivity at 1.00 and 1.07.

## What this does NOT claim
B365 and the market average are **proxies for Mozzart**, not Mozzart. **A FAIL
does not rule out local books, and a PASS is encouraging, not proof.** A PASS
becomes a **CONFIRMATION CANDIDATE** with this rule text frozen; the locked
confirmation seasons stay locked.
