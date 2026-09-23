"""Phase 1 pipeline runner (Windows-friendly; no make required).

Usage:
    python run.py ingest-historical
    python run.py ingest-xg
    python run.py refresh
    python run.py fixtures [--date YYYY-MM-DD]     # no --date => tomorrow
    python run.py requests-today

Heavy modules (penaltyblog, pandas) are imported lazily inside each command so
that light commands like ``requests-today`` stay fast.
"""

from __future__ import annotations

import argparse
import sys

COMMANDS = {
    "ingest-historical": "Full historical pull from football-data.co.uk (all seasons, all leagues).",
    "ingest-xg": "Understat xG coverage test (expected gaps are reported, not debugged).",
    "refresh": "Re-pull only the current season and merge (idempotent; adds 0 rows on a repeat run).",
    "fixtures": "Pull fixtures for a date (default: tomorrow). Refuses out-of-window dates.",
    "requests-today": "Print today's API-Football request count from the local log.",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Phase 1 football data pipeline runner.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ingest-historical", help=COMMANDS["ingest-historical"])
    sub.add_parser("ingest-xg", help=COMMANDS["ingest-xg"])
    sub.add_parser("refresh", help=COMMANDS["refresh"])
    sub.add_parser("requests-today", help=COMMANDS["requests-today"])

    fixtures = sub.add_parser("fixtures", help=COMMANDS["fixtures"])
    fixtures.add_argument(
        "--date",
        default=None,
        help="Target date as YYYY-MM-DD. Defaults to tomorrow.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "requests-today":
        import api_log

        api_log.print_today()
        return 0

    if args.command == "ingest-historical":
        import ingest_historical

        return ingest_historical.main()

    if args.command == "ingest-xg":
        import ingest_xg

        return ingest_xg.main()

    if args.command == "refresh":
        import refresh_historical

        return refresh_historical.main()

    if args.command == "fixtures":
        import get_fixtures

        forwarded = ["--date", args.date] if args.date else []
        return get_fixtures.main(forwarded)

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())