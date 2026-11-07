"""安全、可序列化的 ETL 转换 DSL。

规则仅解释固定操作符，不调用 ``eval``、Python、Jinja 或动态导入。
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from app.application.elt.errors import EltError

ALLOWED_TRANSFORMS = frozenset(
    {
        "trim",
        "cast",
        "date",
        "datetime",
        "time",
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
_INVISIBLE_TEXT_RE = re.compile(r"[\ufeff\u200b\u200c\u200d\u2060]")


def _clean_string(value: str) -> str:
    text = _INVISIBLE_TEXT_RE.sub("", value)
    text = text.replace("\xa0", " ").replace("\u3000", " ")
    return re.sub(r"[\t\r\n ]+", " ", text).strip()


def neutralize_spreadsheet_formula(value: Any) -> Any:
    """防止导出 CSV/XLSX 时触发公式注入。"""
    if not isinstance(value, str):
        return value
    if value.lstrip().startswith(_DANGEROUS_FORMULA_PREFIXES):
        return "'" + value
    return value


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value == "")


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise EltError("ELT_TRANSFORM_NUMBER_INVALID", f"布尔值不能当作数字: {value}")
    if isinstance(value, Decimal):
        return value
    # Excel stores doubles but shows 15 significant digits; that is the business value.
    text = _clean_string(format(value, ".15g") if isinstance(value, float) else str(value))
    percent = text.endswith(("%", "％"))
    if percent:
        text = text[:-1]
    negative = (text.startswith("(") and text.endswith(")")) or (
        text.startswith("（") and text.endswith("）")
    )
    if negative:
        text = text[1:-1]
    text = re.sub(r"[\s,，]", "", text)
    text = re.sub(r"^[￥¥$€£]", "", text)
    text = re.sub(r"元$", "", text)
    if negative:
        text = "-" + text
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise EltError("ELT_TRANSFORM_NUMBER_INVALID", f"无法转换为数字: {value}") from exc
    if not number.is_finite():
        raise EltError("ELT_TRANSFORM_NUMBER_INVALID", f"无法转换为数字: {value}")
    return number.scaleb(-2) if percent else number


_EXCEL_SERIAL_RANGE = (1, 2958465)
_TIME_FORMATS = ("%H:%M:%S", "%H:%M", "%H:%M:%S.%f", "%H时%M分%S秒", "%H时%M分", "%H点%M分")


def _excel_serial(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    if not _EXCEL_SERIAL_RANGE[0] <= value <= _EXCEL_SERIAL_RANGE[1]:
        return None
    from openpyxl.utils.datetime import from_excel

    converted = from_excel(float(value))
    return converted if isinstance(converted, datetime) else None


def _parse_time(text: str) -> time | None:
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def _datetime(value: Any, formats: list[str] | None = None) -> datetime:
    """Parse dates, datetimes, Excel serials and text dates without dropping the time."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time())
    serial = _excel_serial(value)
    if serial is not None:
        return serial
    text = _clean_string(str(value))
    text = text.replace("－", "-").replace("／", "/").replace("．", ".").replace("。", ".")
    if re.fullmatch(r"(?:19|20)\d{6}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    date_part, _, time_part = text.partition("T" if "T" in text else " ")
    clock = _parse_time(time_part.strip()) if time_part.strip() else time()
    if clock is not None:
        for fmt in formats or [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y.%m.%d",
            "%Y年%m月%d日",
            "%d/%m/%Y",
            "%m/%d/%Y",
        ]:
            try:
                return datetime.combine(datetime.strptime(date_part.strip(), fmt).date(), clock)
            except ValueError:
                continue
    raise EltError("ELT_TRANSFORM_DATE_INVALID", f"无法转换为日期: {value}")


def _date(value: Any, formats: list[str] | None = None) -> Any:
    if _is_blank(value):
        return value
    return _datetime(value, formats).date().isoformat()


def _datetime_text(value: Any, formats: list[str] | None = None) -> Any:
    if _is_blank(value):
        return value
    return _datetime(value, formats).isoformat(sep=" ")


def _time_text(value: Any) -> Any:
    if _is_blank(value):
        return value
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.time().isoformat()
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) and 0 <= value < 1:
        from openpyxl.utils.datetime import from_excel

        converted = from_excel(float(value))
        if isinstance(converted, time):
            return converted.isoformat()
    clock = _parse_time(_clean_string(str(value)))
    if clock is None:
        return _datetime(value).time().isoformat()
    return clock.isoformat()


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _cast(value: Any, kind: str) -> Any:
    key = str(kind or "string").lower()
    if _is_blank(value):
        return value
    if key == "string":
        return str(value)
    if key in {"number", "decimal", "float"}:
        number = _decimal(value)
        return float(number) if key == "float" else str(number)
    if key in {"integer", "int"}:
        number = _decimal(value)
        if number != number.to_integral_value():
            raise EltError("ELT_TRANSFORM_INTEGER_PRECISION", f"整数转换不能截断小数: {value}")
        return int(number)
    if key in {"boolean", "bool"}:
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "是", "有"}:
            return True
        if text in {"0", "false", "no", "n", "否", "无"}:
            return False
        raise EltError("ELT_TRANSFORM_BOOLEAN_INVALID", f"无法转换为布尔值: {value}")
    if key == "date":
        return _date(value)
    if key == "datetime":
        return _datetime_text(value)
    if key == "time":
        return _time_text(value)
    raise EltError("ELT_TRANSFORM_CAST_UNSUPPORTED", f"不支持的类型转换: {kind}")


def _operand(raw: Any, row: dict[str, Any]) -> Any:
    if isinstance(raw, dict):
        if set(raw) == {"field"}:
            return row.get(str(raw["field"]))
        if set(raw) == {"literal"}:
            return raw["literal"]
        raise EltError("ELT_FORMULA_OPERAND_INVALID", "公式操作数只允许 field 或 literal")
    return raw


def _formula(rule: dict[str, Any], row: dict[str, Any]) -> Any:
    operator = str(rule.get("operator") or "").lower()
    if operator not in ALLOWED_FORMULA_OPERATORS:
        raise EltError("ELT_FORMULA_OPERATOR_FORBIDDEN", f"不允许的公式操作符: {operator}")
    operands = rule.get("operands")
    if not isinstance(operands, list) or not operands:
        raise EltError("ELT_FORMULA_OPERANDS_REQUIRED", "公式必须提供 operands")
    values = [_operand(item, row) for item in operands]
    if operator == "coalesce":
        return next((value for value in values if value not in (None, "")), "")
    if any(_is_blank(value) for value in values):
        return None
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
                raise EltError("ELT_FORMULA_DIVISION_BY_ZERO", "公式除数不能为 0")
            result /= number
    return str(result)


def apply_transform(value: Any, rule: dict[str, Any], row: dict[str, Any]) -> Any:
    op = str(rule.get("op") or "").strip().lower()
    if op not in ALLOWED_TRANSFORMS:
        raise EltError("ELT_TRANSFORM_FORBIDDEN", f"不允许的转换操作: {op}")
    if op == "trim":
        return _clean_string(value) if isinstance(value, str) else value
    if op == "cast":
        return _cast(value, str(rule.get("type") or "string"))
    if op == "date":
        formats = rule.get("formats")
        return _date(value, formats if isinstance(formats, list) else None)
    if op == "datetime":
        formats = rule.get("formats")
        return _datetime_text(value, formats if isinstance(formats, list) else None)
    if op == "time":
        return _time_text(value)
    if op == "number":
        if _is_blank(value):
            return value
        return str(_decimal(value))
    if op == "default":
        return rule.get("value") if value in (None, "") else value
    if op in {"map", "lookup"}:
        table = rule.get("values")
        if not isinstance(table, dict):
            raise EltError("ELT_TRANSFORM_MAP_INVALID", "枚举映射必须提供 values 对象")
        key = "" if value is None else str(value)
        return table.get(key, rule.get("fallback", value))
    if op == "split":
        delimiter = str(rule.get("delimiter") or ",")
        index = int(rule.get("index") or 0)
        parts = _text(value).split(delimiter)
        return parts[index].strip() if -len(parts) <= index < len(parts) else ""
    if op == "concat":
        fields = rule.get("fields")
        if not isinstance(fields, list):
            raise EltError("ELT_TRANSFORM_CONCAT_INVALID", "合并操作必须提供 fields")
        separator = str(rule.get("separator") or "")
        return separator.join(_text(row.get(str(field))) for field in fields)
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
            raise EltError("ELT_TRANSFORMS_INVALID", f"{target} 的 transforms 必须是数组")
        context = {**source, **normalized}
        for rule in rules:
            if not isinstance(rule, dict):
                raise EltError("ELT_TRANSFORM_INVALID", "转换规则必须是 JSON 对象")
            value = apply_transform(value, rule, context)
            context[target] = value
        normalized[target] = value
    return normalized
