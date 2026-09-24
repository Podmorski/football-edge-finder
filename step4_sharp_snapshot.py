"""Step 4 — sharp snapshot test (max 20 credits).

Lists upcoming events for the four sport keys (free), then pulls h2h + totals
for region eu for up to five matches (2 credits each). Confirms whether Pinnacle
is present; if not, the median of available books is used and labelled.

Raw responses are saved under data/odds_snapshots/oddsapi/.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

import odds_api_log

BASE = "https://api.the-odds-api.com/v4"
SNAP = Path("data/odds_snapshots/oddsapi")
MAX_CREDITS = 20

SPORTS = {
    "soccer_germany_bundesliga": "bundesliga_1",
    "soccer_germany_bundesliga2": "bundesliga_2",
    "soccer_england_league1": "league_one_t3",
    "soccer_france_ligue_two": "ligue_2_t2",
}

TARGET_HOME = "Hoffenheim"
TARGET_AWAY = "Hamburger SV"


def load_key() -> str:
    for line in Path(".env").read_text().splitlines():
        if line.strip().startswith("ODDS_API_KEY="):
            return line.strip().split("=", 1)[1].strip()
    raise SystemExit("ODDS_API_KEY not found in .env")


def call(session, key, path, params=None, note="", save_as=None):
    query = {"apiKey": key}
    if params:
        query.update(params)
    response = session.get(f"{BASE}{path}", params=query, timeout=30)
    odds_api_log.log_request(
        endpoint=path, params=params or {}, http_status=response.status_code,
        cost=response.headers.get("x-requests-last", ""),
        used=response.headers.get("x-requests-used", ""),
        remaining=response.headers.get("x-requests-remaining", ""), notes=note,
    )
    try:
        data = response.json()
    except Exception:
        data = None
    if save_as and data is not None:
        SNAP.mkdir(parents=True, exist_ok=True)
        (SNAP / save_as).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data, response.headers


def main() -> int:
    key = load_key()
    session = requests.Session()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    spent = 0

    print("=" * 96)
    print("Step 4 — sharp snapshot test (cap 20 credits)")
    print("=" * 96)

    events_by_sport: dict[str, list] = {}
    for sport_key, slug in SPORTS.items():
        data, hdr = call(session, key, f"/sports/{sport_key}/events", note="free",
                         save_as=f"{stamp}_{sport_key}_events.json")
        events = data if isinstance(data, list) else []
        events_by_sport[sport_key] = events
        print(f"  {sport_key:<34} ({slug:<14}) events={len(events):<4} "
              f"cost {hdr.get('x-requests-last')} remaining {hdr.get('x-requests-remaining')}")

    all_events = [(sport, e) for sport, evs in events_by_sport.items() for e in evs]
    print(f"\ntotal upcoming events across the four leagues: {len(all_events)}")

    target = None
    for sport, e in all_events:
        if TARGET_HOME.lower() in e["home_team"].lower() and TARGET_AWAY.lower() in e["away_team"].lower():
            target = (sport, e)
            break
    if target is None:
        for sport, e in all_events:
            if TARGET_HOME.lower() in (e["home_team"] + e["away_team"]).lower():
                target = (sport, e)
                break
    print(f"Hoffenheim vs Hamburger SV listed: {target is not None}")
    if target:
        print(f"  {target[1]['home_team']} vs {target[1]['away_team']} @ {target[1]['commence_time']}")

    # pick the target plus up to four others
    picks = []
    if target:
        picks.append(target)
    for sport, e in all_events:
        if len(picks) >= 5:
            break
        if target and e["id"] == target[1]["id"]:
            continue
        picks.append((sport, e))

    print(f"\npulling h2h + totals for {len(picks)} matches (2 credits each)")
    pinnacle_seen = False
    for sport, e in picks:
        if spent + 2 > MAX_CREDITS:
            print("  credit cap reached")
            break
        data, hdr = call(session, key, f"/sports/{sport}/odds",
                         params={"regions": "eu", "markets": "h2h,totals", "oddsFormat": "decimal"},
                         note=f"sharp snapshot {e['home_team']} vs {e['away_team']}",
                         save_as=f"{stamp}_{sport}_{e['id']}_h2h_totals.json")
        spent += int(hdr.get("x-requests-last") or 0)
        books = sorted({b["key"] for m in (data or []) for b in m.get("bookmakers", [])})
        has_pin = "pinnacle" in books
        pinnacle_seen = pinnacle_seen or has_pin
        print(f"  {e['home_team'][:22]:<24} vs {e['away_team'][:22]:<24} "
              f"books={len(books):<3} pinnacle={'YES' if has_pin else 'no ':<3} "
              f"cost {hdr.get('x-requests-last')} remaining {hdr.get('x-requests-remaining')}")

    print(f"\nPinnacle present in any pull: {pinnacle_seen}")
    if not pinnacle_seen:
        print("  -> fall back to the MEDIAN of available eu books, labelled 'median_eu'")
    print(f"TOTAL CREDITS SPENT: {spent} (cap {MAX_CREDITS})")
    print(f"raw responses -> {SNAP}")
    odds_api_log.print_today()
    return 0


if __name__ == "__main__":
    sys.exit(main())