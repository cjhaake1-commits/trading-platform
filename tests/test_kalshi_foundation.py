from datetime import UTC, datetime, timedelta

import pytest

from autotrader.kalshi.client import KalshiDemoExecutionClient, KalshiReadOnlyClient
from autotrader.kalshi.config import KalshiConfig
from autotrader.kalshi.features import probability_features
from autotrader.kalshi.hedging import evaluate_shadow_hedge
from autotrader.kalshi.models import KalshiMarket
from autotrader.kalshi.paper import KalshiPaperStrategy
from autotrader.kalshi.storage import KalshiResearchStore


def market(**overrides):
    values = dict(
        market_ticker="FED-25",
        category="rates",
        yes_bid=0.40,
        yes_ask=0.50,
        volume=100,
        liquidity=25,
        close_time=datetime.now(UTC) + timedelta(hours=6),
    )
    values.update(overrides)
    return KalshiMarket(**values)


def test_kalshi_defaults_are_disabled_and_zero_capital(monkeypatch):
    monkeypatch.delenv("KALSHI_ENABLED", raising=False)
    monkeypatch.delenv("KALSHI_TRADING_ENABLED", raising=False)
    config = KalshiConfig.from_env()
    assert config.research_only
    assert config.paper_capital == 0
    assert not config.can_trade()


def test_client_is_demo_only_and_read_only():
    client = KalshiReadOnlyClient(KalshiConfig())
    assert client.config.environment == "demo"
    with pytest.raises(ValueError):
        KalshiReadOnlyClient(KalshiConfig(environment="production"))


def test_kalshi_telemetry_snapshot_preserves_request_health_fields():
    from autotrader.kalshi.client import KalshiTelemetry

    telemetry = KalshiTelemetry(requests=4, successes=3, failures=1, timeouts=1, latencies_ms=[10.0, 20.0, 30.0, 40.0])
    snapshot = telemetry.snapshot()
    assert snapshot["requests"] == 4
    assert snapshot["failures"] == 1
    assert snapshot["timeouts"] == 1
    assert snapshot["p50_latency_ms"] == 20.0
    assert snapshot["p95_latency_ms"] == 40.0


def test_demo_mutation_transport_is_separate_and_guarded(monkeypatch):
    monkeypatch.setenv("KALSHI_DEMO_TRADING_ENABLED", "true")
    monkeypatch.setenv("KALSHI_LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    client = KalshiDemoExecutionClient(KalshiConfig.from_env())
    paths = []
    monkeypatch.setattr(client, "_mutation", lambda method, path, payload=None, **kwargs: paths.append((method, path)) or {})
    client.create_order({"ticker": "T", "client_order_id": "diagnostic"})
    client.cancel_order("O")
    assert paths == [("POST", "portfolio/events/orders"), ("DELETE", "portfolio/events/orders/O")]


def test_demo_gate_controls_demo_broker_capability_not_live_flag(monkeypatch):
    monkeypatch.setenv("KALSHI_DEMO_TRADING_ENABLED", "true")
    monkeypatch.setenv("KALSHI_PAPER_CAPITAL", "1000")
    monkeypatch.setenv("KALSHI_TRADING_ENABLED", "false")
    monkeypatch.setenv("KALSHI_LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    config = KalshiConfig.from_env()
    assert config.can_trade()
    assert config.broker_control


def test_perps_account_paths_use_current_margin_namespace(monkeypatch):
    client = KalshiReadOnlyClient(KalshiConfig())
    paths = []
    monkeypatch.setattr(client, "_get", lambda path, *args, **kwargs: paths.append(path) or {})
    client.perps_balance()
    client.perps_positions()
    client.perps_fills()
    assert paths == ["balance", "positions", "fills"]


def test_probability_features_are_namespaced_and_research_only():
    features = probability_features(market(), previous={"mid_probability": 0.35})
    assert features["kalshi.implied_probability"] == 0.45
    assert features["kalshi.probability_change"] == pytest.approx(0.10)
    assert features["broker_control"] is False
    assert features["execution_enabled"] is False


def test_shadow_hedge_never_claims_effectiveness():
    observation = evaluate_shadow_hedge(market(), exposure=-100, contracts=10)
    assert observation.hypothetical_cost == 5
    assert observation.hypothetical_payout == 10
    assert observation.effective is False
    assert observation.mode == "shadow"


def test_resolution_calibration_and_research_storage(tmp_path):
    store = KalshiResearchStore(tmp_path / "research.db")
    store.put_research({"id": "m1", "market_ticker": "FED-25", "retrieved_at": "now"})
    store.put_resolution({"id": "r1", "market_ticker": "FED-25", "final_probability": 0.8, "result": "yes", "resolved_at": "now", "probability_history": []})
    with store.path and __import__("sqlite3").connect(store.path) as conn:
        assert conn.execute("select count(*) from kalshi_research").fetchone()[0] == 1
        assert conn.execute("select brier_score from kalshi_resolutions").fetchone()[0] == pytest.approx(0.04)


def test_future_strategy_cannot_submit_orders():
    with pytest.raises(RuntimeError, match="research-only"):
        KalshiPaperStrategy(KalshiConfig()).submit()
