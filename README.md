# football-edge-finder

Phase 1 of a football data pipeline: historical results, xG coverage testing,
and a daily fixture pull for three in-scope leagues. This is a research /
modelling project — every source is accessed through its public, documented,
rate-limit-respecting interface.

## Leagues in scope

Every league is labelled with its **tier** (division level within that country's
pyramid) so that same-named divisions can never be confused.

| League | Tier | Country | API-Football ID | football-data slug | Understat |
|---|---|---|---|---|---|
| 2. Bundesliga | 2 | Germany | 79 | `D2` | not covered |
| League One | 3 | England | 41 | `E2` | not covered |
| Ligue 2 | 2 | France | 62 | `F2` | not covered |

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
# source venv/bin/activate && pip install -r requirements.txt  # POSIX
```

Create `.env` from the template and add your own key:

```bash
cp .env.example .env
# then edit .env and set API_FOOTBALL_KEY=<your key>
```

`.env` is gitignored and must never be committed. `data/` is gitignored too —
all datasets are regenerated locally by the scripts.

## Scripts

### `smoke_test.py`
Confirms `penaltyblog` imports and prints its installed version.

```bash
./venv/Scripts/python.exe smoke_test.py
```

### `ingest_historical.py`
Pulls historical match results from **football-data.co.uk** via `penaltyblog`
for every in-scope league, one parquet file per league under
`data/historical/`, named by the tier-qualified slug.

```bash
./venv/Scripts/python.exe ingest_historical.py
```

Outputs: `data/historical/bundesliga_2.parquet`, `league_one_t3.parquet`,
`ligue_2_t2.parquet`.

### `ingest_xg.py`
Understat xG **coverage test** via `penaltyblog`. A league returning nothing is
a valid, expected outcome and is reported plainly rather than debugged. Writes
`data/xg/<slug>.parquet` only for leagues that return data.

```bash
./venv/Scripts/python.exe ingest_xg.py
```

### `get_fixtures.py`
Pulls **tomorrow's** fixtures from **API-Football** for the in-scope leagues.
Loads `API_FOOTBALL_KEY` from `.env` (never hardcoded). Classifies each league's
outcome as `fixtures returned` / `no matches scheduled` / `plan/access error` /
`auth error` / `api error`, so an empty result is never confused with an access
problem. Reports how many of the 100 daily free requests were used.

```bash
./venv/Scripts/python.exe get_fixtures.py
```

## Findings and decisions

### Serbian SuperLiga was probed and dropped
Serbian SuperLiga (API-Football ID 287) was in the original scope but was
**probed and removed**:

- It is absent from `penaltyblog`'s football-data.co.uk competition list and
  from Understat, so neither historical source covers it.
- API-Football *does* have it, but the free plan only exposes seasons
  **2022–2024** (`{'plan': 'Free plans do not have access to this season, try
  from 2022 to 2024.'}`). That is a fixed 3-season block that will not grow on
  the free tier, and there is no xG for it.
- Decision: dropped from Phase 1 and replaced with **Ligue 2** (ID 62).

### ID 79 is 2. Bundesliga, not the top-flight Bundesliga
`/leagues?id=79` returns **"2. Bundesliga"** (Germany, tier 2). The top-flight
Bundesliga is **ID 78**, which is deliberately **not used anywhere** in this
project. The in-scope league is the second division, matching football-data
slug `D2`.

Any earlier top-flight Bundesliga artefacts (`data/historical/bundesliga.parquet`,
`data/xg/bundesliga.parquet`) are **out of scope and left untouched** — they are
not produced by the scripts and must not be mixed into 2. Bundesliga work.

### API-Football free-tier constraint
The league-scoped fixtures query (`/fixtures?league=<id>&season=<year>`) is
rejected on the free plan for the current season. The **date-only** query
(`/fixtures?date=<YYYY-MM-DD>`) is not season-gated and works, so
`get_fixtures.py` uses it and filters by league ID locally.

## Repository hygiene

- `.env` — secrets, gitignored, never committed.
- `data/` — generated datasets, gitignored.
- `venv/` — virtual environment, gitignored.
