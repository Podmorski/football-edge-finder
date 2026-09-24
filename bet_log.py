"""Bet log and closing-line value (CLV).

The user logs the bet fields — date, bookmaker, match, market, family, code,
odds taken, stake and the **minimum acceptable odds** from the fair sheet.
``run.py log-close`` fills the two remaining columns after the match:

* ``pinnacle_close`` — the **fair** closing odds for that market, obtained by
  anchoring the half model on the **last Pinnacle snapshot we hold before
  kickoff** (the ``fair_sheet`` snapshot history; no credits are spent here).
  For a derived market this is a model price on a sharp anchor, not a price
  Pinnacle prints — the de-margined closing price is the project's benchmark.
* ``result`` — ``W`` / ``L`` / ``V`` (draw voids the stake, whether or not the
  book prints the market that way), or empty when the market cannot be settled.

Then it reports ``CLV = odds_taken / pinnacle_close - 1`` and P&L.

Decision rule (recorded in ``docs/PROJECT_PLAN.md``): **no conclusion before 50
logged bets, and continue only if the mean CLV is above 0.**
"""

from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import fair_sheet as fs
from core.soccerbet_ext import PREFIX_MAP
from core.team_names import MATCH_SIMILARITY, similarity as _similarity

TEMPLATE = Path("templates/bet_log.csv")
LOG = Path("data/bet_log.csv")
RESULTS_DIR = Path("data/historical")
ALIASES = Path("config/team_aliases.yaml")

FIELDS = ["date", "bookmaker", "match", "market", "family", "code", "odds_taken",
          "stake", "min_acceptable", "pinnacle_close", "result"]
BET_FIELDS = FIELDS[:9]

MIN_BETS_FOR_CONCLUSION = 50
MATCH_TOLERANCE_DAYS = 3


def _split_match(text: str) -> tuple[str, str] | None:
    for separator in (" vs ", " v ", " - "):
        if separator in text:
            home, away = text.split(separator, 1)
            return home.strip(), away.strip()
    return None


# --------------------------------------------------------------------------- #
# results
# --------------------------------------------------------------------------- #
_HISTORY: dict[str, pd.DataFrame] = {}


def history(slug: str) -> pd.DataFrame:
    if slug not in _HISTORY:
        path = RESULTS_DIR / f"{slug}.parquet"
        frame = pd.read_parquet(path) if path.exists() else pd.DataFrame()
        if not frame.empty:
            frame = frame.copy()
            frame["date"] = pd.to_datetime(frame["date"]).dt.date
        _HISTORY[slug] = frame
    return _HISTORY[slug]


def find_result(when: date, home: str, away: str):
    """(slug, row, home_similarity, away_similarity) for the best match, else None."""
    best = None
    for slug in fs.SPORTS.values():
        frame = history(slug)
        if frame.empty:
            continue
        near = frame[frame["date"].apply(
            lambda d: abs((d - when).days) <= MATCH_TOLERANCE_DAYS)]
        for row in near.itertuples(index=False):
            home_sim = _similarity(home, row.team_home)
            away_sim = _similarity(away, row.team_away)
            if home_sim < MATCH_SIMILARITY or away_sim < MATCH_SIMILARITY:
                continue
            score = home_sim + away_sim
            if best is None or score > best[2]:
                best = (slug, row, score, home_sim, away_sim)
    if best is None:
        return None
    return best[0], best[1], best[3], best[4]


# --------------------------------------------------------------------------- #
# closing snapshot
# --------------------------------------------------------------------------- #
def closing_prices(home: str, away: str, when: date):
    """(prices, fetched_at, slug) from the last pre-kickoff Pinnacle snapshot held."""
    best = None
    for fetched_at, data in fs.snapshot_history():
        for event in data if isinstance(data, list) else []:
            if fs.local_date(event["commence_time"]) != when:
                continue
            if _similarity(home, event["home_team"]) < MATCH_SIMILARITY:
                continue
            if _similarity(away, event["away_team"]) < MATCH_SIMILARITY:
                continue
            if best is None or fetched_at > best[1]:
                best = (event, fetched_at, data)
    if best is None:
        return None, None, None
    event, fetched_at, data = best
    slug = fs.SPORTS.get(event.get("sport_key", ""))
    if slug is None:
        return None, None, None
    return fs.pinnacle_prices(event, data), fetched_at, slug


# --------------------------------------------------------------------------- #
# markets
# --------------------------------------------------------------------------- #
def market_index() -> dict[tuple[str, str], object]:
    """(family, printed code) -> market, for the catalogue and the ext section."""
    return {(market.family, label): market for label, market in fs.sheet_markets()}


def resolve_key(index: dict, family: str, code: str) -> tuple[str, str] | None:
    """The catalogue key for a logged market.

    Accepts the code exactly as the sheet prints it, and the book's prefixed form:
    a market the base catalogue already covers has no ``PREFIX:code`` entry (the
    ext section omits duplicates), so ``T:3+`` must resolve to ``GOAL_RANGE_FT 3+``.
    The family is always required, because a bare code is ambiguous.
    """
    if (family, code) in index:
        return family, code
    prefix, _, bare = code.partition(":")
    if bare and prefix in PREFIX_MAP and (family, bare) in index:
        return family, bare
    return None


# --------------------------------------------------------------------------- #
# reading and writing the log
# --------------------------------------------------------------------------- #
def ensure_log() -> Path:
    if not LOG.exists():
        LOG.parent.mkdir(parents=True, exist_ok=True)
        LOG.write_text(TEMPLATE.read_text(encoding="utf-8") if TEMPLATE.exists()
                       else ",".join(FIELDS) + "\n", encoding="utf-8")
    return LOG


def read_bets(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    missing = [field for field in BET_FIELDS if rows and field not in rows[0]]
    if missing:
        raise SystemExit(f"{path} is missing columns {missing}")
    return [row for row in rows if row.get("code")]


def write_bets(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDS})


# --------------------------------------------------------------------------- #
# CLV and P&L
# --------------------------------------------------------------------------- #
def _outcome(market, row):
    hth, hta = row.hthg, row.htag
    if pd.isna(hth) or pd.isna(hta):
        return ""
    outcome = market.outcome(int(hth), int(hta), int(row.fthg), int(row.ftag))
    return {"win": "W", "lose": "L", "void": "V"}.get(outcome, "")


def _pnl(outcome: str, odds_taken: float, stake: float) -> float:
    if outcome == "W":
        return stake * (odds_taken - 1.0)
    if outcome == "L":
        return -stake
    return 0.0


def summarise(bets: list[dict]) -> dict:
    clvs = [row["clv"] for row in bets if row.get("clv") is not None]
    staked = sum(row["stake"] for row in bets if row["result"] in "WLV")
    pnl = sum(row["pnl"] for row in bets)
    summary = {
        "n": len(bets),
        "with_result": sum(1 for row in bets if row["result"] in "WLV"),
        "with_clv": len(clvs),
        "mean_clv": float(np.mean(clvs)) if clvs else None,
        "ci": None, "staked": staked, "pnl": pnl,
    }
    if len(clvs) >= 2:
        half_width = 1.96 * float(np.std(clvs, ddof=1)) / np.sqrt(len(clvs))
        summary["ci"] = (summary["mean_clv"] - half_width, summary["mean_clv"] + half_width)
    return summary


def main(path: str | None = None) -> int:
    log_path = Path(path) if path else ensure_log()
    rows = read_bets(log_path)
    if not rows:
        print(f"{log_path} has no bets yet. Copy {TEMPLATE} and add your bets.")
        return 0

    markets = market_index()
    bets: list[dict] = []
    unmatched: list[str] = []
    unknown: list[str] = []
    no_close: list[str] = []

    for raw in rows:
        entry = dict(raw)
        label = f"{entry['date']} {entry['match']}"
        try:
            odds_taken = float(entry["odds_taken"])
            stake = float(entry["stake"])
        except (TypeError, ValueError):
            unmatched.append(f"{label} (bad odds/stake)")
            continue
        key = resolve_key(markets, entry["family"], entry["code"])
        market = markets.get(key) if key else None
        if market is None:
            unknown.append(f"{label} ({entry['family']} {entry['code']})")

        when = date.fromisoformat(entry["date"])
        parts = _split_match(entry["match"])
        matched = find_result(when, *parts) if parts else None
        result_row = matched[1] if matched else None
        if result_row is None:
            unmatched.append(label)

        prices, _fetched_at, slug = (closing_prices(*parts, when) if parts
                                     else (None, None, None))
        fair_close = None
        if prices is not None:
            fresh, _residual = fs.price_match(slug, prices)
            fair_close = {(r["family"], r["market"]): r["fair_odds"] for r in fresh}.get(key)
        if fair_close is None and key is not None:
            no_close.append(label)

        outcome = (_outcome(market, result_row)
                   if market is not None and result_row is not None else "")
        entry["pinnacle_close"] = f"{fair_close:.4f}" if fair_close else ""
        entry["result"] = outcome
        bets.append({
            "row": entry, "stake": stake, "result": outcome,
            "clv": (odds_taken / fair_close - 1.0) if fair_close else None,
            "pnl": _pnl(outcome, odds_taken, stake),
            "odds_taken": odds_taken,
            "below_min": _below_minimum(entry, odds_taken),
        })

    write_bets(log_path, [bet["row"] for bet in bets])
    report(log_path, bets, unmatched=unmatched, unknown=unknown, no_close=no_close)
    return 0


def _below_minimum(entry: dict, odds_taken: float) -> bool:
    try:
        return odds_taken < float(entry["min_acceptable"])
    except (TypeError, ValueError):
        return False


def report(log_path: Path, bets: list[dict], unmatched, unknown, no_close) -> None:
    summary = summarise(bets)
    print("=" * 72)
    print(f"log-close: {log_path} — {summary['n']} bets")
    print("=" * 72)
    print(f"filled: results {summary['with_result']}/{summary['n']}, "
          f"closing prices {summary['with_clv']}/{summary['n']}")
    if summary["mean_clv"] is not None:
        ci = summary["ci"]
        ci_text = f" (95% CI {ci[0]:+.4f} .. {ci[1]:+.4f})" if ci else " (n<2: no CI)"
        print(f"mean CLV {summary['mean_clv']:+.4f}{ci_text}")
    else:
        print("mean CLV: n/a (no bet has a closing snapshot yet)")
    roi = summary["pnl"] / summary["staked"] if summary["staked"] else 0.0
    print(f"P&L {summary['pnl']:+.2f} on {summary['staked']:.2f} staked (ROI {roi:+.2%})")
    below = sum(1 for bet in bets if bet["below_min"])
    if below:
        print(f"WARNING: {below} bet(s) taken below the logged minimum acceptable odds")
    for title, items in (("no result found", unmatched), ("market not in the catalogue", unknown),
                         ("no pre-kickoff snapshot", no_close)):
        if items:
            print(f"{title}: {len(items)}")
            for item in items[:10]:
                print(f"  {item}")
    if unmatched:
        print("  -> team matching is heuristic (noise-stripped names, similarity "
              f">= {MATCH_SIMILARITY}, plus the locked non-merges). Check the names; a "
              "miss is reported rather than guessed.")
    if no_close:
        print("  -> no closing price means the match was never in a fair-sheet snapshot "
              f"within {fs.CACHE_HOURS}h of a run; re-run the sheet near kickoff.")
    print()
    print(f"DECISION RULE: no conclusion before {MIN_BETS_FOR_CONCLUSION} logged bets; "
          "continue only if mean CLV > 0.")
    if summary["n"] < MIN_BETS_FOR_CONCLUSION:
        print(f"  {MIN_BETS_FOR_CONCLUSION - summary['n']} more bet(s) needed before any conclusion.")
    print("NOTE: pinnacle_close for a derived market is the model's fair price on the "
          "last pre-kickoff Pinnacle anchor, not a price Pinnacle prints.")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))