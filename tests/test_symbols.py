from autotrader.models import AssetClass
from autotrader.symbols import SymbolNormalizer


def test_normalizes_crypto_pair():
    normalizer = SymbolNormalizer()
    assert normalizer.normalize("btc/usd", AssetClass.CRYPTO).symbol == "BTC-USD"
    assert normalizer.normalize("eth", AssetClass.CRYPTO).symbol == "ETH-USD"


def test_normalizes_forex_pair():
    normalizer = SymbolNormalizer()
    assert normalizer.normalize("eurusd", AssetClass.FOREX).symbol == "EUR/USD"
    assert normalizer.normalize("gbp-usd", AssetClass.FOREX).symbol == "GBP/USD"


def test_preserves_exchange_suffix_for_stock():
    normalizer = SymbolNormalizer()
    assert normalizer.normalize("0700.hk", AssetClass.STOCK).symbol == "0700.HK"
