"""Column-name normalisation for football-data.co.uk data.

Some seasons' CSV files begin with a UTF-8 BOM. When ``requests`` decodes those
bytes as latin-1 the BOM survives as the literal 3-character prefix ``ï»¿`` on
the first column name, so ``Div`` becomes ``ï»¿div`` and penaltyblog sanitises
it to ``ï»¿_div``. That leaves two complementary ``Div`` columns.

:func:`coalesce_bom_columns` merges such artefact columns back into their clean
counterparts (filling NaNs both ways) and drops the artefact. Nothing is lost:
the artefact rows are coalesced into the clean column rather than discarded.
"""

from __future__ import annotations

import re

import pandas as pd

# The literal 3-character sequence you get when a UTF-8 BOM (EF BB BF) is
# decoded as latin-1, plus the real BOM character for good measure.
BOM_TEXTS = ("ï»¿", "\ufeff")


def _strip_bom(name: str) -> str:
    text = str(name)
    for bom in BOM_TEXTS:
        text = text.replace(bom, "")
    return text


def is_artefact(name: str) -> bool:
    """True if the column name carries BOM junk or non-ASCII characters."""
    text = str(name)
    return (text != _strip_bom(text)) or (not text.isascii())


def clean_name(name: str) -> str:
    """Turn an artefact column name into its intended clean name."""
    text = _strip_bom(name)
    text = re.sub(r"[^0-9a-zA-Z]+", "_", text)
    return text.strip("_").lower()


def coalesce_bom_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Merge BOM-prefixed duplicate columns into their clean counterparts.

    Returns a new frame. Row count is always preserved.
    """
    artefacts = [c for c in df.columns if is_artefact(c)]
    if not artefacts:
        return df

    out = df.copy()
    for column in artefacts:
        target = clean_name(column)
        if not target:
            out = out.drop(columns=[column])
            continue

        if target in out.columns:
            # Coalesce both directions so no value is lost.
            out[target] = out[target].where(out[target].notna(), out[column])
            out[column] = out[column].where(out[column].notna(), out[target])
            out = out.drop(columns=[column])
        else:
            out = out.rename(columns={column: target})

    return out