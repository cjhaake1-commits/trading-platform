"""Aggressive six-pillar PAPER stress runtime.

This wrapper changes paper-test operating parameters only. It cannot enable
live trading and it preserves provider, duplicate-order, and malformed-state
safety gates. The objective is high utilization, frequent turnover, and rapid
collection of execution/P&L evidence from the $6,000 forward test.
"""
from __future__ import annotations

import os
import sys

from . import runtime_app
from .autonomous_paper import AutonomousPaperConfig as _AutonomousPaperConfig
from .fx_paper import FxPaperConfig as _FxPaperConfig
from .pillar_jobs import InternationalPaperTradingJob as _InternationalPaperTradingJob
from .pillar_jobs import MetalsPaperTradingJob as _MetalsPaperTradingJob


def _autonomous_stress_config(**kwargs):
    defaults = {
        "interval": "5m",
        "lookback_days": 3,
        "minimum_candidate_score": 0.75,
        "momentum_only_score": 1.5,
        "take_profit_r_multiple": 0.60,
        "max_entries_per_cycle": 8,
        "max_unresolved_v2_per_pillar": 8,
        "alpaca_crypto_min_notional": 2.0,
        "crypto_exit_confirmation_cycles": 1,
        "crypto_stale_order_seconds": 180,
        "crypto_market_order_seconds": 45,
    }
    defaults.update(kwargs)
    return _AutonomousPaperConfig(**defaults)


def _fx_stress_config(**kwargs):
    defaults = {
        "interval": "5m",
        "lookback_days": 2,
        "minimum_score": 0.35,
        "max_entries_per_cycle": 8,
        "min_entry_notional": 5.0,
        "take_profit_r_multiple": 0.50,
        "max_holding_minutes": 60,
    }
    defaults.update(kwargs)
    return _FxPaperConfig(**defaults)


def _metals_stress_job(*args, **kwargs):
    kwargs.setdefault("cadence_seconds", 30.0)
    return _MetalsPaperTradingJob(*args, **kwargs)


def _international_stress_job(*args, **kwargs):
    kwargs.setdefault("cadence_seconds", 30.0)
    return _InternationalPaperTradingJob(*args, **kwargs)


def main() -> None:
    # Hard paper-only invariants. A stale environment cannot turn this wrapper
    # into a live-money launcher.
    os.environ["LIVE_TRADING_ENABLED"] = "false"
    os.environ["KALSHI_LIVE_TRADING_ENABLED"] = "false"
    os.environ["PAPER_STRESS_MODE"] = "true"
    os.environ.setdefault("AUTONOMOUS_TRADING_ENABLED", "true")
    os.environ.setdefault("METALS_MIN_CASH_RESERVE_PCT", "0")
    os.environ.setdefault("SAXO_MIN_CASH_RESERVE_PCT", "0")

    runtime_app.AutonomousPaperConfig = _autonomous_stress_config
    runtime_app.FxPaperConfig = _fx_stress_config
    runtime_app.MetalsPaperTradingJob = _metals_stress_job
    runtime_app.InternationalPaperTradingJob = _international_stress_job

    # Existing service units that do not pass an explicit cadence previously
    # inherited 300 seconds. Stress mode defaults to 30 seconds.
    if "--trade-cadence" not in sys.argv:
        sys.argv.extend(["--trade-cadence", "30"])
    if "--mode" not in sys.argv:
        sys.argv.extend(["--mode", "paper"])
    if "--autonomous-paper" not in sys.argv:
        sys.argv.append("--autonomous-paper")

    runtime_app.main()


if __name__ == "__main__":
    main()
