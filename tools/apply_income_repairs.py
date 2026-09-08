"""Deterministic source repair; run only in the isolated repair branch."""
from pathlib import Path


def replace(path, old, new):
    target = Path(path)
    text = target.read_text()
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Source changed; refusing unreviewed replacement in {path}")
    target.write_text(text.replace(old, new))


replace("src/autotrader/capital_allocations.py", "TOTAL_PAPER_CAPITAL = 85000.0", "TOTAL_PAPER_CAPITAL = 5000.0")
replace("src/autotrader/capital_allocations.py", "KALSHI_DEMO_BASE_CAPITAL = 15000.0", "KALSHI_DEMO_BASE_CAPITAL = 1000.0")
replace("src/autotrader/capital_allocations.py", "INTERNATIONAL_SIM_CAPITAL = 15000.0", "INTERNATIONAL_SIM_CAPITAL = 1000.0")
replace("src/autotrader/capital_allocations.py", "METALS_PAPER_CAPITAL = 10000.0", "METALS_PAPER_CAPITAL = 1000.0")
for key, old in {"PILLAR_EQUITIES": "25000.0", "PILLAR_FOREX": "15000.0", "PILLAR_CRYPTO": "20000.0", "PILLAR_METALS": "10000.0", "PILLAR_IBKR_GLOBAL": "15000.0"}.items():
    replace("src/autotrader/capital_allocations.py", f"    {key}: {old},", f"    {key}: 1000.0,")
replace("src/autotrader/capital_allocations.py", "KALSHI_CHILD_MAX = 7500.0", 'KALSHI_CHILD_MAX = 500.0\nCAPITAL_POLICY_VERSION = "income_6000_v1"\nSIX_PILLAR_ALLOCATIONS = {**PILLAR_ALLOCATIONS, PILLAR_KALSHI: KALSHI_DEMO_BASE_CAPITAL}')
path = Path("src/autotrader/capital_allocations.py")
path.write_text(path.read_text().replace("max(realized_profit, 0.0)", "realized_profit"))
replace("src/autotrader/learning.py", '''            query = "SELECT event_type, message, data_json, created_at FROM audit_events ORDER BY id DESC"''', '''            # A new/empty optional audit database contains no evidence. Do not
            # invent outcomes; other SQLite errors still fail.
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='audit_events'").fetchone() is None:
                return []
            query = "SELECT event_type, message, data_json, created_at FROM audit_events ORDER BY id DESC"''')
replace("src/autotrader/runtime_app.py", "from .capital_allocations import PILLAR_ALLOCATIONS, TOTAL_PAPER_CAPITAL", "from .capital_allocations import PILLAR_ALLOCATIONS, SIX_PILLAR_ALLOCATIONS, TOTAL_PAPER_CAPITAL")
replace("src/autotrader/runtime_app.py", "PILLAR_ALLOCATIONS[key_map[pillar]]", "SIX_PILLAR_ALLOCATIONS[key_map[pillar]]")
replace("src/autotrader/runtime_app.py", '''            if pillar == "Stocks" and deployed > 1000.0 + 0.02:
                reason = "legacy allocation breach segregated from current fund"
                deployed = 0.0
                market_value = 0.0
                unrealized = 0.0
                economic = starting + realized + unrealized
                positions_counts[pillar] = 0
''', '''            # Preserve observed exposure, including a budget breach. Hiding it
            # as zero falsely reports idle cash and masks the required review.
''')
replace("src/autotrader/runtime_app.py", "source_valid = provider_seen and available >= -0.02 and economic >= -0.02", '''source_valid = (
                provider_seen and available >= -0.02 and economic >= -0.02
                and starting <= SIX_PILLAR_ALLOCATIONS[key_map[pillar]] + 0.02
                and deployed + pending <= SIX_PILLAR_ALLOCATIONS[key_map[pillar]] + max(realized, 0.0) + 0.02
            )''')
replace("src/autotrader/runtime_app.py", '''        crypto_history = _alpaca_crypto_history()
        kalshi = _kalshi_status()''', '''        crypto_history = _alpaca_crypto_history()
        kalshi = _kalshi_status()
        # Read-only, allowlisted position observations for app and publisher.
        from portfolio_reporting import write_position_observations
        write_position_observations(Path.cwd(), live_positions, live_status, now=now)''')
replace("src/autotrader/runtime_app.py", '"trades_today": int(crypto_history.get("orders_today", 0) or 0) if pillar == "Crypto" else 0,', '"trades_today": int(crypto_history.get("fills_today", 0) or 0) if pillar == "Crypto" else None,')
for path in ("src/autotrader/autonomous_paper.py", "src/autotrader/fx_paper.py"):
    replace(path, "equity=max(self.config.initial_equity, cash + deployed),", "equity=min(self.config.initial_equity, portfolio.equity),")
    replace(path, "            daily_pnl=0.0,\n            weekly_pnl=0.0,\n            positions=strategy_positions,", "            daily_pnl=portfolio.daily_pnl,\n            weekly_pnl=portfolio.weekly_pnl,\n            positions=strategy_positions,")
replace("src/autotrader/pillar_jobs.py", "        open_instruments = tuple(", "        _open_instruments = tuple(")
replace("streamlit_app.py", "def main() -> None:\n    render_dashboard()", "def main() -> None:\n    from dashboard_simple import main as render_income_dashboard\n    render_income_dashboard()")
replace("tests/test_metals_trading.py", "assert result.quantity == 12.0", "assert result.quantity == 2.0")
replace("tests/test_metals_trading.py", 'assert history.records()[0]["notional"] == 1200.0', 'assert history.records()[0]["notional"] == 200.0')
replace("src/autotrader/runtime_app.py", "args = build_parser().parse_args()\n    mode", "args = build_parser().parse_args()\n    # Stale service flags cannot enlarge the owner-authorized paper budget.\n    args.initial_equity = min(args.initial_equity, TOTAL_PAPER_CAPITAL)\n    mode")
# These assertions were changed for the withdrawn $100k experiment. Preserve
# their cash/P&L tests and restore only the owner-authorized sleeve amounts.
replace("tests/test_cash_dashboard.py", 'metrics["pillar_allocations"]["International"] == 15000.0', 'metrics["pillar_allocations"]["International"] == 1000.0')
replace("tests/test_cash_dashboard.py", 'metrics.pillar_allocations["Metals/Commodities"] == 10000.0', 'metrics.pillar_allocations["Metals/Commodities"] == 1000.0')
replace("tests/test_pillar_jobs.py", 'job.service.calls[0][1].equity == 10000.0', 'job.service.calls[0][1].equity == 1000.0')
