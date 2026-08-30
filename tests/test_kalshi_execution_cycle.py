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


def test_perps_baseline_model_is_computed_from_provider_reference():
    from scripts.kalshi_execution_cycle import _perps_baseline, _perps_funnel

    market = {
        "status": "active",
        "bid": "3.20",
        "ask": "3.21",
        "volume_24h": "100",
        "tick_size": "0.0001",
        "settlement_mark_price": {"price": "3.19"},
    }
    model = _perps_baseline(market)
    funnel = _perps_funnel([market])
    assert model is not None
    assert model["signal"] == "LONG"
    assert funnel["model_valid"] == 1


def test_perps_positive_edge_invokes_shared_risk_and_reports_short_rejection():
    from scripts.kalshi_execution_cycle import _perps_risk_evaluation

    market = {
        "ticker": "KXTESTPERP1",
        "status": "active",
        "bid": "3.20",
        "ask": "3.21",
        "volume_24h": "100",
        "tick_size": "0.0001",
        "contract_size": "0.001",
        "settlement_mark_price": {"price": "3.30"},
    }
    result = _perps_risk_evaluation(market)
    assert result["risk_invoked"] is True
    assert result["risk_approved"] is False
    assert result["risk_rejection"] == "Short selling is disabled"
    assert result["capital_approved"] is False


def test_perps_risk_approved_candidate_reaches_capital_and_order_boundary():
    from scripts.kalshi_execution_cycle import _perps_order_payload, _perps_risk_evaluation

    market = {
        "ticker": "KXTESTPERP1",
        "status": "active",
        "bid": "3.20",
        "ask": "3.21",
        "volume_24h": "100",
        "tick_size": "0.0001",
        "contract_size": "0.001",
        "settlement_mark_price": {"price": "3.10"},
    }
    result = _perps_risk_evaluation(market)
    assert result["risk_invoked"] is True
    assert result["risk_approved"] is True
    assert result["capital_approved"] is True
    assert result["qualified"] is True
    payload = _perps_order_payload(market, result)
    assert payload["side"] == "bid"
    assert payload["count"] == "1.00"


def test_candidate_telemetry_is_append_only_and_research_only(tmp_path, monkeypatch):
    from scripts.kalshi_execution_cycle import _write_candidate_telemetry

    monkeypatch.setenv("KALSHI_EXECUTION_STATUS_DIR", str(tmp_path))
    rows = [{"ticker": "KXTEST", "qualification": "REJECTED", "estimated_edge": "UNKNOWN"}]
    _write_candidate_telemetry("predictions", rows)
    _write_candidate_telemetry("predictions", rows)
    path = tmp_path / "candidate-telemetry-predictions.jsonl"
    assert len(path.read_text().splitlines()) == 2
    assert path.exists()


def test_execution_cycle_count_increments_from_existing_status(tmp_path, monkeypatch):
    from scripts.kalshi_execution_cycle import _read_status, _write_status

    monkeypatch.setenv("KALSHI_EXECUTION_STATUS_DIR", str(tmp_path))
    _write_status("predictions", {"cycle_count": 9})
    assert _read_status("predictions")["cycle_count"] == 9
