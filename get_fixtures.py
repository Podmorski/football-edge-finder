"""Pull tomorrow's fixtures for the in-scope leagues from API-Football.

Source: https://v3.football.api-sports.io/ (documented public API).
Auth: ``x-apisports-key`` header, loaded from ``.env`` (never hardcoded, never
committed).

IMPORTANT — free-tier constraint discovered in Step 6:
The league-scoped query ``/fixtures?league=<id>&season=<year>`` is rejected on
the free plan with::

    {'plan': 'Free plans do not have access to this season, try from 2022 to 2024.'}

The date-only query ``/fixtures?date=<YYYY-MM-DD>`` is NOT season-gated and
works on the free plan. This script therefore uses the date-only endpoint and
filters the response by league id.

Outcomes are classified explicitly so that an empty result is never confused
with an access problem:

  - fixtures returned
  - no matches scheduled
  - plan/access error
  - auth error
  - api error
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import requests

BASE_URL = "https://v3.football.api-sports.io"
DAILY_FREE_LIMIT = 100

# In-scope leagues, tier-labelled. IDs verified against /leagues?id= in Step 3.
LEAGUES = [
    {"name": "2. Bundesliga", "tier": 2, "api_football_id": 79},
    {"name": "League One", "tier": 3, "api_football_id": 41},
    {"name": "Ligue 2", "tier": 2, "api_football_id": 62},
]

PLACEHOLDER = "REPLACE_ME_WITH_YOUR_REAL_KEY"


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


def classify(data: dict) -> str:
    """Classify an API-Football response so empty != error."""
    errors = data.get("errors")
    if errors:
        text = str(errors).lower()
        if any(word in text for word in ("plan", "subscription", "do not have access")):
            return "plan/access error"
        if any(word in text for word in ("token", "key", "auth", "application")):
            return "auth error"
        return "api error"
    if not (data.get("response") or []):
        return "no matches scheduled"
    return "fixtures returned"


def main() -> int:
    key = load_api_key()
    headers = {"x-apisports-key": key}

    tomorrow = date.today() + timedelta(days=1)
    date_str = tomorrow.isoformat()

    requests_used = 0
    print(f"Target date (tomorrow): {date_str}\n")

    # Single date-only call (free-tier safe), then filter by league locally.
    response = requests.get(
        f"{BASE_URL}/fixtures", params={"date": date_str}, headers=headers, timeout=30
    )
    requests_used += 1
    data = response.json()

    print(f"=== date-only query | HTTP {response.status_code} ===")
    print(f"  errors  : {data.get('errors')}")
    print(f"  results : {data.get('results')}")
    print(f"  outcome : {classify(data)}\n")

    all_fixtures = data.get("response") or []

    for league in LEAGUES:
        label = f"{league['name']} (tier {league['tier']})"
        matches = [f for f in all_fixtures if f.get("league", {}).get("id") == league["api_football_id"]]

        if data.get("errors"):
            outcome = classify(data)
        elif matches:
            outcome = "fixtures returned"
        else:
            outcome = "no matches scheduled"

        print(f"=== {label} | id={league['api_football_id']} ===")
        print(f"  outcome : {outcome}")
        for fixture in matches:
            fx = fixture.get("fixture", {})
            teams = fixture.get("teams", {})
            home = teams.get("home", {}).get("name")
            away = teams.get("away", {}).get("name")
            print(f"    {fx.get('date')} | {home} vs {away} | status {fx.get('status', {}).get('short')}")
        print()

    # Account-level quota view. This call also counts against the daily limit.
    status_response = requests.get(f"{BASE_URL}/status", headers=headers, timeout=30)
    requests_used += 1
    status = status_response.json()
    print("=== account status ===")
    print("  errors  :", status.get("errors"))
    print("  response:", status.get("response"))

    print(
        f"\nRequests used by this script: {requests_used} "
        f"of {DAILY_FREE_LIMIT} daily free requests."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
