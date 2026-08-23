# Kalshi Perps/Margin compatibility

Verified against the current Perps API documentation at `https://docs.kalshi.com/margin`.

| Supplied/documented surface | Current status | Demo test result | Classification |
|---|---|---|---|
| REST base `https://external-api.demo.kalshi.co/trade-api/v2/margin/` | Current | `/margin/enabled`: HTTP 200 | Available |
| WebSocket `wss://external-api-margin-ws.demo.kalshi.co/trade-api/ws/v2/margin` | Current | Not opened by the bounded collector | Available, inactive |
| `GET /margin/enabled` | Current account gate | HTTP 200, `enabled=false` | Account blocked |
| `GET /margin/markets` | Current | HTTP 200, 34 instruments | Available |
| `GET /margin/markets/{ticker}/orderbook` | Current | Requires an available instrument | Available |
| `GET /margin/portfolio/balance` | Current | Authenticated request rejected while margin disabled | Account blocked |
| `GET /margin/risk` | Current | Authenticated request rejected while margin disabled | Account blocked |
| `GET /margin/funding/rate` | Current | Account/instrument dependent | Account blocked |
| `GET /margin/funding/rates/historical` | Current | Account/instrument dependent | Account blocked |
| `GET /margin/fees/tiers` | Current | Authenticated request rejected while margin disabled | Account blocked |
| Margin orders (`/margin/orders`) | Current, mutation-capable | Not attempted; Demo account gate false | Not executable |
| Margin user WebSocket channels | Current, `_ts_ms` timestamps | Not opened | Available, inactive |

The implementation never falls back to the Predictions `/markets` endpoint for
Perps. The current blocker is the documented account gate, not an undocumented
or guessed endpoint.
