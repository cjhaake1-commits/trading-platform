from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

BASELINE_MODEL_VERSION = "five_pillar_baseline_v1"
DEFAULT_PARAMETERS = {
    "minimum_candidate_score": 5.0,
    "momentum_only_score": 12.0,
    "strategy_weight": 1.0,
    "holding_period_bias": 0.0,
    "entry_timing_bias": 0.0,
    "exit_timing_bias": 0.0,
    "confidence_calibration": 1.0,
    "instrument_preference_bias": 0.0,
}
PARAMETER_BOUNDS = {
    "minimum_candidate_score": (4.0, 8.0),
    "momentum_only_score": (9.0, 16.0),
    "strategy_weight": (0.8, 1.2),
    "holding_period_bias": (-1.0, 1.0),
    "entry_timing_bias": (-1.0, 1.0),
    "exit_timing_bias": (-1.0, 1.0),
    "confidence_calibration": (0.8, 1.2),
    "instrument_preference_bias": (-1.0, 1.0),
}
MAX_PARAMETER_CHANGE = 0.10
PROMOTION_COOLDOWN = timedelta(days=7)
MAX_DRAWDOWN_TOLERANCE = 0.02
RECENCY_HALF_LIFE = timedelta(days=14)
FORBIDDEN_PARAMETERS = {
    "risk_per_trade_pct",
    "max_portfolio_risk_pct",
    "max_daily_loss_pct",
    "max_peak_drawdown_pct",
    "cash_reserve_pct",
    "max_open_positions",
    "pillar_allocations",
    "reconciliation",
    "emergency_close",
    "emergency_kill_switch",
    "broker_environment",
    "live_mode",
    "paper_mode",
    "autonomous_trading_enabled",
    "autonomous_enable_disable",
}


def _manifest_number(record: dict[str, object], *names: str) -> float | None:
    for name in names:
        value = _finite(record.get(name))
        if value is not None:
            return value
    return None


def _costs(record: dict[str, object]) -> float:
    direct = record.get("fees_costs")
    if direct is not None:
        return max(_finite(direct) or 0.0, 0.0)
    metadata = record.get("metadata_json")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            metadata = {}
    if not isinstance(metadata, dict):
        return 0.0
    return sum(max(_finite(metadata.get(key)) or 0.0, 0.0) for key in ("fees", "commission", "costs", "trading_costs"))


def _pillar(record: dict[str, object]) -> str:
    raw = str(record.get("pillar") or "").lower()
    broker = str(record.get("broker") or "").lower()
    if "saxo" in broker or raw in {"international", "ibkr_global"}:
        return "International"
    if "forex" in raw or "oanda" in broker:
        return "Forex"
    if "crypto" in raw or "crypto" in broker:
        return "Crypto"
    if "metal" in raw or "commod" in raw:
        return "Metals/Commodities"
    return "Stocks"


def _regime(record: dict[str, object]) -> str:
    value = record.get("market_regime") or record.get("regime")
    if value is None:
        metadata = record.get("metadata_json")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (TypeError, ValueError):
                metadata = {}
        if isinstance(metadata, dict):
            value = metadata.get("market_regime") or metadata.get("regime")
    return str(value).strip().lower() if value else "unknown"


def _recency_weight(occurred_at: object, *, now: datetime | None = None) -> float:
    if not isinstance(occurred_at, str) or not occurred_at.strip():
        return 1.0
    try:
        observed = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except ValueError:
        return 1.0
    if observed.tzinfo is None:
        return 1.0
    current = now or datetime.now(UTC)
    age = max((current - observed.astimezone(UTC)).total_seconds(), 0.0)
    half_life_seconds = max(RECENCY_HALF_LIFE.total_seconds(), 1.0)
    return max(0.25, 0.5 ** (age / half_life_seconds))


def _learning_intent(record: dict[str, object]) -> str:
    value = str(
        record.get("risk_engine_status")
        or record.get("reconciliation_status")
        or record.get("decision")
        or record.get("status")
        or ""
    ).strip().lower()
    if value in {"approved", "exact_match", "fractional_reconciliation", "broker_confirmed"}:
        return "approved"
    if value in {"rejected", "material_mismatch", "unprotected_position", "manual_review_required"}:
        return "rejected"
    return value or "unknown"


def _normalize_manifest_record(record: dict[str, object], *, now: datetime | None = None) -> dict[str, object] | None:
    if not isinstance(record, dict):
        return None
    proposed_entry = _manifest_number(record, "proposed_entry", "intended_entry", "entry_price", "price")
    if proposed_entry is None:
        return None
    quantity = _manifest_number(
        record,
        "quantity",
        "requested_quantity",
        "submitted_quantity",
        "broker_filled_quantity",
    )
    stop = _manifest_number(record, "stop", "stop_price", "invalidation_price")
    target = _manifest_number(record, "target", "target_price")
    fill_price = _manifest_number(record, "fill_price", "actual_entry")
    exit_price = _manifest_number(record, "exit_price", "actual_exit")
    realized_pnl = _manifest_number(record, "realized_pnl")
    fees = _manifest_number(record, "fees_costs", "fees", "commission", "costs", "trading_costs")
    if realized_pnl is None and fill_price is None and exit_price is None:
        return {
            "broker": str(record.get("broker") or "unknown"),
            "pillar": str(record.get("pillar") or "unknown"),
            "symbol": str(record.get("instrument") or record.get("symbol") or ""),
            "side": str(record.get("side") or ""),
            "proposed_entry": proposed_entry,
            "stop_price": stop,
            "target_price": target,
            "requested_quantity": quantity,
            "fill_price": None,
            "exit_price": None,
            "realized_pnl": None,
            "fees_costs": fees or 0.0,
            "model_confidence": _manifest_number(record, "model_confidence", "confidence") or 0.0,
            "strategy_version": str(record.get("strategy_version") or record.get("model_version") or ""),
            "risk_engine_status": str(record.get("risk_engine_status") or record.get("decision") or "unknown"),
            "rejection_reason": str(record.get("rejection_reason") or ""),
            "market_regime": str(record.get("market_regime") or record.get("regime") or "unknown"),
            "occurred_at": str(record.get("timestamp") or record.get("occurred_at") or ""),
            "manifest_source": "proposal",
            "execution_quality_penalty": 0.0,
            "intent_alignment": _learning_intent(record),
        }
    slippage = 0.0
    if fill_price is not None:
        slippage += abs(fill_price - proposed_entry) * max(quantity or 0.0, 0.0)
    if exit_price is not None and stop is not None:
        slippage += max(abs(exit_price - stop) - abs(exit_price - proposed_entry), 0.0) * 0.0
    return {
        "broker": str(record.get("broker") or "unknown"),
        "pillar": str(record.get("pillar") or "unknown"),
        "symbol": str(record.get("instrument") or record.get("symbol") or ""),
        "side": str(record.get("side") or ""),
        "proposed_entry": proposed_entry,
        "stop_price": stop,
        "target_price": target,
        "requested_quantity": quantity,
        "fill_price": fill_price,
        "exit_price": exit_price,
        "realized_pnl": realized_pnl or 0.0,
        "fees_costs": fees or 0.0,
        "model_confidence": _manifest_number(record, "model_confidence", "confidence") or 0.0,
        "strategy_version": str(record.get("strategy_version") or record.get("model_version") or ""),
        "risk_engine_status": str(record.get("risk_engine_status") or record.get("decision") or "unknown"),
        "rejection_reason": str(record.get("rejection_reason") or ""),
        "market_regime": str(record.get("market_regime") or record.get("regime") or "unknown"),
        "occurred_at": str(record.get("timestamp") or record.get("occurred_at") or ""),
        "manifest_source": "closed_trade" if realized_pnl is not None else "proposal",
        "execution_quality_penalty": slippage,
        "intent_alignment": _learning_intent(record),
        "proposed_vs_actual_quantity": (quantity or 0.0)
        - (_manifest_number(record, "broker_filled_quantity") or quantity or 0.0),
    }


def learning_score(records: list[dict[str, object]]) -> dict[str, float]:
    """Score realized outcomes only; unrealized marks never enter this objective."""

    net_outcomes = []
    execution_penalty = 0.0
    for record in records:
        realized = _finite(record.get("realized_pnl"))
        if realized is None:
            continue
        weight = _recency_weight(record.get("occurred_at") or record.get("closed_at") or record.get("timestamp"))
        net_outcome = (realized - _costs(record)) * weight
        net_outcomes.append(net_outcome)
        execution_penalty += max(_finite(record.get("execution_quality_penalty")) or 0.0, 0.0) * min(weight, 1.0)
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for outcome in net_outcomes:
        cumulative += outcome
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    net_cash = sum(net_outcomes)
    tail_risk = abs(min(net_outcomes)) if net_outcomes and min(net_outcomes) < 0 else 0.0
    excess_utilization = sum(max((_finite(r.get("notional")) or 0.0) - 1000.0, 0.0) for r in records)
    drawdown_penalty = max_drawdown * 0.10
    tail_penalty = tail_risk * 0.25
    utilization_penalty = excess_utilization * 0.01
    execution_penalty = execution_penalty * 0.01
    return {
        "completed_trades": float(len(net_outcomes)),
        "net_realized_cash": net_cash,
        "trading_costs": sum(_costs(r) for r in records if _finite(r.get("realized_pnl")) is not None),
        "max_drawdown": max_drawdown,
        "drawdown_penalty": drawdown_penalty,
        "tail_risk_penalty": tail_penalty,
        "excess_capital_utilization_penalty": utilization_penalty,
        "execution_quality_penalty": execution_penalty,
        "score": net_cash - drawdown_penalty - tail_penalty - utilization_penalty - execution_penalty,
    }


def _group_scores(records: list[dict[str, object]], key) -> dict[str, dict[str, float]]:
    groups: dict[str, list[dict[str, object]]] = {}
    for record in records:
        groups.setdefault(key(record), []).append(record)
    return {name: learning_score(items) for name, items in sorted(groups.items())}


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_learned_parameters(path: str | Path) -> dict[str, float]:
    result = dict(DEFAULT_PARAMETERS)
    source = Path(path)
    if not source.exists():
        return result
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except Exception:
        return result
    if not isinstance(raw, dict):
        return result
    for name, bounds in PARAMETER_BOUNDS.items():
        value = _finite(raw.get(name))
        if value is not None and bounds[0] <= value <= bounds[1]:
            result[name] = value
    return result


@dataclass
class RealizedOutcomeLearner:
    ledger_path: str = "var/autotrader/portfolio.db"
    experiment_baseline_start: str | None = None
    audit_path: str = "var/autotrader/audit.db"
    stats_path: str = "var/autotrader/learning/performance_stats.json"
    parameters_path: str = "var/autotrader/learning/learned_parameters.json"
    history_path: str = "var/autotrader/learning/learning_history.jsonl"
    model_state_path: str = "var/autotrader/learning/model_state.json"
    minimum_samples: int = 20
    preferred_samples: int = 30
    promotion_cooldown: timedelta = PROMOTION_COOLDOWN
    max_parameter_change: float = MAX_PARAMETER_CHANGE

    def _model_state(self) -> dict[str, object]:
        path = Path(self.model_state_path)
        if not path.exists():
            return {
                "baseline_version": BASELINE_MODEL_VERSION,
                "active_version": BASELINE_MODEL_VERSION,
                "promotions": [],
            }
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {
                "baseline_version": BASELINE_MODEL_VERSION,
                "active_version": BASELINE_MODEL_VERSION,
                "promotions": [],
            }
        if isinstance(value, dict):
            return value
        return {
            "baseline_version": BASELINE_MODEL_VERSION,
            "active_version": BASELINE_MODEL_VERSION,
            "promotions": [],
        }

    def _write_model_state(self, state: dict[str, object]) -> None:
        self._write_json(self.model_state_path, state)

    def regime_scores(self, records: list[dict[str, object]]) -> dict[str, dict[str, float]]:
        return _group_scores(records, _regime)

    def pillar_scores(self, records: list[dict[str, object]]) -> dict[str, dict[str, float]]:
        return _group_scores(records, _pillar)

    def manifest_evidence(self, limit: int | None = None) -> list[dict[str, object]]:
        path = Path(self.audit_path)
        if not path.exists():
            return []
        evidence: list[dict[str, object]] = []
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            query = "SELECT event_type, message, data_json, created_at FROM audit_events ORDER BY id DESC"
            if limit is not None:
                query += " LIMIT ?"
                rows = con.execute(query, (max(limit, 0),)).fetchall()
            else:
                rows = con.execute(query).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["data_json"])
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            manifest = payload.get("manifest")
            if isinstance(manifest, list):
                for item in manifest:
                    normalized = _normalize_manifest_record(item, now=datetime.now(UTC))
                    if normalized is not None:
                        normalized["audit_event_type"] = row["event_type"]
                        normalized["audit_message"] = row["message"]
                        normalized["occurred_at"] = row["created_at"]
                        evidence.append(normalized)
            elif payload.get("decision"):
                normalized = _normalize_manifest_record(payload.get("decision"), now=datetime.now(UTC))
                if normalized is not None:
                    normalized["audit_event_type"] = row["event_type"]
                    normalized["audit_message"] = row["message"]
                    normalized["occurred_at"] = row["created_at"]
                    evidence.append(normalized)
        if self.experiment_baseline_start:
            baseline = self.experiment_baseline_start.replace("Z", "+00:00")
            evidence = [
                item for item in evidence
                if str(item.get("occurred_at") or "") >= baseline
            ]
        return evidence

    def propose_challenger(self, baseline: dict[str, float], *, sample_size: int) -> dict[str, float]:
        """Create a bounded candidate without exposing any hard control."""

        proposal = {name: float(baseline.get(name, default)) for name, default in DEFAULT_PARAMETERS.items()}
        if sample_size < self.minimum_samples:
            return proposal
        for name in ("minimum_candidate_score", "momentum_only_score", "strategy_weight", "confidence_calibration"):
            old = proposal[name]
            low, high = PARAMETER_BOUNDS[name]
            direction = -1.0 if name in {"minimum_candidate_score", "momentum_only_score"} else 1.0
            step = min(abs(old) * self.max_parameter_change, max(abs(old), 1.0) * self.max_parameter_change)
            proposal[name] = round(max(low, min(high, old + direction * step)), 6)
        return proposal

    def evaluate_challenger(
        self,
        baseline_records: list[dict[str, object]],
        challenger_records: list[dict[str, object]],
        *,
        baseline_parameters: dict[str, float] | None = None,
        challenger_parameters: dict[str, float] | None = None,
        now: datetime | None = None,
    ) -> dict[str, object]:
        now = now or datetime.now(UTC)
        baseline_score = learning_score(baseline_records)
        challenger_score = learning_score(challenger_records)
        state = self._model_state()
        promotions = state.get("promotions") if isinstance(state.get("promotions"), list) else []
        last_promotion = None
        if promotions and isinstance(promotions[-1], dict):
            last_promotion = promotions[-1].get("timestamp")
        cooldown_ok = True
        if isinstance(last_promotion, str):
            try:
                cooldown_ok = now - datetime.fromisoformat(last_promotion) >= self.promotion_cooldown
            except ValueError:
                cooldown_ok = False
        sample_ok = len(challenger_records) >= self.minimum_samples
        parameters = challenger_parameters or self.propose_challenger(
            baseline_parameters or DEFAULT_PARAMETERS,
            sample_size=len(challenger_records),
        )
        baseline_parameters = baseline_parameters or DEFAULT_PARAMETERS
        change_ok = all(
            name in PARAMETER_BOUNDS
            and PARAMETER_BOUNDS[name][0] <= value <= PARAMETER_BOUNDS[name][1]
            and abs(value - float(baseline_parameters.get(name, DEFAULT_PARAMETERS[name])))
            <= max(abs(float(baseline_parameters.get(name, DEFAULT_PARAMETERS[name]))), 1.0)
            * self.max_parameter_change
            + 1e-12
            for name, value in parameters.items()
        )
        drawdown_ok = challenger_score["max_drawdown"] <= baseline_score["max_drawdown"] + MAX_DRAWDOWN_TOLERANCE
        promoted = bool(
            sample_ok
            and cooldown_ok
            and change_ok
            and drawdown_ok
            and challenger_score["score"] > baseline_score["score"]
        )
        return {
            "promoted": promoted,
            "sample_ok": sample_ok,
            "cooldown_ok": cooldown_ok,
            "parameter_change_ok": change_ok,
            "drawdown_ok": drawdown_ok,
            "baseline": baseline_score,
            "challenger": challenger_score,
            "reason": (
                "challenger beats baseline on walk-forward evidence"
                if promoted
                else "promotion guardrail blocked challenger"
            ),
            "model_version": state.get("active_version", BASELINE_MODEL_VERSION),
        }

    def promote_challenger(
        self,
        evaluation: dict[str, object],
        parameters: dict[str, float],
        *,
        now: datetime | None = None,
    ) -> str:
        if not evaluation.get("promoted"):
            return str(self._model_state().get("active_version", BASELINE_MODEL_VERSION))
        now = now or datetime.now(UTC)
        state = self._model_state()
        previous = str(state.get("active_version", BASELINE_MODEL_VERSION))
        version = f"challenger_{now.astimezone(UTC).strftime('%Y%m%d%H%M%S')}"
        promotions = state.get("promotions") if isinstance(state.get("promotions"), list) else []
        promotions.append(
            {
                "timestamp": now.astimezone(UTC).isoformat(),
                "from": previous,
                "to": version,
                "parameters": parameters,
            }
        )
        state.update({"active_version": version, "active_parameters": parameters, "promotions": promotions})
        self._write_model_state(state)
        return version

    def rollback_if_underperforming(
        self,
        records: list[dict[str, object]],
        prior_score: float,
        *,
        now: datetime | None = None,
    ) -> bool:
        state = self._model_state()
        current = learning_score(records)["score"]
        if current >= prior_score or str(state.get("active_version", BASELINE_MODEL_VERSION)) == BASELINE_MODEL_VERSION:
            return False
        promotions = state.get("promotions") if isinstance(state.get("promotions"), list) else []
        previous = (
            promotions[-1].get("from")
            if promotions and isinstance(promotions[-1], dict)
            else BASELINE_MODEL_VERSION
        )
        state.update(
            {
                "active_version": previous,
                "active_parameters": dict(DEFAULT_PARAMETERS),
                "rollback_at": (now or datetime.now(UTC)).astimezone(UTC).isoformat(),
            }
        )
        self._write_model_state(state)
        return True

    def update(self, now: datetime | None = None) -> dict[str, object]:
        now = now or datetime.now(UTC)
        trades = self._completed_trades()
        manifest_evidence = self.manifest_evidence()
        realized_records = [dict(t) for t in trades]
        learning_records = [*realized_records, *manifest_evidence]
        pnls = [float(t["realized_pnl"]) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        count = len(pnls)
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        expectancy = sum(pnls) / count if count else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
        stats = {
            "generated_at": now.astimezone(UTC).isoformat(),
            "completed_trades": count,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / count if count else 0.0,
            "average_win": sum(wins) / len(wins) if wins else 0.0,
            "average_loss": sum(losses) / len(losses) if losses else 0.0,
            "expectancy": expectancy,
            "profit_factor": None if math.isinf(profit_factor) else profit_factor,
            "cumulative_realized_pnl": sum(pnls),
            "sample_status": "collecting_evidence"
            if count < self.minimum_samples
            else ("limited_adaptation" if count < self.preferred_samples else "adaptive"),
            "hard_guardrails_mutable": False,
            "model_baseline_version": BASELINE_MODEL_VERSION,
            "manifest_evidence_count": len(manifest_evidence),
            "proposal_evidence_count": sum(
                1 for item in manifest_evidence if item.get("manifest_source") == "proposal"
            ),
            "execution_quality_penalty": learning_score(learning_records)["execution_quality_penalty"],
        }
        self._write_json(self.stats_path, stats)

        params = load_learned_parameters(self.parameters_path)
        changes: list[dict[str, object]] = []
        if count >= self.minimum_samples:
            # Only entry selectivity is adapted here. Risk limits remain outside this module.
            direction = -1.0 if expectancy > 0 and (profit_factor >= 1.1 or math.isinf(profit_factor)) else 1.0
            scale = 0.02 if count < self.preferred_samples else 0.05
            for name in ("minimum_candidate_score", "momentum_only_score"):
                old = params[name]
                low, high = PARAMETER_BOUNDS[name]
                proposed = old * (1.0 + direction * scale)
                max_step = abs(old) * 0.10
                proposed = max(old - max_step, min(old + max_step, proposed))
                new = max(low, min(high, proposed))
                if abs(new - old) > 1e-12:
                    params[name] = round(new, 6)
                    changes.append(
                        {
                            "timestamp": now.astimezone(UTC).isoformat(),
                            "parameter": name,
                            "old_value": old,
                            "new_value": params[name],
                            "sample_size": count,
                            "expectancy": expectancy,
                            "profit_factor": stats["profit_factor"],
                            "win_rate": stats["win_rate"],
                            "reason": "bounded realized-outcome adaptation",
                        }
                    )
            if manifest_evidence:
                confidence_quality = sum(
                    max(0.0, min(1.0, _finite(item.get("model_confidence")) or 0.0))
                    for item in manifest_evidence
                    if item.get("manifest_source") == "closed_trade"
                )
                calibration_shift = 0.0
                if confidence_quality > 0:
                    calibration_shift = min(0.02, confidence_quality / max(len(manifest_evidence), 1) * 0.01)
                old = params["confidence_calibration"]
                low, high = PARAMETER_BOUNDS["confidence_calibration"]
                new = max(low, min(high, old + calibration_shift if expectancy >= 0 else old - calibration_shift))
                if abs(new - old) > 1e-12:
                    params["confidence_calibration"] = round(new, 6)
                    changes.append(
                        {
                            "timestamp": now.astimezone(UTC).isoformat(),
                            "parameter": "confidence_calibration",
                            "old_value": old,
                            "new_value": params["confidence_calibration"],
                            "sample_size": count,
                            "expectancy": expectancy,
                            "profit_factor": stats["profit_factor"],
                            "win_rate": stats["win_rate"],
                            "reason": "bounded manifest-calibrated adaptation",
                        }
                    )
        state = self._model_state()
        active_parameters = state.get("active_parameters")
        if isinstance(active_parameters, dict):
            params = load_learned_parameters(self.parameters_path)
            for name in PARAMETER_BOUNDS:
                value = _finite(active_parameters.get(name))
                if value is not None and PARAMETER_BOUNDS[name][0] <= value <= PARAMETER_BOUNDS[name][1]:
                    params[name] = value
        self._write_json(self.parameters_path, params)
        if changes:
            history = Path(self.history_path)
            history.parent.mkdir(parents=True, exist_ok=True)
            with history.open("a", encoding="utf-8") as handle:
                for change in changes:
                    handle.write(json.dumps(change, sort_keys=True) + "\n")
        score = learning_score(learning_records)
        challenger_parameters = self.propose_challenger(params, sample_size=count)
        challenger_version = state.get("challenger_version") or "challenger_candidate_v1"
        state.update(
            {
                "baseline_version": BASELINE_MODEL_VERSION,
                "challenger_version": challenger_version,
                "challenger_parameters": challenger_parameters,
                "last_evaluated_at": now.astimezone(UTC).isoformat(),
                "sample_size": count,
                "manifest_evidence_count": len(manifest_evidence),
            }
        )
        self._write_model_state(state)
        return {
            **stats,
            "parameters": params,
            "changes": changes,
            "objective": score,
            "regime_scores": self.regime_scores(learning_records),
            "pillar_scores": self.pillar_scores(learning_records),
            "active_model_version": state.get("active_version", BASELINE_MODEL_VERSION),
            "challenger_model_version": challenger_version,
            "challenger_parameters": challenger_parameters,
            "promotion_occurred": False,
            "hard_boundary_parameters": sorted(FORBIDDEN_PARAMETERS),
            "manifest_evidence": manifest_evidence,
            "learning_records": learning_records,
        }

    def _completed_trades(self) -> list[dict[str, object]]:
        path = Path(self.ledger_path)
        if not path.exists():
            return []
        with sqlite3.connect(path) as con:
            con.row_factory = sqlite3.Row
            try:
                rows = con.execute(
                    """
                    SELECT broker, symbol, side, quantity, price, realized_pnl,
                           occurred_at, metadata_json
                    FROM fills
                    WHERE ABS(realized_pnl) > 0
                    ORDER BY occurred_at
                    """
                ).fetchall()
            except sqlite3.Error:
                rows = []
            pillar_rows = []
            for table in ("international_trades", "metals_trades"):
                try:
                    pillar_rows.extend(
                        con.execute(
                            f"""
                            SELECT broker, instrument AS symbol, side, quantity,
                                   COALESCE(exit_price, fill_price, proposed_entry) AS price,
                                   COALESCE(realized_pnl, 0) - COALESCE(fees_costs, 0) AS realized_pnl,
                                   closed_at AS occurred_at, metadata_json
                            FROM {table}
                            WHERE status = 'closed'
                            ORDER BY closed_at
                            """
                        ).fetchall()
                    )
                except sqlite3.Error:
                    continue
        records = [dict(row) for row in [*rows, *pillar_rows]]
        if self.experiment_baseline_start:
            baseline = self.experiment_baseline_start.replace("Z", "+00:00")
            records = [
                record for record in records
                if str(record.get("occurred_at") or "") >= baseline
            ]
        return records

    @staticmethod
    def _write_json(path: str | Path, payload: dict[str, object]) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
