import json
from datetime import UTC, datetime

from autotrader.capital_reservations import CapitalReservations
from autotrader.forward_reconciler import reconcile
from autotrader.forward_verification import (
    append_manifest,
    deterministic_submission_id,
    ensure_verification_epoch,
    forward_daily_metrics,
)


def test_verification_epoch_is_persistent_and_not_a_new_experiment(tmp_path, monkeypatch):
    path = tmp_path / "verification-epoch.json"
    monkeypatch.chdir(tmp_path)
    first = ensure_verification_epoch(path)
    second = ensure_verification_epoch(path)
    assert first == second
    assert first["experiment_id"] == "income_6000_v2"
    assert first["ownership_required"] is True
    assert first["provider_fill_required"] is True


def test_deterministic_submission_id_is_bounded():
    values = dict(experiment_id="income_6000_v2", epoch_id="VE-abc", pillar="alpaca_crypto", strategy="active-v2", intent_id="i1")
    assert deterministic_submission_id(**values) == deterministic_submission_id(**values)
    assert len(deterministic_submission_id(**values)) <= 48


def test_manifest_is_append_only_and_daily_empty_is_not_unknown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "manifest.jsonl"
    row = {"pillar": "Stocks", "strategy": "s", "local_submission_id": "sub-1", "timestamp": "2026-09-15T12:00:00Z"}
    first = append_manifest("INTENT_CREATED", row, path=path)
    second = append_manifest("INTENT_CREATED", row, path=path)
    assert first == second
    assert len(path.read_text().splitlines()) == 1
    report = forward_daily_metrics(manifest_path=path, output=tmp_path / "daily.json", now=datetime(2026, 9, 16, tzinfo=UTC))
    assert report["fills_today"] == 0
    assert report["verified_closed_trades"] == 0
    assert report["verification_confidence"] == "NO_FORWARD_EXECUTION"
    assert json.loads((tmp_path / "daily.json").read_text())["unknown_provider_exposure"] == "PRESERVED_OUTSIDE_FORWARD_VERIFIED"


def test_missing_ownership_defaults_fail_closed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "manifest.jsonl"
    append_manifest("INTENT_CREATED", {"local_submission_id": "s1"}, path=path)
    row = json.loads(path.read_text())
    assert row["ownership_classification"] == "OWNERSHIP_INCOMPLETE"


def test_new_york_boundary_converts_utc_date(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "manifest.jsonl"
    epoch = ensure_verification_epoch()
    append_manifest("FILLED", {"local_submission_id": "s1", "timestamp": "2026-09-16T03:30:00Z", "verification_epoch_id": epoch["verification_epoch_id"], "provider_order_id": "o1", "provider_fill_id": "f1", "ownership_classification": "PLATFORM_OWNED_CURRENT_EXPERIMENT"}, path=path)
    report = forward_daily_metrics(manifest_path=path, output=tmp_path / "daily.json", now=datetime(2026, 9, 16, 3, 30, tzinfo=UTC))
    assert report["day"] == "2026-09-15"
    assert report["fills_today"] == 1


def test_reconciler_does_not_adopt_unlinked_provider_positions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "manifest.jsonl"
    append_manifest("INTENT_CREATED", {"local_submission_id": "s1", "provider_order_id": "known", "requested_quantity": 10}, path=path)
    result = reconcile(manifest_path=path, provider_positions=[{"symbol": "SPY", "qty": 2}], provider_fills=[])
    assert result["owned_open_positions"] == []
    assert result["unattributed_provider_positions"] == [{"symbol": "SPY", "qty": 2}]


def test_reconciler_deduplicates_requested_and_fill_quantities(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "manifest.jsonl"
    base = {"local_submission_id": "s1", "provider_order_id": "o1", "verification_epoch_id": "VE-1", "requested_quantity": 10}
    for event in ("INTENT_CREATED", "CAPITAL_RESERVED", "SUBMITTED"):
        append_manifest(event, base, path=path)
    fills = [{"id": "f1", "order_id": "o1", "symbol": "SPY", "qty": 4}, {"id": "f1", "order_id": "o1", "symbol": "SPY", "qty": 4}, {"id": "f2", "order_id": "o1", "symbol": "SPY", "qty": 3}]
    result = reconcile(manifest_path=path, provider_fills=fills)
    assert result["requested_quantity"] == 10
    assert result["filled_quantity"] == 7


def test_reservation_partial_release_requires_confirmed_completion(tmp_path):
    ledger = CapitalReservations(tmp_path / "reservations.db")
    assert ledger.reserve(reservation_id="r1", pillar="stocks", local_submission_id="s1", amount=100, created_at="t")
    try:
        ledger.release(reservation_id="r1", released_at="t2", completion_event="TIMEOUT")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown state must not release capital")
    assert ledger.release(reservation_id="r1", released_at="t3", completion_event="CANCELED", amount=60)
