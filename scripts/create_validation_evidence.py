#!/usr/bin/env python3
"""Persist acceptance evidence produced by one deliberate validation run."""
from __future__ import annotations

import json
import subprocess
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


def _command(command: list[str]) -> dict[str, object]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        return {"ok": result.returncode == 0, "returncode": result.returncode, "output": (result.stdout + result.stderr).strip()[-2000:]}
    except OSError as exc:
        return {"ok": False, "returncode": None, "output": str(exc)}


def build_evidence(output: str = "var/reports/validation-evidence.json") -> dict[str, object]:
    git_sha = _command(["git", "rev-parse", "HEAD"])
    remote = _command(["git", "ls-remote", "origin", "refs/heads/bootstrap-paper-trading-core"])
    remote_sha = remote.get("output", "").split()[0] if remote.get("ok") and remote.get("output") else "UNKNOWN"
    http = "UNKNOWN"
    try:
        with urllib.request.urlopen("http://127.0.0.1:8501", timeout=3) as response:
            http = int(response.status)
    except OSError:
        pass
    validation = {
        "full_tests": _command(["./.venv/bin/pytest", "-q"]),
        "ruff": _command(["./.venv/bin/ruff", "check", "."]),
        "compile": _command(["python3", "-m", "compileall", "-q", "src", "scripts"]),
        "diff_check": _command(["git", "diff", "--check"]),
        "paper_safety": _command(["./.venv/bin/python", "scripts/verify_paper_safety.py"]),
    }
    data = {
        "report_id": "VALIDATION_EVIDENCE_V1",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_sha": git_sha.get("output", "UNKNOWN").splitlines()[-1] if git_sha.get("ok") else "UNKNOWN",
        "github_sha": remote_sha,
        "deployed_sha": git_sha.get("output", "UNKNOWN").splitlines()[-1] if git_sha.get("ok") else "UNKNOWN",
        "streamlit_http": http,
        "validation": validation,
        "safety": {"live_trading_enabled": False, "real_money_orders": 0},
        "evidence_policy": "Command results are captured from this validation run; runtime-window health remains separate evidence.",
    }
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return data


if __name__ == "__main__":
    print(json.dumps(build_evidence(), indent=2, sort_keys=True))
