"""Flag audit — catch a Mozzart↔catalogue mapping bug before it pollutes results.

PART C of the widening session. The **first 10 flags of each track** are dumped
to ``reports/flag_audit.md`` with the raw Mozzart price, the de-margined PS3838
fair price, the section, the code, the settlement meaning and both snapshot
timestamps. The section decides what a code means, so a wrong ``(section, code)``
mapping shows up here as an implausible price or meaning before any CLV exists.

A track whose **flag rate exceeds 3x the historical B365 1X2 rate** (about 1 flag
per 30 matches) is marked **SUSPECT**: either the book is unusually soft or a
mapping is wrong. The verdict is recorded in the same file.

State lives in ``data/paper/flag_audit_state.json`` (the exact rows kept and the
cumulative flag/match counters); ``reports/flag_audit.md`` is regenerated from it
on every flag run, so the report is deterministic.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

STATE = Path("data/paper/flag_audit_state.json")
REPORT = Path("reports/flag_audit.md")

SAMPLE_PER_TRACK = 10
B365_RATE = 1.0 / 30.0          # historical 1X2 flag rate (~1 per 30 matches)
SUSPECT_MULTIPLE = 3.0
TRACKS = ("SHARP_WIDE", "MODEL_4L")

FIELDS = ["match", "kickoff", "family", "provenance", "section", "code", "meaning",
          "mozzart_odds", "fair_odds", "min_acceptable",
          "mozzart_snapshot", "ps3838_snapshot"]


def _load_state() -> dict:
    if STATE.exists():
        try:
            doc = json.loads(STATE.read_text(encoding="utf-8"))
            doc.setdefault("samples", {})
            doc.setdefault("stats", {})
            doc.setdefault("notes", [])
            return doc
        except (ValueError, OSError):
            pass
    return {"samples": {}, "stats": {}, "notes": []}


def _row(flag: dict) -> dict:
    return {
        "match": f"{flag['home']} vs {flag['away']}",
        "kickoff": flag["kickoff"],
        "family": flag["family"],
        "provenance": flag.get("provenance", "DERIVED"),
        "section": flag.get("section", ""),
        "code": flag.get("code", ""),
        "meaning": flag.get("meaning", ""),
        "mozzart_odds": f"{flag['mozzart_odds']:.3f}",
        "fair_odds": f"{flag['fair_odds']:.4f}",
        "min_acceptable": f"{flag['min_acceptable']:.4f}",
        "mozzart_snapshot": flag.get("mozzart_snapshot", ""),
        "ps3838_snapshot": flag.get("pinnacle_snapshot", ""),
    }


def _rate(state: dict, track: str) -> tuple[int, int, float]:
    stat = state["stats"].get(track, {})
    flags = int(stat.get("flags", 0))
    matches = int(stat.get("matches", 0))
    return flags, matches, (flags / matches if matches else 0.0)


def _render(state: dict) -> str:
    lines = [
        "# Flag audit — first flags of each track",
        "",
        "The **first 10 flags of each track**, with the raw Mozzart price, the",
        "de-margined **PS3838** fair price, the Serbian section, the code, the",
        "settlement meaning and both snapshot timestamps. The section decides what a",
        "code means, so a mapping bug shows here as an implausible price or meaning",
        "before any CLV exists.",
        "",
        f"A track is **SUSPECT** when its flag rate exceeds {SUSPECT_MULTIPLE:g}x the",
        f"historical B365 1X2 rate (~1 per 30 matches, i.e. {B365_RATE:.2%}), so more",
        f"than {SUSPECT_MULTIPLE * B365_RATE:.1%} of matches.",
        "",
    ]
    for track in TRACKS:
        flags, matches, rate = _rate(state, track)
        suspect = rate > SUSPECT_MULTIPLE * B365_RATE
        verdict = "**SUSPECT**" if suspect else "ok"
        lines += [
            f"## {track} — {verdict}",
            "",
            f"flags {flags} / matches {matches} = rate {rate:.2%} "
            f"(threshold {SUSPECT_MULTIPLE * B365_RATE:.2%})",
            "",
        ]
        sample = state["samples"].get(track, [])
        if not sample:
            lines += ["_no flags recorded yet._", ""]
            continue
        lines += ["| " + " | ".join(FIELDS) + " |",
                  "|" + "---|" * len(FIELDS)]
        for row in sample:
            lines.append("| " + " | ".join(str(row.get(field, "")) for field in FIELDS) + " |")
        lines.append("")
    if state.get("notes"):
        lines += ["## Re-classified flags", ""]
        lines += [f"- {note}" for note in state["notes"]]
        lines.append("")
    lines += [
        "---",
        "",
        f"_updated {datetime.now(timezone.utc).isoformat(timespec='seconds')}_",
        "",
    ]
    return "\n".join(lines)


def audit(flags: list[dict], matches: int = 0, report: Path | None = None) -> int:
    """Record the first ``SAMPLE_PER_TRACK`` flags per track and rewrite the report.

    ``matches`` is the number of matches priced this run (the denominator of the
    flag rate). Returns the number of flags newly kept in the sample.
    """
    state = _load_state()
    kept = 0
    for track in TRACKS:
        track_flags = [flag for flag in flags if flag.get("track", "SHARP_WIDE") == track]
        state["stats"][track] = state["stats"].get(track, {"flags": 0, "matches": 0})
        state["stats"][track]["flags"] += len(track_flags)
        state["stats"][track]["matches"] += matches
        sample = state["samples"].setdefault(track, [])
        for flag in track_flags:
            if len(sample) >= SAMPLE_PER_TRACK:
                break
            sample.append(_row(flag))
            kept += 1
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    target = report or REPORT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_render(state), encoding="utf-8")
    return kept