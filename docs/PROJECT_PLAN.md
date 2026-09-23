# Project Plan

> Single source of truth for the project objective, principles, and gates.
> Changes to gates must be recorded in the decision log.

## Objective

Find bets with **reliably positive expected value (EV)** against prices we can
actually get, **only** in buckets (league × market × selection [× odds band])
proven on data the model has never seen, and concentrate modelling effort on
those buckets.

- `EV = p_model × odds − 1`
- **"Most likely outcome" is NOT the target.**
- This is **not arbitrage.**

### Success

- Positive **closing-line value (CLV)** monthly.
- Drawdowns within pre-set limits.
- Profit at quarterly / yearly level.

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
| **SHARP benchmark** | Pinnacle closing (`PSCH/PSCD/PSCA`) | 2015-16 … 2024-25 |
| **SHARP benchmark** | market-average closing (`AvgCH/CD/CA`) | 2025-26 onward (Pinnacle degrades to 0% in 2026-27) |
| **BET PRICE proxy** | B365 pre-match (`B365H/D/A`) | all seasons |

The bet price is a *proxy* until the user names a real book. Because the sharp
source changes over time, **`AvgC*` must always be reported alongside `PSC*`** so
a mid-sample switch can never be mistaken for a change in achievable edge.

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
