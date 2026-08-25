from autotrader.crypto_autopsy import build_learning_registry, reconstruct_lifecycles, summarize


def _order(order_id, side, qty, price, timestamp, status="filled"):
    return {
        "id": order_id,
        "symbol": "ETHUSD",
        "asset_class": "crypto",
        "side": side,
        "filled_qty": str(qty),
        "filled_avg_price": str(price),
        "filled_at": timestamp,
        "status": status,
    }


def test_reconstructs_provider_lifecycle_and_excludes_zero_fill():
    trades = reconstruct_lifecycles(
        [
            _order("buy", "buy", 1.0, 100.0, "2026-08-25T00:00:00Z"),
            _order("cancel", "buy", 1.0, 99.0, "2026-08-25T00:00:01Z", status="canceled") | {"filled_qty": "0"},
            _order("sell", "sell", 1.0, 98.0, "2026-08-25T00:01:00Z"),
        ],
        {"buy": {"manifest_id": "m1", "model_version": "five_pillar_baseline_v1", "lane": "BASELINE"}},
    )
    assert len(trades) == 1
    assert trades[0]["active_v2"] is True
    assert trades[0]["net_realized_pnl"] == -2.0


def test_summary_is_transparent_about_all_losses():
    summary = summarize([{"symbol": "ETH/USD", "exit_reason": "EXIT_EDGE_GONE", "net_realized_pnl": -2.0}])
    assert summary["trades"] == 1
    assert summary["wins"] == 0
    assert summary["losses"] == 1
    assert summary["win_rate"] == 0.0
    assert summary["expectancy"] == -2.0


def test_registry_does_not_promote_small_sample():
    registry = build_learning_registry({"trades": 25, "win_rate": 0.0})
    assert registry["state"] == "OBSERVING"
    assert registry["promotion_status"] == "NOT_PROMOTED"
