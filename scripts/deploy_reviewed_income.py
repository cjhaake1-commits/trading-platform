"""Deploy tested paper code while preserving reviewed local changes and losses.

No broker API is used. Only known user services, tracked source, and the
explicit backed-up logical principal adjustment are changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

BRANCH = "bootstrap-paper-trading-core"
RUNTIME = "trading-platform-paper-runtime.service"
DASHBOARD = "trading-platform-streamlit.service"
TIMERS = ("trading-platform-watchdog.timer", "trading-platform-runtime-publisher.timer")
AUXILIARY = ("trading-platform-watchdog.service", "trading-platform-runtime-publisher.service")


def command(*args, check=True, timeout=90):
    return subprocess.run(args, text=True, capture_output=True, check=check, timeout=timeout)


def git(*args):
    return command("git", *args).stdout.strip()


def active(unit):
    return command("systemctl", "--user", "is-active", "--quiet", unit, check=False).returncode == 0


def unit_action(action, unit):
    command("systemctl", "--user", action, unit)


def runtime_artifact(name):
    return name == "dashboard/data.json" or name.startswith("var/")


def check_reviewed_files(root, changed, manifest):
    for name in changed:
        if runtime_artifact(name):
            continue
        if name not in manifest or Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Unreviewed local source change: " + name)
        path = root / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != manifest[name]:
            raise ValueError("Local source changed after review: " + name)
    return sorted(name for name in changed if not runtime_artifact(name))


def assert_paper(root):
    value = json.loads((root / "var/autotrader/status.json").read_text())
    if value.get("live_trading_enabled") is not False:
        raise ValueError("Current runtime does not prove paper-only mode")
    for key in ("LIVE_TRADING_ENABLED", "KALSHI_LIVE_TRADING_ENABLED"):
        if os.environ.get(key, "false").strip().lower() in {"true", "1", "yes", "on"}:
            raise ValueError("Live flag is enabled")
    env = root / ".env"
    if env.exists() and re.search(r"^\s*(LIVE_TRADING_ENABLED|KALSHI_LIVE_TRADING_ENABLED)\s*=\s*[\"']?(true|1|yes|on)[\"']?\s*$", env.read_text(), re.I | re.M):
        raise ValueError("Live flag in environment file is enabled")


def preserve(root, destination, names):
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chmod(destination, 0o700)
    patch = command("git", "diff", "--binary", "HEAD", "--", *names).stdout if names else ""
    (destination / "reviewed-source.patch").write_text(patch)
    untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
    safe_local = [name for name in untracked if not name.startswith("var/") and Path(name).suffix in {".py", ".service", ".timer", ".json"}]
    with tarfile.open(destination / "source-backup.tar.gz", "w:gz") as archive:
        for name in sorted(set(names + safe_local)):
            path = root / name
            if path.is_file() and not path.is_symlink():
                archive.add(path, arcname=name, recursive=False)
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in safe_local if (root / name).is_file()}
    (destination / "untracked-hashes.json").write_text(json.dumps(hashes, indent=2))
    for path in destination.iterdir():
        os.chmod(path, 0o600)
    return hashes


def wait_health(started_at, timeout=150):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        try:
            status = json.loads(Path("var/autotrader/status.json").read_text())
            heartbeat = datetime.fromisoformat(status["last_heartbeat_at"].replace("Z", "+00:00"))
            with urlopen("http://127.0.0.1:8501/_stcore/health", timeout=5) as response:
                http_ok = response.status == 200
            if active(RUNTIME) and active(DASHBOARD) and http_ok and heartbeat >= started_at and status.get("live_trading_enabled") is False:
                return
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(3)
    raise RuntimeError("Fresh runtime/dashboard health was not verified")


def deploy(root, target):
    root = root.resolve()
    if root != Path("/home/cjhaake1/trading-platform") or not re.fullmatch(r"[0-9a-f]{40}", target):
        raise ValueError("Unexpected deployment root or target")
    os.chdir(root)
    os.environ["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"
    assert_paper(root)
    if git("branch", "--show-current") != BRANCH:
        raise ValueError("VM is not on the expected source branch")
    if git("diff", "--cached", "--name-only"):
        raise ValueError("Staged local work must not be overwritten")
    before = git("rev-parse", "HEAD")
    git("fetch", "origin", BRANCH)
    git("merge-base", "--is-ancestor", before, target)
    git("merge-base", "--is-ancestor", target, f"origin/{BRANCH}")
    manifest = json.loads(git("show", f"{target}:docs/vm-preserved-source-manifest.json"))
    changed = git("diff", "HEAD", "--name-only").splitlines()
    reviewed = check_reviewed_files(root, changed, manifest)
    if not active(RUNTIME) or not active(DASHBOARD):
        raise ValueError("Unexpected pre-deployment service state")
    backup = root / "var/backups" / ("income-repair-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"))
    untracked_hashes = preserve(root, backup, reviewed)
    unit_path = Path(git_unit_path := command("systemctl", "--user", "show", RUNTIME, "--property=FragmentPath", "--value").stdout.strip())
    if not git_unit_path or unit_path.parent != Path.home() / ".config/systemd/user":
        raise ValueError("Unexpected runtime unit path")
    unit_before = unit_path.read_text()
    (backup / "runtime-unit-before.service").write_text(unit_before)
    os.chmod(backup / "runtime-unit-before.service", 0o600)
    prior_timers = [unit for unit in TIMERS if active(unit)]
    stash = None
    migrated = False
    source_updated = False
    try:
        for unit in prior_timers:
            unit_action("stop", unit)
        for unit in AUXILIARY:
            if active(unit):
                unit_action("stop", unit)
        unit_action("stop", RUNTIME)
        unit_action("stop", DASHBOARD)
        if active(RUNTIME) or active(DASHBOARD):
            raise RuntimeError("Ledger writers did not stop")
        check_reviewed_files(root, git("diff", "HEAD", "--name-only").splitlines(), manifest)
        if reviewed:
            git("stash", "push", "-m", "preserved-reviewed-income-repair", "--", *reviewed)
            stash = git("rev-parse", "refs/stash")
            (backup / "source-stash-sha.txt").write_text(stash + "\n")
        git("merge", "--ff-only", target)
        source_updated = True
        if git("rev-parse", "HEAD") != target:
            raise RuntimeError("Unexpected deployed source")
        command(str(root / ".venv/bin/python"), "-m", "compileall", "-q", "src")
        command(str(root / ".venv/bin/python"), "-m", "py_compile", "streamlit_app.py", "dashboard_simple.py", "portfolio_reporting.py", "runtime_income_evidence.py")
        # Reverse only evidenced capital inflation; preserve all recorded losses.
        result = command(str(root / ".venv/bin/python"), "scripts/restore_income_capital.py", "--database", "var/autotrader/portfolio.db", "--backup-dir", str(backup / "ledger"), "--writers-stopped")
        (backup / "principal-adjustment.json").write_text(result.stdout)
        migrated = True
        unit_after = re.sub(r"(?<=--initial-equity )85000(?:\.0)?(?=\s|$)", "5000", unit_before)
        if unit_after != unit_before:
            temporary = unit_path.with_suffix(".income-repair-tmp")
            temporary.write_text(unit_after)
            os.chmod(temporary, unit_path.stat().st_mode & 0o777)
            temporary.replace(unit_path)
            command("systemctl", "--user", "daemon-reload")
        started = datetime.now(UTC)
        unit_action("start", RUNTIME)
        unit_action("start", DASHBOARD)
        wait_health(started)
        command(str(root / ".venv/bin/python"), "-c",
                "from streamlit.testing.v1 import AppTest; "
                "app = AppTest.from_file('dashboard_simple.py').run(timeout=30); "
                "assert len(app.exception) == 0, 'Dashboard render failed'; "
                "assert any('$6,000' in title.value for title in app.title), 'Wrong app version'",
                timeout=45)
        for name, digest in untracked_hashes.items():
            if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
                raise RuntimeError("Untracked source changed during deployment: " + name)
        result = {"status": "DEPLOYED", "commit": target, "previous_commit": before,
                  "source_preserved_stash": stash, "backup": str(backup),
                  "capital_policy": "income_6000_v1", "live_trading_enabled": False,
                  "positions_and_orders_modified_by_deployer": False,
                  "runtime_and_dashboard_fresh": True}
        (backup / "deployment-result.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    except Exception:
        if not migrated:
            if source_updated:
                git("switch", "--detach", before)
            if stash:
                git("stash", "apply", stash)
            unit_path.write_text(unit_before)
            command("systemctl", "--user", "daemon-reload")
        # Do not restore an old database after trading could have resumed.
        unit_action("start", RUNTIME)
        unit_action("start", DASHBOARD)
        raise
    finally:
        for unit in prior_timers:
            unit_action("start", unit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    deploy(Path("/home/cjhaake1/trading-platform"), args.target)


if __name__ == "__main__":
    main()
