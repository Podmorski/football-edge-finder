"""Measure the global-feed pass and confirm the last per-league case (one-off)."""

from __future__ import annotations

import collections
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

import mozzart_odds
import pulsescore_log

key = mozzart_odds.load_key()
session = requests.Session()

print("before:", pulsescore_log.used_this_month(), "used this month")

# A full 24h forward window (the daily sheet's worst case: a run at local midnight).
until = datetime.now(timezone.utc) + timedelta(hours=24)
print("until (UTC):", until.isoformat())

before = pulsescore_log.used_this_month()
events, fetched = mozzart_odds.fetch_global_events(session, key, until=until,
                                                   max_age_minutes=0)
after = pulsescore_log.used_this_month()
print(f"pages used: {after - before} · events kept: {len(events)} "
      f"· fetched_at {fetched.isoformat(timespec='seconds')}")
print("by label:", dict(collections.Counter(e.get("league") for e in events)))

print("after:", after, "used this month,", pulsescore_log.remaining_this_month(), "left")
