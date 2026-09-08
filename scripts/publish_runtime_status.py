#!/usr/bin/env python3
"""Publish paper-only read-side truth without mutating trading state."""
from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("TRADING_PLATFORM_ROOT", Path(__file__).resolve().parents[1]))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SOURCE = ROOT / "var" / "runtime"
WORKTREE = Path(os.environ.get("RUNTIME_STATUS_WORKTREE", ROOT / "var" / "runtime-status-worktree"))
PUBLIC = WORKTREE / "runtime-status"
HEALTH = SOURCE / "publisher_health.json"
SOURCE_FILES = {
    "external_status.json": "external_status.json",
    "post_fix_boundary.json": "post_fix_boundary.json",
    "trade_lifecycle_public.jsonl": "trade_lifecycle.jsonl",
}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.I),
    re.compile(r'''\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|bearer|cookie|client[_-]?secret)\b["']?\s*[:=]''', re.I),
    re.compile(r"\b(?:broker|account)[_-]?(?:credential|secret|password|token)\b", re.I),
    re.compile(r"(?:^|[\\/])\.env(?:$|[.])", re.I),
)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run(*args, check=True):
    return subprocess.run(args, cwd=WORKTREE, text=True, capture_output=True, check=check, timeout=60)


def validate_payloads(payloads, boundary, status):
    if status.get("live_trading_enabled") is not False or boundary.get("live_trading_enabled") is not False:
        raise RuntimeError("refusing to publish non-paper/live-enabled status")
    if not boundary.get("boundary_id") or status.get("boundary", {}).get("boundary_id") != boundary.get("boundary_id"):
        raise RuntimeError("status/boundary mismatch")
    for name, raw in payloads.items():
        text = raw.decode("utf-8")
        if any(pattern.search(text) for pattern in SECRET_PATTERNS):
            raise RuntimeError(f"secret-like content refused in {name}")


def synchronize():
    """Preserve remote workflow edits and all existing publication commits."""
    if run("git", "status", "--porcelain").stdout.strip():
        raise RuntimeError("publication worktree has uncommitted changes; preserved for review")
    run("git", "fetch", "origin", "runtime-status")
    try:
        run("git", "merge", "--no-edit", "origin/runtime-status")
    except subprocess.CalledProcessError:
        run("git", "merge", "--abort", check=False)
        raise RuntimeError("publication merge needs review; local and remote history preserved") from None


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        handle.write(data)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def main():
    SOURCE.mkdir(parents=True, exist_ok=True)
    with (SOURCE / "publisher.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        try:
            from portfolio_reporting import build_report

            raw = {name: (SOURCE / local).read_bytes() for name, local in SOURCE_FILES.items()}
            boundary = json.loads(raw["post_fix_boundary.json"])
            status = json.loads(raw["external_status.json"])
            validate_payloads(raw, boundary, status)
            status["boundary_id"] = boundary["boundary_id"]
            status["boundary_timestamp"] = boundary["boundary_timestamp_utc"]
            status["runtime_instance_id"] = boundary["runtime_instance_id"]
            status["running_sha"] = status.get("git", {}).get("commit_sha")
            status["publisher_sha"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
            status["qualified"] = (status.get("first_qualifying_post_boundary_trade") or {}).get("qualified") is True
            status["portfolio_accounting"] = build_report(ROOT)
            raw["external_status.json"] = (json.dumps(status, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
            validate_payloads(raw, boundary, status)
            synchronize()
            for name, data in raw.items():
                atomic_write(PUBLIC / name, data)
            run("git", "add", *(f"runtime-status/{name}" for name in SOURCE_FILES))
            difference = run("git", "diff", "--cached", "--quiet", check=False).returncode
            if difference == 1:
                run("git", "commit", "-m", f"runtime-status: update {now()}")
            elif difference != 0:
                raise RuntimeError("unable to verify publication diff")
            # Always push, including when a prior push left an unpublished commit.
            try:
                run("git", "push", "origin", "HEAD:runtime-status")
            except subprocess.CalledProcessError:
                synchronize()
                run("git", "push", "origin", "HEAD:runtime-status")
            result = {"status": "SUCCESS", "last_attempt": now(), "last_successful_push": now(),
                "publication_commit": run("git", "rev-parse", "HEAD").stdout.strip(),
                "boundary_id": boundary["boundary_id"], "publisher_sha": status["publisher_sha"]}
            atomic_write(HEALTH, (json.dumps(result, indent=2) + "\n").encode())
            return 0
        except Exception as exc:
            result = {"status": "ERROR", "last_attempt": now(), "error_type": type(exc).__name__}
            atomic_write(HEALTH, (json.dumps(result, indent=2) + "\n").encode())
            print(f"Runtime publication failed: {type(exc).__name__}")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
