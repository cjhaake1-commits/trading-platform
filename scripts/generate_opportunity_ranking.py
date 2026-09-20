"""Generate a fail-closed opportunity research report; never submits orders."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import json

from autotrader.native_provider_scan import scan_all_native_providers

if __name__ == "__main__":
    # Discovery is intentionally fail-closed until a provider supplies current,
    # cost-adjusted evidence. These rows make coverage visible without inventing signals.
    rows, health = scan_all_native_providers()
    funnel = {"scanned": len(rows) // 2, "signal_detected": 0, "edge_positive": 0, "risk_quantified": 0, "capital_available": 0, "eligible": 0, "submitted": 0, "rejection_reasons": {}}
    for row in rows:
        funnel["rejection_reasons"][row["status"]] = funnel["rejection_reasons"].get(row["status"], 0) + 1
    Path("var/reports/opportunity-funnel.json").parent.mkdir(parents=True, exist_ok=True)
    Path("var/reports/opportunity-funnel.json").write_text(json.dumps({"provider_health": health, "paper_only": True, **funnel}, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"scan_counts": funnel, "health": health}, sort_keys=True))
