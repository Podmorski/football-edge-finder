"""Weekly job — Mondays 07:30 (``run.py weekly``).

1. **Refresh** the current season's results (football-data.co.uk, free).
2. **Mozzart top-up check** (D3): 2. Bundesliga and Ligue 2 were absent from the
   Mozzart feed at widening time. From ``resume_after`` (2026-10-08) this job
   re-reads the Mozzart league list and, when a pending division finally appears,
   records it in ``data/mozzart/topup.json`` so the next fair-sheet run prices it.
   Before that date the check is skipped and spends no requests.
3. **Paper report** — written to ``reports/paper_report.md`` and printed.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

import requests

import mozzart_odds
import paper_trade
import refresh_historical
from core import league_registry

TOPUP = Path("data/mozzart/topup.json")
REPORT = Path("reports/paper_report.md")


def _mozzart_league_names(session, key) -> set[str]:
    names: set[str] = set()
    for page in (1, 2, 3, 4):
        doc = mozzart_odds._get(session, key, "/soccer/leagues",
                                {"page": page, "limit": 30},
                                note="weekly: mozzart top-up check")
        names |= {league.get("name") for league in (doc or {}).get("leagues", [])}
    return names


def topup_check(today=None) -> dict:
    """Re-check the pending Mozzart divisions and record any that appeared."""
    pending = league_registry.pending_topups(today)
    if not pending:
        return {"checked": [], "added": {}}
    session = requests.Session()
    key = mozzart_odds.load_key()
    names = _mozzart_league_names(session, key)
    added = {slug: name for slug, name in pending if name in names}
    if added:
        existing: dict[str, str] = {}
        if TOPUP.exists():
            try:
                existing = json.loads(TOPUP.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                existing = {}
        existing.update(added)
        TOPUP.parent.mkdir(parents=True, exist_ok=True)
        TOPUP.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"checked": [slug for slug, _ in pending], "added": added}


def main() -> int:
    print("weekly: refreshing current-season results")
    refresh_historical.main()

    info = topup_check()
    if not info["checked"]:
        print("weekly: no Mozzart top-up due yet "
              "(2. Bundesliga / Ligue 2 resume after 2026-10-08).")
    else:
        print(f"weekly: Mozzart top-up checked {info['checked']} -> added {info['added']}")

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        paper_trade.report()
    text = buffer.getvalue()
    print(text)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("```\n" + text + "```\n", encoding="utf-8")
    print(f"weekly: wrote {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())