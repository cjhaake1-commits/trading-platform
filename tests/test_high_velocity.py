from autotrader.high_velocity import (
    arbitrage_observation,
    capability_registry,
    coordinate,
    derivative_simulation,
    micro_candidate,
    short_candidate,
    simulate_arbitrage,
)


def test_micro_candidate_has_positive_net_edge_and_bounded_size():
    candidate = micro_candidate(
        symbol="BTC/USD",
        pillar="Crypto",
        direction="LONG",
        strategy="momentum",
        timeframe="5m",
        signal_strength=0.8,
        expected_gross_edge=0.01,
        costs=0.003,
    )
    assert candidate and candidate.expected_net_edge == 0.007 and 50 <= candidate.capital_requested <= 150
    assert coordinate(candidate, available_capital=1000, paper_environment=True).action == "PAPER_EXECUTE"


def test_short_requires_provider_truth():
    assert (
        short_candidate(
            symbol="AAPL",
            pillar="Stocks",
            strategy="breakdown",
            timeframe="5m",
            shortable=False,
            signal_strength=0.8,
            expected_gross_edge=0.01,
            costs=0.002,
        )
        is None
    )
    assert short_candidate(
        symbol="AAPL",
        pillar="Stocks",
        strategy="breakdown",
        timeframe="5m",
        shortable=True,
        signal_strength=0.8,
        expected_gross_edge=0.01,
        costs=0.002,
    )


def test_derivative_registry_and_notional_are_separate():
    rows = capability_registry(
        {
            "derivatives": [
                {
                    "provider": "demo",
                    "instrument": "BTC-PERP",
                    "product_type": "perpetual",
                    "short_supported": True,
                    "long_supported": True,
                    "paper_sim_supported": True,
                    "margin_requirement": 0.1,
                }
            ]
        }
    )
    result = derivative_simulation(rows[0], cash_committed=25, notional=100, modeled_loss=25)
    assert result["cash_committed"] == 25 and result["notional"] == 100 and result["maximum_modeled_loss"] == 25


def test_arbitrage_requires_net_positive_after_all_costs():
    negative = arbitrage_observation(
        pair="SOL/USDC",
        buy_venue="Orca",
        sell_venue="Raydium",
        size=10,
        buy_quote=100,
        sell_quote=100.1,
        dex_fees=1,
        price_impact=1,
        slippage=1,
        network_fee=1,
        priority_fee=1,
        quote_age_ms=100,
        latency_ms=50,
    )
    assert simulate_arbitrage(negative) is None
    positive = arbitrage_observation(
        pair="SOL/USDC",
        buy_venue="Orca",
        sell_venue="Raydium",
        size=10,
        buy_quote=100,
        sell_quote=101,
        dex_fees=0.1,
        price_impact=0.1,
        slippage=0.1,
        network_fee=0.1,
        priority_fee=0.1,
        quote_age_ms=100,
        latency_ms=50,
    )
    assert simulate_arbitrage(positive)["simulated_fill"] is True
