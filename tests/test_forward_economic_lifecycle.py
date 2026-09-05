from autotrader.forward_economic_lifecycle import EconomicLifecycle


def test_release_requires_owned_exit_fill_and_is_idempotent(tmp_path):
    life = EconomicLifecycle(tmp_path / "economic.db")
    assert life.event("T1", "EXIT_FILL", {"ownership": "PLATFORM_OWNED"})
    assert life.release("T1", amount=100, realized_pnl=5, released_at="2026-09-05T01:00:00Z")
    assert not life.release("T1", amount=100, realized_pnl=5, released_at="2026-09-05T01:01:00Z")
    assert life.metrics()["capital_released"] == 100


def test_protected_exit_cannot_release(tmp_path):
    life = EconomicLifecycle(tmp_path / "economic.db")
    assert not life.event("T2", "EXIT_FILL", {"ownership": "LEGACY"})
    assert not life.release("T2", amount=10, realized_pnl=1, released_at="2026-09-05T01:00:00Z")
