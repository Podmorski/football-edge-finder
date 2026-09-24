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

### The SECTION decides a code, and the family decides the token type (2026-09-24)

> **A bare code has no meaning on its own.** `1` is a home win under *Konačni
> Ishod* and exactly one goal under *Ukupno Golova*; `I1` is a 1st-half home win
> under *Poluvreme* and exactly one 1st-half goal under *I Pol. Uk. Golova*.

Implemented:

1. Every catalogue market carries a **`section`** field (the Serbian heading as
   displayed). `parse()` derives the family from the section; a section that
   contradicts a supplied family **raises** instead of guessing, and an unknown
   section raises too.
2. **The family decides the token type.** Inside the goal families a leg is always
   a goal total, so the 12 codes above can no longer be read as results. A guard
   test requires *every* code in *every* goal family to settle on the goal total
   alone — the invariant the old behaviour violated.
3. `Dupla Super Pobeda` moved to its own family `WIN_BOTH_HALVES_TO_NIL` (it was
   filed under `WIN_BOTH_HALVES`), matching the ext layer. The Holm family count
   therefore went **18 → 19**.
4. Prefixes whose Serbian display name is not confirmed are flagged
   `(section not confirmed)` rather than invented — see
   `reports/phase3_soccerbet_sample.md` §7 for the list.

**Calibration re-run (discovery only, Holm again).** The **PASS list is
unchanged: the same 7 families** (`GOAL_RANGE_1H`, `GOAL_RANGE_2H`, `HALF_RESULT`,
`HALF_DC`, `HTFT`, `HTFT_NE`, `MORE_GOALS_HALF`). Only the two half-goal families
moved, and not enough to change a verdict:

| family | slope before → after | gain vs B0 | verdict |
|---|---|---|---|
| `GOAL_RANGE_1H` | 0.9796 → **0.9730** | +0.0023 | PASS (unchanged) |
| `GOAL_RANGE_2H` | 1.0302 → **1.0207** | +0.0045 | PASS (unchanged) |
| `GOAL_RANGE_FT` | 1.0050 → **1.0048** | +0.0000 | fail (unchanged) |

The earlier run is **superseded** in the ledger (marker row, never deleted) and
its table is kept beside the new one as
`reports/figures/family_calibration_preparserfix.csv`.

> **So the bug was real but not verdict-changing.** The move is small enough that
> the previous session's reading — "the goal-range verdicts are mixed" — should
> be restated: the codes were wrong, the bucket verdicts were not.

### Fair-sheet presentation (2026-09-24)

The user matches prices to Soccer Bet / Mozzart **by hand**, so each match prints
one short table with the columns **SECTION | CODE | MEANING | FAIR | BET ONLY IF
ODDS >= fair x 1.035**, ordered by the family's typical Serbian-book margin,
**lowest first**:

`GOAL_RANGE_FT .0779 · GOAL_RANGE_2H .0779 · GOAL_RANGE_1H .0808 · RESULT .0856 ·
DOUBLE_CHANCE .0901 · NO_BET .1105 · HALF_RESULT .1327 · MORE_GOALS_HALF .1365 ·
HALF_DC .1370 · HTFT .1990 (= HTFT_NE, same section)`

* at most **3 prices per family** and **15 rows per match**, so the cheap families
  all appear instead of 40 goal-total prices filling the sheet;
* rows read straight off the sharp price — **RESULT, DOUBLE_CHANCE, full-time
  No-Bet, and the goal totals from the sharp 1X2 + totals line — carry status
  `SHARP`**, never a calibration verdict;
* the margin figures and their caveats are recorded in
  `reports/phase3_soccerbet_sample.md` §6. **A margin table orders a shortlist; it
  is not a claim that any row is value.**

### MAINLINE-HIST-1: the historical main-line test (2026-09-24)

Pre-registered in `research/preregistration.md` **before computing**, on the same
rule as MAINLINE-1: fair = Pinnacle **pre-match** de-margined (power), bet 1 unit
at the soft book's **pre-match** price when `soft >= fair x 1.035`, discovery
2017-18..2022-23, all four leagues, closing prices used **only** to evaluate.

| book | market | n | ROI | mean CLV | CLV 95% CI | Holm p | verdict |
|---|---|---:|---:|---:|---|---:|---|
| b365 | 1X2 | 273 | −3.55% | **+1.94%** | [+0.74%, +3.14%] | 0.000 | **FAIL** (n<300) |
| b365 | O/U 2.5 | 11 | −9.73% | +11.20% | [+7.37%, +15.07%] | 0.124 | FAIL (n<300) |
| b365 | AH | 7 | −18.43% | +5.91% | [−2.87%, +15.06%] | 0.124 | FAIL (n<300) |
| market average | 1X2 | 1 | −100% | +21.14% | [—] | 0.000 | FAIL (n<300) |
| market average | O/U 2.5 | 8 | −1.00% | +10.42% | [+6.31%, +14.25%] | 0.000 | FAIL (n<300) |
| market average | AH | 0 | — | — | — | — | FAIL (no bets) |

**No CONFIRMATION CANDIDATE. The locked seasons were not opened.**

Three things this run establishes beyond the verdict:

1. **The market average is structurally not a contender.** It cannot beat the
   de-margined sharp price: 1 bet in six seasons of 1X2, 0 in AH, 8 in O/U. The
   `BbAv` fallback behaves the same (0 of 9,246). A mean of many books *is* mostly
   the margin.
2. **O/U 2.5 and AH barely exist before 2019-20** in this data (Pinnacle pre-match
   O/U and AH are 0% before then), so those two markets cover **4** discovery
   seasons, not 6, and cannot reach n=300 at 1 unit per bet.
3. **B365 / 1X2 is the only near-miss**: mean CLV is positive with a CI above 0,
   at **273** bets — one gate short. It is **not** a PASS and it is **not** a
   candidate; the ROI on the same 273 bets is **−3.55%**, which is exactly the
   small-sample divergence CLV and P&L are known to show.

The AH test is limited in general: only half and whole lines were used (quarter
lines split the stake and were excluded, 3,986 rows), pushes are void and were
excluded, and de-margining a 2-way price ignores push mass.

> **Proxies, not Mozzart.** B365 and the market average are **proxies**. **A FAIL
> does not rule out the local books**, and a PASS would have been *encouraging, not
> proof*. Nothing here licenses a bet at Soccer Bet or Mozzart.

### CLV benchmark note (2026-09-24)

`CLV = odds_taken / fair_close - 1` with `fair_close` the **de-margined** closing
price, as the benchmark rule requires. **De-margining makes the closing price
*longer* than the raw book price**, so this gate is **stricter** than the usual
"beat the raw closing odds" CLV — the audit below caught the direction being
written the wrong way round in one review comment, which is why it is stated here.

### Independent CLV audit (2026-09-24)

`audit_clv.py` re-implements the CLV chain **from scratch** (no project imports)
from the raw parquet and checks the backtest and `run.py log-close`:

| check | result |
|---|---|
| 1. recomputed power de-margin vs the bets CSV's `fair_close` (200 bets) | agrees to **1.8e−15** |
| 2. `clv == soft_odds / fair_close - 1` | agrees to **3.1e−16** |
| 3. `fair_close` is a de-margined price, never a raw odd | 0 violations |
| 4. ROI / mean CLV / bootstrap CI recomputed independently | summary agrees exactly; CI brackets the mean |
| 5. `run.py log-close` CLV identity, run end-to-end as a subprocess | holds to 1e−9 |
| 6. no snapshot used after kick-off | 9 snapshots, 0 violations |

> **It found a real defect.** The bets CSV had the CLV value written into the
> `fair_close` column. The headline statistics were unaffected, but the audit
> input was wrong, so the run was repeated with the column corrected and the
> earlier ledger row **superseded**. The fresh-process re-run reproduces every
> headline number exactly.

### MAINLINE-HIST-1 verdict stands; B365/1X2 is a LEAD (2026-09-24)

**The FAIL verdict is unchanged and the `n >= 300` gate is NOT amended.** B365/1X2
missed the gate at **n = 273**; moving the gate to fit the one near-miss would be
fitting the rule to the result. It is recorded as a **LEAD**, not a candidate:

> **LEAD — B365 / 1X2.** mean CLV **+1.94%** [+0.74%, +3.14%], n = 273, ROI
> −3.55%. Positive CLV with a CI above 0, but one gate short and P&L negative.

The **real test is automated Mozzart paper trading** (Parts E–F): the local book's
own prices, recorded forward, settled automatically. Only after that, and only if
it holds, is there **one shot** of the frozen rule on the locked confirmation
seasons. **No bet is ever placed automatically.**

### Era split and outliers for B365/1X2 (2026-09-24)

`research/era_split.py` (read-only, no API calls) splits the 273 B365/1X2 bets at
2019 and audits the largest-CLV bets.

| era | n | mean CLV | 95% CI | ROI |
|---|---:|---:|---|---:|
| 2017-18..2018-19 | 122 | **+1.63%** | [−0.03%, +3.51%] | −13.31% |
| 2019-20..2022-23 | 151 | **+2.20%** | [+0.53%, +3.74%] | +4.34% |

**B365 1X2 margin per season** (mean over the four leagues): 2017-18 **+4.96%**,
2018-19 **+4.95%**, 2019-20 +5.41%, 2020-21 +6.03%, 2021-22 +6.06%, 2022-23
+5.86% — the book's margin **rose** after 2019, so the later-era CLV is not an
artefact of a softer book.

**Pre-2019 B365 columns are genuine book prices, not copies.** Across the four
leagues in 2017-18..2018-19 the B365 margin (2.85%–6.53%) is distinct from both
Pinnacle (2.56%–3.51%) and the market average (4.87%–7.43%); only **2.5%–6.1%** of
rows have `b365_h == psh` and **4.2%–10.5%** have `b365_h == bb_av_h`.

> **Verdict: the signal survives post-2019.** CLV is positive in *both* eras and
> the later era is the stronger one, with its CI above 0. The pre-2019 CI just
> touches 0, so the early era alone would not clear the bar.

**Outliers.** The 10 largest-CLV bets are 9× 1X2 and 1× AH, all on long prices
where Pinnacle moved sharply between pre-match and close (e.g. 2019-02-11 Brest v
Auxerre away 4.75, Pinnacle 4.30 → 3.42). They look like **genuine large line
moves, not data errors**; the two largest (Brest v Auxerre, Clermont v Nimes) are
flagged for a spot-check because the move exceeds 20%.

**Sensitivity (not a gate).** Removing the 9 bets with CLV > 20% drops the 1X2
mean CLV to **+1.05%** [−0.09%, +2.10%] — the CI then includes 0. So a meaningful
part of the headline CLV rests on a handful of large-move bets; the paper-trading
sample must be read with that in mind.

### PulseScore / Mozzart discovery (2026-09-24)

`pulsescore_probe.py` (bounded, every call logged to `logs/pulsescore_requests.csv`).

* **Free tier is a BASIC plan: 1 request per second per bookmaker.** A second call
  in the same second returns **HTTP 429**. No monthly figure is exposed, so the
  local log is the source of truth: configured **monthly cap 400**, **stop at 50
  remaining** (`pulsescore_log.py`).
* **A pre-match endpoint exists — no STOP.** `GET /soccer/events?page=&limit=`
  returns upcoming events with `live: false` and their **full market list with
  odds**. The live WebSocket is not required.
* **PS3838 (Pinnacle) is available with this key** (`/api/ps3838/soccer/leagues` →
  126 leagues). **bet365 is not** (HTTP 404).
* Endpoints confirmed: `/soccer/leagues` (99 leagues, 30/page),
  `/soccer/leagues/:id/events` (returned 0 for the two leagues checked),
  `/soccer/events` (599 upcoming events, 30/page), `/soccer/events/:id`.
* Market shape: `canonicalMarket`, `rawName` (Serbian section), `period`
  (`FULL_TIME`/`FIRST_HALF`/`SECOND_HALF`), `marketId` (line in
  `30:FULL_TIME@2.5`), `selections[]` with `rawName`, `odds`,
  `moreInfo.description`.
* **League mapping (Mozzart Serbian names):** Bundesliga → **Nemačka 1** (4143);
  League One → **Engleska 3** (4080); **2. Bundesliga → not in the list**;
  **Ligue 2 → not in the list**. The 99-league list has Nemačka 1 and Nemačka 3
  but no Nemačka 2, and Francuska 1 and Francuska 3 but no Francuska 2. The feed
  is currently dominated by **Nations League / cup ties (international break)**, so
  this must be **re-checked on a normal matchday** before concluding the two
  leagues are unavailable.
* Discovery used **17 requests** (2 wasted: one 429, one duplicate) of the 400/month.

**C6 sample.** One upcoming match pulled and saved to `data/mozzart/raw/`:
Netherlands v Germany (Nations League, 184 markets). First rows:

| section (rawName) | code | odds |
|---|---|---:|
| Konačan ishod | `1` | 2.60 |
| Konačan ishod | `X` | 3.90 |
| Konačan ishod | `2` | 2.55 |
| Dupla šansa | `1X` | 1.56 |
| Ukupno golova na meču | `0-1` | 5.30 |
| Ukupno golova na meču | `2+` | 1.12 |
| Oba tima daju gol | `GG` | — |
| Poluvreme - Kraj | `1-1` | — |

> **The section decides the code, exactly as with Soccer Bet.** Mozzart prints
> `Konačan ishod`/`Dupla šansa`/`Ukupno golova na meču`/`Oba tima daju gol`/
> `Poluvreme - Kraj`/`Tačan rezultat`/`Daje prvi gol`/`Mozzart šansa`, and the
> same bare code means different things under different sections.

### Automated Mozzart paper trading (2026-09-24)

**Mozzart is the primary automated book; Soccer Bet is the manual secondary.**
The fair sheet now joins Mozzart's pre-match prices (PulseScore) to our fair odds
and prints a **FLAGS** block at the top: match, kickoff, Serbian section, code,
plain-English meaning, Mozzart odds, minimum acceptable odds (`fair x 1.035`) and
**EV after a 20% haircut** on the fair probability. A market is flagged only when
**all** hold:

1. the family **PASSed** calibration, or it is a **SHARP main-line** market
   (RESULT, DOUBLE_CHANCE, full-time No-Bet, GOAL_RANGE_FT);
2. the Mozzart price is at or above `fair x 1.035`;
3. the Pinnacle and Mozzart snapshots are **within 60 minutes** (else `STALE`).

If nothing qualifies the sheet prints **“No value today.”** Each run appends one
line to `reports/fair_sheets/summary.csv` (date, matches, markets compared, flags,
credits).

**Payout.** The user confirmed `payout = stake x odds`, no tax and no fees:
`bookmaker_payout_factor = 1.00`, `stake_fee = 0.00` (`config/paper.yaml`).

**Paper trading is fully automatic and never places a real bet.** Every flag
becomes one paper bet (1 unit at the Mozzart price) in `data/paper/paper_bets.csv`;
`run.py paper-close` saves the de-margined Pinnacle close for matches with paper
bets within 30 minutes of kickoff; `run.py paper-settle` settles finished bets via
the **section-aware** settlement; `run.py paper-report` prints n, mean CLV with a
95% CI, virtual P&L, and the same split by family and by league.

> **Real money only after >= 50 paper bets with mean CLV > 0, the 95% CI lower
> bound > 0, and no contradicting historical evidence.** The B365/1X2 lead is
> positive but one gate short and partly driven by a few large-move bets, so it is
> **not** a licence to bet. **No bet is ever placed automatically.**
