"""Split access for the project.

Splits are defined in ``config/splits.yaml``. The ``confirmation`` split is
**LOCKED**: reading it requires ``confirm=True`` *and* a non-empty ``reason``,
and every access is appended to ``research/confirmation_access.csv``.

Each confirmation season is a one-shot resource: once used it is no longer
fresh, so accesses are logged and few.
"""

from __future__ import annotations

import csv
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from leagues import LEAGUES

CONFIG_PATH = Path("config/splits.yaml")
DATA_DIR = Path("data/historical")
CONFIRMATION_ACCESS_PATH = Path("research/confirmation_access.csv")

CONFIRMATION_ACCESS_FIELDS = [
    "timestamp",
    "git_hash",
    "split",
    "reason",
    "leagues",
    "n_rows",
]


class ConfirmationLockedError(PermissionError):
    """Raised when a locked split is requested without explicit confirmation."""


def git_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001 - not fatal for a research log
        return "unknown"


def load_config(config_path: Path | None = None) -> dict:
    path = Path(config_path) if config_path else CONFIG_PATH
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def available_splits(config_path: Path | None = None) -> list[str]:
    return list(load_config(config_path)["splits"].keys())


def split_seasons(split: str, config_path: Path | None = None) -> list[str]:
    cfg = load_config(config_path)["splits"]
    if split not in cfg:
        raise KeyError(f"Unknown split {split!r}; available: {sorted(cfg)}")
    return list(cfg[split]["seasons"])


def is_locked(split: str, config_path: Path | None = None) -> bool:
    cfg = load_config(config_path)["splits"]
    if split not in cfg:
        raise KeyError(f"Unknown split {split!r}; available: {sorted(cfg)}")
    return bool(cfg[split].get("locked", False))


def _log_confirmation_access(
    reason: str, league_slugs: list[str], n_rows: int, access_log_path: Path | None = None
) -> None:
    path = Path(access_log_path) if access_log_path else CONFIRMATION_ACCESS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CONFIRMATION_ACCESS_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "git_hash": git_hash(),
                "split": "confirmation",
                "reason": reason,
                "leagues": "|".join(league_slugs),
                "n_rows": n_rows,
            }
        )


def load_split(
    split: str,
    *,
    confirm: bool = False,
    reason: str | None = None,
    leagues: list[str] | None = None,
    config_path: Path | None = None,
    data_dir: Path | None = None,
    access_log_path: Path | None = None,
) -> pd.DataFrame:
    """Return the match rows for a named split.

    Locked splits require ``confirm=True`` and a non-empty ``reason``; the access
    is appended to the confirmation access log.

    Parameters
    ----------
    split : str
        One of the splits in ``config/splits.yaml``.
    confirm : bool
        Must be True to read a locked split.
    reason : str
        Non-empty justification. Required for locked splits.
    leagues : list[str] or None
        League slugs to include (default: all in ``leagues.LEAGUES``).
    """
    seasons = split_seasons(split, config_path)
    locked = is_locked(split, config_path)

    if locked:
        if not confirm:
            raise ConfirmationLockedError(
                f"Split {split!r} is locked. Pass confirm=True and a reason=... "
                "to read it; each access is logged."
            )
        if not reason or not reason.strip():
            raise ValueError(
                f"Split {split!r} is locked and requires a non-empty reason=..."
            )

    data_path = Path(data_dir) if data_dir else DATA_DIR
    selected = leagues if leagues is not None else [lg["slug"] for lg in LEAGUES]

    frames: list[pd.DataFrame] = []
    for slug in selected:
        path = data_path / f"{slug}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        df = df[df["season"].isin(seasons)].copy()
        df["league"] = slug
        frames.append(df)

    result = (
        pd.concat(frames).reset_index()
        if frames
        else pd.DataFrame(columns=["id", "league", "season"])
    )

    if locked:
        _log_confirmation_access(reason or "", selected, len(result), access_log_path)

    return result