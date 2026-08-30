from pathlib import Path


def test_runtime_process_roles_document_read_only_reconciliation():
    text = Path("docs/RUNTIME_PROCESS_ROLES.md").read_text()
    assert "broker_control=false" in text
    assert "execution_enabled=false" in text
    assert "count execution workers by role" in text
