from decimal import Decimal

import pytest

from src.alpaca_metals_paper import METALS_UNIVERSE, MetalsRiskLimits, position_shares


def test_metals_universe_contains_gold_and_silver_exposure():
    assert "GLD" in METALS_UNIVERSE
    assert "SLV" in METALS_UNIVERSE


def test_default_pillar_capital_is_1000():
    assert MetalsRiskLimits().pillar_capital == Decimal("1000")


def test_position_respects_single_position_cap():
    shares = position_shares(
        account_equity=Decimal("10000"),
        available_cash=Decimal("10000"),
        entry=Decimal("25"),
        stop=Decimal("24"),
        current_metals_exposure=Decimal("0"),
    )
    assert shares == 3


def test_position_respects_metals_exposure_cap():
    shares = position_shares(
        account_equity=Decimal("10000"),
        available_cash=Decimal("10000"),
        entry=Decimal("25"),
        stop=Decimal("24"),
        current_metals_exposure=Decimal("190"),
    )
    assert shares == 0


def test_cash_reserve_can_block_new_trade():
    shares = position_shares(
        account_equity=Decimal("1000"),
        available_cash=Decimal("250"),
        entry=Decimal("25"),
        stop=Decimal("24"),
        current_metals_exposure=Decimal("0"),
    )
    assert shares == 0


def test_stop_must_differ_from_entry():
    with pytest.raises(ValueError):
        position_shares(
            account_equity=Decimal("1000"),
            available_cash=Decimal("1000"),
            entry=Decimal("25"),
            stop=Decimal("25"),
            current_metals_exposure=Decimal("0"),
        )
