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
- **Whether to integrate PulseScore** (Mozzart's feed; free tier 500 requests/month,
  and it also carries **PS3838 = Pinnacle** and **bet365**). Not integrated yet.
- **Reworking the base catalogue's ambiguous goal-range bare codes** (see the
  2026-09-24 finding): it needs a calibration re-run to be recorded honestly.

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

### Derived-market structure hypothesis: CLOSED (2026-09-24)

> **CLOSED — the book's structure is correct; margin dominates.**

Soccer Bet prices derived markets with the **correct structure**: their implied
first-half goal share (~0.42) matches our historical estimate (0.41–0.44), and
their game-state effects are small. An external analysis of one full Soccer Bet
match (358 + ~100 markets) found **0 markets with positive EV** when anchored on
Soccer Bet's own main line, with margins of ~8% on 1X2, 10–15% on singles and
15–45% on combos.

**Therefore: beating the naive B0 formula is NOT evidence of edge against Soccer
Bet.** B0 is a *plausible book formula*, not the book. The Phase 3 calibration
result (7 families beating B0) shows only that our half-split and game-state
layers are better than a 50/50-split formula — it says nothing about whether
Soccer Bet's prices are beatable.

### Remaining hypothesis: MAINLINE-1 (2026-09-24)

> Soccer Bet's **MAIN LINE** (1X2 + goal totals) sometimes deviates from the sharp
> market by **more than its own margin**.

Sharp prices (Pinnacle, via The Odds API, region `eu`) are used **ONLY** as the
reference for true probability. Bets are placed **ONLY at Soccer Bet**, and only
in the **lowest-margin market that captures the deviation**. **Never combos.**

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

### Daily sheet and bet log (decided 2026-09-24)

The daily workflow is **check locally, then decide**, not collect prices:

| Command | What it does |
|---|---|
| `run.py fair-sheet --date D [--days 3]` | Pinnacle-anchored fair odds + **minimum acceptable odds** per market |
| `run.py log-close` | Fills the closing price and result in the bet log; reports CLV and P&L |

* **The user-driven local check replaces manual price capture.** The user reads
  the price at the book they already use and compares it with the sheet; nothing
  is typed into a recorder before betting.
* **MAINLINE-1 price capture is therefore optional, no longer required.** The
  hypothesis still stands, but it is no longer on the critical path — the sheet
  covers the same ground without a capture step.
* **`MIN ACCEPTABLE ODDS = fair odds x 1.035`.** A bet is only taken at or above
  it, so the cushion is explicit rather than implicit.
* The sheet shows families whose calibration is **PASS**, plus the four main-line
  families (**RESULT, DOUBLE_CHANCE, GOAL_RANGE_FT, NO_BET**) whose fair price
  **is** the de-margined sharp anchor rather than a model estimate. UNTESTABLE and
  UNCONFIRMED markets are never shown.
* Books: **Soccer Bet has no API** — it is checked locally only. **Mozzart is
  reachable through PulseScore** (free tier 500 requests/month, also carrying
  PS3838 = Pinnacle and bet365) but is **not integrated yet**.

### Hoffenheim sample: not evidence for MAINLINE-1 (2026-09-24)

Re-read of `reports/phase3_soccerbet_sample.md` in this light:

* **0 of 720** settleable markets had positive EV against Soccer Bet's **own**
  de-margined main line. The book is self-consistent; the margin dominates.
* The 42 "positive EV" markets found against the Pinnacle anchor came from a
  snapshot that was **STALE by 305 minutes**. A stale sharp price is not a sharp
  price, so **that is not evidence of edge** in either direction.

### CLV decision rule (decided 2026-09-24)

> **No conclusion before 50 logged bets; continue only if the mean CLV is > 0.**

* `CLV = odds_taken / fair_close - 1`, and the summary always reports the mean
  CLV **with a 95% interval** plus P&L (P&L is reported, never used to decide).
* For a **main-line** market the closing benchmark is the de-margined closing
  price, per the benchmark rule. For a **derived** market no book prints a closing
  price we can read, so `fair_close` is the half model's fair price on the **last
  Pinnacle snapshot held before kickoff** (the sheet's snapshot history). This is
  recorded here so the number is never mistaken for an observed book price.
* Closing snapshots are kept **append-only** (`data/odds_snapshots/`), so the
  price nearest a kickoff survives; the 6h cache only decides whether a new fetch
  is needed.

### Finding: the base catalogue's goal-range bare codes are ambiguous (2026-09-24)

> **12 bare codes in `GOAL_RANGE_FT` / `GOAL_RANGE_1H` / `GOAL_RANGE_2H` do not
> mean what their family says.**

`core.market_code.parse_leg` tests a result token before a goal token, and strips
a leading `I`/`II` first, so:

| Catalogue entry | Parses as | Should be |
|---|---|---|
| `GOAL_RANGE_FT 1` / `2` | RESULT `1` / `2` (home / away wins) | exactly 1 / 2 goals |
| `GOAL_RANGE_FT NE 1` / `NE 2` | DOUBLE_CHANCE `X2` / `1X` | not exactly 1 / 2 goals |
| `GOAL_RANGE_1H I1` / `I2` | HALF_RESULT `I1` / `I2` | exactly 1 / 2 first-half goals |
| `GOAL_RANGE_1H NE 1` / `NE 2` | HALF_DC `IX2` / `I1X` | not exactly 1 / 2 first-half goals |
| `GOAL_RANGE_2H II1` / `II2` | HALF_RESULT `II1` / `II2` | exactly 1 / 2 second-half goals |
| `GOAL_RANGE_2H NE 1` / `NE 2` | HALF_DC `IIX2` / `II1X` | not exactly 1 / 2 second-half goals |

**Consequences.**

1. The **GOAL_RANGE_FT / 1H / 2H calibration verdicts are not clean** — part of
   what they measured in the goal-range bucket belonged to RESULT, DOUBLE_CHANCE,
   HALF_RESULT and HALF_DC. (They FAILed either way, but the numbers are mixed.)
2. **A bare goal-range code must not be trusted without its printed prefix.** This
   is the same reason the ext layer is keyed by prefix: `1` is a result under `FT`
   and exactly one goal under `T`.
3. The correct readings are already carried **prefix-keyed** in the catalogue's
   `ext_markets` section (`T:1`, `T1:NE1`, ...), and the daily sheet **drops the
   misparsed rows** by de-duplicating on settlement identity with the canonical
   family first.

**Not fixed in place.** Removing the 12 entries from the base catalogue would
invalidate the committed `reports/figures/family_calibration.csv` without a
re-run, so it is logged as an open decision instead.
