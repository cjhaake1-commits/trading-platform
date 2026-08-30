from autotrader.coordinated_dry_run import DryRunCandidate, FivePillarDryRunner
from autotrader.models import AssetClass, PortfolioState, Position, Side, TradeProposal


def test_pillar_scope_does_not_count_other_pillar_positions():
    portfolio = PortfolioState(10000, 10000, positions={
        "AAPL": Position("AAPL", AssetClass.STOCK, 1, 100, 90),
        "MSFT": Position("MSFT", AssetClass.STOCK, 1, 100, 90),
        "NVDA": Position("NVDA", AssetClass.STOCK, 1, 100, 90),
        "COIN": Position("COIN", AssetClass.STOCK, 1, 100, 90),
        "SPY": Position("SPY", AssetClass.ETF, 1, 100, 90),
        "GLD": Position("GLD", AssetClass.ETF, 1, 100, 90),
    })
    proposal = TradeProposal("BTC/USD", AssetClass.CRYPTO, Side.BUY, 100, 90, .9, "test")
    candidate = DryRunCandidate("alpaca_crypto", "alpaca-crypto-paper", proposal, "market", None, "test", "fixture")
    decision = FivePillarDryRunner().run([candidate], portfolio=portfolio)[0]
    assert decision.risk_engine_status == "approved"


def test_global_scope_is_preserved_without_pillar_context():
    from autotrader.models import TradeProposal
    from autotrader.risk import RiskEngine, RiskLimits
    portfolio = PortfolioState(1000, 1000, positions={str(i): Position(str(i), AssetClass.STOCK, 1, 1, .5) for i in range(6)})
    proposal = TradeProposal("NEW", AssetClass.STOCK, Side.BUY, 10, 9, .9, "test")
    assert RiskEngine(RiskLimits(max_open_positions=6)).evaluate(proposal, portfolio).approved is False
