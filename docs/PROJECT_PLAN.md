# Project Plan

> Single source of truth for the project objective, principles, and gates.
> Changes to gates must be recorded in the decision log.

## Objective

Find outcomes — **singles and same-game combos** — that layered statistical
models rate likely **AND** whose probabilities are **proven calibrated on unseen
seasons**; bet only where the typical payout exceeds break-even
(`p × odds > 1`).

- **Not price-hunting.** Bookmaker choice is **not** a selection criterion.
- **Systematic, market-wide statistical biases** (e.g. over-reaction) **are in
  scope.**
- **"Most likely outcome" alone is NOT the target** — a likely outcome that does
  not pay enough is not a bet.
- This is **not arbitrage.**

### Success

- Probabilities that are **calibrated** on seasons the model has never seen.
- Payouts that clear break-even at the prices actually available.
- Positive **closing-line value (CLV)** monthly; drawdowns within pre-set limits.

A real 3% edge still has roughly **1 losing month in 3** — that is expected,
not failure.

## Principles

1. **Odds are never used to TRAIN models; historical odds ARE used to TEST.**
2. The benchmark is the **de-margined closing price**, not naive base rates.
3. Every evaluation is logged in `research/ledger.csv`, **including failures**.
4. **Confirmation seasons are locked:** one shot per pre-registered candidate
   rule. Once used, they are no longer fresh.
5. Backtest bets use **one realistic bookmaker's pre-closing price**, never
   best-of-market. Default proxy until the user names a book: **B365**, and
   market **Avg**.
6. **Decide on CLV; report P&L.**
7. **Pinnacle odds on football-data.co.uk are unreliable from 2025-07-23**; use
   market-average closing odds from 2025-26 onwards.

## Layers

1. **Data**
2. **Team-strength model** (Dixon-Coles, per league)
3. **Scoreline grid** → all markets: 1X2, O/U lines, BTTS, AH, correct score.
   (Separate half-time model later, for HT/FT.)
4. **Calibration** vs results
5. **Benchmark** vs closing market
6. *Optional* model/market blend
7. **Decision rule**: min EV, fractional Kelly, exposure caps
8. **Live monitoring**: CLV, drift, auto-suspend

## Bucket stages

```
CANDIDATE --> BACKTEST_PASSED --> PAPER --> LIVE_SMALL --> LIVE_FULL
     \______________ any stage ______________/  -->  SUSPENDED
```

Initial gates (revisable — record changes in the decision log):

| Transition | Gate |
|---|---|
| CANDIDATE → BACKTEST_PASSED | Written rule **before** testing; on discovery: ≥300 simulated bets, positive CLV vs close **and** positive ROI at realistic prices; then the **same** rule positive on confirmation. |
| BACKTEST_PASSED → PAPER | Automatic. |
| PAPER → LIVE_SMALL | ≥200 paper bets, mean CLV > 0 with the 95% interval above 0. |
| → SUSPENDED | Rolling 150-bet mean CLV < 0, or drawdown beyond the pre-set limit. |

## Splits

| Split | Seasons |
|---|---|
| Warmup | 2015-16, 2016-17 |
| Discovery | 2017-18 .. 2022-23 |
| Confirmation (**LOCKED**) | 2023-24 .. 2025-26 |
| Live | 2026-27+ |

## Market testability

| Market | Status |
|---|---|
| 1X2, O/U 2.5, AH | **Testable now** — historical odds exist. |
| BTTS, other goal lines, correct score, HT/FT, half-time markets | Modellable now, **testable only after we record odds going forward** (odds recorder, Phase 1.5). |

## Roadmap

1. **Data** — done.
2. **1.5 Odds recorder** — forward snapshots.
3. **2 Models** per league; `xi` tuned walk-forward on **discovery only**.
4. **3 Market derivation**, incl. half-time model.
5. **4 Discovery engine** — walk-forward predictions, calibration + market
   benchmark per bucket, ledger, gates.
6. **5 Decision layer.**
7. **6 Paper → live**, CLV monitoring.

## Open decisions

- Target bookmaker / exchange.
- Bankroll and drawdown limit.
- Promoted / relegated-team rating rule.

## Resolved

- **Ajaccio vs Ajaccio GFCO are different clubs — never merge.**

## Decision log

### Benchmark roles (decided 2026-09-23)

| Role | Source | Availability |
|---|---|---|
| **Accuracy reference** | Pinnacle closing (`PSCH/PSCD/PSCA`) | 2015-16 … 2024-25 |
| **Accuracy reference** | market-average closing (`AvgCH/CD/CA`) | 2025-26 onward |
| **Payout check only** | **market-average pre-match odds** | all seasons |

> **REVERSED (2026-09-24).** The earlier "BET PRICE proxy = B365" entry is
> withdrawn. Prices are used **only** for the payout check, and the payout check
> uses the **market average**. Pinnacle closing is an **accuracy reference
> only** — it is never treated as a price we could take. Because the sharp
> source changes over time, `AvgC*` is always reported alongside `PSC*`.

### Book

**Soccer Bet (Serbia)** is the user's book; online books are possible. The book
is **not** a selection criterion. Later, a **manual log of Soccer Bet prices vs
market-average prices** will be kept for flagged plays.

### Tuning design rule (decided 2026-09-23)

> **A tuned option must be able to affect the tune seasons.**

If an option cannot influence a season, that season cannot judge it. Such an
option may still be chosen, but only on a *stated theory*, and the choice must be
flagged **"post-hoc, discovery-only"** and re-verified on confirmation.

### Findings and corrections (external review, 2026-09-23)

1. **Newcomer blend was inert.** All of the `league_avg` vs `newcomer_prior`
difference sat in the 39 `n = 0` matches; there was **zero** effect for `n = 1..9`.
2. **`promoted_in` / `relegated_in` cannot be derived from League One data**
   alone, and the derived priors looked **inverted**. Requires auxiliary
   divisions (E1/E3).
3. **The COVID option was mis-designed.** "drop" removed 2020-21 *in-season*
data when predicting 2020-21 itself, and could not affect 2017-18 or 2018-19, so
   the tune seasons could not judge it.
4. **O/U 2.5 was under-predicted by ~10pp** in the middle reliability bins.
5. **The closing benchmark mixed sources** (`PSC` pre-2019, `AvgC` 2019+), which
   confounds the sharp reference across the sample.
6. **No confidence intervals** were reported anywhere.
7. **The pure-Python grid differed from `penaltyblog` `predict` by ~1.1e-3.**

> **Void:** the Stage A COVID selection from the previous session is **void** —
the option could not affect the tune seasons. It is superseded by the
`covid_mode` design in Step 4.

### Auxiliary divisions

**E1 (Championship)** and **E3 (League Two)** are ingested as *auxiliary* data
purely to label League One newcomers. They are **never in scope for betting**.

### Scope changes (2026-09-24)

* **Same-game combos from one scoreline grid are IN scope** (1X2, double chance,
  O/U 1.5/2.5/3.5, BTTS, and combinations of them).
* **Multi-match accumulators are later**, capped at **2–3 legs**.
* **HT/FT is back in scope**, via a separate half-time model (later).

### Standing diagnostics and verdicts

* **1X2 verdict: the model adds no information beyond the market.** The
  encompassing test (blend vs market pre-match) is now a **standing diagnostic**
  that every future model must pass, not a one-off.
* **No clean discovery validation remains.** 2021-22 and 2022-23 were consumed by
  the COVID-mode selection, so they are no longer fresh. **Confirmation
  (2023-24 … 2025-26) is the only clean test**, and **every rule must be
  pre-registered in the ledger before confirmation is touched**.

### Newcomer counts (corrected)

Every season has 7 newcomers (3 `relegated_in`, 4 `promoted_in`) **except
2019-20, which had 6** — **Bury were expelled** from League One in August 2019,
so the division ran with 23 teams.

The `n` behind each prior grows because the rule admits an arrival only once it
is **past its first year** (>365 days before the cutoff):

| Target | arrival cohorts old enough | promoted_in n | relegated_in n |
|---|---|---|---|
| 2019-2020 | 2017-18 | 4 | 3 |
| 2020-2021 | + 2018-19, 2019-20 | 11 | 9 |
| 2021-2022 | (same three) | 11 | 9 |
| 2022-2023 | + 2020-21 | 15 | 12 |

Full team lists: `reports/figures/newcomer_prior_detail.csv`
(`newcomer_prior_detail.py`). A team can appear more than once if it arrived in
more than one season (e.g. Rotherham 2017-18 and 2019-20).
