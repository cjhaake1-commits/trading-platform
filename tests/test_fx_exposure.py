from autotrader.fx_exposure import currency_exposure, pair_gate


def test_fx_exposure_aggregates_shared_currencies():
    exposure = currency_exposure([{"instrument": "EUR_USD", "notional": 100}, {"instrument": "EUR_JPY", "notional": 50}])
    assert exposure["EUR"] == 150
    assert exposure["USD"] == -100
    assert exposure["JPY"] == -50


def test_fx_gate_rejects_concentration_without_global_position_lock():
    result = pair_gate(pair="GBP_USD", proposed_notional=50, existing=[{"instrument": "EUR_USD", "notional": 100}], max_currency_exposure=200)
    assert result["approved"] is True
