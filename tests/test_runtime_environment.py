import os

from autotrader.runtime_environment import load_runtime_environment


def test_loader_does_not_overwrite_process_environment(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("ALPACA_PAPER_API_KEY=file-secret\nOANDA_PRACTICE_TOKEN=token\n")
    monkeypatch.setenv("ALPACA_PAPER_API_KEY", "process-value")
    result = load_runtime_environment(repo_env=path, kalshi_env=tmp_path / "missing")
    assert os.environ["ALPACA_PAPER_API_KEY"] == "process-value"
    assert result["presence"]["ALPACA_PAPER_API_KEY"] == "PRESENT"


def test_authoritative_loader_uses_last_provider_assignment(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("ALPACA_PAPER_SECRET_KEY=bad\nALPACA_PAPER_SECRET_KEY=good\n")
    monkeypatch.setenv("ALPACA_PAPER_SECRET_KEY", "stale")
    load_runtime_environment(repo_env=path, kalshi_env=tmp_path / "missing", authoritative=True)
    assert os.environ["ALPACA_PAPER_SECRET_KEY"] == "good"
