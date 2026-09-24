"""Does the global feed accept a league filter? (one-off, few requests)"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import mozzart_odds

key = mozzart_odds.load_key()
session = requests.Session()

tests = [
    ("league name", {"page": 1, "limit": 30, "league": "Engleska 4"}),
    ("leagueId", {"page": 1, "limit": 30, "leagueId": "4047"}),
    ("competitionId", {"page": 1, "limit": 30, "competitionId": "4047"}),
]
for name, params in tests:
    try:
        doc = mozzart_odds._get(session, key, "/soccer/events", params,
                                note=f"probe: filter {name}")
    except Exception as exc:  # noqa: BLE001
        print(f"{name}: {exc}")
        continue
    events = (doc or {}).get("events", []) if isinstance(doc, dict) else []
    labels = {e.get("league") for e in events}
    print(f"{name}: total={doc.get('total')} n={len(events)} labels={labels}")

print("used:", __import__("pulsescore_log").used_this_month())
