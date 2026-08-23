from autotrader.capital_allocations import (
    KALSHI_DEMO_BASE_CAPITAL,
    SIX_PILLAR_BASE_CAPITAL,
    kalshi_pool_available,
    validate_kalshi_reservation,
)
from autotrader.global_intelligence import (
    CashLedger,
    Opportunity,
    global_state,
    hedge_state,
    pillar_hierarchy,
    rank_opportunities,
)


def test_six_pillar_and_kalshi_child_hierarchy():
    assert SIX_PILLAR_BASE_CAPITAL == 6000
    assert pillar_hierarchy()["kalshi"] == ("predictions", "perps")
    assert len(pillar_hierarchy()) == 6


def test_shared_kalshi_pool_never_double_counts_children():
    assert kalshi_pool_available(committed=500, pending=300) == 200
    assert validate_kalshi_reservation(predictions_committed=500, perps_committed=500) is True
    assert validate_kalshi_reservation(predictions_committed=700, perps_committed=700) is False
    assert KALSHI_DEMO_BASE_CAPITAL == 1000


def test_normalized_global_ranking_and_hold_cash():
    low = Opportunity("stocks", "paper", "SPY", "long", .02, .01, .8, .2, .9, .01, .001, 100,
                      data_quality=1, model_quality=1)
    high = Opportunity("kalshi", "predictions", "KXTEST", "yes", .05, .04, .9, .1, .95, .005, .001, 50,
                       data_quality=1, model_quality=1)
    assert rank_opportunities([low, high], available_cash=100)[0] == high
    cash = CashLedger(6000, liquid_cash=10)
    assert global_state(opportunities=[high], cash=cash)["decision"] == "HOLD_CASH"


def test_realized_cash_excludes_unrealized_pnl():
    cash = CashLedger(1000, unrealized_pnl=80, liquid_cash=100)
    assert cash.equity == 1080
    assert cash.redeployable_cash == 0
    cash.settle(gross_pnl=25, fees=2, released_capital=100)
    assert cash.realized_net_pnl == 23
    assert cash.redeployable_cash == 23


def test_hedges_need_evidence():
    assert hedge_state(2, -.9) == "COLLECTING_EVIDENCE"
    assert hedge_state(30, -.3) == "SHADOW_CANDIDATE"
    assert hedge_state(30, .3) == "RESEARCH_ONLY"
