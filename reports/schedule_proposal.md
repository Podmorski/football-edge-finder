# Schedule — daily fair sheet + paper trading

**Status: ACTIVATED (2026-09-24).** The five tasks are registered with Windows
Task Scheduler by [`scheduler.py`](../scheduler.py). Every run appends to
`logs/scheduler.log`; `reports/health.md` is written daily.

```bash
./venv/Scripts/python.exe scheduler.py create     # register the five tasks
./venv/Scripts/python.exe scheduler.py dry-run    # print the schtasks commands
./venv/Scripts/python.exe scheduler.py disable    # keep them, stop them
./venv/Scripts/python.exe scheduler.py delete     # remove them all
```

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

## Activated tasks (Windows Task Scheduler)

Each task is registered from XML so it gets **start-when-available** (run as soon
as possible after a missed start) and **wake-to-run**, runs with the project root
as its working directory, and appends to `logs/scheduler.log`.

| Task | Trigger | Command |
|---|---|---|
| `Betting\FairSheetDaily` | daily 09:00 | `run.py fair-sheet --days 1` |
| `Betting\FairSheetPreKick` | every 20 min, 10:00–23:00 | `run.py kickoff-run` (~2h before each window) |
| `Betting\PaperClose` | every 15 min, 12:00–22:00 | `run.py paper-close` |
| `Betting\ResultsDaily` | daily 08:00 | `run.py results` (settle + `health.md`) |
| `Betting\Weekly` | Mondays 07:30 | `run.py weekly` |

Replace `<ROOT>` with `C:\Users\t14s\Desktop\Work\Betting` and `<PY>` with
`<ROOT>\venv\Scripts\python.exe`. The exact `schtasks /Create ... /XML` commands
are printed by `scheduler.py dry-run`.

* `FairSheetPreKick` runs often but does nothing unless a kickoff window opens in
  ~2h; `PaperClose` is free unless a match with a paper bet is within 30 minutes
  of kickoff.
* The fixture gate uses the **free** Odds API events endpoint, so a league with no
  match in the window costs zero PulseScore requests.