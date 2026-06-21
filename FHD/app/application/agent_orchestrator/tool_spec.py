from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal

# Data tables are externalised into the ``tool_spec_data`` package. They are
# re-exported here under their original names so downstream code (and tests)
# can keep importing them from ``tool_spec`` unchanged.
from app.application.agent_orchestrator.tool_spec_data import (  # noqa: F401
    _BUSINESS_ENTITIES,
    _DEFAULT_OUTPUT_SCHEMA,
    _SPECIAL_INPUT_SCHEMAS,
    _SPECIAL_OUTPUT_SCHEMAS,
    _SPECIAL_TEST_FIXTURES,
)
from app.application.agent_orchestrator.tool_spec_data.constants import (
    AIOPEN_DEFAULT_RISK,
    AIOPEN_LOW_RISK,
    AIOPEN_LOW_RISK_ACTIONS,
    DATASET_RAG_READ_ACTIONS,
    DATASET_RAG_READ_PERMISSION,
    DATASET_RAG_WRITE_PERMISSION,
    DEFAULT_COST,
    DEFAULT_LOW_RISK_COST,
    DEFAULT_RETRY,
    DEFAULT_TIMEOUT_SECONDS,
    PERMISSION_BARE_PREFIX_TOOLS,
    PERMISSION_OVERRIDES,
    TOOL_ACTION_COST_OVERRIDES,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

RiskLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class ToolActionSpecV2:
    tool_id: str
    action: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_OUTPUT_SCHEMA))
    risk: RiskLevel = "medium"
    permission: str = ""
    cost_units: int = 0
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    retry: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_RETRY))
    idempotent: bool = False
    required_params: list[str] = field(default_factory=list)
    availability: str = "shared"
    test_fixtures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "action": self.action,
            "description": self.description,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "risk": self.risk,
            "permission": self.permission,
            "cost_units": self.cost_units,
            "timeout_seconds": self.timeout_seconds,
            "retry": self.retry,
            "idempotent": self.idempotent,
            "required_params": self.required_params,
            "availability": self.availability,
            "test_fixtures": self.test_fixtures,
        }


@dataclass(frozen=True)
class ToolValidationResult:
    ok: bool
    tool_id: str
    action: str
    spec: ToolActionSpecV2 | None = None
    error_code: str = ""
    message: str = ""


def _normalize_tool_action(action: str, params: dict[str, Any] | None = None) -> str:
    from app.services.tools_execution.registry import _normalize_action

    return _normalize_action(action, params)


def _risk_value(value: Any) -> RiskLevel:
    text = str(value or "medium").strip().lower()
    if text in {"low", "medium", "high"}:
        return text  # type: ignore[return-value]
    return "medium"


def _schema_from_required(required_params: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": list(required_params),
        "properties": {key: {} for key in required_params},
    }


def _sample_value_for_property(key: str, prop: dict[str, Any]) -> Any:
    enum_values = prop.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return enum_values[0]

    expected_type = str(prop.get("type") or "").strip()
    if key == "success":
        return True
    if key in {"ids", "records", "artifacts", "data"} and expected_type == "array":
        return [{"sample": True}]
    if key == "payload":
        return {"sample": True}
    if key in {"created_customers", "created_products", "imported_count"}:
        return 1
    if key == "download_url":
        return "/api/sample/download"
    if key == "file_name":
        return "sample.docx"
    if expected_type == "object":
        return {"sample": True}
    if expected_type == "array":
        return [{"sample": True}]
    if expected_type == "integer":
        return 1
    if expected_type == "number":
        return 1.0
    if expected_type == "boolean":
        return True
    return f"sample_{key}"


def _sample_payload_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    payload: dict[str, Any] = {}
    for key, prop in properties.items():
        payload[str(key)] = _sample_value_for_property(
            str(key), prop if isinstance(prop, dict) else {}
        )
    for key in required:
        normalized_key = str(key)
        if normalized_key not in payload:
            payload[normalized_key] = f"sample_{normalized_key}"
    return payload


def _default_fixture(
    tool_id: str,
    action: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        {
            "name": f"{tool_id}.{action}.contract",
            "input": _sample_payload_from_schema(input_schema),
            "output": _sample_payload_from_schema(output_schema),
        }
    ]


def _special_permission(tool_id: str, action: str) -> str:
    if tool_id in PERMISSION_BARE_PREFIX_TOOLS:
        return f"{tool_id}.{action}"
    if tool_id == "dataset_rag":
        if action in DATASET_RAG_READ_ACTIONS:
            return DATASET_RAG_READ_PERMISSION
        return DATASET_RAG_WRITE_PERMISSION
    fixed = PERMISSION_OVERRIDES.get(tool_id)
    if fixed is not None:
        return fixed
    return f"tool.{tool_id}.{action}"


def _cost_units(tool_id: str, action: str, risk: RiskLevel) -> int:
    override = TOOL_ACTION_COST_OVERRIDES.get((tool_id, action))
    if override is not None:
        return override
    if risk == "low":
        return DEFAULT_LOW_RISK_COST
    return DEFAULT_COST


def _aiopen_tool_risk(action: str) -> tuple[RiskLevel, bool]:
    if action in AIOPEN_LOW_RISK_ACTIONS:
        return AIOPEN_LOW_RISK, True
    return AIOPEN_DEFAULT_RISK, False


def _add_aiopen_tool_specs(specs: dict[tuple[str, str], ToolActionSpecV2]) -> None:
    try:
        from app.application.aiopen.service import TOOL_DEFINITIONS
    except RECOVERABLE_ERRORS:
        return

    output_schema = {
        "type": "object",
        "required": ["success"],
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "code": {"type": "string"},
            "data": {},
            "routes": {"type": "array"},
            "sessions": {"type": "array"},
            "status_code": {"type": "integer"},
        },
    }
    for tool in TOOL_DEFINITIONS:
        if not isinstance(tool, dict):
            continue
        action = _normalize_tool_action(str(tool.get("name") or ""))
        if not action:
            continue
        input_schema = tool.get("inputSchema")
        if not isinstance(input_schema, dict):
            input_schema = {"type": "object", "properties": {}}
        required = (
            input_schema.get("required") if isinstance(input_schema.get("required"), list) else []
        )
        required_params = [str(item) for item in required]
        risk, idempotent = _aiopen_tool_risk(action)
        fixture = _default_fixture("aiopen", action, input_schema, output_schema)
        if action == "api_catalog":
            fixture = [
                {
                    "name": "list_aiopen_catalog",
                    "input": {},
                    "output": {
                        "success": True,
                        "routes": [{"path": "/api/ai/chat", "enabled": True}],
                    },
                }
            ]
        elif action == "chat":
            fixture = [
                {
                    "name": "invoke_aiopen_chat",
                    "input": {"message": "你好"},
                    "output": {"success": True, "data": {"reply": "你好"}},
                }
            ]
        specs[("aiopen", action)] = ToolActionSpecV2(
            tool_id="aiopen",
            action=action,
            description=str(tool.get("description") or f"AIOPEN {action}"),
            input_schema=deepcopy(input_schema),
            output_schema=deepcopy(output_schema),
            risk=risk,
            permission=_special_permission("aiopen", action),
            cost_units=_cost_units("aiopen", action, risk),
            timeout_seconds=30,
            retry=dict(DEFAULT_RETRY),
            idempotent=idempotent,
            required_params=required_params,
            availability="aiopen",
            test_fixtures=deepcopy(fixture),
        )


def build_tool_specs_v2() -> dict[tuple[str, str], ToolActionSpecV2]:
    from app.services.tools_execution.registry import get_workflow_tool_registry

    registry = get_workflow_tool_registry()
    specs: dict[tuple[str, str], ToolActionSpecV2] = {}
    for tool_id, tool_meta in registry.items():
        actions = tool_meta.get("actions") if isinstance(tool_meta, dict) else None
        if not isinstance(actions, dict):
            continue
        tool_description = str(tool_meta.get("description") or "")
        for action, action_meta in actions.items():
            if not isinstance(action_meta, dict):
                continue
            normalized_action = _normalize_tool_action(str(action or "view"))
            required = action_meta.get("required_params")
            required_params = [str(x) for x in required] if isinstance(required, list) else []
            risk = _risk_value(action_meta.get("risk"))
            input_schema = _SPECIAL_INPUT_SCHEMAS.get(
                (str(tool_id), normalized_action),
                _schema_from_required(required_params),
            )
            output_schema = _SPECIAL_OUTPUT_SCHEMAS.get(
                (str(tool_id), normalized_action),
                _DEFAULT_OUTPUT_SCHEMA,
            )
            test_fixtures = _SPECIAL_TEST_FIXTURES.get(
                (str(tool_id), normalized_action),
                _default_fixture(str(tool_id), normalized_action, input_schema, output_schema),
            )
            spec = ToolActionSpecV2(
                tool_id=str(tool_id),
                action=normalized_action,
                description=tool_description,
                input_schema=deepcopy(input_schema),
                output_schema=deepcopy(output_schema),
                risk=risk,
                permission=_special_permission(str(tool_id), normalized_action),
                cost_units=_cost_units(str(tool_id), normalized_action, risk),
                timeout_seconds=int(
                    action_meta.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS
                ),
                retry=dict(action_meta.get("retry") or DEFAULT_RETRY),
                idempotent=bool(action_meta.get("idempotent", False)),
                required_params=required_params,
                availability=str(
                    action_meta.get("availability") or tool_meta.get("availability") or "shared"
                ),
                test_fixtures=deepcopy(test_fixtures),
            )
            specs[(spec.tool_id, spec.action)] = spec
    _add_aiopen_tool_specs(specs)
    return specs


def get_tool_action_spec(tool_id: str, action: str) -> ToolActionSpecV2 | None:
    normalized_tool_id = str(tool_id or "").strip()
    normalized_action = _normalize_tool_action(str(action or "view"))
    return build_tool_specs_v2().get((normalized_tool_id, normalized_action))


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return True


def _validate_schema_payload(
    schema: dict[str, Any],
    payload: dict[str, Any],
    *,
    subject: str,
) -> tuple[bool, str]:
    expected_root_type = str(schema.get("type") or "object").strip()
    if expected_root_type == "object" and not isinstance(payload, dict):
        return False, f"{subject} 必须是 object"
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    if subject == "工具输出" and payload.get("success") is False:
        required = [key for key in required if str(key) == "success"]
    for key in required:
        if _is_empty(payload.get(str(key))):
            return False, f"{subject} 缺少字段：{key}"

    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    for key, prop in properties.items():
        if key not in payload or _is_empty(payload.get(key)):
            continue
        if not isinstance(prop, dict):
            continue
        expected_type = str(prop.get("type") or "").strip()
        if expected_type and not _type_matches(payload.get(key), expected_type):
            return False, f"{subject} 字段 {key} 类型错误，应为 {expected_type}"
        enum_values = prop.get("enum")
        if isinstance(enum_values, list) and enum_values and payload.get(key) not in enum_values:
            return False, f"{subject} 字段 {key} 不在允许范围内"
    return True, ""


def _validate_input_schema(spec: ToolActionSpecV2, params: dict[str, Any]) -> tuple[bool, str]:
    return _validate_schema_payload(spec.input_schema or {}, params, subject="参数")


def validate_tool_result(
    tool_id: str,
    action: str,
    result: dict[str, Any] | None,
) -> ToolValidationResult:
    normalized_tool_id = str(tool_id or "").strip()
    normalized_action = _normalize_tool_action(str(action or "view"))
    spec = get_tool_action_spec(normalized_tool_id, normalized_action)
    if spec is None:
        return ToolValidationResult(
            ok=False,
            tool_id=normalized_tool_id,
            action=normalized_action,
            error_code="unknown_tool_action",
            message=f"未注册的工具动作: {normalized_tool_id}.{normalized_action}",
        )

    payload = dict(result or {})
    ok, message = _validate_schema_payload(spec.output_schema or {}, payload, subject="工具输出")
    if not ok:
        return ToolValidationResult(
            ok=False,
            tool_id=normalized_tool_id,
            action=normalized_action,
            spec=spec,
            error_code="output_schema_validation_failed",
            message=message,
        )
    return ToolValidationResult(
        ok=True,
        tool_id=normalized_tool_id,
        action=normalized_action,
        spec=spec,
    )


def validate_tool_spec_fixtures() -> dict[str, list[str]]:
    errors: dict[str, list[str]] = {}
    for (tool_id, action), spec in build_tool_specs_v2().items():
        key = f"{tool_id}.{action}"
        if not spec.test_fixtures:
            errors.setdefault(key, []).append("missing test_fixtures")
            continue
        for index, fixture in enumerate(spec.test_fixtures):
            name = str(fixture.get("name") or f"fixture_{index}")
            input_payload = fixture.get("input")
            if not isinstance(input_payload, dict):
                errors.setdefault(key, []).append(f"{name}: input must be object")
                continue
            input_result = validate_tool_call(tool_id, action, input_payload)
            if not input_result.ok:
                errors.setdefault(key, []).append(
                    f"{name}: input {input_result.error_code}: {input_result.message}"
                )
            output_payload = fixture.get("output")
            if not isinstance(output_payload, dict):
                errors.setdefault(key, []).append(f"{name}: output must be object")
                continue
            output_result = validate_tool_result(tool_id, action, output_payload)
            if not output_result.ok:
                errors.setdefault(key, []).append(
                    f"{name}: output {output_result.error_code}: {output_result.message}"
                )
    return errors


def validate_tool_call(
    tool_id: str,
    action: str,
    params: dict[str, Any] | None,
) -> ToolValidationResult:
    normalized_tool_id = str(tool_id or "").strip()
    normalized_action = _normalize_tool_action(str(action or "view"), dict(params or {}))
    spec = get_tool_action_spec(normalized_tool_id, normalized_action)
    if spec is None:
        return ToolValidationResult(
            ok=False,
            tool_id=normalized_tool_id,
            action=normalized_action,
            error_code="unknown_tool_action",
            message=f"未注册的工具动作: {normalized_tool_id}.{normalized_action}",
        )

    payload = dict(params or {})
    if spec.tool_id == "business_db" and any(k in payload for k in ("sql", "raw_sql", "query_sql")):
        return ToolValidationResult(
            ok=False,
            tool_id=normalized_tool_id,
            action=normalized_action,
            spec=spec,
            error_code="unsafe_raw_sql",
            message="business_db 不接受任意 SQL，请使用 entity/operation/payload。",
        )

    ok, message = _validate_input_schema(spec, payload)
    if not ok:
        return ToolValidationResult(
            ok=False,
            tool_id=normalized_tool_id,
            action=normalized_action,
            spec=spec,
            error_code="schema_validation_failed",
            message=message,
        )
    return ToolValidationResult(
        ok=True,
        tool_id=normalized_tool_id,
        action=normalized_action,
        spec=spec,
    )
