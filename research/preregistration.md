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
