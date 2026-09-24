"""One-off probe: is the per-league Mozzart endpoint empty while the global feed works?

Answers, with the minimum number of PulseScore requests:

1. Resolve the Mozzart ``leagueId`` for "Engleska 4", "Nemačka 1" and "Engleska 1"
   from ``/soccer/leagues``.
2. Compare ``/soccer/leagues/{id}/events`` against the events the **global**
   ``/soccer/events`` feed tags with the same Serbian league name.
3. Search the full global feed (all pages) by team name for this weekend's
   League One / League Two fixtures and report the league label each is filed
   under, or "absent".

Run:  ./venv/Scripts/python.exe research/mozzart_global_probe.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pulsescore_log  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

BASE = "https://api.pulsescore.net/api/mozzart"
RAW_DIR = Path("data/mozzart/raw")
TIMEOUT = 30
THROTTLE_SECONDS = 1.2

WANT_LEAGUES = ["Engleska 4", "Nemačka 1", "Engleska 1"]

# Team names to look for in the global feed (this weekend's fixtures).
TEAMS = [
    # League One
    "Plymouth", "Burton", "Cambridge", "Wimbledon", "Stockport",
    "Peterborough", "Wycombe", "Reading",
    # League Two (from PS3838)
    "Cheltenham", "Chesterfield", "Accrington", "Barnet", "Bromley",
    "Colchester", "Crawley", "Crewe", "Fleetwood", "Gillingham",
    "Grimsby", "Harrogate", "Milton Keynes", "Newport", "Notts",
    "Oldham", "Port Vale", "Salford", "Shrewsbury", "Swindon",
    "Tranmere", "Walsall",
]

_last_call = [0.0]


def load_key() -> str:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("PULSESCORE_API_KEY="):
            return line.strip().split("=", 1)[1].strip()
    raise SystemExit("PULSESCORE_API_KEY not found in .env")


def call(session, key, path, params=None, note="", save=True):
    allowed, reason = pulsescore_log.budget_ok()
    if not allowed:
        print(f"REFUSED: {reason}")
        return None, None
    wait = THROTTLE_SECONDS - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    response = session.get(f"{BASE}{path}", params=params or {},
                           headers={"X-Secret": key, "Accept": "application/json"},
                           timeout=TIMEOUT)
    _last_call[0] = time.monotonic()
    pulsescore_log.log_request(endpoint=path, params=params or {},
                               http_status=response.status_code, cost=1, notes=note)
    try:
        data = response.json()
    except ValueError:
        data = None
    if save and data is not None:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe = path.strip("/").replace("/", "_")
        (RAW_DIR / f"{safe}__{stamp}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    size = len(data) if isinstance(data, (list, dict)) else "n/a"
    print(f"  GET {path} {params or ''} -> HTTP {response.status_code} ({size})")
    return response.status_code, data


def main() -> int:
    key = load_key()
    session = requests.Session()
    allowed, reason = pulsescore_log.budget_ok()
    print(f"budget: {reason or 'ok'} · remaining {pulsescore_log.remaining_this_month()}")
    if not allowed:
        return 1

    # [1] league list -> ids
    print("\n[1] /soccer/leagues (limit 100)")
    _, doc = call(session, key, "/soccer/leagues", {"page": 1, "limit": 100},
                  note="probe: mozzart league list")
    leagues = (doc or {}).get("leagues", []) if isinstance(doc, dict) else []
    print(f"  {len(leagues)} leagues returned")
    ids = {}
    for lg in leagues:
        if lg.get("name") in WANT_LEAGUES:
            ids[lg["name"]] = str(lg.get("leagueId"))
    for name in WANT_LEAGUES:
        print(f"    {name:<12} leagueId={ids.get(name, 'NOT FOUND')}")

    # [2] per-league endpoint counts
    print("\n[2] /soccer/leagues/{id}/events")
    per_league = {}
    for name, lid in ids.items():
        _, ev = call(session, key, f"/soccer/leagues/{lid}/events", {},
                     note=f"probe: per-league {name}")
        events = (ev or {}).get("events", []) if isinstance(ev, dict) else []
        per_league[name] = events
        print(f"    {name:<12} id={lid} -> {len(events)} event(s)")

    # [3] global feed, all pages
    print("\n[3] /soccer/events (global, paged)")
    global_events: list[dict] = []
    page = 1
    total = None
    while page <= 20:
        _, doc = call(session, key, "/soccer/events",
                      {"page": page, "limit": 200},
                      note=f"probe: global events p{page}", save=(page == 1))
        if not isinstance(doc, dict):
            break
        if total is None:
            total = doc.get("total")
        batch = doc.get("events", [])
        global_events += batch
        print(f"    page {page}: {len(batch)} event(s) (total field: {doc.get('total')})")
        if not batch or (total is not None and len(global_events) >= total):
            break
        page += 1
    print(f"  global feed: {len(global_events)} event(s) over {page} page(s)")

    # [3a] league labels in the global feed
    by_label: dict[str, int] = {}
    for event in global_events:
        label = event.get("league") or event.get("leagueName") or "?"
        by_label[label] = by_label.get(label, 0) + 1
    print("\n  league labels in the global feed (top 40 by count):")
    for label, n in sorted(by_label.items(), key=lambda kv: -kv[1])[:40]:
        print(f"    {n:>4}  {label}")

    print("\n  wanted labels:")
    for name in WANT_LEAGUES:
        print(f"    {name:<12} per-league={len(per_league.get(name, []))} "
              f"global={by_label.get(name, 0)}")

    # [3b] team-name search
    print("\n[4] team-name search in the global feed")
    for team in TEAMS:
        hits = []
        for event in global_events:
            home = event.get("home") or ""
            away = event.get("away") or ""
            if team.lower() in home.lower() or team.lower() in away.lower():
                hits.append((event.get("league") or "?", home, away,
                             event.get("startTime", "")))
        if hits:
            for label, home, away, when in hits:
                print(f"    {team:<14} -> [{label}] {home} vs {away} @ {when}")
        else:
            print(f"    {team:<14} -> absent")

    print(f"\nrequests this run: {pulsescore_log.used_this_month()} used this month, "
          f"{pulsescore_log.remaining_this_month()} remaining")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())