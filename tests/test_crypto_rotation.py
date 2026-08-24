from datetime import datetime

from autotrader.autonomous_paper import AutonomousPaperConfig, AutonomousPaperTradingJob
from autotrader.models import AssetClass, Instrument, MarketBar, PortfolioState, Position, ScanCandidate
from autotrader.paper_experiment import PaperExperimentConfig


def test_open_crypto_position_is_re_evaluated_and_reasoned_hold(tmp_path):
    job = AutonomousPaperTradingJob(
        AutonomousPaperConfig(ledger_path=str(tmp_path / "portfolio.db"), idempotency_path=str(tmp_path / "idempotency.db"))
    )
    job.experiment = PaperExperimentConfig(enabled=False)
    job.scanner.score_instrument = lambda instrument, bars: ScanCandidate(
        instrument, 8.0, 100.0, -0.5, 1.0, None, 95.0, ("current momentum",)
    )
    instrument = Instrument("SOL/USD", AssetClass.CRYPTO)
    portfolio = PortfolioState(
        1000.0, 36.91, positions={"SOL/USD": Position("SOL/USD", AssetClass.CRYPTO, 10.0, 96.34, 95.0)}
    )
    bar = MarketBar("SOL/USD", AssetClass.CRYPTO, datetime(2026, 8, 24), 100, 101, 99, 100, 1)
    decisions, exits = job._manage_crypto_positions(portfolio, {instrument: [bar]})
    assert exits == []
    assert decisions[0]["symbol"] == "SOL/USD"
    assert decisions[0]["decision"] == "TIGHTEN_PROTECTION"
    assert decisions[0]["reason"]
