"""B2 — The Odds API probe (hard cap: 10 credits total).

Sequence:
  1. GET /v4/sports                      (free)  -> sport keys
  2. GET /v4/sports/{key}/events         (free)  -> pick a league with fixtures soon
  3. GET /v4/sports/{key}/events/{id}/markets?regions=eu   (1 credit) -> which markets exist
  4. GET /v4/sports/{key}/odds?regions=eu&markets=h2h,totals (2 credits) -> featured snapshot
  5. GET /v4/sports/{key}/events/{id}/odds?regions=eu&markets=... (<=5 credits) -> additional markets

Every call is logged to logs/odds_api_requests.csv. Raw responses are saved to
data/odds_snapshots/oddsapi/.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import odds_api_log

BASE = "https://api.the-odds-api.com/v4"
SNAP_DIR = Path("data/odds_snapshots/oddsapi")
MAX_CREDITS = 10

# The four leagues we care about, by likely sport-key fragment.
WANTED = {
    "soccer_germany_bundesliga": "Bundesliga (baseline)",
    "soccer_germany_bundesliga2": "2. Bundesliga",
    "soccer_england_league1": "League One",
    "soccer_france_ligue2": "Ligue 2",
}

BALKAN = ("soccerbet", "mozzart", "meridian", "maxbet", "balkan", "serbia")


def load_key() -> str:
    for line in Path(".env").read_text().splitlines():
        line = line.strip()
        if line.startswith("ODDS_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("ODDS_API_KEY not found in .env")


def call(session, key, path, params=None, note="", save_as=None):
    """One logged GET. Returns (json_or_None, headers_dict)."""
    query = {"apiKey": key}
    if params:
        query.update(params)
    url = f"{BASE}{path}"
    response = session.get(url, params=query, timeout=30)
    headers = {
        "status": response.status_code,
        "cost": response.headers.get("x-requests-last", ""),
        "used": response.headers.get("x-requests-used", ""),
        "remaining": response.headers.get("x-requests-remaining", ""),
    }
    odds_api_log.log_request(
        endpoint=path,
        params={k: v for k, v in (params or {}).items()},
        http_status=headers["status"],
        cost=headers["cost"],
        used=headers["used"],
        remaining=headers["remaining"],
        notes=note,
    )
    data = None
    try:
        data = response.json()
    except Exception:
        data = None
    if save_as is not None and data is not None:
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        (SNAP_DIR / save_as).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data, headers


def main() -> int:
    key = load_key()
    session = requests.Session()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    spent = 0

    print("=" * 92)
    print("B2 — The Odds API probe (cap 10 credits)")
    print("=" * 92)

    # ---- 1. sports (free) ----
    sports, hdr = call(session, key, "/sports/", note="free", save_as=f"{stamp}_sports.json")
    print(f"\n[1] /sports  HTTP {hdr['status']}  cost {hdr['cost']}  "
          f"used {hdr['used']}  remaining {hdr['remaining']}")
    if not isinstance(sports, list):
        print("  unexpected response:", str(sports)[:200])
        return 1
    soccer = [s for s in sports if s.get("group") == "Soccer"]
    print(f"  {len(sports)} sports total, {len(soccer)} soccer")

    print("\n  our leagues:")
    found = {}
    for s in soccer:
        if s["key"] in WANTED:
            found[s["key"]] = s
            print(f"    {s['key']:<34} {s['title']:<28} active={s['active']}")
    missing = [k for k in WANTED if k not in found]
    if missing:
        print(f"    NOT FOUND: {missing}")
        print("    all soccer keys containing a hint:")
        for s in soccer:
            if any(h in s["key"] for h in ("germany", "england", "france", "serbia")):
                print(f"      {s['key']:<40} {s['title']}")

    # ---- 2. events per candidate league (free) ----
    print("\n[2] /events per league (free) — looking for fixtures in the next 3 days")
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=3)
    candidates = []
    for sport_key in WANTED:
        if sport_key not in found:
            continue
        events, hdr = call(session, key, f"/sports/{sport_key}/events",
                           note="free", save_as=f"{stamp}_{sport_key}_events.json")
        n = len(events) if isinstance(events, list) else 0
        soon = []
        if isinstance(events, list):
            for e in events:
                try:
                    ct = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
                except Exception:
                    continue
                if now <= ct <= horizon:
                    soon.append(e)
        print(f"    {sport_key:<34} events={n:<4} within 3 days={len(soon)}")
        if soon:
            candidates.append((sport_key, soon))

    if not candidates:
        print("\n  no league has fixtures within 3 days; using the first league with any events")
        for sport_key in WANTED:
            if sport_key not in found:
                continue
            events, _ = call(session, key, f"/sports/{sport_key}/events", note="free")
            if isinstance(events, list) and events:
                candidates.append((sport_key, events))
                break

    if not candidates:
        print("\n  no events available for any of our leagues — stopping before spending credits")
        return 0

    sport_key, events = candidates[0]
    event = sorted(events, key=lambda e: e["commence_time"])[0]
    print(f"\n  chosen: {sport_key} — {event['home_team']} vs {event['away_team']} "
          f"@ {event['commence_time']} (id {event['id']})")

    # ---- 3. event markets (1 credit) ----
    markets, hdr = call(session, key, f"/sports/{sport_key}/events/{event['id']}/markets",
                        params={"regions": "eu"}, note="market discovery",
                        save_as=f"{stamp}_{sport_key}_markets.json")
    spent += int(hdr["cost"] or 0)
    print(f"\n[3] /events/{{id}}/markets  HTTP {hdr['status']}  cost {hdr['cost']}  "
          f"used {hdr['used']}  remaining {hdr['remaining']}  (spent {spent})")
    books = markets.get("bookmakers", []) if isinstance(markets, dict) else []
    print(f"  bookmakers returned: {len(books)}")
    all_keys = set()
    for b in books:
        for m in b.get("markets", []):
            all_keys.add(m["key"])
    print(f"  distinct market keys available: {sorted(all_keys)}")

    # ---- 4. featured bulk snapshot (2 credits) ----
    if spent + 2 <= MAX_CREDITS:
        odds, hdr = call(session, key, f"/sports/{sport_key}/odds",
                         params={"regions": "eu", "markets": "h2h,totals",
                                 "oddsFormat": "decimal"},
                         note="featured snapshot",
                         save_as=f"{stamp}_{sport_key}_odds_featured.json")
        spent += int(hdr["cost"] or 0)
        n = len(odds) if isinstance(odds, list) else 0
        print(f"\n[4] /odds (h2h,totals)  HTTP {hdr['status']}  cost {hdr['cost']}  "
              f"used {hdr['used']}  remaining {hdr['remaining']}  (spent {spent})")
        print(f"  events returned: {n}")
        if n:
            bset = sorted({b['key'] for e in odds for b in e.get('bookmakers', [])})
            print(f"  bookmakers: {bset}")
            mset = sorted({m['key'] for e in odds for b in e.get('bookmakers', [])
                           for m in b.get('markets', [])})
            print(f"  markets returned: {mset}")

    # ---- 5. additional markets for one event (<=5 credits) ----
    wanted_extra = ["btts", "draw_no_bet", "alternate_totals", "h2h_h1", "totals_h1"]
    available_extra = [m for m in wanted_extra if m in all_keys]
    if available_extra and spent + len(available_extra) <= MAX_CREDITS:
        extra, hdr = call(session, key, f"/sports/{sport_key}/events/{event['id']}/odds",
                          params={"regions": "eu", "markets": ",".join(available_extra),
                                  "oddsFormat": "decimal"},
                          note="additional markets",
                          save_as=f"{stamp}_{sport_key}_odds_additional.json")
        spent += int(hdr["cost"] or 0)
        print(f"\n[5] /events/{{id}}/odds ({','.join(available_extra)})  "
              f"HTTP {hdr['status']}  cost {hdr['cost']}  used {hdr['used']}  "
              f"remaining {hdr['remaining']}  (spent {spent})")
        if isinstance(extra, dict):
            bset = sorted({b['key'] for b in extra.get('bookmakers', [])})
            mset = sorted({m['key'] for b in extra.get('bookmakers', [])
                           for m in b.get('markets', [])})
            print(f"  bookmakers: {bset}")
            print(f"  markets returned: {mset}")
    else:
        print(f"\n[5] skipped (available_extra={available_extra}, spent={spent})")

    # ---- Balkan bookmaker check ----
    print("\n--- Balkan / Serbian bookmaker check ---")
    hits = []
    for path in sorted(SNAP_DIR.glob(f"{stamp}_*.json")):
        text = path.read_text(encoding="utf-8").lower()
        for name in BALKAN:
            if name in text:
                hits.append((path.name, name))
    print(f"  matches: {hits if hits else 'none'}")

    print(f"\nTOTAL CREDITS SPENT THIS PROBE: {spent} (cap {MAX_CREDITS})")
    print(f"raw responses -> {SNAP_DIR}")
    odds_api_log.print_today()
    return 0


if __name__ == "__main__":
    sys.exit(main())