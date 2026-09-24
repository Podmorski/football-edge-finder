"""Paper trading — fully automatic, never a real bet.

Every fair-sheet **flag** becomes one paper bet (1 unit at the Mozzart price).
Three jobs keep the log honest:

* ``record`` — append each flag to ``data/paper/paper_bets.csv`` (de-duplicated by
  match + market, so re-running the sheet does not double-count);
* ``close`` — for matches with paper bets, save the **de-margined Pinnacle close**
  from the last pre-kickoff snapshot (the project's CLV benchmark);
* ``settle`` — after the match, settle each bet from the result via the
  **section-aware** settlement and record the virtual P&L.

``report`` prints n bets, mean CLV with a 95% CI, virtual P&L, and the same split
by family and by league. **No bet is ever placed automatically.**
"""

from __future__ import annotations

import csv
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests
import yaml

import bet_log
import fair_sheet as fs

LOG = Path("data/paper/paper_bets.csv")
PAPER_CONFIG = Path("config/paper.yaml")

FIELDS = [
    "date", "kickoff", "league", "home", "away", "family", "section", "code",
    "meaning", "mozzart_odds", "fair_odds", "min_acceptable", "ev", "stake",
    "mozzart_snapshot", "pinnacle_snapshot", "pinnacle_close", "clv", "result", "pnl",
]
CLOSE_WINDOW_MINUTES = 30
SETTLE_AFTER_HOURS = 3


def load_config() -> dict:
    doc = yaml.safe_load(PAPER_CONFIG.read_text(encoding="utf-8"))
    return {"stake": float(doc.get("stake", 1.0)),
            "min_paper_bets": int(doc.get("min_paper_bets", 50))}


def read_rows() -> list[dict]:
    if not LOG.exists():
        return []
    with LOG.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_rows(rows: list[dict]) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDS})


def _key(row: dict) -> tuple:
    return (row["date"], row["home"], row["away"], row["family"], row["code"])


def record(flags: list[dict]) -> int:
    """Append new flags to the paper log. Returns the number added."""
    rows = read_rows()
    seen = {_key(row) for row in rows}
    stake = load_config()["stake"]
    added = 0
    for flag in flags:
        row = {
            "date": fs.local_date(flag["kickoff"]).isoformat(),
            "kickoff": flag["kickoff"], "league": flag["league"],
            "home": flag["home"], "away": flag["away"], "family": flag["family"],
            "section": flag["section"], "code": flag["code"], "meaning": flag["meaning"],
            "mozzart_odds": f"{flag['mozzart_odds']:.4f}",
            "fair_odds": f"{flag['fair_odds']:.4f}",
            "min_acceptable": f"{flag['min_acceptable']:.4f}",
            "ev": f"{flag['ev']:.4f}", "stake": f"{stake:.2f}",
            "mozzart_snapshot": flag.get("mozzart_snapshot", ""),
            "pinnacle_snapshot": flag.get("pinnacle_snapshot", ""),
            "pinnacle_close": "", "clv": "", "result": "", "pnl": "",
        }
        if _key(row) in seen:
            continue
        seen.add(_key(row))
        rows.append(row)
        added += 1
    if added:
        write_rows(rows)
    return added


def _kickoff(row: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(row["kickoff"].replace("Z", "+00:00"))
    except (ValueError, KeyError):
        return None


def _in_close_window(row: dict, now: datetime) -> bool:
    kickoff = _kickoff(row)
    if kickoff is None:
        return False
    return kickoff - timedelta(minutes=CLOSE_WINDOW_MINUTES) <= now < kickoff


def _find_event(events: list[tuple[str, dict]], row: dict):
    """The (sport_key, event) for a paper bet's match, by league and names."""
    from core.team_names import MATCH_SIMILARITY, similarity

    for sport_key, event in events:
        if fs.SPORTS.get(sport_key) != row["league"]:
            continue
        if (similarity(row["home"], event["home_team"]) >= MATCH_SIMILARITY
                and similarity(row["away"], event["away_team"]) >= MATCH_SIMILARITY):
            return sport_key, event
    return None


def close(now: datetime | None = None, session=None, key: str | None = None) -> int:
    """Save the de-margined Pinnacle close for bets within the close window.

    A **fresh** Pinnacle snapshot is fetched for each match that has a paper bet
    (2 credits per match, cached 6h), so the closing price is genuinely close to
    kickoff. Matches without paper bets are never fetched.
    """
    now = now or datetime.now(timezone.utc)
    rows = read_rows()
    pending = [row for row in rows
               if not row.get("pinnacle_close") and _in_close_window(row, now)]
    if not pending:
        return 0
    if session is None:
        session = requests.Session()
    if key is None:
        key = fs.load_key()

    window = {date.fromisoformat(row["date"]) for row in pending}
    events, _headers, _started = fs.upcoming_events(session, key, window)
    markets = bet_log.market_index()
    snapshots: dict[str, object] = {}
    filled = 0
    for row in pending:
        match = _find_event(events, row)
        if match is None:
            continue
        sport_key, event = match
        if event["id"] not in snapshots:
            snapshot, _cost, _source, _balance = fs.fetch_snapshot(session, key, sport_key, event)
            snapshots[event["id"]] = snapshot
        snapshot = snapshots[event["id"]]
        prices = fs.pinnacle_prices(event, snapshot) if snapshot else None
        if prices is None:
            continue
        key_pair = bet_log.resolve_key(markets, row["family"], row["code"])
        fresh, _residual = fs.price_match(fs.SPORTS[sport_key], prices)
        fair_close = {(r["family"], r["market"]): r["fair_odds"] for r in fresh}.get(key_pair)
        if fair_close is None:
            continue
        row["pinnacle_close"] = f"{fair_close:.4f}"
        row["pinnacle_snapshot"] = prices.get("snapshot") or ""
        try:
            row["clv"] = f"{float(row['mozzart_odds']) / fair_close - 1.0:.6f}"
        except (TypeError, ValueError):
            pass
        filled += 1
    if filled:
        write_rows(rows)
    return filled


def settle(now: datetime | None = None) -> int:
    """Settle finished bets from the result, via the section-aware settlement."""
    now = now or datetime.now(timezone.utc)
    rows = read_rows()
    markets = bet_log.market_index()
    settled = 0
    for row in rows:
        if row.get("result"):
            continue
        kickoff = _kickoff(row)
        if kickoff is None or now < kickoff + timedelta(hours=SETTLE_AFTER_HOURS):
            continue
        when = date.fromisoformat(row["date"])
        matched = bet_log.find_result(when, row["home"], row["away"])
        if matched is None:
            continue
        _slug, result_row, _hs, _as = matched
        key = bet_log.resolve_key(markets, row["family"], row["code"])
        market = markets.get(key) if key else None
        if market is None:
            continue
        outcome = bet_log._outcome(market, result_row)
        if outcome not in "WLV":
            continue
        row["result"] = outcome
        try:
            odds = float(row["mozzart_odds"])
            stake = float(row["stake"])
        except (TypeError, ValueError):
            continue
        row["pnl"] = f"{bet_log._pnl(outcome, odds, stake):.4f}"
        settled += 1
    if settled:
        write_rows(rows)
    return settled


def _mean_ci(values: list[float]) -> tuple[float, float, float]:
    if not values:
        return (float("nan"), float("nan"), float("nan"))
    mean = float(np.mean(values))
    if len(values) < 2:
        return (mean, float("nan"), float("nan"))
    half = 1.96 * float(np.std(values, ddof=1)) / np.sqrt(len(values))
    return (mean, mean - half, mean + half)


def _group(rows: list[dict], field: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in rows:
        out.setdefault(row[field], []).append(row)
    return out


def report() -> int:
    rows = read_rows()
    config = load_config()
    print("=" * 72)
    print(f"paper-report: {len(rows)} paper bets")
    print("=" * 72)
    if not rows:
        print("No paper bets yet. Run the fair sheet on a matchday.")
        return 0

    clvs = [float(r["clv"]) for r in rows if r.get("clv")]
    pnls = [float(r["pnl"]) for r in rows if r.get("pnl")]
    mean, low, high = _mean_ci(clvs)
    print(f"settled: {len(pnls)}/{len(rows)} · with CLV: {len(clvs)}/{len(rows)}")
    if clvs:
        ci = f"[{low:+.2%}, {high:+.2%}]" if not np.isnan(low) else "(n<2: no CI)"
        print(f"mean CLV {mean:+.2%} {ci}")
    print(f"virtual P&L {sum(pnls):+.2f} on {len(pnls)} units "
          f"(ROI {sum(pnls) / len(pnls):+.2%})" if pnls else "virtual P&L: n/a")

    for field, title in (("family", "by family"), ("league", "by league")):
        print(f"\n{title}:")
        for name, group in sorted(_group(rows, field).items()):
            group_clv = [float(r["clv"]) for r in group if r.get("clv")]
            group_pnl = [float(r["pnl"]) for r in group if r.get("pnl")]
            gmean, glow, ghigh = _mean_ci(group_clv)
            clv_text = (f"CLV {gmean:+.2%} [{glow:+.2%}, {ghigh:+.2%}]"
                        if group_clv and not np.isnan(glow) else
                        f"CLV {gmean:+.2%}" if group_clv else "CLV n/a")
            print(f"  {name:<22} n={len(group):<4} {clv_text}  P&L {sum(group_pnl):+.2f}")

    print()
    print(f"DECISION RULE: real money only after >= {config['min_paper_bets']} paper bets "
          "with mean CLV > 0 and the 95% CI lower bound > 0, and no contradicting "
          "historical evidence. NEVER place bets automatically.")
    if len(rows) < config["min_paper_bets"]:
        print(f"  {config['min_paper_bets'] - len(rows)} more paper bet(s) needed.")
    return 0


def main(action: str) -> int:
    if action == "record":
        print("record is driven by the fair sheet; nothing to do standalone.")
        return 0
    if action == "close":
        print(f"paper-close: filled {close()} closing price(s)")
        return 0
    if action == "settle":
        print(f"paper-settle: settled {settle()} bet(s)")
        return 0
    if action == "report":
        return report()
    raise SystemExit(f"unknown paper action {action!r}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "report"))