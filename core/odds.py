"""Canonical odds accessors across football-data.co.uk eras.

football-data.co.uk changed odds providers over time:

* **2015-16 .. 2018-19** — B365 pre-match + Pinnacle + **BetBrain** averages
  (``BbAvH/D/A``, ``BbMxH/D/A``, ``BbAv>2.5``, ``BbAv<2.5``, ``BbAHh``,
  ``BbAvAHH/A``). No market average, no closing prices.
* **2019-20 onward** — market average (``Avg``), closing averages (``AvgC``)
  and closing B365/Pinnacle, plus Asian handicap lines.

Every accessor returns odds **plus a per-row source label**, so downstream code
can tell which provider actually priced each match. Probability conversion is by
proportional normalisation (default) or the power method (alternative).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# candidate cascades: (label, column names in output order)
# --------------------------------------------------------------------------- #
PREMATCH_1X2 = [
    ("Avg", ("avg_h", "avg_d", "avg_a")),
    ("BbAv", ("bb_av_h", "bb_av_d", "bb_av_a")),
    ("B365", ("b365_h", "b365_d", "b365_a")),
]
CLOSING_1X2 = [
    ("AvgC", ("avg_ch", "avg_cd", "avg_ca")),
    ("PSC", ("psch", "pscd", "psca")),
    ("B365C", ("b365_ch", "b365_cd", "b365_ca")),
]
PREMATCH_OU25 = [
    ("Avg>2.5", ("avg>2.5", "avg<2.5")),
    ("BbAv>2.5", ("bb_av>2.5", "bb_av<2.5")),
    ("B365>2.5", ("b365>2.5", "b365<2.5")),
]
CLOSING_OU25 = [
    ("AvgC>2.5", ("avg_c>2.5", "avg_c<2.5")),
    ("PC>2.5", ("pc>2.5", "pc<2.5")),
    ("B365C>2.5", ("b365_c>2.5", "b365_c<2.5")),
]
# Asian handicap: the odds columns only. The handicap LINE lives in a
# separate column ('a_hh' pre-match, 'ah_ch' closing) and is attached below.
PREMATCH_AH = [
    ("AvgAH", ("avg_ahh", "avg_aha")),
    ("BbAH", ("bb_av_ahh", "bb_av_aha")),
    ("B365AH", ("b365_ahh", "b365_aha")),
]
CLOSING_AH = [
    ("AvgCAH", ("avg_cahh", "avg_caha")),
    ("PCAH", ("pcahh", "pcaha")),
    ("B365CAH", ("b365_cahh", "b365_caha")),
]

OUT_1X2 = ("home", "draw", "away")
OUT_OU = ("over", "under")
OUT_AH = ("home", "away")


@dataclass
class Market:
    """Odds for one market, with the source label used per row."""

    odds: pd.DataFrame  # requested probability columns (+ 'line' for AH)
    source: pd.Series  # provider label, None where unavailable

    @property
    def available(self) -> pd.Series:
        return self.source.notna()

    def __len__(self) -> int:
        return len(self.odds)


def _cascade(df: pd.DataFrame, candidates, out_names) -> Market:
    """Fill odds by preference order, per row, recording which source was used."""
    n, n_out = len(df), len(out_names)
    odds = pd.DataFrame(np.nan, index=range(n), columns=list(out_names))
    source = pd.Series([None] * n, index=range(n), dtype=object)
    filled = pd.Series(False, index=range(n))

    for label, cols in candidates:
        if not all(c in df.columns for c in cols):
            continue
        block = df.loc[:, list(cols)].astype(float).reset_index(drop=True)
        valid = ~filled & block.notna().all(axis=1) & (block > 1.0).all(axis=1)
        if valid.any():
            for i in range(n_out):
                odds.loc[valid, out_names[i]] = block.loc[valid, cols[i]].to_numpy()
            source.loc[valid] = label
            filled = filled | valid
        if filled.all():
            break

    return Market(odds=odds, source=source)


def prematch_1x2(df: pd.DataFrame) -> Market:
    """Avg, else BbAv, else B365."""
    return _cascade(df, PREMATCH_1X2, OUT_1X2)


def closing_1x2(df: pd.DataFrame) -> Market:
    """AvgC, else PSC, else B365C, else unavailable."""
    return _cascade(df, CLOSING_1X2, OUT_1X2)


def prematch_ou25(df: pd.DataFrame) -> Market:
    return _cascade(df, PREMATCH_OU25, OUT_OU)


def closing_ou25(df: pd.DataFrame) -> Market:
    return _cascade(df, CLOSING_OU25, OUT_OU)


def _first_column(df: pd.DataFrame, names: tuple[str, ...]) -> pd.Series:
    """First present column from ``names``, else an all-NaN series."""
    for name in names:
        if name in df.columns:
            return df[name].astype(float).reset_index(drop=True)
    return pd.Series(np.nan, index=range(len(df)), dtype=float)


def prematch_ah(df: pd.DataFrame) -> Market:
    """Asian handicap with the pre-match line (``a_hh``, else ``bb_a_hh``)."""
    market = _cascade(df, PREMATCH_AH, OUT_AH)
    market.odds["line"] = _first_column(df, ("a_hh", "bb_a_hh"))
    return market


def closing_ah(df: pd.DataFrame) -> Market:
    """Asian handicap with the closing line (``ah_ch``)."""
    market = _cascade(df, CLOSING_AH, OUT_AH)
    market.odds["line"] = _first_column(df, ("ah_ch",))
    return market


# --------------------------------------------------------------------------- #
# probability conversion
# --------------------------------------------------------------------------- #
def demargin_proportional(odds: pd.DataFrame) -> pd.DataFrame:
    """p_i = (1/o_i) / sum_j (1/o_j)."""
    raw = 1.0 / odds.to_numpy(dtype=float)
    return pd.DataFrame(
        raw / raw.sum(axis=1, keepdims=True), index=odds.index, columns=odds.columns
    )


def demargin_power(odds: pd.DataFrame) -> pd.DataFrame:
    """p_i ∝ (1/o_i)^k, with k solved so the probabilities sum to 1."""
    raw = 1.0 / odds.to_numpy(dtype=float)
    out = np.empty_like(raw)
    for i in range(raw.shape[0]):
        row = raw[i]
        if not np.all(np.isfinite(row)):
            out[i] = np.nan
            continue
        lo, hi = 0.5, 5.0
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            total = np.power(row, mid).sum()
            if total > 1.0:
                lo = mid
            else:
                hi = mid
        powered = np.power(row, 0.5 * (lo + hi))
        out[i] = powered / powered.sum()
    return pd.DataFrame(out, index=odds.index, columns=odds.columns)


def demargin(odds: pd.DataFrame, method: str = "proportional") -> pd.DataFrame:
    if method == "proportional":
        return demargin_proportional(odds)
    if method == "power":
        return demargin_power(odds)
    raise ValueError(f"unknown de-margin method: {method!r}")


def booksum_margin(odds: pd.DataFrame) -> pd.Series:
    """Overround implied by the raw book: sum(1/o) - 1, per row."""
    raw = 1.0 / odds.to_numpy(dtype=float)
    return pd.Series(raw.sum(axis=1) - 1.0, index=odds.index)