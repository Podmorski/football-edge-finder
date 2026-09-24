# football-edge-finder

Phase 1 of a football data pipeline: historical results, xG coverage testing,
and a daily fixture pull. This is a research / modelling project — every source
is accessed through its public, documented, rate-limit-respecting interface.

## Leagues in scope

Every league is labelled with its **tier** (division level within that country's
pyramid) and **role** (`baseline` = top-flight reference league; `target` =
in-scope league) so that same-named divisions can never be confused. The single
source of truth is [`leagues.py`](leagues.py).

| League | Tier | Role | API-Football ID | football-data code | Understat |
|---|---|---|---|---|---|
| 2. Bundesliga | 2 | target | 79 | `D2` | not covered |
| Bundesliga | 1 | **baseline** | 78 | `D1` | covered |
| League One | 3 | target | 41 | `E2` | not covered |
| Ligue 2 | 2 | target | 62 | `F2` | not covered |

## Data sources

| Source | Used for | Access method | Auth |
|---|---|---|---|
| [football-data.co.uk](https://www.football-data.co.uk/) | Historical results | `penaltyblog` `FootballData` scraper (per-season CSV) | none |
| [Understat](https://understat.com/) | xG | `penaltyblog` `Understat` scraper (`getLeagueData` JSON) | none |
| [API-Football](https://www.api-football.com/) | Daily fixtures | `GET /fixtures?date=` | `x-apisports-key` header |

## Setup

Requires Python 3.12.

```bash
python -m venv venv
./venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
```

`requirements.txt` is the top-level list. For **reproducible results**, install
the fully pinned set instead:

```bash
./venv/Scripts/python.exe -m pip install -r requirements-lock.txt
```

The lock file is the exact environment every result in `reports/` was produced
with. Results are sensitive to library versions, so prefer the lock file when
re-running anything.

Create `.env` from the template and add your own key:

```bash
cp .env.example .env
# then edit .env and set API_FOOTBALL_KEY=<your key>
```

`.env` is gitignored and must never be committed.

## Running — `run.py`

A Windows-friendly runner; no make required.

```bash
./venv/Scripts/python.exe run.py ingest-historical
./venv/Scripts/python.exe run.py ingest-xg
./venv/Scripts/python.exe run.py refresh
./venv/Scripts/python.exe run.py fixtures              # tomorrow (local date)
./venv/Scripts/python.exe run.py fixtures --date 2026-09-24
./venv/Scripts/python.exe run.py requests-today
./venv/Scripts/python.exe run.py snapshot-fd
./venv/Scripts/python.exe run.py fair-sheet --date 2026-09-25 --days 3
./venv/Scripts/python.exe run.py log-close
```

## Scripts

| Script | What it does | Output |
|---|---|---|
| `leagues.py` | Canonical tier/role-labelled league registry | — |
| `api_log.py` | Local API-Football request log + today's count | `logs/api_requests.csv` |
| `smoke_test.py` | Confirms `penaltyblog` imports; prints version | stdout |
| `ingest_historical.py` | Full history from football-data.co.uk | `data/historical/<slug>.parquet` |
| `ingest_xg.py` | Understat xG coverage test | `data/xg/<slug>.parquet` (covered leagues only) |
| `refresh_historical.py` | Re-pulls the **current season only** and merges | updates `data/historical/<slug>.parquet` |
| `get_fixtures.py` | Fixtures for a date via API-Football | `data/fixtures/raw/<date>.json`, `data/fixtures/<date>.csv` |
| `team_audit.py` | Team-name audit per league (local only) | `reports/team_audit_<slug>.md` |
| `fair_sheet.py` | Daily Pinnacle-anchored fair odds + minimum acceptable odds | `reports/fair_sheets/<date>.md` / `.csv` |
| `bet_log.py` | Closing price + result per logged bet; CLV and P&L | fills `data/bet_log.csv` |
| `run.py` | Runner for all of the above | — |

`refresh_historical.py` de-duplicates on `(date, team_home, team_away)` and is
idempotent — running it twice adds 0 rows the second time.

## Regenerating `data/`

`data/` is gitignored; everything under it is rebuilt locally.

```bash
# Full rebuild from scratch (all seasons, all leagues)
./venv/Scripts/python.exe run.py ingest-historical
./venv/Scripts/python.exe run.py ingest-xg

# Daily / routine: pull only the current season and merge
./venv/Scripts/python.exe run.py refresh

# Fixtures (defaults to tomorrow)
./venv/Scripts/python.exe run.py fixtures

# Local investigation
./venv/Scripts/python.exe team_audit.py
```

## Odds recorder (Phase 1.5)

The project is **not** price-hunting. The recorder exists to build a history of
**market-average payouts for markets that have no historical prices on
football-data.co.uk** — BTTS, alternate goal lines, half-time markets, correct
score, HT/FT and same-game combos — so the payout check can be run on them
later. h2h and totals 2.5 are already covered free by football-data.co.uk and
are deliberately **not** the priority.

### Two request logs

Both live under `logs/` (gitignored) and are the source of truth for quota,
because provider counters lag.

| Log | Covers | Helper |
|---|---|---|
| `logs/api_requests.csv` | API-Football (`/fixtures`, `/status`) | `api_log.py`, `run.py requests-today` |
| `logs/odds_api_requests.csv` | The Odds API (credits from `x-requests-*` headers) | `odds_api_log.py` |

### `run.py snapshot-fd`

Saves `https://football-data.co.uk/fixtures.csv` to
`data/odds_snapshots/fd/<timestamp>.csv` **only if its content hash changed**,
so repeated runs are free no-ops. This is the only forward-looking fixture
source available without an API key, and it is the free fallback for the odds
recorder.

### The Odds API probe

`oddsapi_probe.py` performs a bounded, fully logged probe (hard cap 10 credits)
and writes raw responses to `data/odds_snapshots/oddsapi/`. Findings and the
proposed snapshot plan are in `reports/phase2_step6_league_one.md`.

## The daily fair-odds sheet

```bash
./venv/Scripts/python.exe run.py fair-sheet --date 2026-09-25 --days 3
./venv/Scripts/python.exe run.py log-close          # after the matches
```

`fair-sheet` pulls the upcoming events for the four sport keys (free), then
Pinnacle h2h + totals for each match in the window (region `eu`, 2 credits per
match, **cached per match for 6h**, hard cap **60 credits per run**, stops when the
account drops below **100**). It de-margins Pinnacle with the **power** method,
solves the half model's `(lambda, mu)` anchor on it, and prices every market in
the catalogue plus every market in the catalogue's `ext_markets` section.

Each row states the **fair odds** and the **minimum acceptable odds**
(`fair x 1.035`). Only families whose calibration **PASSED** are shown, plus the
four main-line families (RESULT, DOUBLE_CHANCE, GOAL_RANGE_FT, NO_BET) whose price
is the sharp anchor itself. UNTESTABLE / UNCONFIRMED markets are hidden.

The anchor is only as fresh as the snapshot printed at the top of the sheet:
**odds move — re-run within ~1h of betting.**

Bet settlements and closing-line value are in
[`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) (decision log), including the rule
that **no conclusion is drawn before 50 logged bets**.

### The catalogue has two sections

| Section | Keyed by | Generated from |
|---|---|---|
| `markets` | bare code | `docs/soccerbet_rules_sr.txt` (`step1_catalogue.py`) |
| `ext_markets` | printed `PREFIX` | `core/soccerbet_ext.py` + the sample capture |

`ext_markets` is a separate section on purpose: it is keyed by prefix because the
same bare code means different things under different prefixes, and it omits any
code whose settlement matches a base market exactly, so the two sections together
list each distinct market once. Regenerating the catalogue keeps `ext_markets`
unchanged when the sample capture is absent (`data/` is gitignored).

### Fitted half-model parameters are cached on disk

`data/cache/half_params/` holds the L2/L3 fit per league, keyed by an exact hash of
its inputs. The fit is deterministic, so the cache only saves the ~40 s per league
that solving an anchor for every training match would otherwise cost on every run.

## Findings and decisions

### Serbian SuperLiga was probed and dropped
Serbian SuperLiga (API-Football ID 287) was in the original scope but was
probed and removed: it is absent from `penaltyblog`'s football-data.co.uk
competition list and from Understat, and the API-Football free plan only
exposes seasons 2022–2024 for it. It was replaced with **Ligue 2** (ID 62).

### ID 79 is 2. Bundesliga; ID 78 is the top-flight Bundesliga
`/leagues?id=79` returns **"2. Bundesliga"** (Germany, tier 2). The top-flight
Bundesliga is **ID 78**. Per project decision:
- **ID 79 / `D2`** is the in-scope `target` league → `bundesliga_2`.
- **ID 78 / `D1`** is the `baseline` league → `bundesliga_1`.

Both are ingested, clearly labelled, and stored in *separate* files
(`bundesliga_1.parquet` vs `bundesliga_2.parquet`) so tiers can never be mixed.
Historical and xG artefacts are never shared between them.

### API-Football free plan — two independent gates
Both gates were observed in practice against the free plan. `get_fixtures.py`
works within them and **refuses to spend a request on a date the plan will
reject**.

1. **Season gate** — the league-scoped query
   `/fixtures?league=<id>&season=<year>` is rejected for the current season:

   ```
   {'plan': 'Free plans do not have access to this season, try from 2022 to 2024.'}
   ```

2. **Date gate** — the date-only query `/fixtures?date=<YYYY-MM-DD>` only serves
   a rolling window of **`today ± 1 day`**:

   ```
   {'plan': 'Free plans do not have access to this date, try from 2026-09-22 to 2026-09-24.'}
   ```

Consequences:
- `get_fixtures.py` uses the **date-only** endpoint and filters by league ID
  locally. It defaults to tomorrow and refuses out-of-window dates with a clear
  message (`FREE_PLAN_WINDOW_DAYS = 1`; set it to `None` on a paid plan).
- A daily pull of *tomorrow's* fixtures works, since tomorrow is always inside
  the window. Scheduling further ahead is not possible on the free plan.
- The window check is computed from the **UTC** date (the provider's window
  appears UTC-based) and warns if the local and UTC dates differ.

### Understat xG coverage
Only the **baseline** league (Bundesliga, `bundesliga_1`) has xG. All three
`target` leagues are **goals-only** — Understat does not cover 2. Bundesliga,
League One, or Ligue 2.

### COVID-2019-20
The **2019-20 season was curtailed in both League One and Ligue 2**, so those
seasons have fewer matches than a normal campaign (League One: 400 rows vs. the
usual 552; Ligue 2: 280 vs. 380). This is expected and not a data error.

## Request log

The provider's own `/status` counter lags, so the **local log is the source of
truth** for API-Football quota usage.

- Every call goes through `api_log.log_request` → `logs/api_requests.csv`
  (gitignored): timestamp, endpoint, params, HTTP status, results count, errors.
- `./venv/Scripts/python.exe run.py requests-today` prints today's count.
- Calls made before logging existed are recorded as one `prior-estimate` row.

## Repository hygiene

Tracked: source, `README.md`, `reports/`. Gitignored: `.env`, `data/`, `logs/`,
`venv/`.