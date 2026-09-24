# Phase 2d — League One (objective reframed, totals decomposed)

**Zero API calls. Zero downloads.** League One only. Confirmation seasons
(2023-24+) never loaded. Final config: `xi=0.002`, `covid_mode=exclude_after`,
`newcomer=newcomer_prior`.

## 0. Plan changes

* **Objective reframed:** find outcomes — singles and same-game combos — that
  layered models rate likely **AND** whose probabilities are **calibrated on
  unseen seasons**; bet only where the typical payout beats break-even
  (`p × odds > 1`). Not price-hunting; the book is not a selection criterion;
  systematic market-wide biases are in scope.
* **Reversed:** the "BET PRICE proxy = B365" entry is withdrawn. Prices are used
  **only** for the payout check, at the **market average**. Pinnacle closing is
  an **accuracy reference only**.
* **Book:** Soccer Bet (Serbia); a manual Soccer Bet vs market-average price log
  comes later.
* **Scope:** same-game combos from one grid are **in**; multi-match accas later
  (max 2–3 legs); HT/FT back in scope via a half-time model.
* **Standing diagnostics:** the 1X2 "model adds no information beyond the market"
  verdict, and the encompassing test, now apply to every future model.
* **No clean discovery validation remains** — 2021-22 and 2022-23 were consumed
  by the COVID selection. Confirmation is the only clean test, and every rule
  must be pre-registered in the ledger before it is touched.

### Newcomer counts (corrected)

Every season has 7 newcomers (3 `relegated_in`, 4 `promoted_in`) **except
2019-20, which had 6** — **Bury were expelled** in August 2019, so the division
ran with 23 teams.

The `n` behind each prior grows because an arrival counts only once it is **past
its first year** (>365 days before the cutoff):

| Target | cohorts old enough | promoted_in n | relegated_in n |
|---|---|---|---|
| 2019-2020 | 2017-18 | 4 | 3 |
| 2020-2021 | + 2018-19, 2019-20 | 11 | 9 |
| 2021-2022 | (same three) | 11 | 9 |
| 2022-2023 | + 2020-21 | 15 | 12 |

Full team lists: `reports/figures/newcomer_prior_detail.csv`.

## 1. Totals stress test

### Per-season correlation with the actual over outcome

| Season | corr(market P(over)) | corr(model P(over)) | mkt E[total] | model E[total] | actual E[total] |
|---|---|---|---|---|---|
| 2017-2018 | +0.0313 | −0.0634 | 2.758 | 2.576 | 2.538 |
| 2018-2019 | −0.0403 | −0.0504 | 2.741 | 2.548 | 2.649 |
| 2019-2020 | −0.1424 | +0.0984 | 2.711 | 2.595 | 2.604 |
| 2020-2021 | −0.1088 | +0.1409 | 2.757 | 2.559 | 2.621 |
| 2021-2022 | −0.0951 | +0.0358 | 2.734 | 2.642 | 2.697 |
| 2022-2023 | −0.0228 | −0.0741 | 2.734 | 2.645 | 2.562 |

Both are near zero. The market's correlation is **negative in four of six
seasons** — a hint of the over-reaction flavour. *(The market E[total] column is
a Poisson-implied value from P(over 2.5), so it is not directly comparable to
the actual mean; treat it as indicative only.)*

### Decomposition — credit the model only for M2 − M1

| Target | M0 market | M1 recalibration | M2 recal + model | M1 − M0 | M2 − M1 |
|---|---|---|---|---|---|
| 2018-2019 | 0.6995 | 0.6983 | 0.6932 | −0.0012 | −0.0052 |
| 2019-2020 | 0.7113 | 0.6922 | 0.6940 | −0.0190 | +0.0018 |
| 2020-2021 | 0.7082 | 0.6888 | 0.6981 | −0.0194 | +0.0093 |
| 2021-2022 | 0.7032 | 0.6895 | 0.6897 | −0.0137 | +0.0001 |
| 2022-2023 | 0.7002 | 0.6926 | 0.6907 | −0.0075 | −0.0019 |

Pooled: M0 0.7041, M1 0.6923, M2 0.6931.

* **M1 − M0 = −0.0118, 95% CI [−0.0171, −0.0066]** → **significant**. The
  market's O/U probabilities are miscalibrated and a plain logistic
  recalibration improves them.
* **M2 − M1 = +0.0008, 95% CI [−0.0013, +0.0029]** → **not significant**. The
  model adds **nothing** beyond recalibration.

**De-margin sensitivity** (rules out an artifact): proportional −0.0118
[−0.0171, −0.0066]; power −0.0132 [−0.0188, −0.0077]. Both agree. (Raw `1/odds`
is not a probability and is shown only to demonstrate that.)

### Over-reaction probe (M1 + last-5 / last-10 total goals)

| Target | b_mkt | b_h5 | b_h10 | b_a5 | b_a10 | probe − M1 |
|---|---|---|---|---|---|---|
| 2018-2019 | +0.277 | −0.063 | +0.052 | +0.027 | −0.144 | −0.0019 |
| 2019-2020 | −0.350 | −0.156 | +0.003 | +0.017 | −0.199 | +0.0035 |
| 2020-2021 | −0.642 | −0.167 | +0.028 | +0.097 | −0.127 | +0.0048 |
| 2021-2022 | −0.794 | −0.096 | +0.034 | +0.023 | −0.050 | −0.0030 |
| 2022-2023 | −0.926 | −0.161 | +0.056 | +0.027 | −0.043 | −0.0003 |

**Pooled probe − M1 = +0.0005, 95% CI [−0.0015, +0.0025]** → not significant.

Coefficient stability: `b_h5` −0.129 (negative in all 5 seasons), `b_h10` +0.035,
`b_a5` +0.038, `b_a10` −0.113 (all sign-consistent) — but the magnitudes are
tiny and the net effect is nil. `b_mkt` is unstable (signs +,−,−,−,−).

### Verdict

> **A stable O/U market bias exists, but it is RECALIBRATION ONLY.** It is
> **not** tied to recent scoring, and the model adds nothing. The external
> review's hypothesis is decomposed and **not supported**: the blend's apparent
> gain was the market's own miscalibration, not model information.

## 2. Pattern layer

| Base | base log loss | + features | diff | 95% CI | improves? |
|---|---|---|---|---|---|
| model P(over), w=10 | 0.6954 | 0.7001 | **+0.0046** | [+0.0015, +0.0079] | No |
| market P(over), w=10 | 0.6924 | 0.6972 | **+0.0047** | [+0.0016, +0.0080] | No |
| model P(over), w=20 | 0.6954 | 0.7007 | +0.0053 | [+0.0020, +0.0088] | No |
| market P(over), w=20 | 0.6924 | 0.6997 | +0.0073 | [+0.0035, +0.0113] | No |

A **positive** diff means worse. The layer **degrades both bases** at both
windows. **Verdict: the pattern layer adds no information.**

### Descriptive rule tables (window 10)

| Rule | n | observed hit | 95% CI | mean model p | mean market p | mean odds | break-even | clears? |
|---|---|---|---|---|---|---|---|---|
| both bottom third → UNDER 2.5 | 531 | 0.4878 | [0.4455, 0.5302] | 0.5652 | 0.4665 | 1.777 | 0.5627 | **No** |
| both top third → OVER 2.5 | 620 | 0.4661 | [0.4272, 0.5055] | 0.5135 | 0.4991 | 1.895 | 0.5277 | **No** |

Neither side clears break-even. Note the model is **badly over-confident** on the
bottom-third profile (0.5652 predicted vs 0.4878 observed), while the market is
close (0.4665).

## 3. Combo menu + calibration

22 markets written to `data/predictions/league_one/<config_id>_markets.parquet`.
Ranked by ECE (best first) — full table in `reports/figures/combo_calibration.csv`:

| Market | base | mean p | log loss | naive | gain | slope | ECE |
|---|---|---|---|---|---|---|---|
| Away & Under 3.5 | 0.231 | 0.230 | 0.5234 | 0.5401 | **+0.0167** | 0.923 | **0.0101** |
| DC 12 | 0.739 | 0.739 | 0.5747 | 0.5742 | −0.0006 | 0.402 | 0.0122 |
| 1X2 draw | 0.261 | 0.261 | 0.5747 | 0.5742 | −0.0006 | 0.402 | 0.0122 |
| DC 1X | 0.692 | 0.689 | 0.5857 | 0.6179 | +0.0322 | 0.955 | 0.0128 |
| 1X2 away | 0.309 | 0.311 | 0.5857 | 0.6179 | +0.0322 | 0.955 | 0.0128 |
| Home & Under 3.5 | 0.310 | 0.301 | 0.6087 | 0.6187 | +0.0100 | 0.798 | 0.0147 |
| 1X2 home | 0.430 | 0.428 | 0.6573 | 0.6834 | +0.0261 | 0.823 | 0.0254 |
| … | | | | | | | |
| BTTS yes / no | 0.511 | 0.502 | 0.7024 | 0.6929 | −0.0095 | **0.001** | 0.0518 |
| Over 2.5 & BTTS yes | 0.390 | 0.381 | 0.6808 | 0.6685 | −0.0123 | −0.011 | 0.0556 |
| **Under 2.5 / Over 2.5** | 0.515 | 0.523 | 0.7061 | 0.6927 | **−0.0134** | **0.057** | **0.0648** |

**Reading:** the 1X2 and double-chance markets are genuinely calibrated
(slope 0.82–0.96, ECE 0.012–0.025) and beat naive. The **totals and BTTS markets
are nearly flat** (slope ≈ 0.001–0.16) and **worse than naive** — the model has
almost no discriminative power there. Over-confident high-probability bins
(mean predicted ≥ 0.6) are concentrated exactly in those markets, e.g. Over 2.5
bin 0.6–0.7: predicted 0.630, observed 0.482; Under 2.5 bin 0.7–0.8: predicted
0.738, observed 0.467.

## 4. Payout check (1X2 + O/U 2.5, market-average pre-match odds)

Descriptive only — no staking, no ROI optimisation, no rule tuning.

**TOTAL BINS INSPECTED: 64** (5 selections × 2 binning schemes × up to 10 bins).
That is the multiple-testing count.

**Bins whose hit-rate 95% CI sits above break-even: 0.**

Every selection, binned by model probability *and* by market probability, sits
just short of break-even. The closest is 1X2 home binned by model at 0.6–0.7:
hit 0.5992 [0.5389, 0.6567] vs break-even 0.6270. Full tables:
`reports/figures/payout_check.csv`; all five logged to the ledger.

## 5. Self-audit

Fresh process, recomputed from artifacts: **20 previous claims + 17 new claims,
0 mismatches, 0 claims without an artifact.** Cache-clear reproducibility still
bit-identical (max abs difference 0.000e+00).

## 6. Failures and what I tried

1. **Smart App Control blocked pandas/pyarrow/penaltyblog** at the start of the
   session (machine-level, also blocking Chrome DLLs). Resolved by the user
   turning SAC off; verified no CodeIntegrity block touches the venv.
2. **`newcomer_prior_detail.py` crashed on a blocked DLL** before SAC was off —
   re-run cleanly afterwards.
3. **Pattern-layer rule tables had an index-alignment bug** (feature arrays were
   restricted to the priced rows, outcomes were not) — fixed.
4. **The pattern-layer verdict print was inverted** (it treated a positive diff
   as "adds information") — fixed to require a negative diff with the CI
   excluding 0.
5. **The raw-`1/odds` sensitivity row was misleading** (it is not a probability,
   so its M0 is meaningless) — relabelled and explained.
6. **The market E[total] column is Poisson-implied**, not a direct market mean —
   flagged as indicative only.

## 7. Commits

See the final summary.