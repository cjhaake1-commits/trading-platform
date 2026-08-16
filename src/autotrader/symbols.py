from __future__ import annotations

from dataclasses import dataclass

from .models import AssetClass, Instrument


@dataclass(frozen=True)
class SymbolNormalizer:
    """Normalize user/provider symbols into the platform's canonical form.

    Canonical conventions:
    - Stocks/ETFs: uppercase ticker, exchange suffix preserved (e.g. BRK-B, 0700.HK)
    - Crypto: BASE-QUOTE, e.g. BTC-USD
    - Forex: BASE/QUOTE, e.g. EUR/USD

    Provider-specific adapters can translate from this canonical representation
    into their own symbol formats at the boundary.
    """

    default_crypto_quote: str = "USD"
    default_forex_quote: str = "USD"

    def normalize(self, symbol: str, asset_class: AssetClass) -> Instrument:
        raw = symbol.strip().upper()
        if not raw:
            raise ValueError("Symbol cannot be empty")

        if asset_class in {AssetClass.STOCK, AssetClass.ETF, AssetClass.FUTURE, AssetClass.OPTION}:
            normalized = raw.replace(" ", "")
        elif asset_class is AssetClass.CRYPTO:
            normalized = self._normalize_pair(raw, separator="-", default_quote=self.default_crypto_quote)
        elif asset_class is AssetClass.FOREX:
            normalized = self._normalize_pair(raw, separator="/", default_quote=self.default_forex_quote)
        else:
            raise ValueError(f"Unsupported asset class: {asset_class}")

        return Instrument(normalized, asset_class)

    @staticmethod
    def _normalize_pair(raw: str, *, separator: str, default_quote: str) -> str:
        compact = raw.replace(" ", "")
        for existing in ("/", "-", "_"):
            if existing in compact:
                base, quote = compact.split(existing, 1)
                if not base or not quote:
                    raise ValueError("Pair symbols require both base and quote")
                return f"{base}{separator}{quote}"

        if len(compact) == 6 and compact.isalpha():
            return f"{compact[:3]}{separator}{compact[3:]}"

        if compact.isalpha():
            return f"{compact}{separator}{default_quote}"

        raise ValueError(f"Cannot normalize pair symbol: {raw}")
