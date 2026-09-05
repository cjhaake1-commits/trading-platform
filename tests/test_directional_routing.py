from autotrader.directional_routing import route_directional_candidate


def test_long_route_is_provider_neutral_and_explicit():
    result = route_directional_candidate({"direction": "LONG", "max_loss": 10}, {})
    assert result["state"] == "ELIGIBLE"


def test_short_route_fails_closed_without_provider_support():
    result = route_directional_candidate({"direction": "SHORT", "max_loss": 10}, {"short": False, "reason": "paper adapter long-only"})
    assert result["state"] == "REJECTED"
    assert result["reason"] == "paper adapter long-only"


def test_short_route_requires_borrow_and_margin():
    result = route_directional_candidate({"direction": "SHORT", "max_loss": 10, "short_margin_required": 25}, {"short": True, "short_enabled": True, "borrow_available": True})
    assert result["state"] == "ELIGIBLE"
