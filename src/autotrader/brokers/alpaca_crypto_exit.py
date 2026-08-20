from __future__ import annotations

from urllib.parse import quote, urlencode

from autotrader.broker_environment import require_alpaca_paper_url
from autotrader.crypto_exit import CryptoOrderSnapshot, CryptoPositionSnapshot

from .safety import _alpaca_api_symbol, _alpaca_auth, _alpaca_headers, _request


class AlpacaCryptoExitPaperBroker:
    """Exact-host PAPER gateway used only by the guarded crypto exit coordinator."""

    def __init__(self, key: str, secret: str, base_url: str) -> None:
        if not key.strip() or not secret.strip():
            raise RuntimeError("Missing Alpaca paper credentials")
        self.key = key
        self.secret = secret
        self.base_url = require_alpaca_paper_url(base_url)

    @classmethod
    def from_env(cls) -> AlpacaCryptoExitPaperBroker:
        key, secret, base = _alpaca_auth()
        return cls(key, secret, base)

    def _headers(self) -> dict[str, str]:
        return _alpaca_headers(self.key, self.secret)

    def position(self, symbol: str) -> CryptoPositionSnapshot | None:
        api_symbol = _alpaca_api_symbol(symbol)
        try:
            payload, _ = _request(
                f"{self.base_url}/v2/positions/{quote(api_symbol, safe='')}",
                method="GET",
                headers=self._headers(),
            )
        except RuntimeError as exc:
            if "HTTP 404:" in str(exc):
                return None
            raise
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected Alpaca PAPER crypto position response")
        quantity = _number(payload.get("qty"))
        available = _number(payload.get("qty_available"), quantity)
        return CryptoPositionSnapshot(
            symbol=symbol,
            quantity=abs(quantity),
            available_quantity=max(available, 0.0),
            average_price=_number(payload.get("avg_entry_price")),
        )

    def open_orders(self, symbol: str) -> tuple[CryptoOrderSnapshot, ...]:
        # Alpaca represents crypto positions as BTCUSD in some endpoints and
        # BTC/USD in orders. Fetch PAPER open orders once and canonicalize
        # locally so a server-side symbol mismatch cannot hide protection.
        query = urlencode({"status": "open", "nested": "true", "limit": 500})
        payload, _ = _request(
            f"{self.base_url}/v2/orders?{query}",
            method="GET",
            headers=self._headers(),
        )
        rows = payload if isinstance(payload, list) else []
        api_symbol = _alpaca_api_symbol(symbol)
        return tuple(
            _order_snapshot(row, symbol)
            for row in rows
            if isinstance(row, dict)
            and _alpaca_api_symbol(str(row.get("symbol") or "")) == api_symbol
        )

    def order(self, order_id: str) -> CryptoOrderSnapshot:
        payload, _ = _request(
            f"{self.base_url}/v2/orders/{quote(order_id, safe='')}",
            method="GET",
            headers=self._headers(),
        )
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected Alpaca PAPER crypto order response")
        return _order_snapshot(payload, str(payload.get("symbol") or ""))

    def cancel_order(self, order_id: str) -> None:
        _request(
            f"{self.base_url}/v2/orders/{quote(order_id, safe='')}",
            method="DELETE",
            headers=self._headers(),
        )

    def submit_close(self, symbol: str, quantity: float) -> CryptoOrderSnapshot:
        if quantity <= 0:
            raise ValueError("crypto close quantity must be positive")
        query = urlencode({"qty": f"{quantity:.9f}".rstrip("0").rstrip(".")})
        payload, _ = _request(
            f"{self.base_url}/v2/positions/{quote(_alpaca_api_symbol(symbol), safe='')}?{query}",
            method="DELETE",
            headers=self._headers(),
        )
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected Alpaca PAPER crypto close response")
        return _order_snapshot(payload, symbol)

    def submit_protection(
        self,
        symbol: str,
        quantity: float,
        stop_price: float,
        client_order_id: str,
    ) -> CryptoOrderSnapshot:
        if quantity <= 0 or stop_price <= 0:
            raise ValueError("positive protection quantity and stop are required")
        payload = {
            "symbol": symbol,
            "qty": f"{quantity:.9f}".rstrip("0").rstrip("."),
            "side": "sell",
            "type": "stop_limit",
            "time_in_force": "gtc",
            "stop_price": f"{stop_price:.2f}",
            "limit_price": f"{max(stop_price * 0.995, 1e-8):.2f}",
            "client_order_id": client_order_id,
        }
        response, _ = _request(
            f"{self.base_url}/v2/orders",
            method="POST",
            headers=self._headers(),
            body=payload,
        )
        if not isinstance(response, dict):
            raise RuntimeError("Unexpected Alpaca PAPER protection response")
        return _order_snapshot(response, symbol)


def _order_snapshot(payload: dict[str, object], fallback_symbol: str) -> CryptoOrderSnapshot:
    order_id = str(payload.get("id") or "")
    if not order_id:
        raise RuntimeError("Alpaca PAPER order response omitted id")
    return CryptoOrderSnapshot(
        order_id=order_id,
        symbol=str(payload.get("symbol") or fallback_symbol),
        side=str(payload.get("side") or ""),
        order_type=str(payload.get("type") or ""),
        status=str(payload.get("status") or ""),
        quantity=abs(_number(payload.get("qty"))),
        filled_quantity=abs(_number(payload.get("filled_qty"))),
        filled_average_price=_optional_number(payload.get("filled_avg_price")),
        stop_price=_optional_number(payload.get("stop_price")),
        client_order_id=str(payload.get("client_order_id") or "") or None,
    )


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_number(value: object) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
