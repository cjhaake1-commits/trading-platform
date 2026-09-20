"""Run one bounded provider-native research scan."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from autotrader.native_provider_scan import scan_all_native_providers

if __name__ == "__main__":
    rows, health = scan_all_native_providers()
    Path("var/reports/native-provider-health.json").write_text(__import__("json").dumps(health, indent=2, sort_keys=True) + "\n")
    options_status = "AUTH_BLOCKED" if health["alpaca_options"].get("status") == "AUTH_REQUIRED" else "UNAVAILABLE"
    Path("var/reports/options-capability.json").write_text(__import__("json").dumps({"provider": "alpaca-paper", "environment": "paper", "classification": options_status, "market_data": health["alpaca_options"], "paper_order_submission": "NOT_ATTEMPTED", "multi_leg": "NOT_ATTEMPTED", "paper_only": True}, indent=2, sort_keys=True) + "\n")
    print(__import__("json").dumps({"rows": len(rows), "health": health}, sort_keys=True))
