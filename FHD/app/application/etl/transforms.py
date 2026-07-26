"""安全、可序列化的 ETL 转换 DSL。

规则仅解释固定操作符，不调用 ``eval``、Python、Jinja 或动态导入。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.application.etl.errors import EtlError

ALLOWED_TRANSFORMS = frozenset(
    {
        "trim",
        "cast",
        "date",
        "number",
        "default",
        "map",
        "split",
        "concat",
        "lookup",
        "formula",
    }
)
ALLOWED_FORMULA_OPERATORS = frozenset({"add", "sub", "mul", "div", "coalesce"})
_DANGEROUS_FORMULA_PREFIXES = ("=", "+", "-", "@")


def neutralize_spreadsheet_formula(value: Any) -> Any:
    """防止导出 CSV/XLSX 时触发公式注入。"""
    if not isinstance(value, str):
        return value
    if value.lstrip().startswith(_DANGEROUS_FORMULA_PREFIXES):
        return "'" + value
    return value


def _decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    text = str(value).strip().replace(",", "").replace("，", "")
    text = re.sub(r"[￥¥$€£]", "", text)
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise EtlError("ETL_TRANSFORM_NUMBER_INVALID", f"无法转换为数字: {value}") from exc


def _date(value: Any, formats: list[str] | None = None) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    candidates = formats or [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%Y年%m月%d日",
        "%d/%m/%Y",
        "%m/%d/%Y",
    ]
    for fmt in candidates:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError as exc:
        raise EtlError("ETL_TRANSFORM_DATE_INVALID", f"无法转换为日期: {value}") from exc


def _cast(value: Any, kind: str) -> Any:
    key = str(kind or "string").lower()
    if key == "string":
        return "" if value is None else str(value)
    if key in {"number", "decimal", "float"}:
        if value in (None, ""):
            return ""
        number = _decimal(value)
        return float(number) if key == "float" else str(number)
    if key in {"integer", "int"}:
        if value in (None, ""):
            return ""
        return int(_decimal(value))
    if key in {"boolean", "bool"}:
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().lower()
        if text in {"1", "true", "yes", "y", "是", "有"}:
            return True
        if text in {"0", "false", "no", "n", "否", "无", ""}:
            return False
        raise EtlError("ETL_TRANSFORM_BOOLEAN_INVALID", f"无法转换为布尔值: {value}")
    if key == "date":
        return _date(value)
    raise EtlError("ETL_TRANSFORM_CAST_UNSUPPORTED", f"不支持的类型转换: {kind}")


def _operand(raw: Any, row: dict[str, Any]) -> Any:
    if isinstance(raw, dict):
        if set(raw) == {"field"}:
            return row.get(str(raw["field"]))
        if set(raw) == {"literal"}:
            return raw["literal"]
        raise EtlError("ETL_FORMULA_OPERAND_INVALID", "公式操作数只允许 field 或 literal")
    return raw


def _formula(rule: dict[str, Any], row: dict[str, Any]) -> Any:
    operator = str(rule.get("operator") or "").lower()
    if operator not in ALLOWED_FORMULA_OPERATORS:
        raise EtlError("ETL_FORMULA_OPERATOR_FORBIDDEN", f"不允许的公式操作符: {operator}")
    operands = rule.get("operands")
    if not isinstance(operands, list) or not operands:
        raise EtlError("ETL_FORMULA_OPERANDS_REQUIRED", "公式必须提供 operands")
    values = [_operand(item, row) for item in operands]
    if operator == "coalesce":
        return next((value for value in values if value not in (None, "")), "")
    numbers = [_decimal(value) for value in values]
    result = numbers[0]
    for number in numbers[1:]:
        if operator == "add":
            result += number
        elif operator == "sub":
            result -= number
        elif operator == "mul":
            result *= number
        elif operator == "div":
            if number == 0:
                raise EtlError("ETL_FORMULA_DIVISION_BY_ZERO", "公式除数不能为 0")
            result /= number
    return str(result)


def apply_transform(value: Any, rule: dict[str, Any], row: dict[str, Any]) -> Any:
    op = str(rule.get("op") or "").strip().lower()
    if op not in ALLOWED_TRANSFORMS:
        raise EtlError("ETL_TRANSFORM_FORBIDDEN", f"不允许的转换操作: {op}")
    if op == "trim":
        return value.strip() if isinstance(value, str) else value
    if op == "cast":
        return _cast(value, str(rule.get("type") or "string"))
    if op == "date":
        formats = rule.get("formats")
        return _date(value, formats if isinstance(formats, list) else None)
    if op == "number":
        if value in (None, ""):
            return ""
        return str(_decimal(value))
    if op == "default":
        return rule.get("value") if value in (None, "") else value
    if op in {"map", "lookup"}:
        table = rule.get("values")
        if not isinstance(table, dict):
            raise EtlError("ETL_TRANSFORM_MAP_INVALID", "枚举映射必须提供 values 对象")
        key = "" if value is None else str(value)
        return table.get(key, rule.get("fallback", value))
    if op == "split":
        delimiter = str(rule.get("delimiter") or ",")
        index = int(rule.get("index") or 0)
        parts = str(value or "").split(delimiter)
        return parts[index].strip() if -len(parts) <= index < len(parts) else ""
    if op == "concat":
        fields = rule.get("fields")
        if not isinstance(fields, list):
            raise EtlError("ETL_TRANSFORM_CONCAT_INVALID", "合并操作必须提供 fields")
        separator = str(rule.get("separator") or "")
        return separator.join(str(row.get(str(field)) or "") for field in fields)
    return _formula(rule, row)


def apply_mapping(source: dict[str, Any], mappings: list[dict[str, Any]]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for mapping in mappings:
        target = str(mapping.get("target") or "").strip()
        source_name = str(mapping.get("source") or "").strip()
        if not target:
            continue
        value = source.get(source_name)
        rules = mapping.get("transforms") or []
        if not isinstance(rules, list):
            raise EtlError("ETL_TRANSFORMS_INVALID", f"{target} 的 transforms 必须是数组")
        context = {**source, **normalized}
        for rule in rules:
            if not isinstance(rule, dict):
                raise EtlError("ETL_TRANSFORM_INVALID", "转换规则必须是 JSON 对象")
            value = apply_transform(value, rule, context)
            context[target] = value
        normalized[target] = value
    return normalized
