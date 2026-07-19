"""Single source of truth for every autonomous action risk decision.

Callers may adapt their legacy payloads, but risk classification, medium-policy
handling, approval validation, hard boundaries and audit writes live here.
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

import yaml


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"


class MediumRiskPolicy(str, Enum):
    AUTO_APPROVE = "auto_approve"
    REQUIRE_HUMAN = "require_human"
    COOLDOWN_60MIN = "cooldown_60min"


class ProhibitedActionError(PermissionError):
    def __init__(self, action: str, reason: str, *, action_id: str = "") -> None:
        self.action = action
        self.reason = reason
        self.action_id = action_id
        super().__init__(f"prohibited autonomous action {action}: {reason}")


@dataclass
class RiskDecision:
    # First three fields preserve the established workflow-gate constructor.
    requires_confirmation: bool
    reason: str
    blocking_nodes: list[str] | None = field(default_factory=list)
    allowed: bool = False
    risk_level: RiskLevel = RiskLevel.BLOCKED
    decision: str = "blocked"
    action: str = "unknown"
    action_id: str = ""
    rollback_path: str = ""
    policy: str = ""
    approver: str = ""
    prohibited: bool = False
    denied_nodes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "action_id": self.action_id,
            "allowed": self.allowed,
            "approver": self.approver or None,
            "blocking_nodes": list(self.blocking_nodes or []),
            "decision": self.decision,
            "denied_nodes": list(self.denied_nodes or []),
            "policy": self.policy,
            "prohibited": self.prohibited,
            "reason": self.reason,
            "requires_confirmation": self.requires_confirmation,
            "risk_level": self.risk_level.value,
            "rollback_path": self.rollback_path,
        }


_FHD_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_REGISTRY_PATH = _FHD_ROOT / "config" / "risk_actions.registry.json"
_DEFAULT_BOUNDARIES_PATH = _FHD_ROOT / "config" / "autonomy_boundaries.yaml"
_REQUIRED_AUTONOMOUS_ACTIONS = frozenset(
    {
        "apply_release_to_cvm",
        "rollback_release",
        "freeze_manifest",
        "restart_service",
        "self_heal_pr_merge",
        "mod_auto_publish",
        "db_migration",
        "delete_user_data",
    }
)
_REQUIRED_ACTION_CLASSES = frozenset(
    {
        "business_db.write",
        "im.send",
        "permission.grant",
        "payment.charge",
        "bulk_import",
        "delete.batch",
    }
)
_HIGH_RISK_HANDLERS = frozenset({"shell_exec", "ssh_exec", "vibe_edit", "vibe_heal", "vibe_code"})
_MEDIUM_RISK_HANDLERS = frozenset(
    {"agent", "doc_sync", "openapi_tool", "fhd_business", "http_request", "webhook"}
)
_CODE_WRITE_TOOL_NAMES = frozenset({"patch_file", "write_file"})
_ACTION_ALIASES = {
    "rollback_version": "rollback_release",
    "rollback_to_last_tarball": "rollback_to_last_tarball",
    "restart_backend": "restart_service",
    "repair_config": "freeze_manifest",
}


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    return isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}


def _risk_level(value: Any, *, default: RiskLevel = RiskLevel.BLOCKED) -> RiskLevel:
    if isinstance(value, RiskLevel):
        return value
    raw = str(getattr(value, "value", value) or "").strip().lower()
    try:
        return RiskLevel(raw)
    except ValueError:
        return default


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


class AutonomyGuard:
    def __init__(
        self,
        *,
        registry_path: str | Path | None = None,
        boundaries_path: str | Path | None = None,
        audit_sink: Any | None = None,
    ) -> None:
        registry_override = (os.environ.get("XCAGI_RISK_REGISTRY_PATH") or "").strip()
        boundaries_override = (os.environ.get("XCAGI_AUTONOMY_BOUNDARIES_PATH") or "").strip()
        self.registry_path = Path(
            registry_path or registry_override or _DEFAULT_REGISTRY_PATH
        ).expanduser()
        self.boundaries_path = Path(
            boundaries_path or boundaries_override or _DEFAULT_BOUNDARIES_PATH
        ).expanduser()
        self._audit_sink = audit_sink
        self._registry = self._load_registry()
        self._boundaries = self._load_boundaries()
        self.medium_risk_policy = self._resolve_medium_policy()
        self._record_config_state()

    def _load_registry(self) -> dict[str, Any]:
        if not self.registry_path.is_file():
            raise FileNotFoundError(f"risk registry not found: {self.registry_path}")
        data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("risk registry root must be an object")
        actions = data.get("autonomous_actions")
        if not isinstance(actions, dict):
            raise ValueError("risk registry must include autonomous_actions")
        missing = _REQUIRED_AUTONOMOUS_ACTIONS - set(actions)
        if missing:
            raise ValueError(f"risk registry missing autonomous_actions: {sorted(missing)}")
        missing_classes = _REQUIRED_ACTION_CLASSES - set(data.get("action_classes") or {})
        if missing_classes:
            raise ValueError(f"risk registry missing action_classes: {sorted(missing_classes)}")
        tools = data.get("tools")
        if not isinstance(tools, dict) or not tools:
            raise ValueError("risk registry must include non-empty tools object")
        for name, raw in actions.items():
            if not isinstance(raw, dict):
                raise ValueError(f"autonomous action {name} must be an object")
            level = _risk_level(raw.get("risk"))
            if not str(raw.get("rollback_path") or "").strip():
                raise ValueError(f"autonomous action {name} missing rollback_path")
            if level == RiskLevel.BLOCKED and raw.get("allow_auto_execute") is not False:
                raise ValueError(f"BLOCKED action {name} must set allow_auto_execute=false")
        return data

    def _load_boundaries(self) -> dict[str, str]:
        if not self.boundaries_path.is_file():
            raise FileNotFoundError(f"autonomy boundaries not found: {self.boundaries_path}")
        raw = yaml.safe_load(self.boundaries_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("autonomy boundaries root must be an object")
        items = raw.get("prohibited_actions")
        if not isinstance(items, list) or not items:
            raise ValueError("autonomy boundaries must list prohibited_actions")
        result: dict[str, str] = {}
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("prohibited action entries must be objects")
            action = str(item.get("action") or "").strip()
            reason = str(item.get("reason") or "").strip()
            if not action or not reason:
                raise ValueError("prohibited action entries require action and reason")
            result[action] = reason
        return result

    def _resolve_medium_policy(self) -> MediumRiskPolicy:
        raw = (
            os.environ.get("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY")
            or self._registry.get("medium_risk_policy")
            or MediumRiskPolicy.REQUIRE_HUMAN.value
        )
        try:
            return MediumRiskPolicy(str(raw).strip().lower())
        except ValueError:
            return MediumRiskPolicy.REQUIRE_HUMAN

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
        return copy.deepcopy(self._registry)

    def boundaries_snapshot(self) -> dict[str, str]:
        return dict(self._boundaries)

    def autonomous_action_names(self) -> frozenset[str]:
        return frozenset((self._registry.get("autonomous_actions") or {}).keys())

    def list_code_write_tools(self) -> frozenset[str]:
        return _CODE_WRITE_TOOL_NAMES

    def get_action_spec(self, tool_id: str, operation: str) -> dict[str, Any] | None:
        tool = (self._registry.get("tools") or {}).get(str(tool_id))
        if not isinstance(tool, dict):
            return None
        spec = (tool.get("actions") or {}).get(str(operation))
        if not isinstance(spec, dict):
            return None
        result = copy.deepcopy(spec)
        action_class = str(result.get("action_class") or "").strip()
        class_spec = (self._registry.get("action_classes") or {}).get(action_class)
        if isinstance(class_spec, dict):
            for key, value in class_spec.items():
                result.setdefault(key, value)
        return result

    def requires_write_approval(self, tool_id: str, operation: str = "execute") -> bool:
        tid = str(tool_id or "").strip()
        if tid in {"import_excel_to_database", "products_bulk_import"} | set(
            _CODE_WRITE_TOOL_NAMES
        ):
            return True
        spec = self.get_action_spec(tid, operation)
        return bool((spec or {}).get("requires_write_approval"))

    def requires_write_approval_for_spec(self, spec: dict[str, Any]) -> bool:
        if spec.get("requires_write_approval") is True:
            return True
        action_class = str(spec.get("action_class") or "").strip()
        class_spec = (self._registry.get("action_classes") or {}).get(action_class)
        return isinstance(class_spec, dict) and class_spec.get("requires_write_approval") is True

    def list_write_tools(self) -> frozenset[str]:
        result = {"import_excel_to_database", "products_bulk_import", *_CODE_WRITE_TOOL_NAMES}
        for tool_id, tool in (self._registry.get("tools") or {}).items():
            if not isinstance(tool, dict):
                continue
            for operation in tool.get("actions") or {}:
                if self.requires_write_approval(str(tool_id), str(operation)):
                    result.add(str(tool_id))
                    break
        return frozenset(result)

    def aggregate_decisions(
        self,
        node_decisions: Iterable[tuple[str, RiskDecision]],
        *,
        action: str,
        action_id: str,
    ) -> RiskDecision:
        """Combine already-evaluated node decisions without recreating risk policy in callers."""

        decisions = list(node_decisions)
        blocking_nodes = [
            node_id for node_id, decision in decisions if decision.requires_confirmation
        ]
        denied_nodes = [
            node_id
            for node_id, decision in decisions
            if not decision.requires_confirmation and not decision.allowed
        ]
        rank = {
            RiskLevel.LOW: 0,
            RiskLevel.MEDIUM: 1,
            RiskLevel.HIGH: 2,
            RiskLevel.BLOCKED: 3,
        }
        aggregate = max(
            (decision.risk_level for _, decision in decisions),
            key=lambda item: rank[item],
            default=RiskLevel.LOW,
        )
        if denied_nodes:
            reason = "plan contains actions denied by autonomy_guard"
        elif blocking_nodes:
            reason = "plan requires human risk approval"
        else:
            reason = "all plan actions approved by autonomy_guard"
        return RiskDecision(
            requires_confirmation=bool(blocking_nodes),
            reason=reason,
            blocking_nodes=blocking_nodes,
            allowed=not blocking_nodes and not denied_nodes,
            risk_level=aggregate,
            decision=(
                "blocked" if denied_nodes else "require_human" if blocking_nodes else "allow"
            ),
            action=action,
            action_id=action_id,
            denied_nodes=denied_nodes,
        )

    def assess_employee_risk(
        self,
        manifest: dict[str, Any],
        handlers: Iterable[str],
        payload: dict[str, Any] | None = None,
    ) -> tuple[RiskLevel, str]:
        declared = ""
        if isinstance(manifest, dict):
            ev2 = manifest.get("employee_config_v2")
            if isinstance(ev2, dict):
                declared = str(ev2.get("risk_level") or "").strip().lower()
        handler_list = [str(item or "").strip() for item in (handlers or [])]
        inferred = (
            RiskLevel.HIGH
            if any(item in _HIGH_RISK_HANDLERS for item in handler_list)
            else RiskLevel.MEDIUM
            if any(item in _MEDIUM_RISK_HANDLERS for item in handler_list)
            else RiskLevel.LOW
        )
        declared_level = _risk_level(declared, default=RiskLevel.LOW)
        declared_valid = declared in {item.value for item in RiskLevel}
        order = {
            RiskLevel.LOW: 0,
            RiskLevel.MEDIUM: 1,
            RiskLevel.HIGH: 2,
            RiskLevel.BLOCKED: 3,
        }
        level = (
            declared_level
            if declared_valid and order[declared_level] >= order[inferred]
            else inferred
        )
        reason = (
            f"manifest declared risk_level={declared_level.value}"
            if declared_valid and level == declared_level
            else f"handlers inferred risk_level={inferred.value}"
        )
        tool_name = str((payload or {}).get("tool") or "").strip()
        if tool_name in _CODE_WRITE_TOOL_NAMES:
            return RiskLevel.HIGH, f"code-write tool {tool_name} forces high risk"
        return level, reason

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
        action_name = _ACTION_ALIASES.get(action_name, action_name)
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

        autonomous_spec = (self._registry.get("autonomous_actions") or {}).get(action_name)
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

        risk = _risk_level((spec or {}).get("risk"), default=explicit_level or RiskLevel.BLOCKED)
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
        allow_auto = bool(
            (spec or {}).get("allow_auto_execute", risk in {RiskLevel.LOW, RiskLevel.MEDIUM})
        )
        approved, approver = self._approval_evidence(ctx, risk)

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

        if risk == RiskLevel.LOW and allow_auto:
            return self._decision(
                action=action_name,
                action_id=resolved_action_id,
                risk=risk,
                decision="allow",
                allowed=True,
                requires_confirmation=False,
                reason="LOW risk action is registered for automatic execution",
                rollback_path=rollback_path,
                source=source,
                context=ctx,
            )

        if risk == RiskLevel.MEDIUM and allow_auto:
            if self.medium_risk_policy == MediumRiskPolicy.AUTO_APPROVE:
                return self._decision(
                    action=action_name,
                    action_id=resolved_action_id,
                    risk=risk,
                    decision="auto_approve",
                    allowed=True,
                    requires_confirmation=False,
                    reason="medium_risk_policy=auto_approve",
                    rollback_path=rollback_path,
                    source=source,
                    context=ctx,
                )
            if self.medium_risk_policy == MediumRiskPolicy.COOLDOWN_60MIN:
                if not self._cooldown_active(action_name):
                    return self._decision(
                        action=action_name,
                        action_id=resolved_action_id,
                        risk=risk,
                        decision="auto_approve",
                        allowed=True,
                        requires_confirmation=False,
                        reason="medium_risk_policy=cooldown_60min; first action in window",
                        rollback_path=rollback_path,
                        source=source,
                        context=ctx,
                    )
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
            explicit = _risk_level(raw_level) if raw_level is not None else None
            return name or "unknown", explicit, tool_id, operation, metadata
        action_type = getattr(action, "type", None)
        name = _enum_value(action_type) or str(getattr(action, "action", "") or "").strip()
        raw_level = getattr(action, "risk", None)
        explicit = _risk_level(raw_level) if raw_level is not None else None
        metadata = {
            "idempotency_key": str(getattr(action, "idempotency_key", "") or ""),
            "params": copy.deepcopy(getattr(action, "params", {}) or {}),
        }
        return name or "unknown", explicit, "", "", metadata

    def _resolve_spec(self, action: str, tool_id: str, operation: str) -> dict[str, Any] | None:
        raw = (self._registry.get("autonomous_actions") or {}).get(action)
        if isinstance(raw, dict):
            return raw
        if tool_id and operation:
            return self.get_action_spec(tool_id, operation)
        if "." in action:
            candidate_tool, candidate_operation = action.split(".", 1)
            return self.get_action_spec(candidate_tool, candidate_operation)
        return None

    def _rollback_path(self, action: str) -> str:
        spec = (self._registry.get("autonomous_actions") or {}).get(action)
        return str((spec or {}).get("rollback_path") or "not_applicable")

    def _approval_evidence(self, context: dict[str, Any], risk: RiskLevel) -> tuple[bool, str]:
        approver = str(context.get("approved_by") or context.get("approver") or "").strip()
        if _truthy(context.get("human_approved")) and approver:
            return True, approver
        if risk == RiskLevel.MEDIUM and _truthy(context.get("allow_medium_risk")):
            return True, approver or "legacy_explicit_runtime_approval"
        if risk == RiskLevel.HIGH and _truthy(context.get("workflow_auto_approve_high_risk")):
            return True, approver or "explicit_workflow_session_override"
        if risk == RiskLevel.HIGH and _truthy(context.get("allow_high_risk_real_run")):
            configured = (
                os.environ.get("FHD_RISK_HIGH_GATE_TOKEN")
                or os.environ.get("MODSTORE_RISK_HIGH_GATE_TOKEN")
                or ""
            ).strip()
            supplied = str(context.get("high_risk_gate_token") or "").strip()
            if not configured or (supplied and supplied == configured):
                return True, approver or "legacy_high_risk_gate"
        return False, ""

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
