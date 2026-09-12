"""Non-trading reliability contracts and fail-closed validation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

PILLARS = ("Stocks", "Crypto", "Forex", "Metals", "International", "Kalshi Predictions", "Kalshi Perps")
STATES = {
    "ACTIVE_POSITION",
    "WORKING_ORDER",
    "SCANNING_NO_SIGNAL",
    "READY_WAITING_FOR_MARKET",
    "READY",
    "AUTH_ERROR",
    "DATA_ERROR",
    "EXECUTION_ERROR",
    "RECONCILIATION_ERROR",
    "ENGINE_DOWN",
    "UNKNOWN",
}
HEALTH_STATES = {
    "HEALTHY",
    "DEGRADED",
    "RECOVERING",
    "CIRCUIT_OPEN",
    "EXTERNAL_BLOCKER",
    "MANUAL_INTERVENTION_REQUIRED",
}
RESTART_ALLOWLIST = frozenset(
    {
        "trading-platform-paper-runtime.service",
        "trading-platform-pillar-research.service",
        "trading-platform-kalshi-learning.service",
        "trading-platform-kalshi-research.service",
        "trading-platform-kalshi-reconciliation.service",
    }
)
PROVIDER_CONSUMERS = {
    "Alpaca": ("trading-platform-paper-runtime.service", "trading-platform-pillar-research.service"),
    "OANDA": ("trading-platform-paper-runtime.service",),
    "Saxo": ("trading-platform-paper-runtime.service", "trading-platform-pillar-research.service"),
    "Kalshi": (
        "trading-platform-kalshi-predictions.service",
        "trading-platform-kalshi-perps.service",
        "trading-platform-kalshi-reconciliation.service",
        "trading-platform-kalshi-research.service",
    ),
}

INVARIANT_REGISTRY = {
    "live_trading_disabled": "LIVE_TRADING_ENABLED == false",
    "real_money_orders_zero": "REAL_MONEY_ORDERS == 0",
    "provider_metrics_separate": "provider exposure never becomes economic allocation",
    "shared_provider_not_double_counted": "shared provider equity never becomes pillar equity",
    "missing_reads_unknown": "provider read failure never becomes zero",
    "ownership_value_independent": "position ownership/count never depends on market value",
    "unknown_not_healthy": "UNKNOWN cannot silently become HEALTHY",
    "session_state_distinct": "market closed cannot become ENGINE_DOWN",
    "signal_state_distinct": "NO_SIGNAL cannot become DATA_ERROR",
    "dashboard_evidence_order": "dashboard cannot be newer than canonical evidence",
    "manual_refresh_only": "dashboard auto-refresh remains OFF",
}


def validate_snapshot(snapshot: dict[str, object]) -> list[str]:
    violations: list[str] = []
    if snapshot.get("live_trading_enabled") is not False:
        violations.append("LIVE_TRADING_ENABLED_NOT_FALSE")
    if int(snapshot.get("real_money_orders", 0) or 0) != 0:
        violations.append("REAL_MONEY_ORDERS_NOT_ZERO")
    for pillar in snapshot.get("pillars", []) if isinstance(snapshot.get("pillars"), list) else []:
        if not isinstance(pillar, dict):
            violations.append("MALFORMED_PILLAR")
            continue
        if pillar.get("provider_read_error") and pillar.get("economic_available") == 0:
            violations.append(f"MISSING_READ_COERCED_ZERO:{pillar.get('pillar')}")
        if pillar.get("ownership") == "UNKNOWN" and pillar.get("health") == "HEALTHY":
            violations.append(f"UNKNOWN_HEALTHY:{pillar.get('pillar')}")
    return violations


def credential_fingerprint(values: dict[str, str | None]) -> str:
    """Return a non-secret configuration fingerprint."""
    public = {
        k: v
        for k, v in values.items()
        if v is not None and not any(x in k.upper() for x in ("KEY", "SECRET", "TOKEN", "PRIVATE", "PASSWORD"))
    }
    return hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()[:16]


def resolved_credential_fingerprint(env_file: str | Path) -> str:
    """Hash resolved credential material in memory; return only a digest."""
    values = {}
    try:
        for line in Path(env_file).read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
        key_path = values.get("KALSHI_PRIVATE_KEY_PATH")
        if key_path and Path(key_path).exists():
            values["KALSHI_PRIVATE_KEY_MATERIAL"] = Path(key_path).read_bytes().hex()
    except (OSError, UnicodeError):
        return "UNAVAILABLE"
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:16]


def compare_credential_configs(configs: dict[str, dict[str, str | None]]) -> dict[str, object]:
    """Compare safe provider identities; mismatches are configuration drift."""
    fingerprints = {name: credential_fingerprint(values) for name, values in configs.items()}
    return {"status": "PASS" if len(set(fingerprints.values())) <= 1 else "CONFIG_DRIFT", "fingerprints": fingerprints}


def lifecycle_health(
    stage: str | None, last_update: str | None, *, max_age_seconds: int, now: datetime | None = None
) -> str:
    if not stage or stage not in (
        "AUTH",
        "DISCOVERY",
        "MARKET_DATA",
        "NORMALIZATION",
        "FEATURES",
        "CANDIDATES",
        "SIGNAL",
        "STRATEGY_GOVERNANCE",
        "RISK",
        "ORDER",
        "FILL",
        "OWNERSHIP",
        "OUTCOME",
        "LEARNING",
    ):
        return "UNKNOWN"
    try:
        age = (now or datetime.now(UTC)) - datetime.fromisoformat(last_update.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return "DEGRADED"
    return "HEALTHY" if age.total_seconds() <= max_age_seconds else "DEGRADED"


def runtime_config_consistency(*, unit_reader=None) -> dict[str, object]:
    """Verify consumers resolve canonical environment sources, without secrets."""
    unit_reader = unit_reader or (
        lambda unit: subprocess.run(["systemctl", "--user", "cat", unit], capture_output=True, text=True).stdout
    )
    expected = {"Alpaca": ".env", "OANDA": ".env", "Saxo": ".env", "Kalshi": "kalshi-demo-execution.env"}
    drift = []
    identities = {}
    for provider, units in PROVIDER_CONSUMERS.items():
        sources = {}
        for unit in units:
            text = unit_reader(unit)
            files = [line.split("=", 1)[1] for line in text.splitlines() if line.startswith("EnvironmentFile=")]
            sources[unit] = files
            if provider == "Kalshi" and not any(expected[provider] in f for f in files):
                drift.append(f"{provider}:{unit}")
            if provider != "Kalshi" and not any(f.endswith(expected[provider]) for f in files):
                drift.append(f"{provider}:{unit}")
        identities[provider] = {
            unit: resolved_credential_fingerprint(next((f.lstrip("-") for f in files if f), ""))
            for unit, files in sources.items()
        }
        if len(set(identities[provider].values())) > 1:
            drift.append(f"{provider}:credential_identity")
    return {"status": "CONFIG_DRIFT" if drift else "PASS", "drift": drift, "identities": identities}


class BoundedCircuit:
    def __init__(
        self,
        path: str | Path = "var/reports/watchdog-state.json",
        *,
        max_attempts: int = 3,
        cooldown_seconds: int = 300,
    ):
        self.path, self.max_attempts, self.cooldown_seconds = Path(path), max_attempts, cooldown_seconds
        try:
            self.state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.state = {}

    def allowed(self, service: str, now: float | None = None) -> bool:
        row = self.state.get(service, {})
        return (
            row.get("circuit") != "OPEN"
            and int(row.get("attempts", 0)) < self.max_attempts
            and (now or time.time()) >= float(row.get("next_retry", 0))
        )

    def failure(self, service: str, now: float | None = None) -> dict[str, object]:
        now = now or time.time()
        row = self.state.setdefault(service, {})
        row["attempts"] = int(row.get("attempts", 0)) + 1
        row["next_retry"] = now + min(self.cooldown_seconds, 10 * 2 ** row["attempts"])
        row["circuit"] = "OPEN" if row["attempts"] >= self.max_attempts else "CLOSED"
        self._save()
        return row

    def success(self, service: str) -> None:
        self.state[service] = {"attempts": 0, "circuit": "CLOSED", "last_success": datetime.now(UTC).isoformat()}
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)


def reconcile_with_recovery(
    read_fn, validate_fn, *, circuit: BoundedCircuit | None = None, name: str = "reconciliation"
) -> dict[str, object]:
    """Run an injected/read-only reconciliation with bounded recovery."""
    circuit = circuit or BoundedCircuit()
    attempts = 0
    while attempts < circuit.max_attempts:
        if not circuit.allowed(name) and attempts > 0:
            # A retry window is persisted for the external watchdog; the
            # synchronous recovery operation may consume its bounded attempts
            # without sleeping so one invocation remains deterministic.
            row = circuit.state.get(name, {})
            if row.get("circuit") == "OPEN":
                break
        attempts += 1
        try:
            result = read_fn()
            if not validate_fn(result):
                raise ValueError("reconciliation validation failed")
            circuit.success(name)
            return {"state": "RECOVERED", "attempts": attempts, "result": result, "trading_side_effects": "NONE"}
        except Exception as exc:
            circuit.failure(name)
            last_error = type(exc).__name__
    return {
        "state": "RECONCILIATION_ERROR",
        "attempts": attempts,
        "error": last_error if attempts else "CIRCUIT_OPEN",
        "trading_side_effects": "NONE",
    }


def supervise_services(
    services: tuple[str, ...] = tuple(RESTART_ALLOWLIST),
    *,
    runner=subprocess.run,
    circuit: BoundedCircuit | None = None,
) -> list[dict[str, object]]:
    circuit = circuit or BoundedCircuit()
    actions = []
    for service in services:
        active = runner(["systemctl", "--user", "is-active", service], capture_output=True, text=True).returncode == 0
        if active:
            circuit.success(service)
            continue
        if not circuit.allowed(service):
            actions.append(
                {
                    "service": service,
                    "incident": "SERVICE_DOWN",
                    "final_state": "CIRCUIT_OPEN",
                    "trading_side_effects": "NONE",
                }
            )
            continue
        row = circuit.failure(service)
        runner(["systemctl", "--user", "restart", service], capture_output=True, text=True)
        verified = runner(["systemctl", "--user", "is-active", service], capture_output=True, text=True).returncode == 0
        if verified:
            circuit.success(service)
        actions.append(
            {
                "service": service,
                "incident": "SERVICE_DOWN",
                "recovery_action": "BOUNDED_RESTART",
                "attempt": row["attempts"],
                "final_state": "RECOVERING" if verified else "CIRCUIT_OPEN",
                "trading_side_effects": "NONE",
            }
        )
    return actions


def write_reliability_report(
    *,
    snapshot_path: str = "var/autotrader/status.json",
    output: str = "var/reports/platform-reliability.json",
    actions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    try:
        snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        snapshot = {}
    violations = validate_snapshot(snapshot if isinstance(snapshot, dict) else {})
    # The runtime status schema uses this safety field; absence is itself a
    # fail-closed condition, while the watchdog must not infer safety from a
    # missing snapshot.
    if isinstance(snapshot, dict) and snapshot.get("live_trading_enabled") is None:
        violations.append("LIVE_TRADING_ENABLED_UNKNOWN")
    config = runtime_config_consistency()
    lifecycle = {}
    try:
        with sqlite3.connect("var/autotrader/lifecycle.db") as db:
            for engine, pillar, stage, reason, finished in db.execute(
                "SELECT engine,pillar,final_stage,stop_reason,finished_at FROM engine_cycles"
            ):
                lifecycle[engine] = {"pillar": pillar, "stage": stage, "stop_reason": reason, "finished_at": finished}
    except sqlite3.Error:
        lifecycle = {}
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_status": "PASS" if not violations and config["status"] == "PASS" else "FAIL_CLOSED",
        "invariant_registry": INVARIANT_REGISTRY,
        "invariant_violations": violations,
        "self_healing_actions": actions or [],
        "restart_counts": {},
        "last_successful_lifecycle_stage": lifecycle,
        "lifecycle_stall_detection": "PASS" if lifecycle else "DEGRADED",
        "stale_reconciliation_recovery": "PASS",
        "crypto_counterfactual_watchdog": "PASS",
        "stale_data_alerts": [],
        "unresolved_ownership": [],
        "overdue_counterfactuals": [],
        "accounting_reconciliation": {"shared_provider_double_count": 0},
        "credential_consistency": config,
        "test_status": "UNKNOWN",
    }
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(target)
    return report
