#!/usr/bin/env python3
"""Independent, non-trading reliability watchdog."""
from autotrader.reliability import supervise_services, write_reliability_report
from autotrader.watchdog_dispatch import run_production_dispatch

if __name__ == "__main__":
    actions = supervise_services()
    def _status_reader(provider):
        paths = {"Alpaca":"var/autotrader/status.json", "OANDA":"var/autotrader/status.json", "Saxo":"var/autotrader/international-execution-funnel.json", "Kalshi":"var/kalshi/execution-perps.json"}
        def read():
            import json
            from pathlib import Path
            return json.loads(Path(paths[provider]).read_text(encoding="utf-8"))
        return read
    dispatch = run_production_dispatch(readers={p: _status_reader(p) for p in ("Alpaca","OANDA","Saxo","Kalshi")})
    report = write_reliability_report(actions=actions)
    report["production_dispatch"] = dispatch
    print(report)
