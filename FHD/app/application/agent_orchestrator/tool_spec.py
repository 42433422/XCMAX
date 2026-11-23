from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, Literal, cast

# Re-export tool data for existing callers.
from app.application.agent_orchestrator.tool_spec_data import (  # noqa: F401
    _BUSINESS_ENTITIES,
    _DEFAULT_OUTPUT_SCHEMA,
    _SPECIAL_INPUT_SCHEMAS,
    _SPECIAL_OUTPUT_SCHEMAS,
    _SPECIAL_TOOL_CONTRACTS,
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
from app.application.agent_orchestrator.tool_spec_data.contract_samples import _default_fixture
from app.utils.operational_errors import RECOVERABLE_ERRORS

# 批量文件的数组参数超出上限时按上限截断，而不是让整轮计划失败。
_TRUNCATABLE_BATCH_KEYS = frozenset({"file_paths", "run_ids"})

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
    contract_samples: list[dict[str, Any]] = field(default_factory=list)
    version: str = "2"
    read_only: bool = False
    read_only_if_unset: list[str] = field(default_factory=list)
    owner_mod_id: str = ""
    policy: dict[str, Any] = field(default_factory=dict)

    @property
    def schema_digest(self) -> str:
        """Bind discovery and dispatch to the same host-owned action contract."""
        contract = {
            key: value
            for key, value in self.to_dict().items()
            if key not in {"description", "contract_samples", "test_fixtures"}
        }
        return hashlib.sha256(
            json.dumps(
                contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()

    def is_read_only_call(self, params: dict[str, Any]) -> bool:
        """Resolve host-declared effects from the validated call, before dispatch."""
        if self.read_only:
            return True
        return (
            bool(self.read_only_if_unset)
            and _validate_schema_payload(self.input_schema, params, subject="工具参数")[0]
            and all(
                params.get(key) is None or params.get(key) == "" for key in self.read_only_if_unset
            )
        )

    @property
    def receipt_permission(self) -> str:
        """Keep action-level audit identity without changing the real RBAC gate."""
        if (
            self.tool_id == "document_template"
            or (self.tool_id == "materials" and self.permission == "material.edit")
            or (
                self.tool_id in {"shipment_records", "shipment_orders"}
                and self.permission == "shipment.edit"
                and self.action != "clear"
            )
        ):
            return f"tool.{self.tool_id}.{self.action}"
        return self.permission

    @property
    def test_fixtures(self) -> list[dict[str, Any]]:
        """Compat alias for contract_samples (historical name)."""
        return self.contract_samples

    def to_dict(self) -> dict[str, Any]:
        return {
            **deepcopy(self.policy),
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
            "version": self.version,
            "read_only": self.read_only,
            "read_only_if_unset": list(self.read_only_if_unset),
            "owner_mod_id": self.owner_mod_id,
            "required_params": self.required_params,
            "availability": self.availability,
            "contract_samples": self.contract_samples,
            "test_fixtures": self.contract_samples,  # compat alias
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
        return cast(RiskLevel, text)
    return "medium"


def _schema_from_required(required_params: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": list(required_params),
        "properties": {key: {} for key in required_params},
    }


def _special_permission(tool_id: str, action: str) -> str:
    if tool_id == "products" and action in {"exists", "query"}:
        return "product.view"
    if tool_id == "shipment_records" and action in {"query", "list"}:
        return "shipment.view"
    if tool_id == "shipment_orders" and action in {"generate", "generate_batch"}:
        return "shipment.create"
    if tool_id == "materials" and action in {"list", "query"}:
        return "material.view"
    if tool_id == "materials" and action in {"create", "update", "delete", "batch_delete", "clear"}:
        return "material.edit"
    if (tool_id, action) == ("customers", "query"):
        return "customer.view"
    if tool_id == "customers" and action in {
        "ensure_exists",
        "delete",
        "batch_delete",
        "clear",
    }:
        return "customer.edit"
    if tool_id == "products" and action == "clear":
        return "product.edit"
    if tool_id == "shipment_records" and action == "clear":
        return "shipment.edit"
    if tool_id in PERMISSION_BARE_PREFIX_TOOLS:
        if (tool_id, action) == ("employee", "context"):
            return "employee.execute"
        return f"{tool_id}.{action}"
    if tool_id == "dataset_rag":
        if action in DATASET_RAG_READ_ACTIONS:
            return DATASET_RAG_READ_PERMISSION
        return DATASET_RAG_WRITE_PERMISSION
    if tool_id == "template_preview" and action in {"list", "query", "view"}:
        return "elt.read"
    if tool_id in {"template_preview", "document_template"}:
        return "elt.template.manage"
    if (
        tool_id == "excel_analysis"
        and action in {"read", "structure", "query", "aggregate", "statistics"}
    ) or tool_id == "excel_join_compare":
        return "tool.excel_analysis.read"
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
        return cast("RiskLevel", AIOPEN_LOW_RISK), True
    return cast("RiskLevel", AIOPEN_DEFAULT_RISK), False


def _add_aiopen_tool_specs(specs: dict[tuple[str, str], ToolActionSpecV2]) -> None:
    try:
        from app.application.aiopen.definitions import TOOL_DEFINITIONS
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
    for tool in TOOL_DEFINITIONS or []:
        if not isinstance(tool, dict):
            continue
        action = _normalize_tool_action(str(tool.get("name") or ""))
        if not action:
            continue
        input_schema = tool.get("inputSchema")
        if not isinstance(input_schema, dict):
            input_schema = {"type": "object", "properties": {}}
        input_schema = deepcopy(input_schema)
        raw_required = input_schema.get("required")
        required = list(raw_required) if isinstance(raw_required, list) else []
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
                    "input": {"message": "你好", "request_id": "contract-aiopen-chat"},
                    "output": {"success": True, "data": {"reply": "你好"}},
                }
            ]
        elif action == "ui_upload":
            fixture = [
                {
                    "name": "upload_text_file",
                    "input": {
                        "selector": "input[type=file]",
                        "files": [
                            {
                                "name": "sample.txt",
                                "text": "AIOPEN upload sample",
                                "type": "text/plain",
                            }
                        ],
                    },
                    "output": {"success": True, "uploaded": ["sample.txt"]},
                }
            ]
        registered = specs.get(("aiopen", action))
        prior = registered or ToolActionSpecV2(
            tool_id="aiopen",
            action=action,
            risk=risk,
            permission=_special_permission("aiopen", action),
            cost_units=_cost_units("aiopen", action, risk),
            timeout_seconds=30,
            retry=dict(DEFAULT_RETRY),
            idempotent=idempotent,
            # api_catalog reads the live account's canonical capability projection.
            # Other low-risk AIOPEN actions still need explicit side-effect review.
            read_only=action == "api_catalog",
            required_params=required_params,
            availability="aiopen",
        )
        description = str(tool.get("description") or f"AIOPEN {action}")
        if (
            registered is not None
            and action.startswith("ui_")
            and prior.risk == "high"
            and not prior.read_only
        ):
            if "session_id" not in required_params:
                required_params.append("session_id")
            input_schema["required"] = list(required_params)
            properties = input_schema.setdefault("properties", {})
            properties["session_id"] = {
                **properties.get("session_id", {}),
                "type": "string",
                "minLength": 1,
                "pattern": r"[\s\S]*\S[\s\S]*",
                "description": "必须显式指定已绑定的屏幕会话，后续 ui_verify 使用完全相同的 session_id。",
            }
            from app.application.aiopen.agent_bridge import screen_verification_schema

            properties["verification"] = screen_verification_schema()
            description += (
                " Agent 写入要求：显式提供非空 session_id。动态动作必须提供同会话 verification"
                "（aiopen.ui_verify 参数），与动作一并审批冻结，宿主执行后独立回读；点击、上传的预期结果"
                "在执行前必须尚未成立。确定性多步计划也可通过 depends_on/next 无条件连接同会话后续"
                " ui_verify，计划不得包含 branches。页面核验仅证明可见状态，不代表外部业务已完成。"
            )
            for sample in fixture:
                sample["input"]["session_id"] = "screen-session-1"
        # The registry owns authority/retries; wire definitions only supply the
        # schema and guidance. Do not downgrade a high-risk registered UI write.
        specs[("aiopen", action)] = replace(
            prior,
            description=description,
            input_schema=deepcopy(input_schema),
            output_schema=deepcopy(output_schema),
            required_params=required_params,
            contract_samples=deepcopy(fixture),
        )


_TOOL_SPECS_CACHE: dict[tuple[str, str], ToolActionSpecV2] | None = None
_TOOL_SPECS_SOURCE: dict[str, Any] | None = None


def invalidate_tool_specs_cache() -> None:
    global _TOOL_SPECS_CACHE, _TOOL_SPECS_SOURCE
    _TOOL_SPECS_CACHE = None
    _TOOL_SPECS_SOURCE = None


def build_tool_specs_v2() -> dict[tuple[str, str], ToolActionSpecV2]:
    global _TOOL_SPECS_CACHE, _TOOL_SPECS_SOURCE
    from app.application.agent_orchestrator.tool_spec_data.input_schemas import (
        workbook_input_schemas,
    )
    from app.application.tools.mcp.registry import merge_mcp_tools
    from resources.config.risk_actions_loader import get_workflow_tools_from_registry

    registry = merge_mcp_tools(get_workflow_tools_from_registry())
    if _TOOL_SPECS_CACHE is not None and registry == _TOOL_SPECS_SOURCE:
        return _TOOL_SPECS_CACHE
    input_schemas = {**_SPECIAL_INPUT_SCHEMAS, **workbook_input_schemas()}
    specs: dict[tuple[str, str], ToolActionSpecV2] = {}
    for tool_id, tool_meta in registry.items():
        actions = tool_meta.get("actions") if isinstance(tool_meta, dict) else None
        if not isinstance(actions, dict):
            continue
        tool_description = str(tool_meta.get("description") or "")
        for action, action_meta in actions.items():
            if not isinstance(action_meta, dict):
                continue
            normalized_action = (
                str(action).strip()
                if str(tool_id).startswith("mcp__")
                else _normalize_tool_action(str(action or "view"))
            )
            if (str(tool_id), normalized_action) in specs:
                raise ValueError(f"Duplicate capability identity: {tool_id}.{normalized_action}")
            required = action_meta.get("required_params")
            required_params = [str(x) for x in required] if isinstance(required, list) else []
            risk = _risk_value(action_meta.get("risk"))
            declared_input = action_meta.get("input_schema")
            declared_output = action_meta.get("output_schema")
            input_schema = input_schemas.get(
                (str(tool_id), normalized_action),
                declared_input
                if isinstance(declared_input, dict)
                else _schema_from_required(required_params),
            )
            output_schema = _SPECIAL_OUTPUT_SCHEMAS.get(
                (str(tool_id), normalized_action),
                declared_output if isinstance(declared_output, dict) else _DEFAULT_OUTPUT_SCHEMA,
            )
            input_schema = deepcopy(input_schema)
            required_params = list(
                dict.fromkeys(
                    [*required_params, *(str(x) for x in input_schema.get("required") or [])]
                )
            )
            input_schema["required"] = list(required_params)
            contract_samples = (
                _SPECIAL_TOOL_CONTRACTS.get((str(tool_id), normalized_action))
                or action_meta.get("contract_samples")
                or _default_fixture(str(tool_id), normalized_action, input_schema, output_schema)
            )
            conditional_reads = action_meta.get("read_only_if_unset")
            description = str(action_meta.get("description") or tool_description)
            if str(tool_id) in {"excel_analysis", "excel_join_compare"}:
                description += (
                    " file_path 可直接使用当前账号的上传 ID/文件名或同原任务已核验产物 URI；"
                    "宿主按账号、租户和原文件哈希读取。read 返回 has_more 时用 next_offset 继续读取。"
                )
            if (str(tool_id), normalized_action) == ("employee", "execute"):
                from app.domain.workbook_write_contract import WORKBOOK_WRITER

                description += (
                    f" Excel 模板写入使用已安装受信员工 {WORKBOOK_WRITER}，"
                    "input.template_path 为当前账号上传 ID/文件名或同原任务已核验产物 URI；"
                    "input.plan 按下方精确 schema 提交，经过原审批、真实写出和独立 QC。"
                    "公式按文本保存，不能宣称数值已重算。先用 employee.list 查看可用员工。"
                )
            spec = ToolActionSpecV2(
                tool_id=str(tool_id),
                action=normalized_action,
                description=description,
                input_schema=deepcopy(input_schema),
                output_schema=deepcopy(output_schema),
                risk=risk,
                permission=str(
                    action_meta.get("permission")
                    or _special_permission(str(tool_id), normalized_action)
                ),
                cost_units=_cost_units(str(tool_id), normalized_action, risk),
                timeout_seconds=int(action_meta.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS),
                retry=dict(action_meta.get("retry") or DEFAULT_RETRY),
                idempotent=bool(action_meta.get("idempotent", False)),
                read_only=(
                    action_meta.get("read_only") is True
                    or (
                        str(tool_id) == "dataset_rag"
                        and normalized_action in DATASET_RAG_READ_ACTIONS
                    )
                ),
                read_only_if_unset=(
                    list(conditional_reads)
                    if isinstance(conditional_reads, list)
                    and all(isinstance(key, str) and key for key in conditional_reads)
                    else []
                ),
                required_params=required_params,
                availability=str(
                    action_meta.get("availability") or tool_meta.get("availability") or "shared"
                ),
                contract_samples=deepcopy(contract_samples),
                version=str(action_meta.get("version") or "2"),
                owner_mod_id=str(
                    action_meta.get("owner_mod_id") or tool_meta.get("owner_mod_id") or ""
                ),
                policy={
                    key: deepcopy(action_meta[key])
                    for key in (
                        "approval",
                        "compensate",
                        "required_any",
                        "action_class",
                        "requires_write_approval",
                        "provider_scope",
                        "data_scope",
                    )
                    if key in action_meta
                },
            )
            specs[(spec.tool_id, spec.action)] = spec
    _add_aiopen_tool_specs(specs)
    _TOOL_SPECS_CACHE = specs
    _TOOL_SPECS_SOURCE = deepcopy(registry)
    return specs


def get_tool_action_spec(tool_id: str, action: str) -> ToolActionSpecV2 | None:
    normalized_tool_id = str(tool_id or "").strip()
    normalized_action = (
        str(action).strip()
        if normalized_tool_id.startswith("mcp__")
        else _normalize_tool_action(str(action or "view"))
    )
    return build_tool_specs_v2().get((normalized_tool_id, normalized_action))


def _is_empty(value: Any) -> bool:
    if isinstance(value, str):
        value = value.strip()
    return value is None or (isinstance(value, (str, list, tuple, dict)) and not value)


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


def _numeric_bound_error(key: str, value: Any, prop: dict[str, Any]) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if "minimum" in prop and value < prop["minimum"]:
        return f"字段 {key} 低于最小值 {prop['minimum']}"
    if "maximum" in prop and value > prop["maximum"]:
        return f"字段 {key} 超过最大值 {prop['maximum']}"
    if "exclusiveMinimum" in prop and value <= prop["exclusiveMinimum"]:
        return f"字段 {key} 必须大于 {prop['exclusiveMinimum']}"
    if "exclusiveMaximum" in prop and value >= prop["exclusiveMaximum"]:
        return f"字段 {key} 必须小于 {prop['exclusiveMaximum']}"
    return ""


def _string_constraint_error(key: str, value: Any, prop: dict[str, Any]) -> str:
    if not isinstance(value, str):
        return ""
    if "minLength" in prop and len(value) < int(prop["minLength"]):
        return f"字段 {key} 短于最小长度"
    if "maxLength" in prop and len(value) > int(prop["maxLength"]):
        return f"字段 {key} 超过最大长度 {prop['maxLength']}"
    pattern = prop.get("pattern")
    if isinstance(pattern, str) and pattern and re.fullmatch(pattern, value) is None:
        return f"字段 {key} 格式不符合要求"
    expected = str(prop.get("format") or "")
    if expected == "date" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        return f"字段 {key} 不是日期"
    if expected == "email":
        local, separator, domain = value.partition("@")
        if (
            not local
            or not separator
            or "@" in domain
            or "." not in domain[1:-1]
            or any(char.isspace() for char in value)
        ):
            return f"字段 {key} 不是邮箱"
    if expected == "phone" and re.fullmatch(r"1\d{10}", value) is None:
        return f"字段 {key} 不是手机号"
    return ""


def _validate_schema_payload(
    schema: dict[str, Any],
    payload: dict[str, Any],
    *,
    subject: str,
    allow_references_from: set[str] | frozenset[str] | None = None,
    allow_missing_fields: set[str] | frozenset[str] | None = None,
    path_prefix: str = "",
) -> tuple[bool, str]:
    expected_root_type = str(schema.get("type") or "object").strip()
    if expected_root_type == "object" and not isinstance(payload, dict):
        return False, f"{subject} 必须是 object"
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    if subject == "工具输出" and payload.get("success") is False:
        required = [key for key in (required or []) if str(key) == "success"]
    for key in required or []:
        name = str(key)
        full_name = f"{path_prefix}.{name}" if path_prefix else name
        normalized_name = re.sub(r"\[(\d+)\]", r".\1", full_name)
        if any(
            candidate in (allow_missing_fields or ())
            for candidate in (name, full_name, normalized_name)
        ):
            continue
        present = isinstance(payload, dict) and name in payload
        value = payload.get(name) if present else None
        # A present array or object is the field, including an empty list.
        if (
            not present
            or value is None
            or (_is_empty(value) and not isinstance(value, (list, dict)))
        ):
            return False, f"{subject} 缺少字段：{name}"

    raw_properties = schema.get("properties")
    properties = raw_properties if isinstance(raw_properties, dict) else {}
    if schema.get("additionalProperties") is False:
        unknown = [key for key in payload if key not in properties]
        if unknown:
            return False, f"{subject} 存在未定义字段：{unknown[0]}"
    dependencies = schema.get("dependentRequired")
    if isinstance(dependencies, dict):
        for key, needed in dependencies.items():
            if _is_empty(payload.get(str(key))) or not isinstance(needed, list):
                continue
            for item in needed:
                if _is_empty(payload.get(str(item))):
                    return False, f"{subject} 字段 {key} 需要同时提供 {item}"
    for key, prop in (properties or {}).items():
        if key not in payload or payload.get(key) is None:
            continue
        if not isinstance(prop, dict):
            continue
        value = payload.get(key)
        if (
            allow_references_from is not None
            and isinstance(value, str)
            and ("{{" in value or "}}" in value)
        ):
            from app.application.agent_orchestrator.param_references import (
                validate_plan_references,
            )

            reference_error = validate_plan_references(value, allow_references_from)
            if reference_error:
                return False, f"{subject} 字段 {key}：{reference_error}"
            # The concrete value is checked again after its declared predecessor
            # has completed and the reference has been resolved.
            continue
        expected_type = str(prop.get("type") or "").strip()
        if expected_type == "array" and isinstance(value, str) and value.strip():
            # 模型常把一组 id 写成逗号/分号分隔的字符串；这里拆成数组，
            # 否则会被类型校验拦成「字段 xxx 类型错误，应为 array」。
            payload[key] = [
                part.strip() for part in re.split(r"[,;，；\s]+", value) if part.strip()
            ]
            value = payload[key]
        if (
            expected_type == "string"
            and key == "reference_id"
            and isinstance(value, int)
            and not isinstance(value, bool)
        ):
            # Order tools often resolve a numeric id. Keep the reference as text.
            payload[key] = str(value)
            value = payload[key]
        if expected_type and not _type_matches(value, expected_type):
            return False, f"{subject} 字段 {key} 类型错误，应为 {expected_type}"
        enum_values = prop.get("enum")
        if isinstance(enum_values, list) and enum_values and value not in enum_values:
            return False, f"{subject} 字段 {key} 不在允许范围内"
        bound = _numeric_bound_error(key, value, prop) or _string_constraint_error(key, value, prop)
        if bound:
            return False, f"{subject} {bound}"
        if expected_type == "object" and isinstance(value, dict) and prop.get("properties"):
            nested_ok, nested_message = _validate_schema_payload(
                prop,
                value,
                subject=f"{subject}.{key}",
                allow_references_from=allow_references_from,
                allow_missing_fields=allow_missing_fields,
                path_prefix=f"{path_prefix}.{key}" if path_prefix else str(key),
            )
            if not nested_ok:
                return False, nested_message
        if expected_type == "array" and isinstance(value, list):
            if "minItems" in prop and len(value) < int(prop["minItems"]):
                return False, f"{subject} 字段 {key} 数量不足"
            if "maxItems" in prop and len(value) > int(prop["maxItems"]):
                # 批量文件/预演编号超出上限时截断而不是整轮失败：
                # 模型可能把所有附件一次列全，工具本身也按同一上限处理。
                if key in _TRUNCATABLE_BATCH_KEYS:
                    del value[int(prop["maxItems"]) :]
                else:
                    return False, f"{subject} 字段 {key} 数量超限"
            raw_items = prop.get("items")
            item_schema = raw_items if isinstance(raw_items, dict) else {}
            item_type = str(item_schema.get("type") or "")
            for index, item in enumerate(value):
                if (
                    allow_references_from is not None
                    and isinstance(item, str)
                    and ("{{" in item or "}}" in item)
                ):
                    from app.application.agent_orchestrator.param_references import (
                        validate_plan_references,
                    )

                    reference_error = validate_plan_references(item, allow_references_from)
                    if reference_error:
                        return False, f"{subject} 字段 {key}[{index}]：{reference_error}"
                    continue
                if item_type and not _type_matches(item, item_type):
                    return False, f"{subject} 字段 {key}[{index}] 类型错误，应为 {item_type}"
                if item_type == "object" and isinstance(item, dict):
                    nested_ok, nested_message = _validate_schema_payload(
                        item_schema,
                        item,
                        subject=f"{subject}.{key}[{index}]",
                        allow_references_from=allow_references_from,
                        allow_missing_fields=allow_missing_fields,
                        path_prefix=(
                            f"{path_prefix}.{key}[{index}]" if path_prefix else f"{key}[{index}]"
                        ),
                    )
                    if not nested_ok:
                        return False, nested_message
    options = schema.get("anyOf")
    if isinstance(options, list) and options:
        last = ""
        matched = False
        for option in options:
            if not isinstance(option, dict):
                continue
            ok, last = _validate_schema_payload(
                option,
                payload,
                subject=subject,
                allow_references_from=allow_references_from,
                allow_missing_fields=allow_missing_fields,
                path_prefix=path_prefix,
            )
            if ok:
                matched = True
                break
        if not matched:
            return False, last or f"{subject} 未满足任一必填组合"
    exclusive_options = schema.get("oneOf")
    if isinstance(exclusive_options, list) and exclusive_options:
        matches = sum(
            _validate_schema_payload(
                option,
                deepcopy(payload),
                subject=subject,
                allow_references_from=allow_references_from,
                allow_missing_fields=allow_missing_fields,
                path_prefix=path_prefix,
            )[0]
            for option in exclusive_options
            if isinstance(option, dict)
        )
        if matches != 1:
            return False, f"{subject} 必须且只能满足一个字段组合"
    return True, ""


def validate_schema_object(schema: dict[str, Any], payload: dict[str, Any]) -> tuple[bool, str]:
    """Validate one object against the subset of JSON Schema used by tool calls."""
    return _validate_schema_payload(schema or {}, payload, subject="参数")


def _validate_input_schema(spec: ToolActionSpecV2, params: dict[str, Any]) -> tuple[bool, str]:
    return _validate_input_schema_with_references(
        spec, params, allow_references_from=None, allow_missing_fields=None
    )


def _validate_input_schema_with_references(
    spec: ToolActionSpecV2,
    params: dict[str, Any],
    *,
    allow_references_from: set[str] | frozenset[str] | None,
    allow_missing_fields: set[str] | frozenset[str] | None = None,
) -> tuple[bool, str]:
    from app.application.agent_orchestrator.param_references import (
        host_reference_params,
        unresolved_placeholders,
    )

    params = host_reference_params(spec.tool_id, spec.action, params)[0]
    has_references = bool(unresolved_placeholders(params))
    if has_references and allow_references_from is None:
        return False, "参数含有尚未解析的前序结果引用"
    from app.application.shipment_inputs import missing_shipment_call_fields

    # Domain-specific cross-field checks need concrete values. Defer only those
    # checks that depend on a reference; the full JSON shape is still checked now.
    defer_domain_checks = has_references or bool(allow_missing_fields)
    missing = (
        []
        if defer_domain_checks
        else missing_shipment_call_fields(spec.tool_id, spec.action, params)
    )
    if missing:
        return False, "缺少有效出货参数：" + "、".join(missing)
    if not defer_domain_checks and (spec.tool_id, spec.action) == ("inventory", "stock_in"):
        from app.domain.app_pure.inventory_inputs import validate_stock_in_request

        try:
            validate_stock_in_request(params)
        except ValueError as exc:
            return False, str(exc)
    if (
        not defer_domain_checks
        and spec.tool_id == "sales"
        and spec.action in {"quote", "create_order"}
    ):
        from app.application.sales_quote_inputs import validated_quote_request

        try:
            validated_quote_request(params)
        except ValueError as exc:
            return False, str(exc)
    return _validate_schema_payload(
        spec.input_schema or {},
        params,
        subject="参数",
        allow_references_from=allow_references_from,
        allow_missing_fields=allow_missing_fields,
    )


def validate_tool_result(
    tool_id: str,
    action: str,
    result: dict[str, Any] | None,
) -> ToolValidationResult:
    normalized_tool_id = str(tool_id or "").strip()
    normalized_action = (
        str(action).strip()
        if normalized_tool_id.startswith("mcp__")
        else _normalize_tool_action(str(action or "view"))
    )
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
        if not spec.contract_samples:
            errors.setdefault(key, []).append("missing contract_samples")
            continue
        for index, fixture in enumerate(spec.contract_samples):
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
    *,
    allow_references_from: set[str] | frozenset[str] | None = None,
    allow_missing_fields: set[str] | frozenset[str] | None = None,
) -> ToolValidationResult:
    normalized_tool_id = str(tool_id or "").strip()
    normalized_action = (
        str(action).strip()
        if normalized_tool_id.startswith("mcp__")
        else _normalize_tool_action(str(action or "view"), dict(params or {}))
    )
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

    ok, message = (
        _validate_input_schema(spec, payload)
        if allow_references_from is None and not allow_missing_fields
        else _validate_input_schema_with_references(
            spec,
            payload,
            allow_references_from=allow_references_from,
            allow_missing_fields=allow_missing_fields,
        )
    )
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
