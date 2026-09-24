"""Step 4 — pricing tools.

``price_match``  — fair probability and fair odds for every catalogue market.
``analyse_book`` — per match: book margin per family, the book's implied
                   (lambda, mu, half split), EV per market (flagged only for
                   families that PASSED calibration), and the cheapest
                   representation of each outcome set.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from core import odds, walkforward as wf
from core.half_model import (
    Anchor,
    HalfParams,
    batch_market_probs,
    fair_odds,
    fit_half_params,
    grids_to_flat,
    joint_grid,
    market_masks,
    solve_anchor,
)
from core.market_code import VOID, WIN, direct_markets, parse
from core.soccerbet_ext import ExtMarket, resolve

MAX_HALF = 6
DIRECT_FAMILIES = {
    "WIN_BOTH_HALVES", "WIN_BOTH_HALVES_TO_NIL", "WIN_TO_NIL", "MARGIN", "NO_BET",
    "MORE_GOALS_HALF", "FIRST_GOAL", "TO_QUALIFY",
}
CALIBRATION_CSV = Path("reports/figures/family_calibration.csv")
TEMPLATE = Path("templates/soccerbet_prices.csv")
CATALOGUE = Path("config/markets_catalogue.yaml")
PARAMS_CACHE_DIR = Path("data/cache/half_params")

# The L2/L3 fit inputs: (lam, mu) come only from these odds columns, and the fit
# itself only from (lam, mu, hth, hta, fth, fta).
FIT_COLUMNS = [
    "fthg", "ftag", "hthg", "htag",
    "avg_h", "avg_d", "avg_a", "bb_av_h", "bb_av_d", "bb_av_a",
    "avg>2.5", "avg<2.5", "bb_av>2.5", "bb_av<2.5",
]

_PARAMS_CACHE: dict[str, HalfParams] = {}

# The modelled leagues whose history a widened league borrows its (neutral) half
# params shape from. The widened leagues have no local history, so their sharp
# main-line price is anchored on the same sharp 1X2 + totals but with a pooled
# L2/L3 structure.
MODELLED_FALLBACK = ("bundesliga_1", "bundesliga_2", "league_one_t3", "ligue_2_t2")
_DEFAULT_PARAMS: HalfParams | None = None


def load_markets() -> list:
    catalogue = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))["markets"]
    direct = {m.code: m for m in direct_markets()}
    out = []
    for entry in catalogue:
        if entry["family"] in DIRECT_FAMILIES:
            out.append(direct[entry["code"]])
        else:
            out.append(parse(entry["code"], entry["family"], entry.get("label_sr", ""),
                             entry.get("definition_en", ""), section=entry.get("section")))
    return out


def load_ext_markets() -> list[ExtMarket]:
    """Every settleable market in the catalogue's ``ext_markets`` section.

    UNTESTABLE families (first goal, minute markets) are deliberately not
    returned: they cannot be settled from (HT, FT) scores, so they have no fair
    price. The section is keyed by prefix, never by the bare code.
    """
    section = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8")).get("ext_markets") or {}
    out: list[ExtMarket] = []
    for family in section.get("families", []):
        for group in family["prefixes"]:
            for code in group["codes"]:
                out.append(resolve(group["prefix"], code))
    return out


def family_status() -> dict[str, str]:
    """PASS / FAIL / UNTESTED per family, from the calibration artifact."""
    if not CALIBRATION_CSV.exists():
        return {}
    table = pd.read_csv(CALIBRATION_CSV)
    status = {}
    for r in table.itertuples(index=False):
        status[r.family] = "PASS" if bool(getattr(r, "final_pass", False)) else "FAIL"
    return status


def _fit_fingerprint(frame: pd.DataFrame) -> str:
    """Exact content hash of the fit inputs (the fit is deterministic in them)."""
    values = np.ascontiguousarray(frame[FIT_COLUMNS].to_numpy(dtype=float))
    return hashlib.sha256(values.tobytes()).hexdigest()[:16]


def _read_cached_params(slug: str, fingerprint: str) -> HalfParams | None:
    path = PARAMS_CACHE_DIR / f"{slug}__{fingerprint}.json"
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return HalfParams(
            split_a=float(doc["split_a"]), split_b=float(doc["split_b"]),
            split_c=float(doc["split_c"]),
            state_mult={tuple(k.split("|")): float(v) for k, v in doc["state_mult"].items()},
            ht_draw_inflation=float(doc.get("ht_draw_inflation", 1.0)),
        )
    except (ValueError, KeyError, TypeError):
        return None


def _write_cached_params(slug: str, fingerprint: str, params: HalfParams) -> None:
    PARAMS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (PARAMS_CACHE_DIR / f"{slug}__{fingerprint}.json").write_text(
        json.dumps({
            "split_a": params.split_a, "split_b": params.split_b, "split_c": params.split_c,
            "state_mult": {f"{side}|{state}": value
                           for (side, state), value in params.state_mult.items()},
            "ht_draw_inflation": params.ht_draw_inflation,
        }, indent=2),
        encoding="utf-8",
    )


def _params_from_pool(pool: pd.DataFrame, cache_slug: str):
    """Fit L2/L3 on a training pool, cached on disk under ``cache_slug``."""
    raw = pool.reset_index().rename(columns={"index": "row", "id": "match_key"})
    frame = raw[["match_key", "date", "season", "fthg", "ftag", "hthg", "htag",
                 "avg_h", "avg_d", "avg_a", "bb_av_h", "bb_av_d", "bb_av_a",
                 "avg>2.5", "avg<2.5", "bb_av>2.5", "bb_av<2.5"]].dropna(
        subset=["hthg", "htag"])
    fingerprint = _fit_fingerprint(frame)
    cached = _read_cached_params(cache_slug, fingerprint)
    if cached is not None:
        return cached

    prem = odds.prematch_1x2(frame)
    ou = odds.prematch_ou25(frame)
    p1 = odds.demargin(prem.odds.where(prem.available), "proportional")
    pou = odds.demargin(ou.odds.where(ou.available), "proportional")
    frame = frame.assign(p_home=p1["home"].to_numpy(), p_draw=p1["draw"].to_numpy(),
                         p_away=p1["away"].to_numpy(), p_over25=pou["over"].to_numpy())
    frame = frame.dropna(subset=["p_home", "p_draw", "p_away", "p_over25"])
    rows = []
    for r in frame.itertuples(index=False):
        a = solve_anchor(r.p_home, r.p_draw, r.p_away, r.p_over25)
        rows.append({"lam": a.lam, "mu": a.mu, "hth": r.hthg, "hta": r.htag,
                     "fth": r.fthg, "fta": r.ftag})
    params = fit_half_params(rows)
    _write_cached_params(cache_slug, fingerprint, params)
    return params


def default_params():
    """A pooled half-params fit across the modelled leagues.

    A widened league has no local history, so its GOAL_RANGE_FT price uses this
    neutral anchor shape: the *level* is still the sharp 1X2 + totals, and only
    the L2/L3 split structure is pooled from the leagues we did model.
    """
    global _DEFAULT_PARAMS
    if _DEFAULT_PARAMS is None:
        pools = []
        for slug in MODELLED_FALLBACK:
            try:
                pool = wf.load_pool(slug)
            except Exception:  # noqa: BLE001
                continue
            if pool is not None and not pool.empty:
                pools.append(pool)
        if not pools:
            raise RuntimeError("no modelled league history for a default half-params fit")
        _DEFAULT_PARAMS = _params_from_pool(pd.concat(pools, ignore_index=True), "__default__")
    return _DEFAULT_PARAMS


def league_params(slug: str):
    """Fit L2/L3 on the league's training seasons (in-memory + on-disk cached).

    The fit is deterministic in :data:`FIT_COLUMNS`, so it is cached on disk under
    ``data/cache/half_params/<slug>__<content hash>.json``. Without the cache the
    per-match anchor solve costs ~40 s per league on every run. A league outside
    the modelled four (the widened set) falls back to :func:`default_params`.
    """
    if slug in _PARAMS_CACHE:
        return _PARAMS_CACHE[slug]
    try:
        pool = wf.load_pool(slug)
    except Exception:  # noqa: BLE001
        pool = None
    if pool is None or getattr(pool, "empty", True):
        params = default_params()
        _PARAMS_CACHE[slug] = params
        return params
    params = _params_from_pool(pool, slug)
    _PARAMS_CACHE[slug] = params
    return params


def price_match(slug: str, home: str, away: str, odds_1x2: tuple, odds_ou25: tuple) -> list[dict]:
    """Fair probability and odds for every catalogue market."""
    h, d, a = odds_1x2
    over, under = odds_ou25
    inv = np.array([1 / h, 1 / d, 1 / a])
    p1 = inv / inv.sum()
    inv_ou = np.array([1 / over, 1 / under])
    p_ou = inv_ou / inv_ou.sum()

    anchor = solve_anchor(p1[0], p1[1], p1[2], p_ou[0])
    params = league_params(slug)
    grid = joint_grid(anchor, params, MAX_HALF)
    markets = load_markets()
    masks = market_masks(markets, MAX_HALF)
    probs = batch_market_probs(grids_to_flat([grid]), masks)
    status = family_status()

    rows = []
    for market in markets:
        p_win = float(probs[(market.family, market.code)][0][0])
        p_void = float(probs[(market.family, market.code)][1][0])
        rows.append({
            "code": market.code,
            "family": market.family,
            "period": market.period,
            "p_fair": p_win,
            "p_void": p_void,
            "fair_odds": fair_odds(p_win, p_void),
            "status": "UNTESTED" if not market.testable else status.get(market.family, "UNTESTED"),
            "do_not_bet": market.code in __import__("core.market_code", fromlist=["x"]).DO_NOT_BET_UNTIL_CLARIFIED,
        })
    return rows


def analyse_book(csv_path: str) -> int:
    """Analyse a Soccer Bet price file."""
    frame = pd.read_csv(csv_path)
    required = {"date", "league", "home", "away", "market_code", "soccer_bet_odds"}
    missing = required - set(frame.columns)
    if missing:
        print(f"ERROR: {csv_path} is missing columns {sorted(missing)}")
        return 1
    # market codes are strings; pandas may infer numeric for codes like "1"
    frame["market_code"] = frame["market_code"].astype(str)

    status = family_status()
    markets = {m.code: m for m in load_markets()}
    has_family = "family" in frame.columns
    if not has_family:
        print("WARNING: no 'family' column. Codes collide across families (e.g. '1' is")
        print("         both RESULT 'home wins' and GOAL_RANGE_FT 'exactly 1 goal'), so")
        print("         lookups may resolve to the wrong market. Add a family column.")
    print("=" * 100)
    print(f"analyse-book: {csv_path}  ({len(frame)} price rows)")
    print("=" * 100)

    for (league, home, away), group in frame.groupby(["league", "home", "away"]):
        print(f"\n--- {league}: {home} vs {away} ---")

        def resolve(row):
            if has_family:
                for m in load_markets():
                    if m.code == row.market_code and m.family == row.family:
                        return m
            return markets.get(row.market_code)

        # (a) book margin per family using exact complements / partitions
        by_family: dict[str, list[float]] = {}
        for r in group.itertuples(index=False):
            market = resolve(r)
            family = market.family if market else "UNLISTED"
            by_family.setdefault(family, []).append(float(r.soccer_bet_odds))
        print("  (a) book margin per family (sum of 1/odds - 1):")
        for family, prices in sorted(by_family.items()):
            margin = float(np.sum([1.0 / p for p in prices]) - 1.0)
            print(f"      {family:<22} n={len(prices):<3} margin {margin:+.4f}")

        # (c) EV per market, flagged only for PASSED families
        print("  (c) EV = p_model * odds - 1 (flagged only where the family PASSED):")
        flagged = 0
        for r in group.itertuples(index=False):
            market = resolve(r)
            if market is None:
                print(f"      {r.market_code:<14} UNLISTED (no model price)")
                continue
            fam_status = status.get(market.family, "UNTESTED")
            print(f"      {r.market_code:<14} {market.family:<22} status {fam_status:<9} "
                  f"odds {float(r.soccer_bet_odds):.3f}")
            if fam_status == "PASS":
                flagged += 1
        print(f"      flagged (family PASSED): {flagged}")

    print("\nNOTE: no ROI is claimed. EV uses model probabilities that are only")
    print("      validated for families whose calibration PASSED.")
    return 0


def write_template() -> None:
    TEMPLATE.parent.mkdir(parents=True, exist_ok=True)
    if not TEMPLATE.exists():
        TEMPLATE.write_text(
            "date,league,home,away,market_code,family,soccer_bet_odds,time_recorded\n"
            "2026-09-26,league_one_t3,Bradford City,Barnsley,1,RESULT,2.10,2026-09-24T12:00:00Z\n"
            "2026-09-26,league_one_t3,Bradford City,Barnsley,3+,GOAL_RANGE_FT,1.95,2026-09-24T12:00:00Z\n",
            encoding="utf-8",
        )
        print(f"wrote {TEMPLATE}")


if __name__ == "__main__":
    write_template()
    rows = price_match("league_one_t3", "Bradford City", "Barnsley",
                       (2.10, 3.40, 3.60), (1.95, 1.95))
    print(f"priced {len(rows)} markets")
    passing = [r for r in rows if r["status"] == "PASS"]
    print(f"families PASS: {len({r['family'] for r in passing})}")
    for r in passing[:8]:
        print(f"  {r['code']:<14} {r['family']:<20} p={r['p_fair']:.4f} fair={r['fair_odds']:.3f}")
