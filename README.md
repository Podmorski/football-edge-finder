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
./venv/Scripts/python.exe run.py kickoff-run           # pre-kickoff dispatcher
./venv/Scripts/python.exe run.py log-close
./venv/Scripts/python.exe run.py paper-close           # <= 30 min before kickoff
./venv/Scripts/python.exe run.py paper-settle          # next morning
./venv/Scripts/python.exe run.py paper-report
./venv/Scripts/python.exe run.py results               # settle + write reports/health.md
./venv/Scripts/python.exe run.py weekly                # refresh + top-up + report
./venv/Scripts/python.exe run.py budget-plan           # monthly API budget + margin
./venv/Scripts/python.exe scheduler.py create          # register the 5 Windows tasks
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
| `fair_sheet.py` | Daily Pinnacle-anchored fair odds + minimum acceptable odds, with a **FLAGS** block joining Mozzart prices | `reports/fair_sheets/<date>.md` / `.csv`, `reports/fair_sheets/summary.csv` |
| `ps3838_odds.py` | **Primary sharp source**: PS3838 (Pinnacle) via PulseScore, fetched in the same run as Mozzart | `data/ps3838/leagues/<slug>.json` |
| `mozzart_odds.py` | Mozzart (PulseScore) pre-match odds from the **global** feed, filtered locally by Serbian league label (the per-league endpoint is empty on the free tier) | `data/mozzart/global_events.json`, `data/mozzart/raw/` |
| `paper_trade.py` | Automatic paper trading by **track**: record flags, save the PS3838 close, settle, report | `data/paper/paper_bets.csv` |
| `flag_audit.py` | First 10 flags per track with raw prices + a SUSPECT flag-rate check | `reports/flag_audit.md` |
| `scores.py` | Results for the widened leagues via The Odds API **scores** (fallback) | — |
| `kickoff_run.py` | Derives the day's kickoff windows and runs the sheet ~2h before one | — |
| `weekly.py` | Weekly refresh + Mozzart top-up check + paper report | `reports/paper_report.md` |
| `health.py` | Daily health summary | `reports/health.md` |
| `budget_plan.py` | Recomputed monthly budget + margin for both APIs | stdout |
| `scheduler.py` | Windows Task Scheduler tasks (create/delete/dry-run) | `logs/scheduler.log` |
| `pulsescore_log.py` | Local PulseScore request log + monthly budget (cap 400, stop at 50) | `logs/pulsescore_requests.csv` |
| `team_audit_mozzart.py` | Cross-source team-name audit (Mozzart / Odds API / historical) | stdout |
| `bet_log.py` | Closing price + result per logged bet; CLV and P&L | fills `data/bet_log.csv` |
| `step6_mainline_hist.py` | MAINLINE-HIST-1: the pre-registered soft-book backtest | `reports/figures/mainline_hist_*.csv` |
| `mainline_data_check.py` | Coverage + price-comparability check for that backtest | `reports/figures/mainline_hist_data_check.csv` |
| `audit_clv.py` | Independent CLV re-implementation and audit (no project imports) | stdout |
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
(`fair x 1.035`) for the code **inside its section**. Rows carry the columns
`SECTION | CODE | MEANING | FAIR | BET ONLY IF ODDS >= ...`, ordered by the
family's typical Serbian-book margin (lowest first), at most 3 prices per family
and 15 rows per match, so the cheapest sections are the ones you check first.

Markets read straight off the sharp price (**RESULT, DOUBLE_CHANCE, full-time
No-Bet, and the goal totals from the sharp 1X2 + totals line**) are marked
`SHARP`; everything else shown is a family whose calibration **PASSED** on unseen
seasons. UNTESTABLE / UNCONFIRMED markets are hidden.

### PS3838 sharp source, Mozzart flags and paper trading

The sheet anchors on **PS3838 (Pinnacle) via PulseScore** — the **primary sharp
source**, read in the **same run** as the Mozzart feed so the two snapshots are
minutes apart. The Odds API is a **fallback only** (the league-wide odds
endpoint, never per event) and supplies **scores** for the widened leagues. The
sheet joins **Mozzart**'s pre-match prices to our fair odds and prints a **FLAGS**
block at the top: match, kickoff, **track**, Serbian section, code, plain-English
meaning, Mozzart odds, minimum acceptable odds (`fair x 1.035`) and **EV after a
20% haircut**. A market is flagged only when the family PASSed (or is a SHARP
main-line market), the Mozzart price is at or above `fair x 1.035`, and the two
snapshots are within 60 minutes (else `STALE`). If nothing qualifies the sheet
prints **“No value today.”**

Every flag becomes one **paper** bet (1 unit at the Mozzart price) in
`data/paper/paper_bets.csv`, tagged with its **track**:

* **SHARP_WIDE** — a sharp main-line market (RESULT, DOUBLE_CHANCE, full-time
  No-Bet, the FT goal totals), run in **every league where both books price it**;
* **MODEL_4L** — a model family, limited to our four modelled leagues.

`run.py paper-close` saves the de-margined **PS3838** close for matches with paper
bets within 30 minutes of kickoff; `run.py paper-settle` settles finished bets
(local history for the modelled leagues, The Odds API **scores** for the widened
ones); `run.py paper-report` prints n, mean CLV with a 95% CI, virtual P&L, and
the same split **by track, league and family**, gating each track separately.
**No bet is ever placed automatically.**

The widened set and the budget are in [`config/leagues_wide.yaml`](config/leagues_wide.yaml)
and `run.py budget-plan`. The **activated** Task Scheduler setup is
[`reports/schedule_proposal.md`](reports/schedule_proposal.md) and
`scheduler.py`; `reports/flag_audit.md` audits the first flags of each track and
`reports/health.md` records the daily loop.

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

**The section decides a code's meaning, never the bare code.** Every market
carries a Serbian `section` (as displayed by Soccer Bet), and the parser derives
the family from it: `1` is a home win under *Konačni Ishod* and exactly one goal
under *Ukupno Golova*; `I1` is a 1st-half home win under *Poluvreme* but exactly
one 1st-half goal under *I Pol. Uk. Golova*. Inside a goal family a leg is always
a goal total. A prefix whose display name is not confirmed is flagged
`(section not confirmed)` rather than guessed.

`ext_markets` is a separate section on purpose: it is keyed by prefix because the
same bare code means different things under different prefixes, and it omits any
code whose settlement matches a base market exactly **when its family is already
in the base catalogue**, so the two sections together list each distinct market
once. A printed code inside a family the base does not cover is always kept, and
one that happens to settle like a base market is recorded in
`settles_like_a_base_market` rather than hidden. Regenerating the catalogue keeps
`ext_markets` unchanged when the sample capture is absent (`data/` is gitignored).

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