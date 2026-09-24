# How to capture Soccer Bet prices

The recorder exists to test **one** hypothesis (MAINLINE-1): that Soccer Bet's
**main line** sometimes deviates from the sharp market by more than its own
margin. Sharp prices are only the probability reference; bets would be placed
only at Soccer Bet, only in the lowest-margin market capturing the deviation,
and **never combos**.

## What to screenshot

**Only two screens per match:**

1. **The first screen** — Konačni Ishod (1X2), Dupla Šansa (DC) and X No Bet.
2. **Ukupno Golova** — every goal-total line offered.

Do **not** capture combos, HT/FT, per-half or team-goal markets. They carry
15–45% margins and are out of scope.

## Leagues in scope

`bundesliga_1`, `bundesliga_2`, `league_one`, `ligue_2`.

## Target

**30–40 matches over ~2 weeks**, at **varied times**:

| when | why |
|---|---|
| ~48h before kick-off | early line, before the market has settled |
| ~24h before kick-off | the main comparison point |
| ~2h before kick-off | late movement |

Capture the **local time** of each screenshot — the tool compares only against
sharp prices captured within **60 minutes** of it, and flags anything else
`STALE`.

## How to record

Fill `templates/soccerbet_mainline.csv`:

```
date,league,home,away,capture_time_local,market,code,odds
```

* `market` is one of `1X2`, `DC`, `XNB`, `goals`.
* `code` is the Soccer Bet code as printed (`1`, `X`, `2`, `1X`, `12`, `X2`,
  `XNB FT 1`, `0-1`, `1-2`, `3+`, …).
* `odds` is the decimal price.

One row per market per match. Then run:

```bash
./venv/Scripts/python.exe run.py compare-mainline --file templates/soccerbet_mainline.csv
```

## What the tool reports

Per match: the sharp de-margined probability for each market, Soccer Bet's odds,
`EV = p_sharp × odds − 1`, the sharp-anchored fair price of **every** Soccer Bet
market, the cheapest Soccer Bet representation of each outcome set, the maximum
EV market, and a flag only when EV exceeds **+3% after a safety haircut**
(`p_sharp` shrunk 20% toward Soccer Bet's de-margined probability).

## Pre-registered success criterion

See `research/preregistration.md`, entry **MAINLINE-1**. In short: over ≥30
matches captured within 60 minutes of a sharp snapshot, the hypothesis is
supported only if **≥10% of matches have a flagged market** AND the **mean EV of
flagged markets is > 0 with a bootstrap 95% CI above 0**. Otherwise the betting
hypothesis for Soccer Bet is **CLOSED**.
