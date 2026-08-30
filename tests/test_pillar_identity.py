from autotrader.pillar_identity import canonical_identity


def test_international_legacy_key_is_displayed_as_saxo_sim():
    identity = canonical_identity("International", "ibkr_global")
    assert identity["execution_provider"] == "Saxo SIM"
    assert identity["legacy_internal_key"] == "ibkr_global"
    assert identity["current_epoch"] == "international-current-fund-v1"
