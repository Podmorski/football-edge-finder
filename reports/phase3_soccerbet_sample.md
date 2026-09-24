# Soccer Bet sample ingest — Hoffenheim vs Hamburger SV

**One match, one capture. No API calls, no downloads.** Confirmation seasons
untouched; this is book-side bookkeeping for the MAINLINE-1 recorder, not a
model result.

| | |
|---|---|
| match | Hoffenheim vs Hamburger SV, `bundesliga_1`, kickoff 2026-10-10 15:30 local |
| capture | 2026-09-24 ≈17:25 local (15:25Z) |
| input | `data/soccerbet/hoffenheim_hamburg_raw.txt` (2 blocks) |
| output | `data/soccerbet/2026-09-24_hoffenheim_hamburg.csv` (`data/` is gitignored) |

## 1. Ingest

**777 price rows across 41 families**, resolved through `core/soccerbet_ext`:

| status | n | meaning |
|---|---|---|
| OK | 720 | settlement function defined |
| UNTESTABLE | 54 | `MINUTE_MARKETS` 32, `FIRST_GOAL` 22 — ingest only |
| UNCONFIRMED | 3 | listed below — never guessed |

**UNCONFIRMED (3):**

| code | why |
|---|---|
| `SANSA:1vGG3+`, `SANSA:2vGG3+` | `GG3+` is probably "both score AND 3+ goals", but the printed code does not say so; refuse rather than guess |
| `SANSA:I2-3+vII3+` | malformed (`I2-3+` has a stray `+`) |

## 2. New settlement layer

`core/soccerbet_ext.py` covers the families the sample uses that are **not** in
the base grammar (`core/market_code.py`), keyed by the printed prefix:
`TEAM_GOALS_{HOME,AWAY}_{FT,1H,2H}`, `BTTS`, `BTTS_COMBOS`, `ODD_EVEN`,
`OR_MARKETS` (SANSA, `v` = OR), `CORRECT_SCORE`(+`_1H`),
`TEAM_HALF_COMBOS_{HOME,AWAY}`, `DOUBLE_CHANCE_AND_GOALS`,
`HALF_RESULT_AND_BTTS`, `MINUTE_MARKETS`, `WIN_BOTH_HALVES_TO_NIL`.

Prefix-keying is required, not cosmetic: `II0` is "no 2H goals" under `T2` but
"away leads" under `H2`, and `1-2` is a HT/FT pair under `HF`/`HFG`/`SANSA` but
a 1..2 goal range under `T`/`R`/`DCG`/`C`. The base catalogue is **not** modified
(it is generated from the rules text and keyed by bare code).

`tests/test_soccerbet_ext.py` adds **112 tests**: the official definition of
every family on hand-made scores, and — mechanically — that each margin
partition has exactly `reference` winners on every scoreline in `0..3⁴`.

## 3. Margin per family (partitions only)

A partial set's `sum(1/odds)` is **not** a margin and is not shown as one.

| partition | n | margin | | partition | n | margin |
|---|---|---|---|---|---|---|
| RESULT | 3 | +0.0856 | | HTFT | 9 | +0.1990 |
| DOUBLE_CHANCE | 3 | +0.0901 | | BTTS | 2 | +0.0799 |
| HALF_RESULT_1H | 3 | +0.1402 | | BTTS_2PLUS | 2 | +0.0794 |
| HALF_RESULT_2H | 3 | +0.1327 | | BTTS_HALVES | 4 | +0.1164 |
| HALF_DC_1H | 3 | +0.1373 | | ODD_EVEN | 2 | +0.0929 |
| HALF_DC_2H | 3 | +0.1370 | | MORE_GOALS_HALF | 3 | +0.1365 |

~8.5% on 1X2, 13–14% on per-half singles, 20% on HTFT, 8–12% on BTTS: the
"margin dominates" picture from the phase-3 correction, reproduced.

## 4. EV, two ways

Anchors: (i) Soccer Bet's **own** de-margined main line, (ii) the Pinnacle
snapshot. Both price all 720 settleable markets through the half model
(`league_params('bundesliga_1')`, discovery seasons only).

| view | anchor | implied 1H share | positive EV |
|---|---|---|---|
| (i) | SB 1X2 0.6789/0.1854/0.1357 (margin 8.56%) | **0.4355** (model 0.4525) | **0** of 720 |
| (ii) | Pinnacle 1.42/4.76/7.00 (**STALE**, 305 min) | — | 42 (5.8%); **11** above +3% after a 20% haircut |

**(i) is the headline: zero positive-EV markets** when the book is compared to
itself — its structure is self-consistent, exactly as the phase-3 correction
predicted. The anchor residual is 0.0058.

**Pinnacle 1X2 is confirmed as 1.42 / 4.76 / 7.00** (kickoff 13:30Z matches
15:30 local). Soccer Bet EV per 1X2 outcome: home **−0.83%**, draw **−24.3%**,
away **−16.5%** — SB's home price matches the sharp market, its draw and away
prices do not.

Top 5 by EV under (ii) — note only `GOAL_RANGE_1H` is a calibration-PASS family:

| market | family | odds | p_pin | EV | status |
|---|---|---|---|---|---|
| T1:3+ | GOAL_RANGE_1H | 4.20 | 0.2523 | +0.0599 | PASS |
| C:I2+&4+ | HALF_GOAL_COMBOS | 2.70 | 0.3915 | +0.0570 | FAIL |
| DCG:1X&I2+&4+ | DOUBLE_CHANCE_AND_GOALS | 3.00 | 0.3509 | +0.0527 | UNTESTED |
| C:I2+&3+ | HALF_GOAL_COMBOS | 2.18 | 0.4826 | +0.0520 | FAIL |
| T1:2+ | GOAL_RANGE_1H | 2.03 | 0.5180 | +0.0516 | PASS |

**This is not evidence for MAINLINE-1.** The snapshot is STALE by 5 hours, and
only 2 of the 15 highest-EV markets sit in a family whose calibration passed.
Both are `GOAL_RANGE_1H`, and their sign is consistent with the model expecting
more first-half goals than SB prices — not with a main-line deviation.

## 5. Corrections to the first draft

The first draft of this ingest was re-run from scratch; re-running found:

1. **O/U 2.5 was inverted** — the anchor was fitted to over 0.317 instead of
   0.683, which alone gave 132 "positive-EV" markets under (i) and a residual of
   0.078. Fixed → 0 positive, residual 0.0058.
2. **`2GG` settled as its own complement** and `IGG`/`IIGG` were inverted by a
   `startswith("GG")` test; `II` was also tested after `I`, so every 2nd-half
   variant used the 1st half.
3. **`NE1-2` (no space) was read as a HT/FT pair**, not a 1..2 goal range, so
   `T:NE1-2` priced at 0.99.
4. **`TEAM_GOALS_*_1H/2H` families never matched** (a broken `or` inside a
   tuple), leaving 36 markets UNCONFIRMED that settle fine.
5. **A leading `NE` was applied per component, not to the conjunction**
   (`NE GG&3+`).
6. **`HTFT_DC` is not an exhaustive partition** and must not be shown as a
   margin.

`data/soccerbet/2026-09-24_ev_table.csv` holds the per-market EV under both
anchors. **No ROI is claimed.**

## 6. Appendix — partition margins added for the fair-sheet ordering (2026-09-24)

The daily sheet orders its rows by the family's typical Serbian-book margin,
lowest first. §3 measures the exhaustive partitions that happen to exist as
*sets*; the goal-total and No-Bet families had none, so two-way partitions of the
same capture were added. All of these are exhaustive, so each sum **is** a margin:

| section | partition | prices | margin |
|---|---|---|---|
| Ukupno Golova | `T:0-2` / `T:3+` | 2.75 / 1.40 | **+0.0779** |
| Ukupno Golova | `T:0-1` / `T:2+` | 5.90 / 1.10 | +0.0786 |
| Ukupno Golova | `T:2` / `T:NE2` | 4.45 / 1.16 | +0.0868 |
| Ukupno Golova | `T:1` / `T:NE1` | 6.85 / 1.06 | +0.0894 |
| II Pol. Uk. Golova | `T2:0-2` / `T2:3+` | 1.40 / 2.75 | **+0.0779** |
| I Pol. Uk. Golova | `T1:0-1` / `T1:2+` | 1.70 / 2.03 | **+0.0808** |
| X No Bet | `XNB:1` / `XNB:2` (draw voids) | 1.11 / 4.77 | **+0.1105** |

Cheapest partition per family, which is what the sheet's ordering uses:
**Ukupno Golova +0.0779**, **II Pol. Uk. Golova +0.0779**, **I Pol. Uk. Golova
+0.0808**, **X No Bet +0.1105**; RESULT +0.0856 and DOUBLE_CHANCE +0.0901 are
§3's. `HTFT_NE` and `HTFT_DC` are printed in the **Poluvreme/Kraj** section, so
they take HTFT's +0.1990 rather than a figure of their own.

**Caveat, stated plainly:** a 3-way partition carries more margin than a 2-way one
at the same "vig level", so the goal-total and No-Bet entries are not strictly
comparable with §3's 3-way RESULT figure. They are the margins the book actually
charges on those markets **as it prints them**, which is what the ordering needs.

## 7. What the sample does NOT settle (2026-09-24)

**Section names.** The capture records only the printed prefix (`FT`, `T`, `I1`,
`HRG` …), never the Serbian heading, so every section name we hold comes from the
rules text or from the user. Prefixes whose display name is still unconfirmed are
flagged `(section not confirmed)` in the catalogue **rather than guessed**:

> AT, AT1, AT2, C, CA, CH, CS, CS1, DCG, GG, GGC, HFG, HT, HT1, HT2, PN, R,
> SANSA (and M15/M30, PGC, which are ingest-only)

The **section is what decides a code's meaning**, so an invented name would be
worse than an admitted gap: `1` is a home win under `Konačni Ishod` and exactly
one goal under `Ukupno Golova`, and `I1` is a 1st-half home win under `Poluvreme`
but exactly one 1st-half goal under `I Pol. Uk. Golova`.
