from autotrader.marketdata import YahooSymbolMapper
from autotrader.models import AssetClass, Instrument


def test_yahoo_symbol_mapper_handles_crypto_and_forex():
    mapper = YahooSymbolMapper()
    assert mapper.to_yahoo(Instrument("BTC-USD", AssetClass.CRYPTO)) == "BTC-USD"
    assert mapper.to_yahoo(Instrument("EUR/USD", AssetClass.FOREX)) == "EURUSD=X"


def test_yahoo_symbol_mapper_preserves_equities():
    mapper = YahooSymbolMapper()
    assert mapper.to_yahoo(Instrument("NVDA", AssetClass.STOCK)) == "NVDA"
