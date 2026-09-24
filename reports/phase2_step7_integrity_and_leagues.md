# Phase 2e — totals integrity and cross-league transfer

**Zero API calls.** football-data.co.uk downloads: **F1 (Ligue 1) 2014-15…2022-23
only** (9 files, auxiliary, for Ligue 2 newcomer labels). Confirmation seasons
(2023-24+) were **never touched** in any league.

## 1. Totals integrity — BUG FOUND AND FIXED

### The bug

`core/odds.py` defines `OUT_OU = ("over", "under")`, so `ou.odds` columns are
`("over", "under")`. Four consumers indexed `.to_numpy()[:, 1]` — which is
**UNDER** — and used it as **P(over)**:

| File | Line | Effect |
|---|---|---|
| `totals_stress_test.py` | 108–109 | M0/M1/M2 and the probe used inverted market P(over) |
| `pattern_layer.py` | 189 | both layer bases and the rule tables |
| `encompass_league_one.py` | 180 | the O/U blend test |
| `self_audit.py` | 128/177 | replicated the same inversion |

`benchmark_league_one.py`, `diagnose_ou.py` and `step4_payout_check.py` indexed
**by name** and were always correct.

### Evidence

| Check | Buggy | Correct |
|---|---|---|
| mean de-margined P(over) | 0.5154 | **0.4846** (observed over rate 0.4850) |
| corr(market P(over), over) | −0.0591 | **+0.0591** |
| pooled market M0 log loss | 0.7029 | **0.6897** (constant 0.6931) |

**1a** — raw football-data CSV vs pipeline, 30 random matches: **552/552 matched,
0 value mismatches** across `BbAv>2.5`, `BbAv<2.5`, `BbMx>2.5`, `BbMx<2.5`.
(E2 raw CSVs were not downloadable this session; E1 uses identical headers.)

**1b** — column map, correct end to end:

| era | raw header | parquet | core/odds.py | table |
|---|---|---|---|---|
| BbAv | `BbAv>2.5` | `bb_av>2.5` | `over` | P(over) |
| BbAv | `BbAv<2.5` | `bb_av<2.5` | `under` | P(under) |
| Avg | `Avg>2.5` | `avg>2.5` | `over` | P(over) |
| Avg | `Avg<2.5` | `avg<2.5` | `under` | P(under) |
| Avg | `AvgC>2.5` | `avg_c>2.5` | `over` (closing) | P(over) |

penaltyblog's `sanitize_columns` is a **pure rename** (`df.columns = [to_snake_case(x) …]`)
— no reordering, no value change. So ingestion and `core/odds.py` were right;
only the consumers were wrong.

**1c** — per season (corrected):

| season | n | base | const | market P(over) | corr(mkt) | corr(model) | M1 slope |
|---|---|---|---|---|---|---|---|
| 2017-2018 | 552 | 0.473 | 0.6931 | 0.6985 | −0.0313 | −0.0634 | 0.292 |
| 2018-2019 | 552 | 0.516 | 0.6931 | 0.6948 | +0.0403 | −0.0504 | 0.292 |
| 2019-2020 | 399 | 0.492 | 0.6931 | 0.6841 | +0.1424 | +0.0984 | 1.369 |
| 2020-2021 | 552 | 0.471 | 0.6931 | 0.6861 | +0.1088 | +0.1409 | 1.369 |
| 2021-2022 | 552 | 0.491 | 0.6931 | 0.6888 | +0.0951 | +0.0358 | 1.363 |
| 2022-2023 | 552 | 0.469 | 0.6931 | 0.6931 | +0.0228 | −0.0741 | 0.292 |

M1 slopes are **positive** everywhere (a negative slope would mean an inverted
input). Pooled: constant 0.6931, market 0.6897, corr **+0.0591**.

**1d** — the 0.4665 figure: the script set `p_mkt = demargin(...)[:, 1]`
(= P(under)) and then took `1 − p_mkt`, which is P(over). So **P(OVER) was
printed in the P(under) column**. Corrected value: **0.5335**. Cross-check: mean
under odds 1.8424 → break-even 0.5428, consistent with P(under) ≈ 0.5154, not
0.4665.

### 1e — old vs new (totals-dependent results only)

| Metric | Old (buggy) | New (fixed) |
|---|---|---|
| pooled market M0 | 0.7029 | **0.6897** |
| **M1 − M0** | **−0.0118 [−0.0171, −0.0066]** | **+0.0026 [−0.0003, +0.0055]** |
| M2 − M1 | +0.0008 [−0.0013, +0.0029] | +0.0008 [−0.0013, +0.0029] |
| probe − M1 | +0.0005 [−0.0015, +0.0025] | +0.0005 [−0.0015, +0.0025] |
| rule bottom-third market P(under) | 0.4665 | **0.5335** |
| pattern `layer_market_diff` | +0.0047 [+0.0016, +0.0080] | +0.0044 [+0.0009, +0.0081] |
| O/U blend − market | **−0.0110 [−0.0165, −0.0055]** | **+0.0034 [−0.0001, +0.0068]** |
| corr(mkt P(over), over) | negative in 4/6 seasons | positive in 5/6 |

**Verdict: the previous session's "stable O/U market bias, recalibration only"
finding is VOID — it was entirely an artifact of the inversion.** Corrected
reading: **there is no stable O/U market bias.** The market is well calibrated
(pooled M0 0.6897 beats the 0.6931 constant), recalibration does not help
(M1 − M0 positive, CI includes 0), and the model adds nothing (M2 − M1 not
significant). The pattern layer still degrades both bases, and neither rule
table clears break-even.

**Tripwire note:** the market is nominally worse than a constant in 2017-18
(+0.0053) and 2018-19 (+0.0016), but **both bootstrap CIs include 0**
([−0.0030, +0.0135] and [−0.0064, +0.0102]) — within noise. Pooled, the market
beats the constant.

**Regression test:** `tests/test_ou_alignment.py` (5 tests) pins the alignment,
including a pooled positive-correlation assertion and a "market beats a
constant" assertion that both fail under the bug.

## 2. Price-cost table (League One, descriptive)

Mean margin (`sum(1/odds) − 1`) per season:

| season | market avg 1X2 | market avg O/U | B365 1X2 | B365 O/U | Pinnacle 1X2 | Pinnacle O/U |
|---|---|---|---|---|---|---|
| 2017-2018 | 0.0671 | 0.0629 | 0.0287 | – | 0.0272 | – |
| 2018-2019 | 0.0632 | 0.0604 | 0.0284 | – | 0.0430 | – |
| 2019-2020 | 0.0640 | 0.0587 | 0.0371 | 0.0588 | 0.0383 | 0.0467 |
| 2020-2021 | 0.0647 | 0.0582 | 0.0528 | 0.0576 | 0.0350 | 0.0379 |
| 2021-2022 | 0.0628 | 0.0584 | 0.0536 | 0.0508 | 0.0422 | 0.0418 |
| 2022-2023 | 0.0640 | 0.0617 | 0.0538 | 0.0488 | 0.0363 | 0.0369 |

Coverage: market avg 3,159/3,160; B365 1X2 3,156 / O/U 2,054; Pinnacle 1X2
3,149 / O/U 2,045 (B365 and Pinnacle O/U do not exist before 2019-20).

⚠️ **B365's 1X2 margin roughly doubles from 2019-20** (0.028 → 0.054). Pre-2019
the `b365_*` columns behave like best-odds rather than a single book — worth
knowing before treating them as a book price.

**Payout check at Pinnacle pre-match prices ("low-margin book sensitivity"):**

| price source | bins clearing break-even |
|---|---|
| market average | 0 |
| B365 | 0 |
| Pinnacle pre-match | 0 |

**102 bins inspected** (3 sources × 5 selections × up to 10 bins). **No bin
clears break-even at any price source** — a sharper book does not turn any of
these selections into a bet.

## 3. Cross-league transfer (config fixed, not re-tuned)

Config transferred unchanged: `xi=0.002`, `covid_mode=exclude_after`,
`newcomer=newcomer_prior`. Ledger note "TRANSFERRED CONFIG" appended.

**Newcomer labels** (from auxiliary divisions): F2 ← F1, D2 ← D1, D1 ← D2.
A team counts as `relegated_in`/`promoted_in` only if it was in the adjacent
division in the **immediately preceding** season. Requiring the immediately
prior season matters: using "any earlier season" mislabelled **Bastia** and
**Ingolstadt** (2021-22) as `relegated_in` when both actually arrived from the
third tier. No third-tier data exists for France/Germany, so remaining
newcomers are `promoted_or_other` (flagged, not guessed).

Spot checks (2 seasons per league, all PASS):

| league | season | relegated_in | promoted_in / promoted_or_other |
|---|---|---|---|
| ligue_2_t2 | 2021-2022 | Dijon, Nimes | Bastia, Quevilly Rouen |
| ligue_2_t2 | 2022-2023 | Bordeaux, Metz, St Etienne | Annecy, Laval |
| bundesliga_2 | 2021-2022 | Schalke 04, Werder Bremen | Dresden, Hansa Rostock, Ingolstadt |
| bundesliga_2 | 2022-2023 | Bielefeld, Greuther Furth | Braunschweig, Kaiserslautern, Magdeburg |
| bundesliga_1 | 2021-2022 | – | Bochum, Greuther Furth |
| bundesliga_1 | 2022-2023 | – | Schalke 04, Werder Bremen |

**COVID:** Ligue 2 2019-20 was curtailed (280 rows vs 380); the German leagues
finished 2019-20 behind closed doors and played 2020-21 largely without crowds.
`covid_mode=exclude_after` drops 2020-21 from training for later targets in all
three leagues.

### (a) 1X2 — model vs naive vs market vs Pinnacle close

| league | model | naive | market pre | PSC close | model − market | 95% CI |
|---|---|---|---|---|---|---|
| ligue_2_t2 | 1.0453 | 1.0707 | 1.0444 | 1.0386 | **+0.0187** | [+0.0121, +0.0261] |
| bundesliga_2 | 1.0556 | 1.0813 | 1.0518 | 1.0474 | **+0.0177** | [+0.0100, +0.0255] |
| bundesliga_1 | 1.0022 | 1.0620 | 0.9840 | 0.9831 | **+0.0182** | [+0.0110, +0.0256] |

**In every league the model beats naive but loses to the market**, with the CI
excluding 0. Identical to League One.

### (b) 1X2 blend (diagnostic)

| league | per-season b | blend − market | 95% CI |
|---|---|---|---|
| ligue_2_t2 | −0.14, +0.28, +0.11, +0.01, −0.03 | +0.0009 | [−0.0015, +0.0033] |
| bundesliga_2 | −0.62, −0.03, −0.05, −0.01, −0.10 | +0.0038 | [−0.0004, +0.0083] |
| bundesliga_1 | −0.42, −0.39, −0.45, −0.50, −0.29 | +0.0004 | [−0.0034, +0.0043] |

`b` is near zero or negative everywhere and **no blend beats the market** (all
CIs include 0, point estimates positive = worse).

### (c) Totals

| league | pooled M0 | M0 vs constant | M1 − M0 | M2 − M1 | tripwire |
|---|---|---|---|---|---|
| ligue_2_t2 | 0.6702 | beats constant every season | +0.0011 [−0.0013, +0.0035] | +0.0007 [−0.0013, +0.0027] | none |
| bundesliga_2 | 0.6782 | beats constant every season | −0.0006 [−0.0030, +0.0018] | +0.0008 [−0.0014, +0.0030] | none |
| bundesliga_1 | 0.6546 | beats constant every season | +0.0013 [−0.0013, +0.0041] | **+0.0107 [+0.0027, +0.0191]** | none |

**No tripwire hits** — the de-margined market beats a constant in every season
in all three leagues. Recalibration never helps. In bundesliga_1 the model
significantly *hurts* (+0.0107).

### (d) Combo calibration (ranked by log-loss gain vs naive, then slope)

Markets with gain > 0 and slope > 0.3: **ligue_2_t2 10, bundesliga_2 7,
bundesliga_1 16** (of 22). Top markets are consistently 1X2 / double chance and
`Home & Over 1.5`; the bottom is consistently BTTS and totals — the same pattern
as League One.

### (e) Payout check

| league | bins inspected | clearing at market avg | clearing at Pinnacle |
|---|---|---|---|
| ligue_2_t2 | 84 | 0 | 0 |
| bundesliga_2 | 74 | 1 | 0 |
| bundesliga_1 | 90 | 1 | 2 |

## 4. Cross-league table

| league | model − market | 95% CI | model − PSC | M0 | M1 − M0 | M2 − M1 | tripwire | calibrated markets | bins | clearing (mkt avg) |
|---|---|---|---|---|---|---|---|---|---|---|
| ligue_2_t2 | +0.0187 | [+0.0121, +0.0261] | +0.0238 | 0.6702 | +0.0011 | +0.0007 | none | 10 | 84 | 0 |
| bundesliga_2 | +0.0177 | [+0.0100, +0.0255] | +0.0192 | 0.6782 | −0.0006 | +0.0008 | none | 7 | 74 | 1 |
| bundesliga_1 | +0.0182 | [+0.0110, +0.0256] | +0.0191 | 0.6546 | +0.0013 | +0.0107 | none | 16 | 90 | 1 |

**Which markets are calibrated where:** 1X2 and double chance are calibrated in
all four leagues (including League One); totals and BTTS are not, in any league.

## 5. Candidate list

Pre-registered rule: a league × market becomes a CONFIRMATION CANDIDATE only if
(i) model or blend beats market pre-match with the CI excluding 0, **or**
(ii) payout bins clear break-even at **market-average** prices with CI.

- **(i) fails everywhere.** No league's model or blend beats the market; all
  model − market CIs are positive and exclude 0.
- **(ii)** nominally qualifies **bundesliga_2 (1 of 74 bins)** and
  **bundesliga_1 (1 of 90 bins)**.

> **Candidates: bundesliga_2 and bundesliga_1, on the payout-bins clause only.**
> **Multiple-testing count: 74 and 90 bins inspected.** One bin clearing
> break-even out of 74–90 is **entirely consistent with chance**, so these are
> weak candidates at best and should be treated as such. **No candidate in
> ligue_2_t2, and none in League One.**

Confirmation seasons were **not** touched.

## 6. Self-audit

Fresh process, recomputed from artifacts: **52 claims (20 + 17 + 15), 0
mismatches, 0 claims without an artifact.** Full pytest: **49 passed**.

## 7. Failures and what I tried

1. **The O/U inversion bug** (the main finding) — found by grepping for
   positional indexing on the O/U market, confirmed by correlation sign and by
   the market-vs-constant comparison, fixed in four files, pinned by 5 tests.
2. **`totals_integrity.py` 1a matched 0 rows** — the raw 2017-18 file uses
   2-digit years, so `%d/%m/%Y` gave NaT; added the `%d/%m/%y` fallback the
   ingest already used. Also `itertuples` mangles column names containing `>`
   and `.`, so I switched to name-based `.iloc` access.
3. **The multi-league blend fit overflowed** (`b → 1e255`, `nan`) because I used
   a 3-parameter logistic; replaced with the 2-parameter power blend.
4. **Newcomer labels were wrong for returning teams** — Bastia and Ingolstadt
   (2021-22) were labelled `relegated_in` though both came up from the third
   tier. Fixed by requiring the **immediately preceding** season.
5. **`self_audit.py` failed twice** — first on the stale O/U blend claim, then
   on the stale `M1 − M0`; both updated to the corrected values.

## 8. Commits

See the final summary.