#!/usr/bin/env python3
"""Publish sanitized runtime truth from the paper VM to the runtime-status branch.

This process is deliberately outside the execution loop.  It only copies the
authoritative, already-sanitized local artifacts and never creates lifecycle
events or changes trading state.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("TRADING_PLATFORM_ROOT", Path(__file__).resolve().parents[1]))
SOURCE = ROOT / "var" / "runtime"
WORKTREE = Path(os.environ.get("RUNTIME_STATUS_WORKTREE", ROOT / "var" / "runtime-status-worktree"))
PUBLIC = WORKTREE / "runtime-status"
HEALTH = SOURCE / "publisher_health.json"
SOURCE_FILES = {"external_status.json": "external_status.json", "post_fix_boundary.json": "post_fix_boundary.json", "trade_lifecycle_public.jsonl": "trade_lifecycle.jsonl"}
FILES = tuple(SOURCE_FILES)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I),
    re.compile(r"\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|bearer|cookie|client[_-]?secret)\b\s*[:=]", re.I),
    re.compile(r"\b(?:broker|account)[_-]?(?:credential|secret|password|token)\b", re.I),
    re.compile(r"(?:^|[\\/])\.env(?:$|[.])", re.I),
)

def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")

def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=WORKTREE, text=True, capture_output=True, check=check)

def validate_payloads(payloads: dict[str, bytes], boundary: dict, status: dict) -> None:
    if status.get("live_trading_enabled") is not False or boundary.get("live_trading_enabled") is not False:
        raise RuntimeError("refusing to publish non-paper/live-enabled status")
    if status.get("boundary", {}).get("boundary_id") != boundary.get("boundary_id"):
        raise RuntimeError("status/boundary mismatch")
    for name, raw in payloads.items():
        text = raw.decode("utf-8")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                raise RuntimeError(f"secret-like content refused in {name}")

def health(status: str, error: str | None = None, pushed: str | None = None) -> dict:
    return {"generated_at_utc": now(), "source_runtime_instance": None,
            "boundary_id": None, "running_sha": None,
            "publisher_sha": subprocess.run(("git", "rev-parse", "HEAD"), cwd=ROOT, text=True,
                                             capture_output=True).stdout.strip(),
            "last_successful_push": pushed, "last_attempt": now(),
            "status": status, "error": error}

def main() -> int:
    try:
        raw = {name: (SOURCE / source_name).read_bytes() for name, source_name in SOURCE_FILES.items()}
        boundary = json.loads(raw["post_fix_boundary.json"])
        status = json.loads(raw["external_status.json"])
        validate_payloads(raw, boundary, status)
        # Pin the public running identity to the boundary, avoiding git/runtime drift.
        public_status = dict(status)
        public_status["boundary_id"] = boundary["boundary_id"]
        public_status["boundary_timestamp"] = boundary["boundary_timestamp_utc"]
        public_status["runtime_instance_id"] = boundary["runtime_instance_id"]
        public_status["running_sha"] = boundary["git_commit_sha"]
        public_status["qualified"] = public_status.get("first_qualifying_post_boundary_trade") is not None
        raw["external_status.json"] = (json.dumps(public_status, indent=2, sort_keys=True) + "\n").encode()
        validate_payloads(raw, boundary, public_status)
        PUBLIC.mkdir(parents=True, exist_ok=True)
        for name, data in raw.items():
            target = PUBLIC / name
            with tempfile.NamedTemporaryFile("wb", dir=target.parent, delete=False) as f:
                f.write(data); temp = Path(f.name)
            os.replace(temp, target)
        run("git", "add", *(f"runtime-status/{name}" for name in FILES))
        changed = run("git", "diff", "--cached", "--quiet", check=False).returncode != 0
        if changed:
            run("git", "commit", "-m", f"runtime-status: update {now()}")
            pushed = run("git", "rev-parse", "HEAD").stdout.strip()
            run("git", "push", "origin", "HEAD:runtime-status")
        else:
            pushed = run("git", "rev-parse", "HEAD").stdout.strip()
        h = health("SUCCESS", pushed=pushed)
        h.update({"source_runtime_instance": boundary.get("runtime_instance_id"),
                  "boundary_id": boundary.get("boundary_id"), "running_sha": boundary.get("git_commit_sha")})
        HEALTH.write_text(json.dumps(h, indent=2, sort_keys=True) + "\n")
        return 0
    except Exception as exc:
        h = health("ERROR", error=str(exc))
        HEALTH.write_text(json.dumps(h, indent=2, sort_keys=True) + "\n")
        print(f"runtime status publish failed: {exc}")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
