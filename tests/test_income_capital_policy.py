import pytest

from autotrader.capital_allocations import (
    KALSHI_CHILD_MAX,
    KALSHI_DEMO_BASE_CAPITAL,
    PILLAR_ALLOCATIONS,
    SIX_PILLAR_BASE_CAPITAL,
    TOTAL_PAPER_CAPITAL,
    kalshi_pool_available,
    validate_kalshi_reservation,
)


def test_starting_capital_is_six_thousand_not_provider_balance():
    assert len(PILLAR_ALLOCATIONS) == 5
    assert set(PILLAR_ALLOCATIONS.values()) == {1000.0}
    assert TOTAL_PAPER_CAPITAL == 5000
    assert KALSHI_DEMO_BASE_CAPITAL == 1000
    assert SIX_PILLAR_BASE_CAPITAL == 6000
    assert 2 * KALSHI_CHILD_MAX == KALSHI_DEMO_BASE_CAPITAL


def test_signed_net_profit_compounds_and_losses_reduce_headroom():
    assert kalshi_pool_available(committed=500, pending=50, realized_profit=20) == 470
    assert kalshi_pool_available(committed=500, pending=50, realized_profit=-20) == 430
    assert not validate_kalshi_reservation(predictions_committed=500, perps_committed=500, realized_profit=-1)


def test_shared_pool_not_double_counted_and_overallocation_is_zero_new_capacity():
    assert not validate_kalshi_reservation(predictions_committed=600, perps_committed=600)
    assert kalshi_pool_available(committed=1500, pending=0) == 0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1])
def test_invalid_reservations_fail_closed(bad):
    assert kalshi_pool_available(committed=bad, pending=0) == 0
    assert not validate_kalshi_reservation(predictions_committed=bad, perps_committed=0)
