# Schedule proposal — daily fair sheet + paper trading

**Status: PROPOSED, NOT ACTIVATED.** No Task Scheduler task has been created.
This file records the budget and the exact task definitions for approval.

## What runs, and what it costs

| Job | Command | PulseScore | Odds API | Notes |
|---|---|---:|---:|---|
| Pre-match flag run | `run.py fair-sheet --days 1` | 1 per mapped league (league ids cached 7 days) | 4 free event-list calls + **2 credits per match** in the window (hard cap 60/run) | writes the sheet, the FLAGS block, `summary.csv` and any paper bets |
| Pre-kickoff close run | `run.py paper-close` | 0 | **2 credits per match with a paper bet** (6h cache) | only matches that already have a paper bet are fetched |
| Next-morning results run | `run.py paper-settle` | 0 | 0 | results come from football-data.co.uk (free) |
| Weekly refresh | `run.py refresh` | 0 | 0 | current-season results only |

## Budget per matchday (four leagues)

A normal weekend spread over Fri–Sun plus a midweek League One round:

| Day | Matches | Odds API credits (flag run) |
|---|---:|---:|
| Fri | ~9 | ~18 |
| Sat | ~22 | ~44 |
| Sun | ~6 | ~12 |
| Tue | ~4 | ~8 |
| **Week** | **~41** | **~82** |

* **PulseScore:** 4 requests per matchday (league ids cached weekly, so the
  4-page league list is fetched ~once a week). Monthly ≈ **120 + 17 = 137** of the
  configured **400** cap → **66% margin**.
* **Odds API:** ≈ **82 credits/week × 4.3 = ~353/month**, plus close runs (mostly
  served by the 6h cache) ≈ **20/month** → **~373 of 500** → **25% margin**.
  The fair sheet also self-limits: it stops when the account drops below **100**
  credits and never spends more than **60** in one run.

> **If the margin needs to be wider**, switch the fair sheet from the per-event
> odds endpoint (2 credits **per match**) to the league-wide endpoint
> (`/sports/{key}/odds`, 2 credits **per league** per run). That cuts the flag run
> to ~8 credits and the monthly Odds API use to ~**140** (72% margin). It is a
> behaviour change, so it is **not** made here.

## Proposed tasks (Windows Task Scheduler)

Replace `<ROOT>` with `C:\Users\t14s\Desktop\Work\Betting` and `<PY>` with
`<ROOT>\venv\Scripts\python.exe`.

```bat
:: 1. Pre-match flag run — every day at 09:00 local
schtasks /Create /TN "Betting\FairSheet" /SC DAILY /ST 09:00 ^
  /TR "\"<PY>\" \"<ROOT>\run.py\" fair-sheet --days 1" /F

:: 2. Pre-kickoff close run — every 30 min from 12:00 to 21:30 local
schtasks /Create /TN "Betting\PaperClose" /SC DAILY /ST 12:00 /RI 30 /DU 09:30 ^
  /TR "\"<PY>\" \"<ROOT>\run.py\" paper-close" /F

:: 3. Next-morning results run — every day at 08:00 local
schtasks /Create /TN "Betting\PaperSettle" /SC DAILY /ST 08:00 ^
  /TR "\"<PY>\" \"<ROOT>\run.py\" paper-settle" /F

:: 4. Weekly results refresh — Mondays at 07:30 local
schtasks /Create /TN "Betting\Refresh" /SC WEEKLY /D MON /ST 07:30 ^
  /TR "\"<PY>\" \"<ROOT>\run.py\" refresh" /F
```

* Task 2 runs often but is **free** unless a match with a paper bet is within 30
  minutes of kickoff, and the 6h cache means each such match is fetched once.
* Task 3 is free (football-data.co.uk).
* Every task logs to `logs/`; `run.py paper-report` prints the running CLV.

## Approval

**Waiting for the user's OK before creating any task.** Nothing above has been
registered with Task Scheduler.