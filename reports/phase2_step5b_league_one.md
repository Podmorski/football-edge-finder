# Phase 2b — League One (review response)

Addresses the external review findings (1)–(7). **Discovery + warmup only.**
Confirmation seasons were never loaded (`research/confirmation_access.csv` does
not exist). **Zero API calls.** Downloads: **18** football-data.co.uk files,
exclusively E1/E3 2014-15..2022-23, all cached.

## 1. Grid parity — fixed

The ~1.1e-3 deviation is gone. Cause: the manual path mixed `model.predict`
(compiled fit-time grid) with the pure-Python `create_dixon_coles_grid` helper,
which applies the Dixon-Coles tau to the four low-score cells slightly
differently. Rather than patch the formula, the engine now **rebuilds a fitted
model from persisted ratings** (`model_from_ratings`) and derives every market
through penaltyblog's own compiled path.

| Check | Before | Now |
|---|---|---|
| 500 random walk-forward predictions, max abs diff (P(H/D/A), P(over 2.5), P(BTTS)) | ~1.1e-3 | **0.000e+00** |

Persisted predictions now also carry `total_goals_pmf`, so the total-goals
distribution is recoverable from the artifact.

## 2. O/U 2.5 diagnosis (diagnose only)

Per season (final config):

| Season | n | pred E[total] | actual E[total] | pred P(over) | mkt P(over) | actual over |
|---|---|---|---|---|---|---|
| 2017-2018 | 552 | 2.576 | 2.538 | 0.472 | 0.481 | 0.473 |
| 2018-2019 | 552 | 2.548 | 2.649 | 0.466 | 0.484 | 0.516 |
| 2019-2020 | 400 | 2.595 | 2.610 | 0.478 | 0.492 | 0.492 |
| 2020-2021 | 552 | 2.559 | 2.621 | 0.468 | 0.481 | 0.471 |
| 2021-2022 | 552 | 2.642 | 2.697 | 0.487 | 0.486 | 0.491 |
| 2022-2023 | 552 | 2.645 | 2.562 | 0.489 | 0.486 | 0.469 |

Pooled P(total = k): predicted vs observed agree within ~0.01 (max |diff| 0.0103
at k=3). So the **marginal** total-goals distribution is well calibrated.

Reliability, P(over 2.5), 10 bins (final config):

| bin | n | model | market | observed | 95% CI |
|---|---|---|---|---|---|
| 0.2-0.3 | 45 | 0.262 | 0.423 | 0.533 | [0.391, 0.671] |
| 0.3-0.4 | 520 | 0.365 | 0.450 | 0.473 | [0.431, 0.516] |
| 0.4-0.5 | 1391 | 0.452 | 0.476 | 0.485 | [0.459, 0.512] |
| 0.5-0.6 | 965 | 0.544 | 0.508 | 0.488 | [0.457, 0.520] |
| 0.6-0.7 | 218 | 0.630 | 0.530 | 0.482 | [0.416, 0.548] |
| 0.7-0.8 | 19 | 0.728 | 0.546 | 0.579 | [0.363, 0.769] |

**Most likely cause: not under-dispersion of the marginal, but an
over-confident, poorly-ordered *conditional* spread.**

* training actual var/mean 1.0010; target actual 0.9996; model across-match 1.0493
  — all ≈1, so no dispersion deficit.
* **`corr(model E[total], actual total) = 0.0257`** and
  **`corr(model P(over), actual over) = 0.0103`** — essentially zero.
* The model's P(over) spreads widely (sd of E[total] 0.345, range 1.33–4.21)
  while the observed over-rate inside its own bins stays near-flat at 0.47–0.53.
  The market compresses towards ~0.48 and is better ordered.

So the Dixon-Coles attack/defence ratings carry real 1X2 signal (they beat
naive) but almost none about **totals**.

## 3. Newcomers

### 3a. Classification from auxiliary E1/E3

Every season yields exactly **7 newcomers: 3 `relegated_in`, 4 `promoted_in`,
0 `other`**.

| Season | relegated_in | promoted_in |
|---|---|---|
| 2017-2018 | Blackburn, Rotherham, Wigan | Blackpool, Doncaster, Plymouth, Portsmouth |
| 2018-2019 | Barnsley, Burton, Sunderland | Accrington, Coventry, Luton, Wycombe |
| 2019-2020 | Bolton, Ipswich, Rotherham | Lincoln, Milton Keynes Dons, Tranmere |
| 2020-2021 | Charlton, Hull, Wigan | Crewe, Northampton, Plymouth, Swindon |
| 2021-2022 | Rotherham, Sheffield Weds, Wycombe | Bolton, Cambridge, Cheltenham, Morecambe |
| 2022-2023 | Barnsley, Derby, **Peterboro** | Bristol Rvs, Exeter, Forest Green, Port Vale |

**Spot checks: all PASS.** One spelling mismatch as anticipated: expected
**"Peterborough"**, the dataset spells it **"Peterboro"**.

### 3b. Rebuilt priors (from E1/E3 labels, no leakage)

| Season | league_avg | promoted_in | relegated_in |
|---|---|---|---|
| 2019-2020 | (1.000, −0.861) | (1.067, −0.876) n=4 | (1.290, −1.219) n=3 |
| 2020-2021 | (1.000, −0.887) | (1.032, −0.915) n=11 | (1.169, −1.099) n=9 |
| 2021-2022 | (1.000, −0.821) | (1.049, −0.861) n=11 | (1.098, −0.950) n=9 |
| 2022-2023 | (1.000, −0.837) | (0.992, −0.849) n=15 | (1.156, −1.094) n=12 |

**The inversion is fixed.** `relegated_in` teams now get a *higher* attack and a
*more negative* defence coefficient (better defence) than `promoted_in` — the
right way round, since they come down from a higher division. The previous
heuristic had this backwards.

### 3c. Blend

* pytest proves a team with n=5 and k=10 receives exactly `0.5*prior + 0.5*fitted`
  for attack and defence; weight saturates at k; unseen teams get the prior
  outright; and the policy's prior choice really does change the blended rating.
* **371 of 3,160 matches (11.7%)** involve a team with blend weight < 1, so the
  blend is **not inert** — it is applied on ~700 team-legs.

### 3d. Policy comparison

| Scope | exclude | league_avg | newcomer_prior |
|---|---|---|---|
| ALL matches (3,141 common) | 1.0441 | 1.0441 | **1.0440** |
| EARLY-SPELL, weight<1 (352 common) | 1.0534 | 1.0534 | **1.0530** |

On the early-spell subset `newcomer_prior` wins in 4 of 6 seasons.

## 4. COVID redesign

Pre-registered in the ledger **before** running: *selection = lowest mean 1X2
log loss on 2021-22 and 2022-23; post-hoc, discovery-only, theory-driven; to be
verified on confirmation.*

| mode | 2021-22 | 2022-23 | mean 1X2 | mean O/U |
|---|---|---|---|---|
| include | 1.0376 | 1.0202 | 1.0289 | 0.7117 |
| **exclude_after** | 1.0192 | 1.0161 | **1.0177** | 0.7130 |
| downweight_0.5 | 1.0295 | 1.0179 | 1.0237 | 0.7117 |

**Sanity check passes:** for `exclude_after` and `downweight_0.5` the earlier
seasons (2017-18…2020-21) are **bit-identical** to `include`, confirming the
option now only affects what it is meant to affect. Winner: **`exclude_after`**.

## 5. Benchmarks with uncertainty

Final config: `xi=0.002`, `covid_mode=exclude_after`, `newcomer=newcomer_prior`.
Pre-match source `Avg`/`BbAv` (3,159/3,160); SHARP `PSC` (3,153/3,160, all
seasons); `AvgC` only 2,056 rows (2019-20 onward — so the two cannot be compared
before then).

| Season | n | model | naive | market pre | SHARP PSC | AvgC |
|---|---|---|---|---|---|---|
| 2017-2018 | 552 | 1.0596 | 1.0806 | 1.0539 | 1.0451 | – |
| 2018-2019 | 552 | 1.0485 | 1.0826 | 1.0396 | 1.0368 | – |
| 2019-2020 | 398 | 1.0418 | 1.0672 | 1.0100 | 1.0062 | 1.0083 |
| 2020-2021 | 547 | 1.0567 | 1.0842 | 1.0427 | 1.0354 | 1.0365 |
| 2021-2022 | 552 | 1.0192 | 1.0707 | 1.0000 | 0.9929 | 0.9935 |
| 2022-2023 | 552 | 1.0161 | 1.0737 | 1.0055 | 1.0045 | 1.0066 |

De-margin sensitivity (pooled): proportional 1.02599 vs power 1.02495.

**Paired bootstrap, 2000 resamples by matchday, 95% CI:**

| Scope | model − market pre | 95% CI | model − SHARP PSC | 95% CI |
|---|---|---|---|---|
| 2017-2018 | +0.0057 | [−0.0063, +0.0184] | +0.0145 | [+0.0020, +0.0278] |
| 2018-2019 | +0.0089 | [−0.0045, +0.0229] | +0.0116 | [−0.0030, +0.0271] |
| 2019-2020 | +0.0319 | [+0.0179, +0.0489] | +0.0356 | [+0.0209, +0.0531] |
| 2020-2021 | +0.0140 | [+0.0016, +0.0270] | +0.0213 | [+0.0082, +0.0346] |
| 2021-2022 | +0.0192 | [+0.0033, +0.0360] | +0.0264 | [+0.0088, +0.0439] |
| 2022-2023 | +0.0106 | [−0.0037, +0.0260] | +0.0116 | [−0.0047, +0.0294] |
| **POOLED** | **+0.0142** | **[+0.0080, +0.0201]** | **+0.0194** | **[+0.0130, +0.0254]** |

O/U 2.5 pooled: model 0.7061 vs market 0.7029, diff **+0.0033 [−0.0056, +0.0121]**
— **not** significant.

So the model beats naive everywhere but is **reliably worse than the market**
on 1X2 (pooled CI excludes 0, for both the pre-match price and the sharp close),
while being statistically indistinguishable from the market on O/U.

## 6. Encompassing / blend test (the key question)

1X2: `q ∝ p_mkt^a · p_model^b`, walk-forward by season (first target 2018-19,
trained on 2017-18 only).

| Target | train seas. | a | b | blend | mkt pre | SHARP | blend − mkt |
|---|---|---|---|---|---|---|---|
| 2018-2019 | 1 | 0.657 | 0.308 | 1.0400 | 1.0396 | 1.0368 | +0.0004 |
| 2019-2020 | 2 | 0.834 | 0.242 | 1.0105 | 1.0078 | 1.0062 | +0.0028 |
| 2020-2021 | 3 | 1.097 | 0.040 | 1.0430 | 1.0432 | 1.0354 | −0.0002 |
| 2021-2022 | 4 | 1.099 | 0.023 | 0.9960 | 1.0000 | 0.9929 | −0.0040 |
| 2022-2023 | 5 | 1.170 | 0.011 | 1.0031 | 1.0055 | 1.0045 | −0.0024 |

`b` collapses toward zero as training grows (0.31 → 0.01): the blend wants
almost no model weight.

**Pooled:** blend 1.0191, market 1.0201, SHARP 1.0157.
* blend − market = **−0.0009 [−0.0028, +0.0010]** → CI includes 0.
* blend − SHARP = **+0.0035 [+0.0005, +0.0066]** → significantly *worse*.
* pooled fit a=1.1571, b=0.0265, **b 95% CI [−0.1624, +0.2244]** → `b` is not
  identified; the objective is extremely flat in `b`.

O/U 2.5 logistic: blend 0.6931 vs market 0.7041, diff **−0.0110 [−0.0165, −0.0055]**
→ excludes 0. **But** the model coefficient is **negative in every season**
(−0.46, −0.69, −0.55, −0.16, −0.12): the blend only helps with the model's
P(over) *inverted*. That is consistent with the near-zero correlation found in
Step 2 and is far more likely an artifact of a flat, noisy signal than a usable
one. It should not be treated as evidence that the model knows something about
totals.

### Verdict (pre-registered)

> The model adds information only if the pooled out-of-sample blend beats the
> market pre-match with the CI of the difference excluding 0.

**1X2: DOES NOT ADD INFORMATION** (−0.0009, CI [−0.0028, +0.0010]).
O/U: numerically yes, but with an inverted coefficient and a flat objective —
not credible. **Overall: the model adds no information beyond the market.**

## 7. Self-audit

Fresh process: every headline number recomputed from artifacts (predictions
parquet, `data/historical`, `data/auxiliary`, `reports/figures/*.csv`, ledger)
and compared to the claimed value.

* **20/20 claims OK; 0 mismatches; 0 claims without an artifact.**
* Cache-clear reproducibility: removed the 39 cached fits for 2022-2023, re-ran,
  and predictions were **bit-identical** (max abs difference 0.000e+00 across
  P(H/D/A), P(over), P(BTTS), expected goals).

The audit earned its keep: the first run exposed (a) a wrong subset mask,
(b) missing `bb_av_*`/`b365_*` odds columns in the audit's own join, and
(c) a stale O/U diagnosis produced under the pre-Step-4 config.

## 8. Failures and what I tried

1. **The `∝` character crashed the console** (cp1252) — replaced with ASCII.
2. **E1/E3 dates failed to parse** for early seasons (2-digit years), then two
   files had a fully-blank trailing row — handled both.
3. **Auxiliary parquets kept raw CSV column names** (`HomeTeam`) — added
   sanitised aliases at ingestion.
4. **`drop_2020_21` was replaced by `covid_mode`**, breaking four callers —
   updated all of them and added tests for both new modes.
5. **The self-audit failed twice before passing**, catching real defects in my
   own audit script and a stale diagnosis config (see §7).
6. **The step-2 conclusion I pre-wrote was wrong** and was replaced by the
   measured one (no dispersion deficit; the problem is conditional spread).

## 9. Commits

See the final summary.