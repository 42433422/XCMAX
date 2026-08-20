"""Validated registry and boundary catalog used only by the autonomy guard SSOT."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Iterable

import yaml

from app.domain.autonomy.risk_types import MediumRiskPolicy, RiskLevel, parse_risk_level

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


class RiskPolicyCatalog:
    """Load and validate policy data; evaluation remains in ``AutonomyGuard``."""

    def __init__(
        self,
        *,
        registry_path: str | Path | None = None,
        boundaries_path: str | Path | None = None,
    ) -> None:
        registry_override = (os.environ.get("XCAGI_RISK_REGISTRY_PATH") or "").strip()
        boundaries_override = (os.environ.get("XCAGI_AUTONOMY_BOUNDARIES_PATH") or "").strip()
        self.registry_path = Path(
            registry_path or registry_override or _DEFAULT_REGISTRY_PATH
        ).expanduser()
        self.boundaries_path = Path(
            boundaries_path or boundaries_override or _DEFAULT_BOUNDARIES_PATH
        ).expanduser()
        self.registry = self._load_registry()
        self.boundaries, self.veto_boundaries = self._load_boundaries()
        self.medium_risk_policy = self._resolve_medium_policy()

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
            level = parse_risk_level(raw.get("risk"))
            if not str(raw.get("rollback_path") or "").strip():
                raise ValueError(f"autonomous action {name} missing rollback_path")
            if level == RiskLevel.BLOCKED and raw.get("allow_auto_execute") is not False:
                raise ValueError(f"BLOCKED action {name} must set allow_auto_execute=false")
        return data

    @staticmethod
    def _parse_boundary_items(
        raw: dict[str, Any], field: str, *, allow_empty: bool = False
    ) -> dict[str, str]:
        items = raw.get(field)
        if not isinstance(items, list) or (not items and not allow_empty):
            raise ValueError(f"autonomy boundaries must list {field}")
        result: dict[str, str] = {}
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(f"{field} entries must be objects")
            action = str(item.get("action") or "").strip()
            reason = str(item.get("reason") or "").strip()
            if not action or not reason:
                raise ValueError(f"{field} entries require action and reason")
            if action in result:
                raise ValueError(f"duplicate {field} action: {action}")
            result[action] = reason
        return result

    def _load_boundaries(self) -> tuple[dict[str, str], dict[str, str]]:
        if not self.boundaries_path.is_file():
            raise FileNotFoundError(f"autonomy boundaries not found: {self.boundaries_path}")
        raw = yaml.safe_load(self.boundaries_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("autonomy boundaries root must be an object")
        prohibited = self._parse_boundary_items(raw, "prohibited_actions")
        requires_veto = self._parse_boundary_items(raw, "requires_veto", allow_empty=True)
        overlap = set(prohibited) & set(requires_veto)
        if overlap:
            raise ValueError(
                f"actions cannot be both prohibited and requires_veto: {sorted(overlap)}"
            )
        registered = set(self.registry.get("autonomous_actions") or {})
        unknown = (set(prohibited) | set(requires_veto)) - registered
        if unknown:
            raise ValueError(f"autonomy boundaries contain unregistered actions: {sorted(unknown)}")
        return prohibited, requires_veto

    def _resolve_medium_policy(self) -> MediumRiskPolicy:
        raw = (
            os.environ.get("XCAGI_AUTONOMY_MEDIUM_RISK_POLICY")
            or self.registry.get("medium_risk_policy")
            or MediumRiskPolicy.REQUIRE_HUMAN.value
        )
        try:
            return MediumRiskPolicy(str(raw).strip().lower())
        except ValueError:
            return MediumRiskPolicy.REQUIRE_HUMAN

    def canonical_action(self, action: str) -> str:
        return _ACTION_ALIASES.get(action, action)

    def registry_snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.registry)

    def boundaries_snapshot(self) -> dict[str, str]:
        return dict(self.boundaries)

    def veto_boundaries_snapshot(self) -> dict[str, str]:
        return dict(self.veto_boundaries)

    def veto_reason(self, action: str) -> str | None:
        return self.veto_boundaries.get(action)

    def autonomous_action_names(self) -> frozenset[str]:
        return frozenset((self.registry.get("autonomous_actions") or {}).keys())

    def autonomous_action_spec(self, action: str) -> dict[str, Any] | None:
        raw = (self.registry.get("autonomous_actions") or {}).get(action)
        return raw if isinstance(raw, dict) else None

    def list_code_write_tools(self) -> frozenset[str]:
        return _CODE_WRITE_TOOL_NAMES

    def get_action_spec(self, tool_id: str, operation: str) -> dict[str, Any] | None:
        tool = (self.registry.get("tools") or {}).get(str(tool_id))
        if not isinstance(tool, dict):
            return None
        spec = (tool.get("actions") or {}).get(str(operation))
        if not isinstance(spec, dict):
            return None
        result = copy.deepcopy(spec)
        action_class = str(result.get("action_class") or "").strip()
        class_spec = (self.registry.get("action_classes") or {}).get(action_class)
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
        class_spec = (self.registry.get("action_classes") or {}).get(action_class)
        return isinstance(class_spec, dict) and class_spec.get("requires_write_approval") is True

    def list_write_tools(self) -> frozenset[str]:
        result = {"import_excel_to_database", "products_bulk_import", *_CODE_WRITE_TOOL_NAMES}
        for tool_id, tool in (self.registry.get("tools") or {}).items():
            if not isinstance(tool, dict):
                continue
            for operation in tool.get("actions") or {}:
                if self.requires_write_approval(str(tool_id), str(operation)):
                    result.add(str(tool_id))
                    break
        return frozenset(result)

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
        request = payload or {}
        work_contract = (
            request.get("work_contract") if isinstance(request.get("work_contract"), dict) else {}
        )
        truthy = {"1", "true", "yes", "on"}
        required_read_only_flags = (
            "burn_in",
            "burn_in_read_only",
            "suppress_employee_im",
            "suppress_handoff",
            "suppress_change_requests",
            "suppress_lifecycle_events",
        )
        if not isinstance(work_contract, dict):
            work_contract = {}
        read_only_burn_in = (
            str(work_contract.get("risk_level") or "").strip().lower()
            in {"low", "read_only", "readonly"}
            and all(
                value is True or str(value or "").strip().lower() in truthy
                for value in (request.get(name) for name in required_read_only_flags)
            )
            and set(handler_list).issubset({"agent", "llm_md", "echo", "specialized"})
            and "agent" in handler_list
        )
        inferred = (
            RiskLevel.LOW
            if read_only_burn_in
            else RiskLevel.HIGH
            if any(item in _HIGH_RISK_HANDLERS for item in handler_list)
            else RiskLevel.MEDIUM
            if any(item in _MEDIUM_RISK_HANDLERS for item in handler_list)
            else RiskLevel.LOW
        )
        declared_level = parse_risk_level(declared, default=RiskLevel.LOW)
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
            "strict read-only burn-in contract"
            if read_only_burn_in and level == RiskLevel.LOW
            else f"manifest declared risk_level={declared_level.value}"
            if declared_valid and level == declared_level
            else f"handlers inferred risk_level={inferred.value}"
        )
        tool_name = str((payload or {}).get("tool") or "").strip()
        if tool_name in _CODE_WRITE_TOOL_NAMES:
            return RiskLevel.HIGH, f"code-write tool {tool_name} forces high risk"
        return level, reason

    def resolve_spec(self, action: str, tool_id: str, operation: str) -> dict[str, Any] | None:
        raw = self.autonomous_action_spec(action)
        if raw is not None:
            return raw
        if tool_id and operation:
            return self.get_action_spec(tool_id, operation)
        if "." in action:
            candidate_tool, candidate_operation = action.split(".", 1)
            return self.get_action_spec(candidate_tool, candidate_operation)
        return None

    def rollback_path(self, action: str) -> str:
        spec = self.autonomous_action_spec(action)
        return str((spec or {}).get("rollback_path") or "not_applicable")


__all__ = ["RiskPolicyCatalog"]
