from autotrader.marketdata import YahooSymbolMapper, normalize_ohlc
from autotrader.models import AssetClass, Instrument


def test_yahoo_symbol_mapper_handles_crypto_and_forex():
    mapper = YahooSymbolMapper()
    assert mapper.to_yahoo(Instrument("BTC-USD", AssetClass.CRYPTO)) == "BTC-USD"
    assert mapper.to_yahoo(Instrument("EUR/USD", AssetClass.FOREX)) == "EURUSD=X"


def test_yahoo_symbol_mapper_preserves_equities():
    mapper = YahooSymbolMapper()
    assert mapper.to_yahoo(Instrument("NVDA", AssetClass.STOCK)) == "NVDA"


def test_normalize_ohlc_repairs_provider_rounding_anomalies():
    assert normalize_ohlc(100.01, 100.00, 99.00, 99.50) == (
        100.01,
        100.01,
        99.00,
        99.50,
    )
    assert normalize_ohlc(100.00, 101.00, 100.01, 100.50) == (
        100.00,
        101.00,
        100.00,
        100.50,
    )
