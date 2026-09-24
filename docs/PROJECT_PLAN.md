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

### Standing tripwires (2026-09-24)

> **Any hit = STOP and bug-hunt before interpreting anything.**

1. A **de-margined market worse than a constant / base-rate predictor** in any
   season × market.
2. A **model not beating naive in-sample**.
3. A **probability inconsistent with its own odds**:
   `|1/odds − p_demargined| > that row's margin + 0.02`.
4. **Calibration slope < 0**, or **corr(prob, outcome) < 0**, for any market.

### Ranking rule (2026-09-24)

Rank market calibration by **log-loss gain vs naive + calibration slope**.
**ECE is reported but is NOT used for ranking.**

### Margin

> **Margin is the cost of betting.** Low-margin price sensitivity is
> **descriptive, not price-hunting** — it tells us what a sharper book would
> cost, not where to shop.

### Findings and corrections (external review, 2026-09-24)

An internal contradiction was reported in the totals path: the rule table
printed market P(under) = 0.4665 alongside mean under odds 1.777
(break-even 0.5627), and market M0 O/U log loss (0.6995–0.7113) was **worse
than a 50/50 constant (0.6931) in all five seasons** — implausible for a real
de-margined market. Hypothesis: **over/under swapped or misaligned** somewhere in
the O/U path. Verified in Step 1 below; 1X2 was never under suspicion.

### STRATEGY PIVOT (2026-09-24): derived goal markets

**The main-market hypothesis FAILED.** Results-only models cannot beat the sharp
market on 1X2 or O/U 2.5 in any of our four leagues. Discovery verdict, with CIs:
model − market = +0.0187 (ligue_2_t2), +0.0177 (bundesliga_2), +0.0182
(bundesliga_1), +0.0142 (League One) — every CI excludes 0 and every sign says
*the market is better*. No blend beats the market either.

**New direction.** Soccer Bet (Serbia) prices hundreds of **derived goal markets**
per match — goal ranges, per-half markets, HT/FT (incl. NE and double-chance
variants), win both halves, which half more goals, half-goal combos,
result&goals, HT/FT&goals, stake-back "No Bet" — almost certainly by formula.
Every one settles on **(HT home, HT away, FT home, FT away)**, which we hold for
every match since 2015.

**Plan.** Take the SHARP **pre-match** 1X2 + O/U 2.5 as *input*, build a joint
half-by-half scoreline model with an uneven half split and half-time game-state
effects, and test calibration per market family on history. Edge = families our
model prices accurately **AND** where Soccer Bet's price (entered later by the
user) exceeds fair value net of margin. **Not cross-book price hunting.**

### New principle: sharp pre-match odds as INPUTS

> **Sharp PRE-MATCH odds (`Avg` / `BbAv`; NEVER closing) may be model INPUTS.**

This is a deliberate change from "odds are never used to train models". The
closing price remains an **accuracy reference only**. The distinction that keeps
this honest: pre-match prices are information available *at bet time*, whereas
closing prices are not.

### Layers

| Layer | Content |
|---|---|
| **L1 anchor** | per match, solve (lambda, mu) so a Dixon-Coles FT grid reproduces the de-margined pre-match 1X2 and O/U 2.5 |
| **L2 half split** | first-half share of each team's goal rate, from training seasons only; may depend on expected goals and favourite strength |
| **L3 game state** | Dixon-Robinson (1998) style: second-half rates scaled by HT-state factors (leading / level / trailing, by side); optional HT-draw inflation |
| **Output** | joint grid over (h1, a1, h2, a2), every catalogue market derived from it |

### Market families

RESULT, DOUBLE_CHANCE, HALF_RESULT, HALF_DC, HTFT (9), HTFT_NE, HTFT_DC,
WIN_BOTH_HALVES, WIN_TO_NIL, MARGIN, NO_BET, GOAL_RANGE_FT, GOAL_RANGE_1H,
GOAL_RANGE_2H, MORE_GOALS_HALF, HALF_GOAL_COMBOS, RESULT_AND_GOALS,
HTFT_AND_GOALS, FIRST_GOAL (untestable from HT/FT data), TO_QUALIFY (out of scope).

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
