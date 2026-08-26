from autotrader.autonomous_paper import pillar_allocation_room


def test_new_order_room_includes_pending_reservations():
    assert pillar_allocation_room(allocation=1000, current_exposure=700, pending_capital=250) == 50


def test_new_order_is_rejected_when_filled_plus_pending_reaches_cap():
    assert pillar_allocation_room(allocation=1000, current_exposure=700, pending_capital=300) == 0
