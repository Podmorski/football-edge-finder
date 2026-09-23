"""Pull fixtures for a date from API-Football, for the in-scope leagues.

Source: https://v3.football.api-sports.io/ (documented public API).
Auth: ``x-apisports-key`` header, loaded from ``.env`` (never hardcoded, never
committed).

Free-plan restrictions (both gates observed in practice):

1. **Season gate** — the league-scoped query
   ``/fixtures?league=<id>&season=<year>`` is rejected with::

       {'plan': 'Free plans do not have access to this season, try from 2022 to 2024.'}

2. **Date gate** — the date-only query ``/fixtures?date=<YYYY-MM-DD>`` is
   rejected for dates outside a rolling window of ``today +/- 1 day``::

       {'plan': 'Free plans do not have access to this date, try from <today-1> to <today+1>.'}

This script therefore:

* uses the date-only endpoint and filters by league id locally;
* refuses to spend a request on an out-of-window date (see
  ``FREE_PLAN_WINDOW_DAYS``; set it to ``None`` on a paid plan);
* saves each successful pull so it never needs repeating:
  - raw JSON -> ``data/fixtures/raw/<date>.json``
  - filtered in-scope fixtures -> ``data/fixtures/<date>.csv``

Every request is recorded in the local request log (see ``api_log``).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

import api_log
from leagues import LEAGUES, label_of

BASE_URL = "https://v3.football.api-sports.io"

# Rolling window (days either side of "today") the free plan will serve.
# Set to None on a paid plan to disable the guard entirely.
FREE_PLAN_WINDOW_DAYS: int | None = 1

RAW_DIR = Path("data/fixtures/raw")
FILTERED_DIR = Path("data/fixtures")

PLACEHOLDER = "REPLACE_ME_WITH_YOUR_REAL_KEY"

CSV_COLUMNS = [
    "fixture_id",
    "date",
    "league_id",
    "league_name",
    "season",
    "round",
    "team_home",
    "team_away",
    "status",
    "goals_home",
    "goals_away",
]


def load_api_key() -> str:
    """Load API_FOOTBALL_KEY from .env without hardcoding it."""
    env_path = Path(".env")
    if not env_path.exists():
        raise SystemExit("ERROR: .env not found. Create it with API_FOOTBALL_KEY=...")

    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("API_FOOTBALL_KEY="):
            key = line.split("=", 1)[1].strip()
            if not key or key == PLACEHOLDER:
                raise SystemExit("ERROR: API_FOOTBALL_KEY in .env is still the placeholder.")
            return key

    raise SystemExit("ERROR: API_FOOTBALL_KEY not found in .env.")


def classify_error(errors: object) -> str | None:
    """Return 'plan_access_error', 'auth_request_error', or None."""
    if not errors:
        return None
    text = str(errors).lower()
    if any(w in text for w in ("plan", "subscription", "do not have access")):
        return "plan_access_error"
    if any(w in text for w in ("token", "key", "auth", "application", "not found")):
        return "auth_request_error"
    return "auth_request_error"


def describe(fixture: dict) -> str:
    fx = fixture.get("fixture", {})
    teams = fixture.get("teams", {})
    home = teams.get("home", {}).get("name")
    away = teams.get("away", {}).get("name")
    season = fixture.get("league", {}).get("season")
    return f"{fx.get('date')} | {home} vs {away} | season={season} | status {fx.get('status', {}).get('short')}"


def check_window(target: date) -> bool:
    """Guard: refuse to spend a request on a date the free plan will reject.

    The provider's window appears to be UTC-based, so the check uses the UTC
    date and warns when the local date differs.
    """
    if FREE_PLAN_WINDOW_DAYS is None:
        print("Window guard disabled (FREE_PLAN_WINDOW_DAYS is None — paid plan assumed).")
        return True

    local_today = date.today()
    utc_today = datetime.now(timezone.utc).date()
    if local_today != utc_today:
        print(
            f"WARNING: local date ({local_today}) != UTC date ({utc_today}). "
            "The provider's window is UTC-based; the check uses UTC."
        )

    low = utc_today - timedelta(days=FREE_PLAN_WINDOW_DAYS)
    high = utc_today + timedelta(days=FREE_PLAN_WINDOW_DAYS)
    print(f"Free-plan date window (UTC ref {utc_today}): {low} .. {high}")

    if low <= target <= high:
        return True

    print(
        f"REFUSING: {target} is outside the free-plan window {low}..{high}.\n"
        "  No request spent. The plan would reject this with "
        "\"Free plans do not have access to this date\".\n"
        "  (Set FREE_PLAN_WINDOW_DAYS = None if you move to a paid plan.)"
    )
    return False


def flatten(fixtures: list[dict]) -> list[dict]:
    rows = []
    for fixture in fixtures:
        fx = fixture.get("fixture", {})
        league = fixture.get("league", {})
        teams = fixture.get("teams", {})
        goals = fixture.get("goals", {})
        rows.append(
            {
                "fixture_id": fx.get("id"),
                "date": fx.get("date"),
                "league_id": league.get("id"),
                "league_name": league.get("name"),
                "season": league.get("season"),
                "round": league.get("round"),
                "team_home": teams.get("home", {}).get("name"),
                "team_away": teams.get("away", {}).get("name"),
                "status": fx.get("status", {}).get("short"),
                "goals_home": goals.get("home"),
                "goals_away": goals.get("away"),
            }
        )
    return rows


def save_pull(date_str: str, data: dict) -> tuple[Path, Path]:
    """Persist the raw response and the filtered in-scope fixtures."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    FILTERED_DIR.mkdir(parents=True, exist_ok=True)

    raw_path = RAW_DIR / f"{date_str}.json"
    raw_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    all_fixtures = data.get("response") or []
    in_scope_ids = {league["api_football_id"] for league in LEAGUES}
    scoped = [f for f in all_fixtures if f.get("league", {}).get("id") in in_scope_ids]

    csv_path = FILTERED_DIR / f"{date_str}.csv"
    pd.DataFrame(flatten(scoped), columns=CSV_COLUMNS).to_csv(csv_path, index=False)
    return raw_path, csv_path


def run(date_str: str) -> int:
    target = date.fromisoformat(date_str)
    if not check_window(target):
        return 2

    key = load_api_key()
    params = {"date": date_str}
    response = requests.get(
        f"{BASE_URL}/fixtures", params=params, headers={"x-apisports-key": key}, timeout=30
    )
    data = response.json()
    all_fixtures = data.get("response") or []

    api_log.log_request(
        endpoint="/fixtures",
        params=params,
        http_status=response.status_code,
        results_count=data.get("results"),
        errors=data.get("errors"),
    )

    print(f"\n=== RAW DIAGNOSTICS | date={date_str} | HTTP {response.status_code} ===")
    print(f"  total results        : {data.get('results')}")
    print(f"  errors (verbatim)    : {data.get('errors')}")
    print(f"  distinct league IDs  : {len({f.get('league', {}).get('id') for f in all_fixtures})}")
    seasons = sorted({f.get('league', {}).get('season') for f in all_fixtures if f.get('league')})
    print(f"  distinct seasons     : {seasons}")
    print()

    error_class = classify_error(data.get("errors"))

    for league in LEAGUES:
        matches = [f for f in all_fixtures if f.get("league", {}).get("id") == league["api_football_id"]]
        print(f"=== {label_of(league)} | id={league['api_football_id']} ===")

        if error_class:
            print(f"  CLASSIFY: {error_class}")
            print(f"  errors  : {data.get('errors')}")
        elif matches:
            print(f"  CLASSIFY: fixtures_returned (count={len(matches)})")
            for fixture in matches[:2]:
                print(f"    {describe(fixture)}")
        else:
            print("  CLASSIFY: no_matches_scheduled (single-date view)")
        print()

    if not error_class:
        raw_path, csv_path = save_pull(date_str, data)
        print(f"Saved raw   -> {raw_path}")
        print(f"Saved scope -> {csv_path}")

    print(f"Logged: {api_log.today_count()} API-Football request(s) today (from local log).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull fixtures for a date.")
    parser.add_argument(
        "--date",
        default=None,
        help="Target date as YYYY-MM-DD. Defaults to tomorrow (local date).",
    )
    args = parser.parse_args(argv)

    date_str = args.date or (date.today() + timedelta(days=1)).isoformat()
    return run(date_str)


if __name__ == "__main__":
    sys.exit(main())