"""Single source of truth for every autonomous action risk decision.

Callers may adapt their legacy payloads, but risk classification, medium-policy
handling, approval validation, hard boundaries and audit writes live here.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from app.domain.autonomy.approval_policy import approval_evidence, human_approval_evidence
from app.domain.autonomy.risk_policy import RiskPolicyCatalog
from app.domain.autonomy.risk_types import (
    MediumRiskPolicy,
    ProhibitedActionError,
    RiskDecision,
    RiskLevel,
    aggregate_risk_decisions,
    enum_value,
    parse_risk_level,
)

UTC = timezone.utc  # noqa: UP017 - MODstore imports this module on Python 3.10


class AutonomyGuard:
    def __init__(
        self,
        *,
        registry_path: str | Path | None = None,
        boundaries_path: str | Path | None = None,
        audit_sink: Any | None = None,
    ) -> None:
        self._policy = RiskPolicyCatalog(
            registry_path=registry_path,
            boundaries_path=boundaries_path,
        )
        self.registry_path = self._policy.registry_path
        self.boundaries_path = self._policy.boundaries_path
        # Retain private aliases for compatibility with diagnostic callers.
        self._registry = self._policy.registry
        self._boundaries = self._policy.boundaries
        self._veto_boundaries = self._policy.veto_boundaries
        self.medium_risk_policy = self._policy.medium_risk_policy
        self._audit_sink = audit_sink
        self._record_config_state()

    def _audit(self, record: dict[str, Any]) -> dict[str, Any]:
        if self._audit_sink is not None:
            result = self._audit_sink(record)
            return result if isinstance(result, dict) else record
        from app.domain.autonomy.audit_log import append_autonomy_audit

        return append_autonomy_audit(record)

    def _record_config_state(self) -> None:
        current = self.medium_risk_policy.value
        previous = None
        if self._audit_sink is None:
            from app.domain.autonomy.audit_log import latest_action_event

            previous = latest_action_event("__configuration__")
        previous_policy = str((previous or {}).get("policy") or "")
        if previous_policy == current:
            return
        self._audit(
            {
                "action_id": f"config:{uuid.uuid4().hex}",
                "action": "__configuration__",
                "risk_level": RiskLevel.LOW.name,
                "decision": "config_changed" if previous else "config_loaded",
                "outcome": "medium_risk_policy_active",
                "event_type": "config",
                "policy": current,
                "source": "autonomy_guard.startup",
                "metadata": {
                    "previous_medium_risk_policy": previous_policy or None,
                    "registry_path": str(self.registry_path),
                    "boundaries_path": str(self.boundaries_path),
                },
            }
        )

    def registry_snapshot(self) -> dict[str, Any]:
        return self._policy.registry_snapshot()

    def boundaries_snapshot(self) -> dict[str, str]:
        return self._policy.boundaries_snapshot()

    def veto_boundaries_snapshot(self) -> dict[str, str]:
        return self._policy.veto_boundaries_snapshot()

    def autonomous_action_names(self) -> frozenset[str]:
        return self._policy.autonomous_action_names()

    def list_code_write_tools(self) -> frozenset[str]:
        return self._policy.list_code_write_tools()

    def get_action_spec(self, tool_id: str, operation: str) -> dict[str, Any] | None:
        return self._policy.get_action_spec(tool_id, operation)

    def requires_write_approval(self, tool_id: str, operation: str = "execute") -> bool:
        return self._policy.requires_write_approval(tool_id, operation)

    def requires_write_approval_for_spec(self, spec: dict[str, Any]) -> bool:
        return self._policy.requires_write_approval_for_spec(spec)

    def list_write_tools(self) -> frozenset[str]:
        return self._policy.list_write_tools()

    def aggregate_decisions(
        self,
        node_decisions: Iterable[tuple[str, RiskDecision]],
        *,
        action: str,
        action_id: str,
    ) -> RiskDecision:
        return aggregate_risk_decisions(
            node_decisions,
            action=action,
            action_id=action_id,
        )

    def assess_employee_risk(
        self,
        manifest: dict[str, Any],
        handlers: Iterable[str],
        payload: dict[str, Any] | None = None,
    ) -> tuple[RiskLevel, str]:
        return self._policy.assess_employee_risk(manifest, handlers, payload)

    def evaluate(
        self,
        action: Any,
        context: dict[str, Any] | None = None,
        *,
        action_id: str | None = None,
        source: str = "runtime",
    ) -> RiskDecision:
        ctx = dict(context or {})
        action_name, explicit_level, tool_id, operation, metadata = self._normalize_action(action)
        action_name = self._policy.canonical_action(action_name)
        resolved_action_id = str(
            action_id
            or metadata.get("action_id")
            or metadata.get("idempotency_key")
            or uuid.uuid4().hex
        )

        prohibited_reason = self._boundaries.get(action_name)
        if prohibited_reason:
            self._audit_decision(
                action=action_name,
                action_id=resolved_action_id,
                risk=RiskLevel.BLOCKED,
                decision="prohibited",
                outcome="exception_raised",
                reason=prohibited_reason,
                rollback_path=self._rollback_path(action_name),
                source=source,
                context=ctx,
            )
            raise ProhibitedActionError(
                action_name, prohibited_reason, action_id=resolved_action_id
            )

        autonomous_spec = self._policy.autonomous_action_spec(action_name)
        spec = self._resolve_spec(action_name, tool_id, operation)
        if spec is None and explicit_level is None:
            return self._decision(
                action=action_name,
                action_id=resolved_action_id,
                risk=RiskLevel.BLOCKED,
                decision="blocked",
                allowed=False,
                requires_confirmation=False,
                reason="unregistered autonomous action; fail-closed",
                rollback_path="not_registered",
                source=source,
                context=ctx,
            )

        risk = parse_risk_level(
            (spec or {}).get("risk"), default=explicit_level or RiskLevel.BLOCKED
        )
        if explicit_level is not None and not isinstance(autonomous_spec, dict):
            rank = {
                RiskLevel.LOW: 0,
                RiskLevel.MEDIUM: 1,
                RiskLevel.HIGH: 2,
                RiskLevel.BLOCKED: 3,
            }
            if rank[explicit_level] > rank[risk]:
                risk = explicit_level
        rollback_path = str(
            (spec or {}).get("rollback_path") or metadata.get("rollback_path") or ""
        )
        default_auto = (
            risk in {RiskLevel.LOW, RiskLevel.MEDIUM}
            if isinstance(autonomous_spec, dict)
            else risk == RiskLevel.LOW
        )
        allow_auto = bool((spec or {}).get("allow_auto_execute", default_auto))
        veto_reason = self._veto_boundaries.get(action_name)
        if veto_reason:
            approved, approver = human_approval_evidence(ctx)
            if approved:
                return self._decision(
                    action=action_name,
                    action_id=resolved_action_id,
                    risk=risk,
                    decision="approved",
                    allowed=True,
                    requires_confirmation=False,
                    reason=f"requires_veto accepted by human ({approver}): {veto_reason}",
                    rollback_path=rollback_path,
                    source=source,
                    context=ctx,
                    approver=approver,
                )
            return self._decision(
                action=action_name,
                action_id=resolved_action_id,
                risk=risk,
                decision="require_human",
                allowed=False,
                requires_confirmation=True,
                reason=f"requires_veto boundary: {veto_reason}",
                rollback_path=rollback_path,
                source=source,
                context=ctx,
            )
        if risk == RiskLevel.BLOCKED:
            return self._decision(
                action=action_name,
                action_id=resolved_action_id,
                risk=risk,
                decision="blocked",
                allowed=False,
                requires_confirmation=False,
                reason="BLOCKED actions can never execute autonomously",
                rollback_path=rollback_path,
                source=source,
                context=ctx,
            )

        automatic_reason = ""
        automatic_decision = "auto_approve"
        if risk == RiskLevel.LOW and allow_auto:
            automatic_decision = "allow"
            automatic_reason = "LOW risk action is registered for automatic execution"
        elif risk == RiskLevel.MEDIUM and allow_auto:
            if self.medium_risk_policy == MediumRiskPolicy.AUTO_APPROVE:
                automatic_reason = "medium_risk_policy=auto_approve"
            elif self.medium_risk_policy == MediumRiskPolicy.COOLDOWN_60MIN:
                if self._cooldown_active(action_name):
                    return self._decision(
                        action=action_name,
                        action_id=resolved_action_id,
                        risk=risk,
                        decision="cooldown",
                        allowed=False,
                        requires_confirmation=True,
                        reason="medium_risk_policy=cooldown_60min; repeat requires human approval",
                        rollback_path=rollback_path,
                        source=source,
                        context=ctx,
                    )
                automatic_reason = "medium_risk_policy=cooldown_60min; first action in window"
        elif risk == RiskLevel.HIGH and allow_auto:
            automatic_reason = "HIGH risk action is registered for automatic execution"
        if automatic_reason:
            return self._decision(
                action=action_name,
                action_id=resolved_action_id,
                risk=risk,
                decision=automatic_decision,
                allowed=True,
                requires_confirmation=False,
                reason=automatic_reason,
                rollback_path=rollback_path,
                source=source,
                context=ctx,
            )

        # Compatibility approval evidence only applies when the registry/policy
        # did not already authorize automatic execution. Registered automatic
        # actions must remain observable as auto decisions, never as a forged
        # or synthetic human approval.
        approved, approver = approval_evidence(ctx, risk)
        if approved:
            return self._decision(
                action=action_name,
                action_id=resolved_action_id,
                risk=risk,
                decision="approved",
                allowed=True,
                requires_confirmation=False,
                reason=f"risk accepted by human approval ({approver})",
                rollback_path=rollback_path,
                source=source,
                context=ctx,
                approver=approver,
            )

        return self._decision(
            action=action_name,
            action_id=resolved_action_id,
            risk=risk,
            decision="require_human",
            allowed=False,
            requires_confirmation=True,
            reason=(
                f"medium_risk_policy={self.medium_risk_policy.value}"
                if risk == RiskLevel.MEDIUM
                else f"{risk.name} risk requires human approval"
            ),
            rollback_path=rollback_path,
            source=source,
            context=ctx,
        )

    def _normalize_action(
        self, action: Any
    ) -> tuple[str, RiskLevel | None, str, str, dict[str, Any]]:
        metadata: dict[str, Any] = {}
        if isinstance(action, str):
            return action.strip(), None, "", "", metadata
        if isinstance(action, dict):
            metadata = dict(action)
            name = str(action.get("action") or action.get("name") or "").strip()
            tool_id = str(action.get("tool_id") or "").strip()
            operation = str(action.get("operation") or action.get("tool_action") or "").strip()
            if not name and tool_id:
                name = f"{tool_id}.{operation or 'execute'}"
            raw_level = action.get("risk_level", action.get("risk"))
            explicit = parse_risk_level(raw_level) if raw_level is not None else None
            return name or "unknown", explicit, tool_id, operation, metadata
        action_type = getattr(action, "type", None)
        name = enum_value(action_type) or str(getattr(action, "action", "") or "").strip()
        raw_level = getattr(action, "risk", None)
        explicit = parse_risk_level(raw_level) if raw_level is not None else None
        metadata = {
            "idempotency_key": str(getattr(action, "idempotency_key", "") or ""),
            "params": copy.deepcopy(getattr(action, "params", {}) or {}),
        }
        return name or "unknown", explicit, "", "", metadata

    def _resolve_spec(self, action: str, tool_id: str, operation: str) -> dict[str, Any] | None:
        return self._policy.resolve_spec(action, tool_id, operation)

    def _rollback_path(self, action: str) -> str:
        return self._policy.rollback_path(action)

    def _cooldown_active(self, action: str) -> bool:
        if self._audit_sink is not None:
            return False
        from app.domain.autonomy.audit_log import latest_action_event

        previous = latest_action_event(action, decisions={"allow", "auto_approve", "approved"})
        if not previous:
            return False
        try:
            ts = datetime.fromisoformat(str(previous.get("timestamp") or ""))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
        except ValueError:
            return False
        return datetime.now(UTC) - ts < timedelta(minutes=60)

    def _decision(
        self,
        *,
        action: str,
        action_id: str,
        risk: RiskLevel,
        decision: str,
        allowed: bool,
        requires_confirmation: bool,
        reason: str,
        rollback_path: str,
        source: str,
        context: dict[str, Any],
        approver: str = "",
    ) -> RiskDecision:
        self._audit_decision(
            action=action,
            action_id=action_id,
            risk=risk,
            decision=decision,
            outcome="allowed" if allowed else "not_executed",
            reason=reason,
            rollback_path=rollback_path,
            source=source,
            context=context,
            approver=approver,
        )
        return RiskDecision(
            requires_confirmation=requires_confirmation,
            reason=reason,
            blocking_nodes=[],
            allowed=allowed,
            risk_level=risk,
            decision=decision,
            action=action,
            action_id=action_id,
            rollback_path=rollback_path,
            policy=self.medium_risk_policy.value if risk == RiskLevel.MEDIUM else "",
            approver=approver,
            prohibited=decision == "prohibited",
        )

    def _audit_decision(
        self,
        *,
        action: str,
        action_id: str,
        risk: RiskLevel,
        decision: str,
        outcome: str,
        reason: str,
        rollback_path: str,
        source: str,
        context: dict[str, Any],
        approver: str = "",
    ) -> None:
        safe_metadata = {
            "reason": reason,
            "approval_id": str(context.get("approval_id") or "") or None,
            "trigger": str(context.get("trigger") or "") or None,
        }
        self._audit(
            {
                "action_id": action_id,
                "action": action,
                "risk_level": risk.name,
                "decision": decision,
                "approver": approver or None,
                "timestamp": datetime.now(UTC).isoformat(),
                "outcome": outcome,
                "event_type": "decision",
                "policy": self.medium_risk_policy.value if risk == RiskLevel.MEDIUM else None,
                "rollback_path": rollback_path,
                "source": source,
                "metadata": safe_metadata,
            }
        )


_GUARD: AutonomyGuard | None = None


def get_autonomy_guard() -> AutonomyGuard:
    global _GUARD
    if _GUARD is None:
        _GUARD = AutonomyGuard()
    return _GUARD


def reload_autonomy_guard() -> AutonomyGuard:
    global _GUARD
    _GUARD = AutonomyGuard()
    return _GUARD


def evaluate_risk(
    action: Any,
    context: dict[str, Any] | None = None,
    *,
    action_id: str | None = None,
    source: str = "runtime",
) -> RiskDecision:
    return get_autonomy_guard().evaluate(action, context, action_id=action_id, source=source)


__all__ = [
    "AutonomyGuard",
    "MediumRiskPolicy",
    "ProhibitedActionError",
    "RiskDecision",
    "RiskLevel",
    "evaluate_risk",
    "get_autonomy_guard",
    "reload_autonomy_guard",
]
