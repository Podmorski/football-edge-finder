"""Mainline historical backtest — MAINLINE-HIST-1.

Tests whether soft-book pre-match prices exceed the de-margined Pinnacle
pre-match (power method) fair price by more than 3.5 %.

Markets: 1X2 (each selection), O/U 2.5 (each side), AH main line (each side).
Soft books: B365 and market average (avg_* where present, else bb_av_*).

Discovery seasons: 2017-18 .. 2022-23 (confirmation seasons are locked).

Outputs
-------
- reports/figures/mainline_hist_bets.csv
- reports/figures/mainline_hist_summary.csv
- reports/figures/mainline_hist_breakdown.csv
- one ledger row via core.ledger.log_evaluation
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from core import ledger, odds, splits
from leagues import LEAGUES

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

DISCOVERY_SEASONS = [
    "2017-2018", "2018-2019", "2019-2020",
    "2020-2021", "2021-2022", "2022-2023",
]

CONFIRMATION_SEASONS = set(splits.split_seasons("confirmation"))

LEAGUE_SLUGS = [lg["slug"] for lg in LEAGUES]

EDGE_THRESHOLD = 1.035

SEED = 20260924
N_BOOTSTRAP = 2000

OUT_1X2 = ("home", "draw", "away")
OUT_OU = ("over", "under")
OUT_AH = ("ah_home", "ah_away")

# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #


def load_all_data() -> pd.DataFrame:
    """Load discovery-season rows for all four leagues."""
    frames: list[pd.DataFrame] = []
    for slug in LEAGUE_SLUGS:
        path = Path("data/historical") / f"{slug}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        df = df[df["season"].isin(DISCOVERY_SEASONS)].copy()
        df["league"] = slug
        frames.append(df)
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    result["date"] = pd.to_datetime(result["date"])
    bad = sorted(set(result["season"].unique()) & CONFIRMATION_SEASONS)
    if bad:
        raise RuntimeError(
            f"REFUSED: data contains confirmation season(s) {bad}. "
            "Confirmation data is locked."
        )
    return result.sort_values("date").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Odds extraction helpers
# --------------------------------------------------------------------------- #


def _extract_cols(df: pd.DataFrame, cols: tuple[str, ...]) -> pd.DataFrame | None:
    """Return a float DataFrame of *cols* if all present, else None."""
    if all(c in df.columns for c in cols):
        return df[list(cols)].astype(float)
    return None


def _cascade_avg(df: pd.DataFrame, out_names: tuple[str, ...],
                 candidates: list[tuple[str, tuple[str, ...]]]) -> tuple[pd.DataFrame, pd.Series]:
    """Cascade: first candidate with all 3 valid odds wins per row."""
    n = len(df)
    out = pd.DataFrame(np.nan, index=range(n), columns=list(out_names))
    src = pd.Series([None] * n, index=range(n), dtype=object)
    filled = pd.Series(False, index=range(n))
    for label, cols in candidates:
        if not all(c in df.columns for c in cols):
            continue
        block = df[list(cols)].astype(float)
        valid = ~filled & block.notna().all(axis=1) & (block > 1.0).all(axis=1)
        if valid.any():
            for i, c in enumerate(cols):
                out.loc[valid, out_names[i]] = block.loc[valid, c]
            src = src.where(src.isna(), label)
            filled = filled | valid
        if filled.all():
            break
    return out, src


# --------------------------------------------------------------------------- #
# AH helpers
# --------------------------------------------------------------------------- #


def _is_valid_ah_line(line: float) -> bool:
    """Half-lines (.5) and whole numbers only; exclude quarter lines.

    Handles negative lines correctly: e.g. -0.5 has fractional part 0.5.
    """
    frac = line - np.floor(line)
    return frac == 0.0 or abs(frac - 0.5) < 1e-9


def _matchday_key(date) -> str:
    d = pd.Timestamp(date)
    monday = d - pd.Timedelta(days=d.weekday())
    return monday.strftime("%Y-%m-%d")


# --------------------------------------------------------------------------- #
# Bet construction (vectorized)
# --------------------------------------------------------------------------- #


def _make_matchday_col(df: pd.DataFrame) -> pd.Series:
    """Vectorized matchday column."""
    dates = pd.to_datetime(df["date"])
    return (dates - pd.to_timedelta(dates.dt.dayofweek, unit="D")).dt.strftime("%Y-%m-%d")


def build_bets(df: pd.DataFrame) -> pd.DataFrame:
    """Build one row per (match, market, selection, soft_book).

    Returns a DataFrame with the audit columns plus internal _* helpers.
    """
    n = len(df)
    if n == 0:
        return pd.DataFrame(columns=[
            "date", "league", "season", "home", "away", "fthg", "ftag",
            "market", "selection", "soft_book", "soft_source", "soft_odds",
            "fair_odds", "fair_close", "stake", "pnl", "clv", "won",
            "_matchday", "_edge", "_line", "_quarter_excluded", "_push",
        ])

    fthg = df["fthg"].to_numpy(dtype=float)
    ftag = df["ftag"].to_numpy(dtype=float)
    matchday = _make_matchday_col(df)
    total_goals = fthg + ftag

    # ---- Pinnacle pre-match ----
    pin_1x2 = _extract_cols(df, ("psh", "psd", "psa"))
    pin_ou = _extract_cols(df, ("p>2.5", "p<2.5"))
    pin_ah_odds = _extract_cols(df, ("pahh", "paha"))
    pin_ah_line = df["a_hh"].astype(float) if "a_hh" in df.columns else pd.Series(dtype=float)

    # ---- Pinnacle closing ----
    pin_c_1x2 = _extract_cols(df, ("psch", "pscd", "psca"))
    pin_c_ou = _extract_cols(df, ("pc>2.5", "pc<2.5"))
    pin_c_ah = _extract_cols(df, ("pcahh", "pcaha"))

    # ---- De-margin Pinnacle ----
    fair_1x2 = odds.demargin(pin_1x2, "power") if pin_1x2 is not None else None
    fair_c_1x2 = odds.demargin(pin_c_1x2, "power") if pin_c_1x2 is not None else None
    fair_ou = odds.demargin(pin_ou, "power") if pin_ou is not None else None
    fair_c_ou = odds.demargin(pin_c_ou, "power") if pin_c_ou is not None else None
    fair_ah = odds.demargin(pin_ah_odds, "power") if pin_ah_odds is not None else None
    fair_c_ah = odds.demargin(pin_c_ah, "power") if pin_c_ah is not None else None

    # ---- Soft books ----
    # B365
    b365_1x2 = _extract_cols(df, ("b365_h", "b365_d", "b365_a"))
    b365_ou = _extract_cols(df, ("b365>2.5", "b365<2.5"))
    b365_ah = _extract_cols(df, ("b365_ahh", "b365_aha"))
    # Average
    avg_1x2, avg_src = _cascade_avg(df, OUT_1X2, [
        ("average", ("avg_h", "avg_d", "avg_a")),
        ("average", ("bb_av_h", "bb_av_d", "bb_av_a")),
    ])
    avg_ou, avg_src_ou = _cascade_avg(df, OUT_OU, [
        ("average", ("avg>2.5", "avg<2.5")),
        ("average", ("bb_av>2.5", "bb_av<2.5")),
    ])
    avg_ah, avg_src_ah = _cascade_avg(df, OUT_AH, [
        ("average", ("avg_ahh", "avg_aha")),
        ("average", ("bb_av_ahh", "bb_av_aha")),
    ])

    # ---- Build bet frames ----
    all_bets: list[pd.DataFrame] = []

    # 1X2
    for sel_idx, sel_name in enumerate(OUT_1X2):
        for soft_df, soft_book, soft_src in [
            (b365_1x2, "b365", pd.Series([None]*n, dtype=object)),
            (avg_1x2, "average", avg_src),
        ]:
            if soft_df is None:
                continue
            soft = soft_df.iloc[:, sel_idx]
            fair = fair_1x2.iloc[:, sel_idx] if fair_1x2 is not None else pd.Series(dtype=float)
            fair_c = fair_c_1x2.iloc[:, sel_idx] if fair_c_1x2 is not None else pd.Series(dtype=float)
            fair_o = 1.0 / fair
            fair_c_o = 1.0 / fair_c

            # Valid: both fair and soft exist, soft > 1
            valid = fair_o.notna() & soft.notna() & (soft > 1.0)
            edge = (soft / fair_o - 1.0)
            edge = edge.where(valid)

            # Selection rule
            qualifies = valid & (soft >= fair_o * EDGE_THRESHOLD)

            if qualifies.any():
                q = qualifies.to_numpy()
                s_vals = soft.loc[q].to_numpy()
                f_vals = fair_o.loc[q].to_numpy()
                fc_vals = fair_c_o.loc[q].to_numpy()
                md = matchday.loc[q].to_numpy()
                src_vals = soft_src.loc[q].to_numpy() if soft_src is not None else np.full(q.sum(), soft_book)

                # Outcome
                if sel_name == "home":
                    won = (fthg[q] > ftag[q]).astype(float)
                elif sel_name == "draw":
                    won = (fthg[q] == ftag[q]).astype(float)
                else:
                    won = (fthg[q] < ftag[q]).astype(float)

                pnl = np.where(won == 1, s_vals - 1.0, -1.0)
                clv = np.where(
                    np.isfinite(fc_vals) & (fc_vals > 0),
                    s_vals / fc_vals - 1.0,
                    np.nan,
                )

                idx_b = np.where(q)[0]
                all_bets.append(_make_bet_frame(
                    df, idx_b, sel_name, "1X2", soft_book, src_vals,
                    s_vals, f_vals, fc_vals, clv, won, pnl, md, edge,
                ))

    # O/U 2.5
    for sel_idx, sel_name in enumerate(OUT_OU):
        for soft_df, soft_book, soft_src in [
            (b365_ou, "b365", pd.Series([None]*n, dtype=object)),
            (avg_ou, "average", avg_src_ou),
        ]:
            if soft_df is None:
                continue
            soft = soft_df.iloc[:, sel_idx]
            fair = fair_ou.iloc[:, sel_idx] if fair_ou is not None else pd.Series(dtype=float)
            fair_c = fair_c_ou.iloc[:, sel_idx] if fair_c_ou is not None else pd.Series(dtype=float)
            fair_o = 1.0 / fair
            fair_c_o = 1.0 / fair_c

            valid = fair_o.notna() & soft.notna() & (soft > 1.0)
            edge = (soft / fair_o - 1.0).where(valid)
            qualifies = valid & (soft >= fair_o * EDGE_THRESHOLD)

            if qualifies.any():
                q = qualifies.to_numpy()
                s_vals = soft.loc[q].to_numpy()
                f_vals = fair_o.loc[q].to_numpy()
                fc_vals = fair_c_o.loc[q].to_numpy()
                md = matchday.loc[q].to_numpy()
                src_vals = soft_src.loc[q].to_numpy() if soft_src is not None else np.full(q.sum(), soft_book)

                if sel_name == "over":
                    won = (total_goals[q] > 2.5).astype(float)
                else:
                    won = (total_goals[q] < 2.5).astype(float)

                pnl = np.where(won == 1, s_vals - 1.0, -1.0)
                clv = np.where(
                    np.isfinite(fc_vals) & (fc_vals > 0),
                    s_vals / fc_vals - 1.0,
                    np.nan,
                )

                idx_b = np.where(q)[0]
                all_bets.append(_make_bet_frame(
                    df, idx_b, sel_name, "OU2.5", soft_book, src_vals,
                    s_vals, f_vals, fc_vals, clv, won, pnl, md, edge,
                ))

    # AH
    if pin_ah_odds is not None and len(pin_ah_line) == n:
        for sel_idx, sel_name in enumerate(OUT_AH):
            for soft_df, soft_book, soft_src in [
                (b365_ah, "b365", pd.Series([None]*n, dtype=object)),
                (avg_ah, "average", avg_src_ah),
            ]:
                if soft_df is None:
                    continue
                soft = soft_df.iloc[:, sel_idx]
                fair = fair_ah.iloc[:, sel_idx] if fair_ah is not None else pd.Series(dtype=float)
                fair_c = fair_c_ah.iloc[:, sel_idx] if fair_c_ah is not None else pd.Series(dtype=float)
                fair_o = 1.0 / fair
                fair_c_o = 1.0 / fair_c
                line = pin_ah_line

                # Valid: fair, soft, line all exist; soft > 1
                valid = fair_o.notna() & soft.notna() & (soft > 1.0) & line.notna()
                edge = (soft / fair_o - 1.0).where(valid)

                # Quarter-line filter
                line_arr = line.to_numpy()
                finite_mask = np.isfinite(line_arr)
                frac = np.where(finite_mask, line_arr - np.floor(line_arr), 0.0)
                vl_full = finite_mask & ((frac == 0.0) | (np.abs(frac - 0.5) < 1e-9))
                valid = valid & vl_full

                qualifies = valid & (soft >= fair_o * EDGE_THRESHOLD)

                if qualifies.any():
                    q = qualifies.to_numpy()
                    s_vals = soft.loc[q].to_numpy()
                    f_vals = fair_o.loc[q].to_numpy()
                    fc_vals = fair_c_o.loc[q].to_numpy()
                    md = matchday.loc[q].to_numpy()
                    src_vals = soft_src.loc[q].to_numpy() if soft_src is not None else np.full(q.sum(), soft_book)
                    l_vals = line.loc[q].to_numpy()

                    margin = fthg[q] - ftag[q] + l_vals
                    # home covers if margin > 0, away covers if margin < 0
                    if sel_name == "ah_home":
                        is_win = margin > 0
                        is_lose = margin < 0
                    else:
                        is_win = margin < 0
                        is_lose = margin > 0
                    is_push = margin == 0

                    won = np.where(is_push, "void", np.where(is_win, 1, 0))
                    pnl = np.where(is_push, 0.0, np.where(is_win, s_vals - 1.0, -1.0))
                    clv = np.where(
                        np.isfinite(fc_vals) & (fc_vals > 0),
                        s_vals / fc_vals - 1.0,
                        np.nan,
                    )

                    idx_b = np.where(q)[0]
                    all_bets.append(_make_bet_frame(
                        df, idx_b, sel_name, "AH", soft_book, src_vals,
                        s_vals, f_vals, fc_vals, clv, won, pnl, md, edge,
                        line_vals=l_vals,
                    ))

    if not all_bets:
        return pd.DataFrame(columns=[
            "date", "league", "season", "home", "away", "fthg", "ftag",
            "market", "selection", "soft_book", "soft_source", "soft_odds",
            "fair_odds", "fair_close", "stake", "pnl", "clv", "won",
            "_matchday", "_edge", "_line", "_quarter_excluded", "_push",
        ])

    result = pd.concat(all_bets, ignore_index=True)
    return result


def _make_bet_frame(
    df: pd.DataFrame, idx: np.ndarray, sel_name: str, market: str,
    soft_book: str, src_vals: np.ndarray,
    s_vals: np.ndarray, f_vals: np.ndarray, fc_vals: np.ndarray, clv: np.ndarray,
    won, pnl: np.ndarray, md: np.ndarray, edge: pd.Series,
    line_vals: np.ndarray | None = None,
) -> pd.DataFrame:
    """Build a bet DataFrame slice from vectorized arrays."""
    n_b = len(idx)
    return pd.DataFrame({
        "date": df.loc[idx, "date"].values,
        "league": df.loc[idx, "league"].values,
        "season": df.loc[idx, "season"].values,
        "home": df.loc[idx, "team_home"].values,
        "away": df.loc[idx, "team_away"].values,
        "fthg": df.loc[idx, "fthg"].values,
        "ftag": df.loc[idx, "ftag"].values,
        "market": market,
        "selection": sel_name,
        "soft_book": soft_book,
        "soft_source": src_vals,
        "soft_odds": s_vals,
        "fair_odds": f_vals,
        "fair_close": fc_vals,
        "stake": 1.0,
        "pnl": pnl,
        "clv": clv,
        "won": won,
        "_matchday": md,
        "_edge": edge.loc[idx].to_numpy(),
        "_line": line_vals if line_vals is not None else np.full(n_b, np.nan),
        "_quarter_excluded": 0,
        "_push": np.where(won == "void", 1, 0),
    })


# --------------------------------------------------------------------------- #
# Quarter-line exclusion count
# --------------------------------------------------------------------------- #


def count_quarter_exclusions(df: pd.DataFrame) -> int:
    """Count rows where Pinnacle AH odds + soft odds exist but line is quarter."""
    pin_ah = _extract_cols(df, ("pahh", "paha"))
    if pin_ah is None:
        return 0
    line = df["a_hh"].astype(float) if "a_hh" in df.columns else pd.Series(dtype=float)
    if len(line) != len(df):
        return 0

    b365_ah = _extract_cols(df, ("b365_ahh", "b365_aha"))
    avg_ah, _ = _cascade_avg(df, OUT_AH, [
        ("average", ("avg_ahh", "avg_aha")),
        ("average", ("bb_av_ahh", "bb_av_aha")),
    ])

    pin_valid = pin_ah.notna().all(axis=1)
    line_valid = line.notna()
    soft_valid = (b365_ah.notna().all(axis=1) if b365_ah is not None else pd.Series(False, index=df.index)) | \
                 (avg_ah.notna().all(axis=1) if avg_ah is not None else pd.Series(False, index=df.index))

    any_valid = pin_valid & line_valid & soft_valid
    if not any_valid.any():
        return 0

    lines = line[any_valid]
    return int(sum(1 for l in lines if not _is_valid_ah_line(l)))


# --------------------------------------------------------------------------- #
# Aggregation & statistics
# --------------------------------------------------------------------------- #


def bootstrap_ci(series: pd.DataFrame, col: str, stat_fn,
                 n_draws: int, seed: int) -> tuple[float, float, float]:
    """Bootstrap 95% CI by matchday (resample matchdays with replacement).

    Parameters
    ----------
    series : DataFrame
        Must contain ``_matchday`` and ``col``.
    col : str
        Column name to compute the statistic on.
    stat_fn : callable
        Function from pandas Series -> float.
    """
    rng = np.random.default_rng(seed)
    if series.empty or col not in series.columns:
        return (float("nan"), float("nan"), float("nan"))

    groups = series.groupby("_matchday")
    md_keys = list(groups.groups.keys())
    n_md = len(md_keys)
    if n_md == 0:
        return (float("nan"), float("nan"), float("nan"))

    group_data = {k: groups.get_group(k)[col].to_numpy() for k in md_keys}
    original_val = stat_fn(series[col])

    resampled = np.empty(n_draws)
    for d in range(n_draws):
        idx = rng.integers(0, n_md, size=n_md)
        combined = np.concatenate([group_data[md_keys[i]] for i in idx])
        resampled[d] = stat_fn(pd.Series(combined))

    return (original_val, float(np.percentile(resampled, 2.5)), float(np.percentile(resampled, 97.5)))


def holm_correction(p_values: list[float]) -> list[float]:
    """Holm-Bonferroni correction.

    Sort ascending, multiply each by (m - rank), enforce monotonicity, cap at 1.
    """
    m = len(p_values)
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    corrected = [0.0] * m
    for rank, (orig_idx, p) in enumerate(indexed):
        corrected[orig_idx] = min(p * (m - rank), 1.0)
    for i in range(1, m):
        corrected[i] = max(corrected[i], corrected[i - 1])
    return corrected


def compute_summary(bets_df: pd.DataFrame) -> pd.DataFrame:
    """Per-(soft_book, market) summary with bootstrap CIs and Holm correction."""
    groups = bets_df.groupby(["soft_book", "market"])
    rows = []
    for (book, market), grp in groups:
        n_bets = len(grp)
        n_void = int((grp["won"] == "void").sum())
        n_missing_close = int(grp["clv"].isna().sum())

        active = grp[grp["won"] != "void"]
        total_staked = float(len(active))
        total_pnl = float(active["pnl"].sum())
        roi = total_pnl / total_staked if total_staked > 0 else float("nan")

        clv_series = grp.dropna(subset=["clv"])
        mean_clv = float(clv_series["clv"].mean()) if not clv_series.empty else float("nan")

        # ROI bootstrap: resample matchdays with replacement
        roi_vals = []
        rng_roi = np.random.default_rng(SEED)
        roi_groups = grp.groupby("_matchday")
        roi_md_keys = list(roi_groups.groups.keys())
        roi_md_n = len(roi_md_keys)
        roi_group_pnl = {k: v[v["won"] != "void"]["pnl"] for k, v in roi_groups}
        roi_group_n = {k: len(v[v["won"] != "void"]) for k, v in roi_groups}
        for _ in range(N_BOOTSTRAP):
            idx = rng_roi.integers(0, roi_md_n, size=roi_md_n)
            total_p = sum(float(roi_group_pnl[roi_md_keys[i]].sum()) for i in idx)
            total_n = sum(int(roi_group_n[roi_md_keys[i]]) for i in idx)
            roi_vals.append(total_p / total_n if total_n > 0 else 0.0)
        roi_vals = np.array(roi_vals)
        roi_ci_low = float(np.percentile(roi_vals, 2.5))
        roi_ci_high = float(np.percentile(roi_vals, 97.5))

        # CLV bootstrap
        clv_vals = []
        rng_clv = np.random.default_rng(SEED + 1)
        clv_groups = clv_series.groupby("_matchday")
        clv_md_keys = list(clv_groups.groups.keys())
        clv_md_n = len(clv_md_keys)
        clv_group_vals = {k: v["clv"].to_numpy() for k, v in clv_groups}
        for _ in range(N_BOOTSTRAP):
            idx = rng_clv.integers(0, clv_md_n, size=clv_md_n)
            combined = np.concatenate([clv_group_vals[clv_md_keys[i]] for i in idx])
            clv_vals.append(float(np.mean(combined)))
        clv_vals = np.array(clv_vals)
        clv_ci_low = float(np.percentile(clv_vals, 2.5))
        clv_ci_high = float(np.percentile(clv_vals, 97.5))

        # p_raw: one-sided bootstrap p that mean CLV <= 0
        p_raw = float(np.mean(clv_vals <= 0))

        passes = bool(mean_clv > 0 and clv_ci_low > 0 and n_bets >= 300)
        n_ge_300 = int(n_bets >= 300)

        rows.append({
            "soft_book": book, "market": market,
            "n_bets": n_bets, "n_void": n_void,
            "n_missing_close": n_missing_close,
            "roi": roi, "roi_ci_low": roi_ci_low, "roi_ci_high": roi_ci_high,
            "mean_clv": mean_clv, "clv_ci_low": clv_ci_low, "clv_ci_high": clv_ci_high,
            "p_raw": p_raw, "holm_p": 0.0,
            "passes": passes, "n_ge_300": n_ge_300,
        })

    summary = pd.DataFrame(rows)
    if len(summary) > 1:
        p_vals = summary["p_raw"].tolist()
        corrected = holm_correction(p_vals)
        summary["holm_p"] = corrected
    return summary


def compute_breakdown(bets_df: pd.DataFrame) -> pd.DataFrame:
    """Descriptive breakdowns (edge, odds, threshold)."""
    rows = []

    # Edge buckets
    edge_col = bets_df["_edge"].dropna()
    for label, lo, hi in [("3.5-5%", 0.035, 0.05), ("5-8%", 0.05, 0.08), ("8%+", 0.08, float("inf"))]:
        mask = (edge_col.index.isin(bets_df.index)) & (edge_col >= lo) & (edge_col < hi)
        subset = bets_df.loc[edge_col[mask].index]
        if subset.empty:
            continue
        for book in subset["soft_book"].unique():
            for market in subset["market"].unique():
                sub = subset[(subset["soft_book"] == book) & (subset["market"] == market)]
                act = sub[sub["won"] != "void"]
                r = float(act["pnl"].sum()) / len(act) if len(act) > 0 else float("nan")
                mc = float(sub["clv"].mean()) if sub["clv"].notna().any() else float("nan")
                rows.append({"soft_book": book, "market": market, "dimension": "edge",
                             "bucket": label, "n_bets": len(sub), "roi": r, "mean_clv": mc})

    # Odds buckets
    for label, lo, hi in [("<2", 0, 2), ("2-4", 2, 4), ("4+", 4, float("inf"))]:
        mask = (bets_df["soft_odds"] >= lo) & (bets_df["soft_odds"] < hi)
        subset = bets_df[mask]
        if subset.empty:
            continue
        for book in subset["soft_book"].unique():
            for market in subset["market"].unique():
                sub = subset[(subset["soft_book"] == book) & (subset["market"] == market)]
                act = sub[sub["won"] != "void"]
                r = float(act["pnl"].sum()) / len(act) if len(act) > 0 else float("nan")
                mc = float(sub["clv"].mean()) if sub["clv"].notna().any() else float("nan")
                rows.append({"soft_book": book, "market": market, "dimension": "odds",
                             "bucket": label, "n_bets": len(sub), "roi": r, "mean_clv": mc})

    # Threshold sensitivity
    for mult in [1.00, 1.035, 1.07]:
        edge_series = bets_df["soft_odds"] / bets_df["fair_odds"] - 1.0
        mask = edge_series >= (mult - 1.0)
        subset = bets_df[mask]
        if subset.empty:
            continue
        for book in subset["soft_book"].unique():
            for market in subset["market"].unique():
                sub = subset[(subset["soft_book"] == book) & (subset["market"] == market)]
                act = sub[sub["won"] != "void"]
                r = float(act["pnl"].sum()) / len(act) if len(act) > 0 else float("nan")
                mc = float(sub["clv"].mean()) if sub["clv"].notna().any() else float("nan")
                rows.append({"soft_book": book, "market": market, "dimension": "threshold",
                             "bucket": str(mult), "n_bets": len(sub), "roi": r, "mean_clv": mc})

    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main() -> int:
    print("=" * 80)
    print("MAINLINE-HIST-1  |  soft-book vs Pinnacle pre-match (power)")
    print("=" * 80)

    df = load_all_data()
    print(f"Loaded {len(df)} matches across {df['league'].nunique()} leagues, "
          f"{df['season'].nunique()} seasons")

    bets = build_bets(df)
    print(f"\nTotal bets generated: {len(bets)}")

    quarter_excluded = count_quarter_exclusions(df)
    push_count = int((bets["won"] == "void").sum()) if not bets.empty else 0
    missing_close = int(bets["clv"].isna().sum()) if not bets.empty else 0

    print(f"  AH quarter-line rows excluded: {quarter_excluded}")
    print(f"  AH pushes (void): {push_count}")
    print(f"  Bets with missing closing price: {missing_close}")

    # Write bets CSV
    bets_path = Path("reports/figures/mainline_hist_bets.csv")
    bets_path.parent.mkdir(parents=True, exist_ok=True)
    bets_out = bets.drop(columns=["_matchday", "_edge", "_line", "_quarter_excluded", "_push"], errors="ignore")
    bets_out.to_csv(bets_path, index=False)
    print(f"\nWrote {len(bets_out)} bets to {bets_path}")

    # Summary
    summary = compute_summary(bets)
    summary_path = Path("reports/figures/mainline_hist_summary.csv")
    summary.to_csv(summary_path, index=False)
    print(f"Wrote summary to {summary_path}")

    # Breakdown
    breakdown = compute_breakdown(bets)
    breakdown_path = Path("reports/figures/mainline_hist_breakdown.csv")
    breakdown.to_csv(breakdown_path, index=False)
    print(f"Wrote breakdown to {breakdown_path}")

    # Print summary table
    print("\n" + "=" * 80)
    print("SUMMARY TABLE")
    print("=" * 80)
    hdr = f"{'soft_book':<12}{'market':<8}{'n_bets':>7}{'n_void':>7}{'n_miss':>7}{'roi':>8}"
    hdr += f"{'roi_ci':>20}{'mean_clv':>10}{'clv_ci':>20}{'holm_p':>8}{'passes':>7}"
    print(hdr)
    for _, row in summary.iterrows():
        roi_ci = f"[{row['roi_ci_low']:.4f}, {row['roi_ci_high']:.4f}]"
        clv_ci = f"[{row['clv_ci_low']:.4f}, {row['clv_ci_high']:.4f}]"
        print(f"{row['soft_book']:<12}{row['market']:<8}{row['n_bets']:>7}{row['n_void']:>7}"
              f"{row['n_missing_close']:>7}{row['roi']:>8.4f}{roi_ci:>20}"
              f"{row['mean_clv']:>10.4f}{clv_ci:>20}{row['holm_p']:>8.4f}"
              f"{'PASS' if row['passes'] else 'FAIL':>7}")

    # Coverage by season
    print("\n" + "=" * 80)
    print("COVERAGE BY SEASON")
    print("=" * 80)
    if not bets.empty:
        cov = bets.groupby(["season", "market"]).size().unstack(fill_value=0)
        print(cov.to_string())

    # Breakdown note
    print("\n" + "-" * 80)
    print("BREAKDOWN (descriptive only — NEVER used to select anything)")
    print("-" * 80)
    if not breakdown.empty:
        print(breakdown.to_string(index=False, float_format=lambda v: f"{v:.4f}" if isinstance(v, float) and not np.isnan(v) else str(v)))

    # Ledger
    active_bets = bets[bets["won"] != "void"]
    pooled_roi = float(active_bets["pnl"].sum()) / len(active_bets) if len(active_bets) > 0 else 0.0
    pooled_clv = float(bets["clv"].mean()) if bets["clv"].notna().any() else 0.0

    verdicts = []
    for _, row in summary.iterrows():
        verdicts.append(f"{row['soft_book']}/{row['market']}={'PASS' if row['passes'] else 'FAIL'}")

    ledger.log_evaluation(
        rule_config="MAINLINE-HIST-1",
        split="discovery:2017-2018..2022-2023",
        market="1X2+OU2.5+AH",
        benchmark_name="pinnacle_prematch_power",
        n_bets=int(len(bets)),
        roi=pooled_roi,
        mean_clv=pooled_clv,
        notes="; ".join(verdicts),
    )
    print(f"\nLogged evaluation to ledger (pooled: {len(bets)} bets, "
          f"ROI={pooled_roi:.4f}, mean CLV={pooled_clv:.4f})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
