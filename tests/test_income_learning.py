from copy import deepcopy

import pytest

from autotrader.income_learning import income_learning_contract, summarize_income_outcomes


def outcome(**changes):
    row = {
        "outcome_id": "paper-1", "capital_policy_id": "income-6000-v1",
        "execution_mode": "PAPER", "ownership": "PLATFORM_OWNED", "origin": "NATURAL",
        "entry_fill_confirmed": True, "exit_fill_confirmed": True, "costs_complete": True,
        "pillar": "Crypto", "strategy": "scalping", "strategy_version": "test-v1",
        "provider": "TEST_ONLY", "entry_provider_order_id": "test-entry",
        "exit_provider_order_id": "test-exit", "net_realized_pnl": "0.0003", "allocated_capital": "10",
        "capital_released": "10.0003", "entry_fill_at": "2026-09-08T12:00:00Z",
        "exit_fill_at": "2026-09-08T12:06:00Z",
    }
    row.update(changes)
    return row


def test_income_only_and_realistic_starting_capital():
    contract = income_learning_contract()
    assert contract["initial_economic_capital"] == 6000
    assert contract["long_term_portfolio_mandate"] is False
    assert contract["force_utilization"] is False
    assert contract["live_authorization"] is False


def test_subcent_profit_survives_without_counting_returned_principal_as_income():
    report = summarize_income_outcomes([outcome()])
    assert report["net_realized_pnl"] == "0.0003"
    assert report["per_strategy_day"][0]["capital_released"] == "10.0003"
    assert report["withdrawable_income"] is None
    assert report["capital_redeployed"] is None
    assert report["account_total_equity_pnl"] is None


def test_losses_are_included_not_just_winning_cashouts():
    report = summarize_income_outcomes([outcome(), outcome(outcome_id="loss", net_realized_pnl="-2")])
    assert report["net_realized_pnl"] == "-1.9997"
    assert report["per_strategy_day"][0]["losses"] == 1


@pytest.mark.parametrize("changes", [
    {"capital_policy_id": "paper-100000"}, {"execution_mode": "LIVE"},
    {"ownership": "LEGACY"}, {"origin": "REPLAY"}, {"origin": "TEST"},
    {"entry_fill_confirmed": False}, {"exit_fill_confirmed": False},
    {"costs_complete": False}, {"net_realized_pnl": None}, {"net_realized_pnl": "NaN"},
    {"net_realized_pnl": "Infinity"}, {"allocated_capital": "0"},
    {"capital_released": "-1"}, {"entry_fill_at": "2026-09-08T12:00:00"},
    {"exit_fill_at": "2026-09-08T11:00:00Z"}, {"strategy_version": None}, {"entry_provider_order_id": None},
])
def test_invalid_or_out_of_scope_data_stays_unknown(changes):
    report = summarize_income_outcomes([outcome(**changes)])
    assert report["qualified_closed_cycles"] == 0
    assert report["net_realized_pnl"] is None
    assert report["status"] == "INSUFFICIENT_INCOME_EVIDENCE"


def test_identical_duplicate_cannot_inflate_income():
    row = outcome()
    assert summarize_income_outcomes([row, deepcopy(row)])["qualified_closed_cycles"] == 1


def test_conflicting_duplicate_cannot_choose_favorable_result():
    report = summarize_income_outcomes([outcome(), outcome(net_realized_pnl="100")])
    assert report["qualified_closed_cycles"] == 0
    assert report["exclusions"]["CONFLICTING_OUTCOME"] == 1


def test_versions_and_providers_not_pooled():
    report = summarize_income_outcomes([
        outcome(), outcome(outcome_id="other", strategy_version="test-v2"),
        outcome(outcome_id="third", provider="OTHER_TEST_ONLY"),
    ])
    assert len(report["per_strategy_day"]) == 3


def test_missing_data_is_not_zero_income():
    assert summarize_income_outcomes([])["net_realized_pnl"] is None


def test_existing_learning_ledger_supplies_income_report_without_relabeling(tmp_path):
    from autotrader.learning_ingestion import LearningIngestor

    learner = LearningIngestor(tmp_path / "outcomes.db")
    row = outcome(decision_at="2026-09-08T12:00:00Z", outcome_at="2026-09-08T12:06:00Z")
    assert learner.ingest(outcome_id=row["outcome_id"], outcome=row)
    before = (tmp_path / "outcomes.db").read_bytes()
    assert learner.income_learning_summary()["net_realized_pnl"] == "0.0003"
    assert (tmp_path / "outcomes.db").read_bytes() == before


def test_old_learning_outcomes_not_promoted_to_new_capital_cohort(tmp_path):
    from autotrader.learning_ingestion import LearningIngestor

    learner = LearningIngestor(tmp_path / "outcomes.db")
    row = outcome(capital_policy_id="old", decision_at="2026-09-08T12:00:00Z", outcome_at="2026-09-08T12:06:00Z")
    assert learner.ingest(outcome_id=row["outcome_id"], outcome=row)
    assert learner.count() == 1
    assert learner.income_learning_summary()["net_realized_pnl"] is None
