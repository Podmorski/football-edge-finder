"""One-off: re-classify the Stockport-Peterborough 4+ flag under the provenance rule.

The flag's fair price was DERIVED by the model from the 3.25 totals line. PS3838
also carries a direct Over/Under **3.5** line, so ``4+`` is DIRECT and its fair
price is that line (2.0914), not the model's 1.8796. Mozzart's 1.95 no longer
clears the 2.1646 minimum, so the flag is withdrawn.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fair_sheet as fs
import flag_audit
import paper_trade
import ps3838_odds

snapshot = json.loads(
    Path("data/ps3838/leagues/league_one_t3.json").read_text(encoding="utf-8"))
event = next(e for e in snapshot["events"] if "Stockport" in e.get("home", ""))
prices = ps3838_odds.sharp_prices(event)
overrides = fs.sharp_overrides(prices)
direct = fs.direct_provenance(prices)
fair = fs.fair_odds(*overrides[("GOAL_RANGE_FT", "4+")])
min_acceptable = fair * 1.035
mozzart = 1.95
print(f"4+ direct={('GOAL_RANGE_FT', '4+') in direct} fair={fair:.4f} "
      f"min={min_acceptable:.4f} mozzart={mozzart}")
assert ("GOAL_RANGE_FT", "4+") in direct
assert mozzart < min_acceptable, "the flag would survive the direct price"

rows = paper_trade.read_rows()
kept = [r for r in rows
        if not (r["home"] == "Stockport County" and r["family"] == "GOAL_RANGE_FT"
                and r["code"] == "4+")]
print(f"paper bets: {len(rows)} -> {len(kept)}")
paper_trade.write_rows(kept)

state = flag_audit._load_state()
state["samples"]["SHARP_WIDE"] = []
state["stats"]["SHARP_WIDE"]["flags"] = 0
state["notes"] = [n for n in state.get("notes", []) if "Stockport" not in n]
state["notes"].append(
    "Stockport County vs Peterborough United GOAL_RANGE_FT 4+ (2026-09-26): "
    "re-classified DIRECT — PS3838 carries Over/Under 3.5, so the fair price is the "
    "de-margined line (2.0914), not the model's 1.8796. Mozzart 1.95 no longer clears "
    "the 2.1646 minimum, so the flag is withdrawn.")
flag_audit.STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
flag_audit.REPORT.write_text(flag_audit._render(state), encoding="utf-8")
print("rewrote", flag_audit.REPORT)
