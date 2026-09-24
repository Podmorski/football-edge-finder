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
    "snapshot-fd": "Save football-data.co.uk fixtures.csv if its content hash has changed.",
    "price-match": "Fair probability and odds for every catalogue market of a match.",
    "analyse-book": "Analyse a Soccer Bet price file (margins, EV, cheapest representation).",
    "compare-mainline": "Compare Soccer Bet's main line against sharp prices (MAINLINE-1).",
    "fair-sheet": "Daily fair-odds sheet anchored on Pinnacle (fair odds + minimum acceptable odds).",
    "log-close": "Fill closing prices + results in the bet log; report CLV and P&L.",
}


def snapshot_fd() -> int:
    """Save football-data.co.uk fixtures.csv only when its content hash changes.

    Free (no API credits). The file is the only forward-looking fixture source
    available without an API key, so keeping a hash-gated history lets us see
    when it rolls over to the next round.
    """
    import hashlib
    from datetime import datetime, timezone
    from pathlib import Path

    import requests

    url = "https://football-data.co.uk/fixtures.csv"
    out_dir = Path("data/odds_snapshots/fd")
    out_dir.mkdir(parents=True, exist_ok=True)

    response = requests.get(url, timeout=30)
    response.raise_for_status()
    content = response.content
    digest = hashlib.sha256(content).hexdigest()

    existing = sorted(out_dir.glob("*.csv"))
    if existing:
        previous = hashlib.sha256(existing[-1].read_bytes()).hexdigest()
        if previous == digest:
            print(f"unchanged since {existing[-1].name} "
                  f"(sha256 {digest[:16]}) - not saved")
            return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{stamp}.csv"
    path.write_bytes(content)
    print(f"saved {path} ({len(content)} bytes, sha256 {digest[:16]})")
    return 0


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
    sub.add_parser("snapshot-fd", help=COMMANDS["snapshot-fd"])

    price = sub.add_parser("price-match", help=COMMANDS["price-match"])
    price.add_argument("--league", required=True)
    price.add_argument("--home", required=True)
    price.add_argument("--away", required=True)
    price.add_argument("--odds-1x2", nargs=3, type=float, required=True, metavar=("H", "D", "A"))
    price.add_argument("--odds-ou25", nargs=2, type=float, required=True, metavar=("OVER", "UNDER"))

    book = sub.add_parser("analyse-book", help=COMMANDS["analyse-book"])
    book.add_argument("--file", required=True)

    mainline = sub.add_parser("compare-mainline", help=COMMANDS["compare-mainline"])
    mainline.add_argument("--file", required=True)

    sheet = sub.add_parser("fair-sheet", help=COMMANDS["fair-sheet"])
    sheet.add_argument("--date", default=None,
                       help="First day of the window, YYYY-MM-DD. Defaults to today.")
    sheet.add_argument("--days", type=int, default=1,
                       help="Length of the window in days (default 1).")

    log_close = sub.add_parser("log-close", help=COMMANDS["log-close"])
    log_close.add_argument("--file", default=None,
                           help="Bet log CSV (default: data/bet_log.csv).")

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

    if args.command == "snapshot-fd":
        return snapshot_fd()

    if args.command == "price-match":
        import step4_pricing

        rows = step4_pricing.price_match(
            args.league, args.home, args.away,
            tuple(args.odds_1x2), tuple(args.odds_ou25),
        )
        passing = {r["family"] for r in rows if r["status"] == "PASS"}
        print(f"{args.home} vs {args.away} ({args.league}) - {len(rows)} markets")
        print(f"families PASS: {len(passing)}")
        print(f"{'code':<16}{'family':<22}{'p_fair':>9}{'fair_odds':>11}{'status':>10}")
        for r in rows:
            print(f"{r['code']:<16}{r['family']:<22}{r['p_fair']:>9.4f}"
                  f"{r['fair_odds']:>11.3f}{r['status']:>10}")
        return 0

    if args.command == "analyse-book":
        import step4_pricing

        return step4_pricing.analyse_book(args.file)

    if args.command == "compare-mainline":
        import step2_compare_mainline

        return step2_compare_mainline.main(args.file)

    if args.command == "fair-sheet":
        import fair_sheet

        return fair_sheet.main(args.date, args.days)

    if args.command == "log-close":
        import bet_log

        return bet_log.main(args.file)

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