# Phase 2 — League One

Walk-forward Dixon-Coles, hygiene fixes, odds audit, tuning, and benchmark.
**Discovery + warmup data only. Confirmation seasons were never loaded.**
Zero API calls; no downloads were needed (the parquets already held every
football-data.co.uk column).

## 0. Hygiene

| Item | Result |
|---|---|
| Ledger append-only | `run_id` + `superseded_by` added; `log_evaluation`/`append_note`/`supersede` only append. 7 new tests, incl. a byte-prefix proof that earlier bytes are never rewritten. |
| Earlier resets | recorded as a `PROCESS NOTE` and a `SCHEMA MIGRATION` note row. |
| BOM artefact | `ï»¿_div` was a *complementary duplicate* of `div` (4,816 + 1,187 = 6,003 rows). Coalesced at ingestion; all four parquets re-saved with **row counts unchanged** and `div` now 100% populated. |
| Confirmation | `research/confirmation_access.csv` does not exist — the lock was never opened. |

## 1. Odds aliases and benchmark availability

Full tables in `reports/odds_alias_audit.md`. Lower-cased parquet names, all four leagues:

| Alias group | 2015-16 … 2018-19 | 2019-20 … 2022-23 |
|---|---|---|
| BetBrain `bb_av_h/d/a`, `bb_mx_h/d/a`, `bb_av>2.5`, `bb_av<2.5`, `bb_a_hh`, `bb_av_ahh/aha` | **100%** | **0%** (replaced) |
| Pinnacle closing `psch/pscd/psca` | **100%** | 99–100% |
| Pinnacle O/U + AH `p>2.5`, `p<2.5`, `pc>2.5`, `pc<2.5`, `pahh/paha`, `pcahh/pcaha` | **0%** | 98–100% |
| Market average `avg_*`, `avg_ch/cd/ca`, `avg>2.5`, `avg_c>2.5`, `a_hh` | **0%** | 100% |

**Correction to an earlier belief:** closing 1X2 prices are available in *every*
season, not just from 2019-20 — `PSC` covers 2015-16 onwards at ~2.5–3.3% margin
(sharper than `AvgC`'s ~6%). Only `AvgC`/`B365C`/market-average columns start at
2019-20.

| Benchmark | 2017-18 | 2018-19 | 2019-20 | 2020-21 | 2021-22 | 2022-23 |
|---|---|---|---|---|---|---|
| 1X2 pre-match | ✅ BbAv | ✅ BbAv | ✅ Avg | ✅ Avg | ✅ Avg | ✅ Avg |
| 1X2 closing (CLV) | ✅ PSC | ✅ PSC | ✅ AvgC | ✅ AvgC | ✅ AvgC | ✅ AvgC |
| O/U 2.5 pre-match | ✅ BbAv | ✅ BbAv | ✅ Avg | ✅ Avg | ✅ Avg | ✅ Avg |
| O/U 2.5 closing | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| AH pre-match | ✅ BbAH | ✅ BbAH | ✅ AvgAH | ✅ AvgAH | ✅ AvgAH | ✅ AvgAH |
| AH closing | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |

So CLV is computable for 1X2 across the whole discovery window, but **not** for
O/U or AH before 2019-20. Mean book margins (League One, 1X2): pre-match
0.063–0.071, closing 0.025–0.065.

## 2. Diagnostics (League One)

| Season | n | home% | draw% | away% | E[home] | E[away] | flag |
|---|---|---|---|---|---|---|---|
| 2015-2016 | 552 | 42.9 | 25.0 | 32.1 | 1.453 | 1.187 | |
| 2016-2017 | 552 | 44.9 | 27.9 | 27.2 | 1.462 | 1.105 | |
| 2017-2018 | 552 | 42.4 | 27.0 | 30.6 | 1.382 | 1.156 | |
| 2018-2019 | 552 | 41.7 | 26.6 | 31.7 | 1.429 | 1.219 | |
| 2019-2020 | 400 | 46.2 | 27.8 | 26.0 | 1.498 | 1.113 | curtailed |
| 2020-2021 | 552 | **40.4** | 23.9 | **35.7** | **1.348** | **1.274** | closed doors |
| 2021-2022 | 552 | 44.7 | 26.4 | 28.8 | 1.500 | 1.197 | |
| 2022-2023 | 552 | 43.7 | 25.4 | 31.0 | 1.415 | 1.147 | |

2020-21 is the COVID outlier: home wins 40.4% (vs 43.4% non-COVID), away wins
35.7% (vs ~30%), and the smallest home/away goal gap of any season.

- **In-sample:** model 1.0526 vs naive 1.0769 → the model **does** beat naive
  in-sample, so the earlier out-of-sample miss was not a bug.
- **Swap test (2021-22 holdout):** correct orientation 1.0738, swapped 1.1094.
  Swapping makes it worse, and mean P(home) drops 0.4179 → 0.3245. Home
  advantage is real and correctly signed.

## 3. Walk-forward engine (`core/walkforward.py`)

Weekly Monday cutoffs; trained strictly on `date < cutoff`; predictions for
`[cutoff, cutoff+7d)`. Fits cached by `(league, xi, covid, cutoff)` — the
newcomer policy is deliberately *not* in the key since it is applied at
prediction time. Confirmation seasons are hard-refused in both training and
target data. Predictions persist lambda/mu/rho plus P(H/D/A), P(over 2.5),
P(BTTS) and newcomer flags.

Goals model (verified against the installed penaltyblog by regression on its own
predictions):

```
log E[home] = attack_home + defence_away + home_advantage
log E[away] = attack_away + defence_home
```

`create_dixon_coles_grid` reproduces `model.predict` to within ~1.1e-3 in
probability (the two apply the DC tau slightly differently); a test bounds this.

## 4. Newcomer policy

"Newcomer" = no League One match in the 365 days before the cutoff. Blend
`weight = min(n/10, 1)` from prior towards fitted, `k = 10` fixed.

Priors per target season (first cutoff):

| Season | league_avg | promoted_in | relegated_in |
|---|---|---|---|
| 2017-2018 | (1.000, −0.923) | (1.000, −0.923) n=0 | (1.000, −0.923) n=0 |
| 2018-2019 | (1.000, −0.900) | (1.000, −0.900) n=0 | (1.000, −0.900) n=0 |
| 2019-2020 | (1.000, −0.861) | (1.187, −0.963) n=4 | (1.129, −1.104) n=3 |
| 2020-2021 | (1.000, −0.887) | (1.112, −0.977) n=11 | (1.070, −1.023) n=9 |
| 2021-2022 | (1.000, −0.821) | (1.092, −0.920) n=11 | (1.046, −0.878) n=9 |
| 2022-2023 | (1.000, −0.837) | (1.130, −1.017) n=12 | (1.013, −0.910) n=15 |

Early seasons have no earlier newcomers because arrivals before 2015-16 are
invisible. `league_avg` attack is exactly 1.000 by the model's identifiability
constraint (`sum(attack) = n_teams`).

**Stage B** (at the Stage-A winner):

| Policy | predicted | newcomer matches | pooled 1X2 | pooled O/U | newcomer-only 1X2 |
|---|---|---|---|---|---|
| exclude | 3,141 | 20 | 1.044086 | 0.705856 | 0.973890 |
| league_avg | 3,160 | 39 | 1.044562 | 0.705773 | 1.046650 |
| **newcomer_prior** | 3,160 | 39 | **1.044205** | **0.705749** | **1.017736** |

On the same 3,141-match subset every policy can predict, all three give
1X2 = 1.0441 — the policies only differ on newcomer matches, and there
`newcomer_prior` is clearly best (1.0177 vs 1.0467).

## 5. Tuning

### Stage A — xi × COVID (newcomer = league_avg), sorted by tune 1X2

| xi | COVID | tune 1X2 | tune O/U | validation 1X2 | 2019-20 (report only) |
|---|---|---|---|---|---|
| **0.002** | **include** | **1.0552** | 0.7055 | 1.0296 | 1.0419 |
| 0.003 | include | 1.0553 | 0.7082 | 1.0285 | 1.0399 |
| 0.0015 | include | 1.0560 | 0.7047 | 1.0300 | 1.0443 |
| 0.001 | include | 1.0579 | 0.7044 | 1.0302 | 1.0481 |
| 0.005 | include | 1.0586 | 0.7151 | 1.0278 | 1.0404 |
| 0.0005 | include | 1.0610 | 0.7048 | 1.0298 | 1.0532 |
| 0.0015 | drop 2020-21 | 1.0698 | 0.7041 | **1.0185** | 1.0443 |
| 0.001 | drop 2020-21 | 1.0699 | 0.7040 | 1.0194 | 1.0481 |
| 0.002 | drop 2020-21 | 1.0699 | 0.7046 | 1.0186 | 1.0419 |
| 0.005 | drop 2020-21 | 1.0705 | 0.7102 | 1.0274 | 1.0404 |
| 0.003 | drop 2020-21 | 1.0707 | 0.7064 | 1.0204 | 1.0399 |
| 0.0005 | drop 2020-21 | 1.0708 | 0.7042 | 1.0208 | 1.0532 |

Tune seasons 2017-18, 2018-19, 2020-21; validation 2021-22, 2022-23; 2019-20
reported but excluded from selection.

**Winner on the pre-registered criterion (tune 1X2): xi = 0.002, COVID include.**
Worth recording plainly: dropping 2020-21 from *training* is **better on
validation** (1.0185 vs 1.0296) but **worse on tune** (1.0698 vs 1.0552), and
selection follows tune.

### Home advantage across refits (winner)

226 refits, home advantage min/mean/max = 0.126 / 0.190 / 0.268.

| Season | mean home advantage | mean rho |
|---|---|---|
| 2017-2018 | 0.2268 | −0.0339 |
| 2018-2019 | 0.1832 | −0.0611 |
| 2019-2020 | 0.2111 | −0.0623 |
| 2020-2021 | 0.1762 | −0.0029 |
| 2021-2022 | 0.1512 | +0.0198 |
| 2022-2023 | 0.1896 | −0.0149 |

Chart: `reports/figures/league_one_home_advantage_over_time.png`.

## 6. Benchmark (best config, same subset for all contenders)

Best config: `xi=0.002`, COVID include, `newcomer_prior`.
Pre-match source: `Avg` (2019-20+) / `BbAv` (earlier), margin 0.0643.
Closing source: `AvgC` / `PSC`, margin 0.0518.

| Season | n | model | naive | market pre | model − market | market close |
|---|---|---|---|---|---|---|
| 2017-2018 | 552 | 1.0595 | 1.0806 | 1.0539 | +0.0055 | 1.0451 |
| 2018-2019 | 552 | 1.0485 | 1.0826 | 1.0396 | +0.0089 | 1.0368 |
| 2019-2020 | 399 | 1.0419 | 1.0676 | 1.0078 | +0.0342 | 1.0042 |
| 2020-2021 | 552 | 1.0572 | 1.0832 | 1.0432 | +0.0141 | 1.0371 |
| 2021-2022 | 552 | 1.0380 | 1.0713 | 1.0000 | +0.0380 | 0.9935 |
| 2022-2023 | 552 | 1.0199 | 1.0733 | 1.0055 | +0.0145 | 1.0066 |

Brier: model 0.612–0.640, naive 0.644–0.657, market 0.596–0.636.

O/U 2.5 vs market (pre-match):

| Season | model | market | source |
|---|---|---|---|
| 2017-2018 | 0.7174 | **0.6971** | BbAv>2.5 |
| 2018-2019 | 0.7165 | **0.6995** | BbAv>2.5 |
| 2019-2020 | **0.6902** | 0.7113 | Avg>2.5 |
| 2020-2021 | **0.6824** | 0.7082 | Avg>2.5 |
| 2021-2022 | 0.7052 | **0.7032** | Avg>2.5 |
| 2022-2023 | 0.7185 | **0.7002** | Avg>2.5 |

O/U is **mixed**: the model wins 2019-20 and 2020-21, loses the other four.

### Reliability, 10 bins, pooled validation seasons

P(home) — model tracks the market closely and is reasonably calibrated:

| bin | n | model | market | observed |
|---|---|---|---|---|
| 0.1–0.2 | 45 | 0.174 | 0.168 | 0.222 |
| 0.2–0.3 | 149 | 0.259 | 0.258 | 0.235 |
| 0.3–0.4 | 317 | 0.353 | 0.352 | 0.372 |
| 0.4–0.5 | 273 | 0.448 | 0.447 | 0.480 |
| 0.5–0.6 | 207 | 0.545 | 0.547 | 0.556 |
| 0.6–0.7 | 85 | 0.641 | 0.646 | 0.659 |

P(over 2.5) — the model is visibly **under-confident/wrong-signed** in the
middle bins, the market is not:

| bin | n | model | market | observed |
|---|---|---|---|---|
| 0.2–0.3 | 19 | 0.268 | – | 0.526 |
| 0.3–0.4 | 138 | 0.367 | 0.386 | 0.471 |
| 0.4–0.5 | 441 | 0.459 | 0.474 | 0.528 |
| 0.5–0.6 | 400 | 0.542 | 0.533 | 0.520 |
| 0.6–0.7 | 99 | 0.634 | 0.617 | 0.566 |
| 0.7–0.8 | 7 | 0.741 | – | 0.286 |

## 7. STOP RULE

| Season | model | naive | verdict |
|---|---|---|---|
| 2021-2022 | 1.0380 | 1.0713 | **beats naive** |
| 2022-2023 | 1.0199 | 1.0733 | **beats naive** |

The walk-forward model **beats naive out-of-sample on both validation seasons**,
so the stop rule is not triggered — but it still **loses to the market on 1X2 in
every season** (+0.0055 to +0.0380 log loss), and the closing price is sharper
still. That is the honest headline.

## 8. Limitations

- `relegated_in` vs `promoted_in` is a proxy (spell index); distinguishing them
  properly needs the divisions above/below.
- Early discovery seasons have no earlier newcomers, so `newcomer_prior`
  degenerates to `league_avg` until 2019-20.
- The manual lambda path differs from `model.predict` by ≤1.1e-3 in probability.
- No ROI, no bet simulation, no CLV this session by instruction.