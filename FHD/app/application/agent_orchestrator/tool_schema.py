"""JSON Schema validation and legacy normalization for existing tool contracts."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any


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
                return False, f"{subject} 字段 {key} 数量超限，请按契约拆分批次；原参数未截断"
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
    """Validate the exact execution contract, retaining existing input normalization."""
    return _validate_input_payload(schema or {}, payload)


def _reference_paths(value: Any, path: tuple = ()):
    if isinstance(value, str) and ("{{" in value or "}}" in value):
        yield path
    elif isinstance(value, (dict, list)):
        for key, child in value.items() if isinstance(value, dict) else enumerate(value):
            yield from _reference_paths(child, (*path, key))


def _deferred_input_error(error: Any, references: set[tuple], missing: set[str]) -> bool:
    """Filter validator errors, never skip unrelated known fields in a pending plan."""
    path = tuple(error.absolute_path)
    if error.validator == "format_unavailable":
        return False

    def allowed_missing(candidate: tuple) -> bool:
        return bool(candidate) and (
            str(candidate[-1]) in missing or ".".join(map(str, candidate)) in missing
        )

    if any(path[: len(reference)] == reference for reference in references):
        return True
    if (error.instance is None or error.instance == "") and allowed_missing(path):
        return True
    if error.validator == "required" and isinstance(error.instance, dict):
        absent = [
            name
            for name in error.validator_value
            if name not in error.instance
            or (isinstance(error.instance[name], str) and not error.instance[name].strip())
        ]
        return bool(absent) and all(allowed_missing((*path, name)) for name in absent)
    if error.context and error.validator in {"anyOf", "oneOf"}:
        branches: dict[Any, list[Any]] = {}
        for child in error.context:
            branches.setdefault(child.schema_path[0], []).append(child)
        # At least one branch must remain possible after only deferred values resolve.
        return any(
            all(_deferred_input_error(child, references, missing) for child in branch)
            for branch in branches.values()
        )
    # A reference somewhere below an object does not make its key presence,
    # a known conditional branch, or an object-level constraint indeterminate.
    return False


def _nonempty_required(validator, required, instance, schema):
    from jsonschema import Draft202012Validator, ValidationError

    yield from Draft202012Validator.VALIDATORS["required"](validator, required, instance, schema)
    if isinstance(instance, dict):
        for name in required:
            if isinstance(instance.get(name), str) and not instance[name].strip():
                yield ValidationError(f"必填字段 {name} 不能为空")


def _supported_format(validator, declared, instance, schema):
    from jsonschema import Draft202012Validator, ValidationError

    if validator.format_checker is None or declared not in validator.format_checker.checkers:
        yield ValidationError(
            f"工具契约格式 {declared} 的校验器未安装或不受支持",
            validator="format_unavailable",
            validator_value=declared,
        )
    else:
        yield from Draft202012Validator.VALIDATORS["format"](validator, declared, instance, schema)


def _validate_input_payload(
    schema: dict[str, Any],
    payload: dict[str, Any],
    *,
    allow_references_from: set[str] | frozenset[str] | None = None,
    allow_missing_fields: set[str] | frozenset[str] | None = None,
) -> tuple[bool, str]:
    from jsonschema import Draft202012Validator, FormatChecker, SchemaError, validators
    from referencing import Registry
    from referencing.exceptions import Unresolvable

    from app.application.agent_orchestrator.param_references import validate_plan_references

    if not isinstance(payload, dict):
        return False, "参数必须是 object"
    try:
        # JSON numeric values must be finite; Python's NaN evades numeric bounds.
        json.dumps(payload, allow_nan=False)
        Draft202012Validator.check_schema(schema)
    except (SchemaError, TypeError, ValueError, RecursionError):
        return False, "工具契约或参数不是有效的 JSON Schema/JSON 对象"
    references: set[tuple] = set()
    if allow_references_from is not None:
        reference_error = validate_plan_references(payload, allow_references_from)
        if reference_error:
            return False, reference_error
        references = set(_reference_paths(payload))
    # Retain established array/reference-id normalization. Structural acceptance
    # belongs to jsonschema, including nullable values and const-based oneOf.
    _validate_schema_payload(
        schema,
        payload,
        subject="参数",
        allow_references_from=allow_references_from,
        allow_missing_fields=allow_missing_fields,
    )
    try:
        checker = FormatChecker()
        checker.checks("phone")(
            lambda value: not isinstance(value, str) or re.fullmatch(r"1\d{10}", value) is not None
        )
        validator = validators.extend(
            Draft202012Validator, {"required": _nonempty_required, "format": _supported_format}
        )(schema, registry=Registry(), format_checker=checker)
        missing = {re.sub(r"\[(\d+)\]", r".\1", key) for key in allow_missing_fields or ()}
        error = next(
            (
                item
                for item in validator.iter_errors(payload)
                if not _deferred_input_error(item, references, missing)
            ),
            None,
        )
    except (SchemaError, Unresolvable, RecursionError):
        return False, "工具契约无法解析；外部 Schema 引用不得触发网络请求"
    if error is not None:
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        if error.validator == "required":
            return (
                False,
                f"参数 {location} 缺少或为空的必填字段：{', '.join(error.validator_value)}",
            )
        if error.validator == "format_unavailable":
            return False, f"工具契约格式 {error.validator_value} 的校验器未安装或不受支持"
        if error.validator == "maxItems":
            return False, f"参数 {location} 数量超限，请按契约拆分批次；原参数未截断"
        return False, f"参数 {location} 不符合工具契约（{error.validator}）"
    return True, ""
