from autotrader.kalshi.config import KalshiConfig


def test_kalshi_execution_config_is_immutable_no_trade():
    config = KalshiConfig()
    assert config.can_trade() is False
    assert config.broker_control is False
    assert config.paper_capital == 0


def test_rejection_funnels_keep_missing_liquidity_out_of_positive_edge():
    from scripts.kalshi_execution_cycle import _perps_funnel, _prediction_funnel

    predictions = _prediction_funnel([{"yes_bid_dollars": "0.40", "yes_ask_dollars": "0.45", "yes_bid_size_fp": "2", "yes_ask_size_fp": "2"}])
    perps = _perps_funnel([{"status": "active"}])
    assert predictions["scanned"] == 1 and predictions["spread_valid"] == 1
    assert predictions["positive_edge"] == 0 and predictions["orders_submitted"] == 0
    assert perps["data_valid"] == 1 and perps["liquid"] == 0
