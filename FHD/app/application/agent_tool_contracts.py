"""Public tool contracts, schema validation, argument coercion, and secret redaction."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

_SCHEMA_TYPES = {"string", "integer", "number", "boolean", "array", "object"}


_SECRET_KEYS = {
    "api_key",
    "apikey",
    "api_token",
    "access_token",
    "refresh_token",
    "authorization",
    "password",
    "secret",
    "token",
}


_SECRET_TEXT = re.compile(
    r"(?i)(sk-[a-z0-9]{8,}|bearer\s+[a-z0-9._\-]{8,}"
    r"|api[_-]?key\s*[:=]\s*\S+|token\s*[:=]\s*\S+)"
)


class ToolLifecycleError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra


@dataclass(frozen=True)
class Actor:
    actor_id: str
    role: str
    employee_id: str | None
    tenant_id: int


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower().replace("-", "_") in _SECRET_KEYS:
                out[str(key)] = "[redacted]"
            else:
                out[str(key)] = _redact(item)
        return out
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _SECRET_TEXT.sub("[redacted]", value)
    return value


def _dumps(value: Any) -> str:
    return json.dumps(_redact(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _require_text(body: Mapping[str, Any], field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ToolLifecycleError("field_required", f"缺少必填字段 {field}", 400, field=field)
    return value.strip()


def validate_input_schema(schema: Any) -> dict[str, Any]:
    if isinstance(schema, str):
        try:
            schema = json.loads(schema)
        except json.JSONDecodeError as exc:
            raise ToolLifecycleError(
                "invalid_json_schema", "JSON Schema 不是合法 JSON", 400
            ) from exc
    if not isinstance(schema, dict):
        raise ToolLifecycleError("invalid_json_schema", "JSON Schema 必须是对象", 400)
    if schema.get("type") != "object":
        raise ToolLifecycleError("invalid_json_schema", "JSON Schema 的 type 必须是 object", 400)
    props = schema.get("properties")
    if not isinstance(props, dict):
        raise ToolLifecycleError("invalid_json_schema", "JSON Schema 缺少 properties 对象", 400)
    for name, spec in props.items():
        _validate_property(str(name), spec)
    required = schema.get("required", [])
    if not isinstance(required, list) or any(
        not isinstance(item, str) or item not in props for item in required
    ):
        raise ToolLifecycleError("invalid_json_schema", "required 含有未声明的字段", 400)
    additional = schema.get("additionalProperties", False)
    if not isinstance(additional, bool):
        raise ToolLifecycleError("invalid_json_schema", "additionalProperties 必须是布尔值", 400)
    cleaned = {
        "type": "object",
        "properties": {str(key): _clean_property(value) for key, value in props.items()},
        "required": list(required),
        "additionalProperties": additional,
    }
    return cast(dict[str, Any], _redact(cleaned))


def _validate_property(name: str, spec: Any) -> None:
    if not isinstance(spec, dict) or spec.get("type") not in _SCHEMA_TYPES:
        raise ToolLifecycleError(
            "invalid_json_schema", f"字段 {name} 的类型不在允许范围内", 400, field=name
        )
    kind = spec["type"]
    if kind == "array":
        items = spec.get("items")
        if not isinstance(items, dict) or items.get("type") not in _SCHEMA_TYPES:
            raise ToolLifecycleError("invalid_json_schema", f"字段 {name} 的数组元素类型无效", 400)
        if items.get("type") == "object":
            _validate_object_fields(f"{name}.items", items)
    if kind == "object":
        _validate_object_fields(name, spec)


def _validate_object_fields(name: str, spec: Mapping[str, Any]) -> None:
    props = spec.get("properties", {})
    if props is None:
        props = {}
    if not isinstance(props, dict):
        raise ToolLifecycleError("invalid_json_schema", f"字段 {name} 的 properties 无效", 400)
    for child, child_spec in props.items():
        _validate_property(f"{name}.{child}", child_spec)
    required = spec.get("required", [])
    if not isinstance(required, list) or any(item not in props for item in required):
        raise ToolLifecycleError("invalid_json_schema", f"字段 {name} 的 required 无效", 400)


def _clean_property(spec: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(spec["type"])
    cleaned: dict[str, Any] = {"type": kind}
    if "description" in spec:
        cleaned["description"] = spec.get("description")
    if "default" in spec:
        cleaned["default"] = spec.get("default")
    if kind == "array":
        cleaned["items"] = _clean_property(spec["items"])
    if kind == "object":
        props = spec.get("properties") or {}
        cleaned["properties"] = {str(key): _clean_property(value) for key, value in props.items()}
        cleaned["required"] = list(spec.get("required") or [])
        cleaned["additionalProperties"] = bool(spec.get("additionalProperties", False))
    return cleaned


def function_spec(name: str, description: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": json.loads(_dumps(dict(schema))),
        },
    }


def apply_arguments(schema: Mapping[str, Any], args: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ToolLifecycleError("invalid_arguments", "arguments 必须是对象", 400)
    return _apply_object(schema, args, "")


def _apply_object(schema: Mapping[str, Any], args: Mapping[str, Any], path: str) -> dict[str, Any]:
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    additional = bool(schema.get("additionalProperties", False))
    unknown = [key for key in args if key not in props]
    if unknown and not additional:
        raise ToolLifecycleError(
            "unexpected_property", f"不允许的字段 {unknown[0]}", 400, field=str(unknown[0])
        )
    filled: dict[str, Any] = {}
    for name, spec in props.items():
        if name not in args:
            if "default" in spec:
                filled[name] = _check_type(spec, spec.get("default"), _join(path, name))
            elif name in required:
                raise ToolLifecycleError("field_required", f"缺少必填参数 {name}", 400, field=name)
            continue
        filled[name] = _check_type(spec, args[name], _join(path, name))
    if additional:
        for name in unknown:
            if str(name).lower().replace("-", "_") in _SECRET_KEYS:
                continue
            filled[name] = args[name]
    return filled


def _join(path: str, name: str) -> str:
    return name if not path else f"{path}.{name}"


def _check_type(spec: Mapping[str, Any], value: Any, path: str) -> Any:
    kind = spec.get("type")
    if kind == "string":
        if not isinstance(value, str):
            raise ToolLifecycleError("type_mismatch", f"{path} 必须是字符串", 400, field=path)
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ToolLifecycleError("type_mismatch", f"{path} 必须是整数", 400, field=path)
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ToolLifecycleError("type_mismatch", f"{path} 必须是数字", 400, field=path)
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            raise ToolLifecycleError("type_mismatch", f"{path} 必须是布尔值", 400, field=path)
        return value
    if kind == "array":
        if not isinstance(value, list):
            raise ToolLifecycleError("type_mismatch", f"{path} 必须是数组", 400, field=path)
        return [
            _check_type(spec.get("items") or {"type": "string"}, item, f"{path}[]")
            for item in value
        ]
    if kind == "object":
        if not isinstance(value, dict):
            raise ToolLifecycleError("type_mismatch", f"{path} 必须是对象", 400, field=path)
        nested = {
            "properties": spec.get("properties") or {},
            "required": spec.get("required") or [],
            "additionalProperties": spec.get("additionalProperties", False),
        }
        return _apply_object(nested, value, path)
    raise ToolLifecycleError("type_mismatch", f"{path} 类型不受支持", 400, field=path)
